"""Acesso PostgreSQL do backend. Nenhuma conexão ou credencial no frontend."""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pandas as pd
import psycopg
from dotenv import load_dotenv
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

BASE_DIR = Path(__file__).resolve().parent
CNPJS_EXCLUIDOS = {'17098794000170', '31887401000139', '42066916000194'}
COLUNAS = {
    'fundos': ('cnpj', 'nome', 'atualizado_em'),
    'cotas_diarias': ('cnpj', 'id_subclasse', 'data', 'valor_cota', 'arquivo_origem', 'atualizado_em'),
    'cargas': ('arquivo', 'url', 'periodo_inicial', 'periodo_final', 'processado_em',
               'linhas_inseridas', 'status', 'erro', 'linhas_atualizadas'),
}
CHAVES = {'fundos': ('cnpj',), 'cotas_diarias': ('cnpj', 'id_subclasse', 'data'), 'cargas': ('arquivo',)}


class ErroBanco(RuntimeError):
    """Mensagem segura: não inclui connection string nem detalhes do servidor."""


def conectar_banco() -> psycopg.Connection:
    load_dotenv(BASE_DIR / '.env', override=False)
    url = os.environ.get('DATABASE_URL', '').strip()
    if not url:
        raise ErroBanco('Configure DATABASE_URL no ambiente do backend.')
    try:
        parametros = conninfo_to_dict(url)
        host = parametros.get('host', '')
        if host not in ('localhost', '127.0.0.1', '::1') and not host.startswith('/'):
            if parametros.get('sslmode') not in ('require', 'verify-ca', 'verify-full'):
                parametros['sslmode'] = 'require'
        parametros.setdefault('connect_timeout', '15')
        parametros['application_name'] = 'fundos_caixa'
        return psycopg.connect(**parametros, autocommit=True, prepare_threshold=None)
    except (psycopg.Error, ValueError):
        raise ErroBanco('Não foi possível conectar ao PostgreSQL. Verifique a configuração e a rede.') from None


@contextmanager
def operacao_banco():
    try:
        with conectar_banco() as conexao:
            yield conexao
    except psycopg.Error:
        raise ErroBanco('A operação no PostgreSQL falhou. Verifique a conexão, o schema e as permissões.') from None


def aplicar_schema() -> None:
    with operacao_banco() as conexao:
        conexao.execute((BASE_DIR / 'supabase' / 'schema.sql').read_text())


def consultar_dataframe(conexao, consulta, parametros=None) -> pd.DataFrame:
    cursor = conexao.execute(consulta, parametros)
    return pd.DataFrame.from_records(cursor.fetchall(), columns=[c.name for c in cursor.description])


def listar_cadastro() -> pd.DataFrame:
    with operacao_banco() as conexao:
        return consultar_dataframe(conexao, 'SELECT cnpj, nome FROM public.fundos WHERE NOT (cnpj = ANY(%s)) ORDER BY nome', [list(CNPJS_EXCLUIDOS)])


def listar_fundos() -> pd.DataFrame:
    with operacao_banco() as conexao:
        dados = consultar_dataframe(conexao, '''
            SELECT f.cnpj, f.nome, COALESCE(s.id_subclasse, '') AS id_subclasse,
                   f.nomes_subclasses ->> s.id_subclasse AS nome_subclasse,
                   MIN(c.data) AS primeira_data_disponivel,
                   MAX(c.data) AS ultima_data_disponivel,
                   COUNT(c.data) AS quantidade_registros,
                   CASE WHEN COUNT(c.data) = 0 THEN 'SEM DADOS' ELSE 'OK' END AS status
            FROM public.fundos f
            LEFT JOIN LATERAL (
                SELECT id_subclasse FROM public.cotas_diarias WHERE cnpj = f.cnpj GROUP BY id_subclasse
                UNION
                SELECT jsonb_object_keys(f.nomes_subclasses)
            ) s ON true
            LEFT JOIN public.cotas_diarias c ON c.cnpj = f.cnpj AND c.id_subclasse = s.id_subclasse
            WHERE NOT (f.cnpj = ANY(%s))
            GROUP BY f.cnpj, f.nome, s.id_subclasse ORDER BY f.nome, s.id_subclasse
        ''', [list(CNPJS_EXCLUIDOS)])
    dados['id_serie'] = dados['cnpj'] + '::' + dados['id_subclasse']
    multiplas = dados['cnpj'].duplicated(keep=False)
    rotular = multiplas | dados['id_subclasse'].ne('')
    dados.loc[rotular, 'nome'] = (
        dados.loc[rotular, 'nome'] + ' — '
        + dados.loc[rotular, 'id_subclasse'].map(lambda s: f'Subclasse {s}' if s else 'Sem subclasse informada')
    )
    nome_definido = dados['nome_subclasse'].notna() & dados['nome_subclasse'].ne('')
    dados.loc[nome_definido, 'nome'] = dados.loc[nome_definido, 'nome_subclasse']
    for coluna in ('primeira_data_disponivel', 'ultima_data_disponivel'):
        dados[coluna] = pd.to_datetime(dados[coluna]).astype('datetime64[us]')
    return dados


def limites_do_banco() -> tuple[pd.Timestamp, pd.Timestamp]:
    with operacao_banco() as conexao:
        inicio, fim = conexao.execute('SELECT MIN(data), MAX(data) FROM public.cotas_diarias').fetchone()
    if inicio is None:
        raise ValueError('O banco ainda não possui cotas diárias.')
    return pd.Timestamp(inicio), pd.Timestamp(fim)


def consultar_cotas(cnpjs, inicio, fim) -> pd.DataFrame:
    # Identificadores explícitos selecionam uma única subclasse, inclusive a vazia.
    # CNPJs simples continuam disponíveis para os consumidores antigos.
    series = [chave.split('::', 1) for chave in cnpjs if '::' in chave]
    simples = [chave for chave in cnpjs if '::' not in chave]
    with operacao_banco() as conexao:
        dados = consultar_dataframe(conexao, '''
            SELECT c.data, s.chave AS cnpj, c.valor_cota
            FROM public.cotas_diarias c
            JOIN (
                SELECT unnest(%s::text[]) AS cnpj,
                       unnest(%s::text[]) AS id_subclasse,
                       unnest(%s::text[]) AS chave
                UNION ALL
                SELECT p, NULL::text, p FROM unnest(%s::text[]) AS p
            ) s ON c.cnpj = s.cnpj
               AND (s.id_subclasse IS NULL OR c.id_subclasse = s.id_subclasse)
            WHERE c.data BETWEEN %s AND %s ORDER BY c.data, s.chave
        ''', [[s[0] for s in series], [s[1] for s in series],
              ['::'.join(s) for s in series], simples, inicio, fim])
    # Usa resolução de microssegundos consistente nos joins e gráficos.
    dados['data'] = pd.to_datetime(dados['data']).astype('datetime64[us]')
    return dados


@dataclass(frozen=True)
class ResultadoUpsert:
    inseridas: int = 0
    atualizadas: int = 0


def upsert_lote(conexao, tabela: str, registros) -> ResultadoUpsert:
    """COPY usa um fluxo em lote, sem INSERT/requisição individual por registro.

    O lock serializa escritores desta tabela e mantém as contagens exatas.
    A transação externa pode abranger todos os lotes de um arquivo.
    Duplicatas dentro do lote: prevalece a última ocorrência, como no coletor.
    """
    colunas, chaves = COLUNAS[tabela], CHAVES[tabela]
    nome = sql.Identifier('public', tabela)
    campos = sql.SQL(', ').join(map(sql.Identifier, colunas))
    pk = sql.SQL(', ').join(map(sql.Identifier, chaves))
    alteraveis = [c for c in colunas if c not in chaves]
    comparaveis = [c for c in alteraveis if c != 'atualizado_em']
    igualdade = sql.SQL(' AND ').join(sql.SQL('t.{0} = s.{0}').format(sql.Identifier(c)) for c in chaves)
    diferencas = sql.SQL(' OR ').join(sql.SQL('t.{0} IS DISTINCT FROM EXCLUDED.{0}').format(sql.Identifier(c)) for c in comparaveis)
    with conexao.transaction():
        conexao.execute(sql.SQL('LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE').format(nome))
        conexao.execute(sql.SQL('CREATE TEMP TABLE lote_importacao (LIKE {} INCLUDING DEFAULTS) ON COMMIT DROP').format(nome))
        conexao.execute('ALTER TABLE lote_importacao ADD COLUMN ordem BIGINT GENERATED ALWAYS AS IDENTITY')
        with conexao.cursor().copy(sql.SQL('COPY lote_importacao ({}) FROM STDIN').format(campos)) as copia:
            for registro in registros:
                copia.write_row(registro)
        origem = sql.SQL('(SELECT DISTINCT ON ({pk}) {campos} FROM lote_importacao ORDER BY {pk}, ordem DESC)').format(pk=pk, campos=campos)
        novas = conexao.execute(sql.SQL('SELECT count(*) FROM {} s WHERE NOT EXISTS (SELECT 1 FROM {} t WHERE {})').format(origem, nome, igualdade)).fetchone()[0]
        atualizacao = sql.SQL(', ').join(sql.SQL('{0} = EXCLUDED.{0}').format(sql.Identifier(c)) for c in alteraveis)
        cursor = conexao.execute(sql.SQL('''
            INSERT INTO {nome} AS t ({campos}) SELECT {campos} FROM {origem} s WHERE true
            ON CONFLICT ({pk}) DO UPDATE SET {atualizacao} WHERE {diferencas}
        ''').format(nome=nome, campos=campos, origem=origem, pk=pk, atualizacao=atualizacao, diferencas=diferencas))
        resultado = ResultadoUpsert(novas, cursor.rowcount - novas)
        conexao.execute('DROP TABLE lote_importacao')
    return resultado


def sincronizar_fundos(conexao, fundos: pd.DataFrame) -> None:
    agora = datetime.now(timezone.utc)
    upsert_lote(conexao, 'fundos', ((r.cnpj, r.nome, agora) for r in fundos.itertuples(index=False)))


def registrar_carga(conexao, arquivo, inseridas, atualizadas=0, erro=None) -> None:
    upsert_lote(conexao, 'cargas', [(arquivo.nome, arquivo.url, arquivo.periodo_inicial,
        arquivo.periodo_final, datetime.now(timezone.utc), inseridas,
        'ERRO' if erro else 'OK', erro, atualizadas)])


def arquivos_concluidos(conexao) -> set[str]:
    return {r[0] for r in conexao.execute("SELECT arquivo FROM public.cargas WHERE status = 'OK'").fetchall()}


def resumo_cargas(conexao):
    resumo = conexao.execute('''SELECT COUNT(*), COUNT(primeira_data_disponivel),
        SUM(quantidade_registros), MIN(primeira_data_disponivel), MAX(ultima_data_disponivel)
        FROM public.fundos_controle WHERE NOT (cnpj = ANY(%s))''', [list(CNPJS_EXCLUIDOS)]).fetchone()
    sem_dados = conexao.execute("SELECT cnpj, nome FROM public.fundos_controle WHERE status = 'SEM DADOS' AND NOT (cnpj = ANY(%s)) ORDER BY nome", [list(CNPJS_EXCLUIDOS)]).fetchall()
    return resumo, sem_dados


def registrar_simulacao(identificador: UUID) -> None:
    with operacao_banco() as conexao:
        conexao.execute('INSERT INTO public.simulacoes (id) VALUES (%s) ON CONFLICT (id) DO NOTHING', [identificador])


def total_simulacoes() -> int:
    with operacao_banco() as conexao:
        return conexao.execute('SELECT COUNT(*) FROM public.simulacoes').fetchone()[0]


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Configurar/verificar PostgreSQL sem exibir credenciais.')
    parser.add_argument('--aplicar-schema', action='store_true')
    args = parser.parse_args()
    try:
        if args.aplicar_schema:
            aplicar_schema()
        with operacao_banco() as conexao:
            print('PostgreSQL conectado; fundos, cobertura e cotas:', resumo_cargas(conexao)[0])
    except (ErroBanco, ValueError) as erro:
        parser.exit(1, f'{erro}\n')
