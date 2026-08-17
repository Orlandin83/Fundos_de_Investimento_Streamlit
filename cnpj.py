"""Coleta o histórico de cotas dos fundos CAIXA no Portal de Dados Abertos CVM.

Na primeira execução, o programa percorre todos os Informes Diários disponíveis
desde 2000. Nas execuções seguintes, processa arquivos ainda pendentes e baixa
novamente os meses mais recentes, que podem ser reapresentados pela CVM.
"""

# %%
from __future__ import annotations

import argparse
import logging
import re
import shutil
import ssl
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import urljoin

import certifi
import duckdb
import pandas as pd
from numbers_parser import Document


BASE_DIR = Path(__file__).resolve().parent
PLANILHA = BASE_DIR / "Fundos CAIXA.numbers"
BANCO_PADRAO = BASE_DIR / "dados" / "fundos.duckdb"
CACHE_PADRAO = BASE_DIR / "dados" / "cache_cvm"

URL_MENSAL = "https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS/"
URL_HISTORICO = urljoin(URL_MENSAL, "HIST/")
PADRAO_ARQUIVO = re.compile(r"^inf_diario_fi_(\d{4})(\d{2})?\.zip$")
# Fundos imobiliários não fazem parte do universo analítico deste projeto.
CNPJS_EXCLUIDOS = {
    "17098794000170",  # CAIXA RIO BRAVO FUNDO DE FII
    "31887401000139",  # CAIXA RIO BRAVO FUNDO DE FII II
    "42066916000194",  # FII CAIXA CARTEIRA IMOBILIÁRIA
}
LOG = logging.getLogger("cotas_cvm")


@dataclass(frozen=True)
class ArquivoCVM:
    nome: str
    url: str
    periodo_inicial: str
    periodo_final: str
    mensal: bool


def normalizar_cnpj(valor: object) -> str | None:
    """Retorna um CNPJ com 14 dígitos ou None para valores inválidos."""
    if pd.isna(valor):
        return None
    digitos = re.sub(r"\D", "", str(valor))
    return digitos.zfill(14) if 1 <= len(digitos) <= 14 else None


def _ler_tabela_fundos_numbers(planilha: Path) -> pd.DataFrame:
    """Localiza uma tabela com os cabeçalhos Nome e CNPJ em um arquivo Numbers."""
    documento = Document(str(planilha))
    for folha in documento.sheets:
        for tabela in folha.tables:
            linhas = tabela.rows(values_only=True)
            for indice_cabecalho, linha in enumerate(linhas):
                cabecalhos = [str(valor).strip() if valor is not None else "" for valor in linha]
                if "Nome" not in cabecalhos or "CNPJ" not in cabecalhos:
                    continue

                coluna_nome = cabecalhos.index("Nome")
                coluna_cnpj = cabecalhos.index("CNPJ")
                registros: list[dict[str, object]] = []
                for linha_dados in linhas[indice_cabecalho + 1 :]:
                    nome = linha_dados[coluna_nome] if coluna_nome < len(linha_dados) else None
                    cnpj_fundo = linha_dados[coluna_cnpj] if coluna_cnpj < len(linha_dados) else None
                    if pd.isna(nome) and pd.isna(cnpj_fundo):
                        continue
                    registros.append({"Nome": nome, "CNPJ": cnpj_fundo})

                if not registros:
                    raise ValueError(
                        f"A tabela '{tabela.name}' da folha '{folha.name}' não possui fundos."
                    )
                return pd.DataFrame(registros, columns=["Nome", "CNPJ"])

    raise ValueError(
        "Nenhuma tabela com os cabeçalhos 'Nome' e 'CNPJ' foi encontrada no arquivo Numbers."
    )


def carregar_fundos(planilha: Path = PLANILHA) -> pd.DataFrame:
    """Lê e valida a relação de fundos do arquivo Apple Numbers."""
    if not planilha.exists():
        raise FileNotFoundError(f"Planilha não encontrada: {planilha}")
    fundos = _ler_tabela_fundos_numbers(planilha)
    ausentes = {"Nome", "CNPJ"} - set(fundos.columns)
    if ausentes:
        raise ValueError(
            "A tabela do arquivo Numbers não possui as colunas obrigatórias: "
            + ", ".join(sorted(ausentes))
        )
    fundos = fundos[["Nome", "CNPJ"]].copy()
    fundos["nome"] = fundos["Nome"].str.strip()
    fundos["cnpj"] = fundos["CNPJ"].map(normalizar_cnpj)
    invalidos = fundos[fundos["cnpj"].isna()]
    if not invalidos.empty:
        linhas = ", ".join(str(i + 2) for i in invalidos.index)
        raise ValueError(f"CNPJ inválido na tabela de fundos, linha(s): {linhas}")
    duplicados = fundos[fundos["cnpj"].duplicated(keep=False)]
    if not duplicados.empty:
        lista = ", ".join(sorted(duplicados["cnpj"].unique()))
        raise ValueError(f"CNPJs duplicados na planilha: {lista}")
    fundos = fundos[~fundos["cnpj"].isin(CNPJS_EXCLUIDOS)]
    return fundos[["cnpj", "nome"]].reset_index(drop=True)


# Dataframe solicitado pelo projeto. A carga da planilha não inicia downloads.
cnpj = carregar_fundos()


def _abrir_url(url: str, tentativas: int = 4, timeout: int = 90):
    cabecalhos = {"User-Agent": "Fundos-CAIXA-COTA/1.0"}
    ultimo_erro: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            requisicao = urllib.request.Request(url, headers=cabecalhos)
            contexto_tls = ssl.create_default_context(cafile=certifi.where())
            return urllib.request.urlopen(requisicao, timeout=timeout, context=contexto_tls)
        except (urllib.error.URLError, TimeoutError) as erro:
            ultimo_erro = erro
            if tentativa == tentativas:
                break
            espera = 2 ** (tentativa - 1)
            LOG.warning("Falha ao acessar %s; nova tentativa em %ss", url, espera)
            time.sleep(espera)
    raise RuntimeError(f"Não foi possível acessar {url}: {ultimo_erro}")


def _listar_nomes_zip(url_diretorio: str) -> list[str]:
    with _abrir_url(url_diretorio) as resposta:
        html = resposta.read().decode("utf-8", errors="replace")
    return sorted(set(re.findall(r'href="(inf_diario_fi_\d{4,6}\.zip)"', html)))


def descobrir_arquivos() -> list[ArquivoCVM]:
    """Descobre os arquivos existentes sem pressupor qual é o mês atual."""
    arquivos: list[ArquivoCVM] = []
    for nome in _listar_nomes_zip(URL_HISTORICO):
        correspondencia = PADRAO_ARQUIVO.match(nome)
        if correspondencia:
            ano = correspondencia.group(1)
            arquivos.append(ArquivoCVM(
                nome, urljoin(URL_HISTORICO, nome), f"{ano}-01", f"{ano}-12", False
            ))
    for nome in _listar_nomes_zip(URL_MENSAL):
        correspondencia = PADRAO_ARQUIVO.match(nome)
        if correspondencia and correspondencia.group(2):
            periodo = f"{correspondencia.group(1)}-{correspondencia.group(2)}"
            arquivos.append(ArquivoCVM(
                nome, urljoin(URL_MENSAL, nome), periodo, periodo, True
            ))
    if not arquivos:
        raise RuntimeError("A CVM não retornou arquivos de Informe Diário.")
    return sorted(arquivos, key=lambda item: (item.periodo_inicial, item.nome))


def conectar_banco(caminho: Path) -> duckdb.DuckDBPyConnection:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    conexao = duckdb.connect(str(caminho))
    conexao.execute("""
        CREATE TABLE IF NOT EXISTS fundos (
            cnpj VARCHAR PRIMARY KEY, nome VARCHAR NOT NULL,
            atualizado_em TIMESTAMP WITH TIME ZONE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cotas_diarias (
            cnpj VARCHAR NOT NULL, id_subclasse VARCHAR NOT NULL DEFAULT '',
            data DATE NOT NULL, valor_cota DOUBLE NOT NULL,
            arquivo_origem VARCHAR NOT NULL,
            atualizado_em TIMESTAMP WITH TIME ZONE NOT NULL,
            PRIMARY KEY (cnpj, id_subclasse, data)
        );
        CREATE TABLE IF NOT EXISTS cargas (
            arquivo VARCHAR PRIMARY KEY, url VARCHAR NOT NULL,
            periodo_inicial VARCHAR NOT NULL, periodo_final VARCHAR NOT NULL,
            processado_em TIMESTAMP WITH TIME ZONE, linhas_inseridas BIGINT,
            status VARCHAR NOT NULL, erro VARCHAR
        );
        CREATE OR REPLACE VIEW fundos_controle AS
        SELECT f.cnpj, f.nome,
               MIN(c.data) AS primeira_data_disponivel,
               MAX(c.data) AS ultima_data_disponivel,
               COUNT(c.data) AS quantidade_registros,
               CASE WHEN COUNT(c.data) = 0 THEN 'SEM DADOS' ELSE 'OK' END AS status
        FROM fundos f LEFT JOIN cotas_diarias c USING (cnpj)
        GROUP BY f.cnpj, f.nome;
    """)
    return conexao


def sincronizar_fundos(conexao: duckdb.DuckDBPyConnection, fundos: pd.DataFrame) -> None:
    agora = datetime.now(timezone.utc)
    registros = [(linha.cnpj, linha.nome, agora) for linha in fundos.itertuples(index=False)]
    conexao.executemany(
        "INSERT OR REPLACE INTO fundos (cnpj, nome, atualizado_em) VALUES (?, ?, ?)", registros
    )
    conexao.execute(
        "DELETE FROM cotas_diarias WHERE cnpj IN (SELECT UNNEST(?::VARCHAR[]))",
        [list(CNPJS_EXCLUIDOS)],
    )
    conexao.execute(
        "DELETE FROM fundos WHERE cnpj IN (SELECT UNNEST(?::VARCHAR[]))",
        [list(CNPJS_EXCLUIDOS)],
    )


def baixar_arquivo(arquivo: ArquivoCVM, cache: Path, sobrescrever: bool) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    destino = cache / arquivo.nome
    if destino.exists() and destino.stat().st_size > 0 and not sobrescrever:
        LOG.info("Usando cache: %s", arquivo.nome)
        return destino
    temporario = destino.with_suffix(destino.suffix + ".part")
    LOG.info("Baixando %s", arquivo.url)
    try:
        with _abrir_url(arquivo.url) as origem, temporario.open("wb") as saida:
            shutil.copyfileobj(origem, saida, length=1024 * 1024)
        if not zipfile.is_zipfile(temporario):
            raise zipfile.BadZipFile(f"Conteúdo inválido recebido para {arquivo.nome}")
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)
    return destino


def _nome_coluna(colunas: set[str], opcoes: tuple[str, ...]) -> str | None:
    return next((opcao for opcao in opcoes if opcao in colunas), None)


def _normalizar_nome_coluna(nome: object) -> str:
    texto = unicodedata.normalize("NFKD", str(nome).strip().upper())
    return "".join(c for c in texto if not unicodedata.combining(c))


def ler_lotes_filtrados(
    caminho_zip: Path, cnpjs_desejados: set[str], tamanho_lote: int
) -> Iterator[pd.DataFrame]:
    """Lê um ZIP da CVM em lotes e devolve apenas os fundos desejados."""
    with zipfile.ZipFile(caminho_zip) as pacote:
        csvs = [nome for nome in pacote.namelist() if nome.lower().endswith(".csv")]
        if not csvs:
            raise ValueError(f"Nenhum CSV encontrado em {caminho_zip.name}")
        for nome_csv in csvs:
            with pacote.open(nome_csv) as arquivo_csv:
                leitor = pd.read_csv(
                    arquivo_csv, sep=";", dtype=str, chunksize=tamanho_lote,
                    encoding="latin-1", low_memory=False
                )
                for lote in leitor:
                    lote.columns = [_normalizar_nome_coluna(c) for c in lote.columns]
                    colunas = set(lote.columns)
                    coluna_cnpj = _nome_coluna(colunas, ("CNPJ_FUNDO_CLASSE", "CNPJ_FUNDO"))
                    if coluna_cnpj is None or "DT_COMPTC" not in colunas:
                        raise ValueError(
                            f"Estrutura desconhecida em {caminho_zip.name}: {sorted(colunas)}"
                        )
                    lote["cnpj"] = lote[coluna_cnpj].map(normalizar_cnpj)
                    lote = lote[lote["cnpj"].isin(cnpjs_desejados)].copy()
                    if lote.empty:
                        continue
                    lote["id_subclasse"] = (
                        lote["ID_SUBCLASSE"].fillna("").str.strip()
                        if "ID_SUBCLASSE" in colunas else ""
                    )
                    lote["data"] = pd.to_datetime(lote["DT_COMPTC"], errors="coerce")
                    lote["valor_cota"] = pd.to_numeric(lote["VL_QUOTA"], errors="coerce")
                    lote = lote[lote["data"].notna() & (lote["valor_cota"] > 0)]
                    yield lote[["cnpj", "id_subclasse", "data", "valor_cota"]]


def processar_arquivo(
    conexao: duckdb.DuckDBPyConnection, arquivo: ArquivoCVM, caminho_zip: Path,
    cnpjs_desejados: set[str], tamanho_lote: int
) -> int:
    """Substitui atomicamente no banco os registros provenientes de um arquivo."""
    total = 0
    agora = datetime.now(timezone.utc)
    conexao.execute("BEGIN TRANSACTION")
    try:
        conexao.execute("DELETE FROM cotas_diarias WHERE arquivo_origem = ?", [arquivo.nome])
        for numero, lote in enumerate(
            ler_lotes_filtrados(caminho_zip, cnpjs_desejados, tamanho_lote), start=1
        ):
            lote["arquivo_origem"] = arquivo.nome
            lote["atualizado_em"] = agora
            temporaria = f"lote_cvm_{numero}"
            conexao.register(temporaria, lote)
            try:
                conexao.execute(f"""
                    INSERT OR REPLACE INTO cotas_diarias
                    SELECT cnpj, id_subclasse, data, valor_cota,
                           arquivo_origem, atualizado_em
                    FROM {temporaria}
                """)
            finally:
                conexao.unregister(temporaria)
            total += len(lote)
        conexao.execute("""
            INSERT OR REPLACE INTO cargas
            VALUES (?, ?, ?, ?, ?, ?, 'OK', NULL)
        """, [arquivo.nome, arquivo.url, arquivo.periodo_inicial,
              arquivo.periodo_final, agora, total])
        conexao.execute("COMMIT")
    except Exception:
        conexao.execute("ROLLBACK")
        raise
    return total


def registrar_erro(
    conexao: duckdb.DuckDBPyConnection, arquivo: ArquivoCVM, erro: Exception
) -> None:
    conexao.execute("""
        INSERT OR REPLACE INTO cargas
        VALUES (?, ?, ?, ?, ?, NULL, 'ERRO', ?)
    """, [arquivo.nome, arquivo.url, arquivo.periodo_inicial, arquivo.periodo_final,
          datetime.now(timezone.utc), str(erro)[:2000]])


def selecionar_arquivos(
    conexao: duckdb.DuckDBPyConnection, arquivos: list[ArquivoCVM],
    inicio: str | None, fim: str | None, forcar: bool, meses_reprocessar: int
) -> tuple[list[ArquivoCVM], set[str]]:
    filtrados = [
        arquivo for arquivo in arquivos
        if (inicio is None or arquivo.periodo_final >= inicio)
        and (fim is None or arquivo.periodo_inicial <= fim)
    ]
    concluidos = {
        linha[0] for linha in conexao.execute(
            "SELECT arquivo FROM cargas WHERE status = 'OK'"
        ).fetchall()
    }
    mensais = [arquivo.nome for arquivo in filtrados if arquivo.mensal]
    recentes = set(mensais[-meses_reprocessar:]) if meses_reprocessar else set()
    if forcar:
        return filtrados, recentes
    return [
        arquivo for arquivo in filtrados
        if arquivo.nome not in concluidos or arquivo.nome in recentes
    ], recentes


def validar_periodo(valor: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}", valor):
        raise argparse.ArgumentTypeError("Use o formato AAAA-MM.")
    ano, mes = map(int, valor.split("-"))
    if ano < 2000 or not 1 <= mes <= 12:
        raise argparse.ArgumentTypeError("Período fora do intervalo válido.")
    return valor


def criar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Baixa o histórico de cotas dos fundos CAIXA na CVM."
    )
    parser.add_argument("--inicio", type=validar_periodo, help="Primeiro mês (AAAA-MM).")
    parser.add_argument("--fim", type=validar_periodo, help="Último mês (AAAA-MM).")
    parser.add_argument("--banco", type=Path, default=BANCO_PADRAO)
    parser.add_argument("--cache", type=Path, default=CACHE_PADRAO)
    parser.add_argument(
        "--manter-cache", action="store_true",
        help="Mantém os ZIPs da CVM após o processamento (usa mais espaço)."
    )
    parser.add_argument("--forcar", action="store_true", help="Reprocessa os arquivos selecionados.")
    parser.add_argument(
        "--meses-reprocessar", type=int, default=2,
        help="Quantidade de meses recentes a baixar novamente (padrão: 2)."
    )
    parser.add_argument("--tamanho-lote", type=int, default=250_000)
    parser.add_argument(
        "--continuar-com-erros", action="store_true",
        help="Continua a carga se um arquivo falhar."
    )
    return parser


def executar(args: argparse.Namespace) -> int:
    if args.inicio and args.fim and args.inicio > args.fim:
        raise ValueError("--inicio não pode ser posterior a --fim.")
    if args.meses_reprocessar < 0 or args.tamanho_lote <= 0:
        raise ValueError("Os parâmetros numéricos devem ser positivos.")
    fundos = carregar_fundos()
    cnpjs_desejados = set(fundos["cnpj"])
    LOG.info("%s fundos carregados da planilha", len(fundos))
    conexao = conectar_banco(args.banco.resolve())
    falhas = 0
    try:
        sincronizar_fundos(conexao, fundos)
        arquivos = descobrir_arquivos()
        selecionados, recentes = selecionar_arquivos(
            conexao, arquivos, args.inicio, args.fim, args.forcar, args.meses_reprocessar
        )
        LOG.info("%s de %s arquivos serão processados", len(selecionados), len(arquivos))
        for posicao, arquivo in enumerate(selecionados, start=1):
            LOG.info("[%s/%s] %s", posicao, len(selecionados), arquivo.nome)
            try:
                caminho = baixar_arquivo(
                    arquivo, args.cache.resolve(), sobrescrever=arquivo.nome in recentes
                )
                linhas = processar_arquivo(
                    conexao, arquivo, caminho, cnpjs_desejados, args.tamanho_lote
                )
                LOG.info("%s: %s registros dos fundos selecionados", arquivo.nome, linhas)
                if not args.manter_cache:
                    caminho.unlink(missing_ok=True)
                    LOG.info("Cache removido após a carga: %s", arquivo.nome)
            except Exception as erro:
                falhas += 1
                registrar_erro(conexao, arquivo, erro)
                LOG.exception("Erro ao processar %s", arquivo.nome)
                if not args.continuar_com_erros:
                    raise
        conexao.execute("CHECKPOINT")
        resumo = conexao.execute("""
            SELECT COUNT(*) AS fundos,
                   COUNT(primeira_data_disponivel) AS fundos_com_dados,
                   SUM(quantidade_registros) AS registros,
                   MIN(primeira_data_disponivel) AS primeira_data,
                   MAX(ultima_data_disponivel) AS ultima_data
            FROM fundos_controle
        """).fetchone()
        sem_dados = conexao.execute(
            "SELECT cnpj, nome FROM fundos_controle WHERE status = 'SEM DADOS' ORDER BY nome"
        ).fetchall()
        LOG.info(
            "Resumo: %s/%s fundos com dados; %s registros; período %s a %s",
            resumo[1], resumo[0], resumo[2] or 0, resumo[3] or "-", resumo[4] or "-"
        )
        if sem_dados:
            LOG.warning("%s fundos ainda estão sem dados no período", len(sem_dados))
            for cnpj_fundo, nome in sem_dados:
                LOG.warning("SEM DADOS: %s - %s", cnpj_fundo, nome)
        try:
            args.cache.resolve().rmdir()
        except OSError:
            pass
    finally:
        conexao.close()
    return 1 if falhas else 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    try:
        return executar(criar_parser().parse_args())
    except KeyboardInterrupt:
        LOG.warning("Execução interrompida; o progresso concluído foi preservado.")
        return 130
    except Exception:
        LOG.exception("A carga não foi concluída.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
