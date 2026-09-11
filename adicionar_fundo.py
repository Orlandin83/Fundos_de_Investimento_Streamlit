"""Execute: python adicionar_fundo.py (usa DATABASE_URL do .env local)."""
import logging
import re
import sys
from tempfile import TemporaryDirectory
from pathlib import Path

import pandas as pd

from cnpj import baixar_arquivo, descobrir_arquivos, processar_arquivo
from database import CNPJS_EXCLUIDOS, operacao_banco, sincronizar_fundos


def validar_cnpj(texto, permitir_excluido=False):
    """Aceita CNPJ numérico com ou sem pontuação e verifica os dígitos."""
    cnpj = re.sub(r"[./\-\s]", "", texto)
    if not re.fullmatch(r"[0-9]{14}", cnpj) or len(set(cnpj)) == 1:
        raise ValueError("Informe um CNPJ numérico válido, com 14 dígitos.")
    for tamanho in (12, 13):
        pesos = list(range(tamanho - 7, 1, -1)) + list(range(9, 1, -1))
        resto = sum(int(n) * p for n, p in zip(cnpj[:tamanho], pesos)) % 11
        if int(cnpj[tamanho]) != (0 if resto < 2 else 11 - resto):
            raise ValueError("Os dígitos verificadores do CNPJ são inválidos.")
    if not permitir_excluido and cnpj in CNPJS_EXCLUIDOS:
        raise ValueError("Esse CNPJ está na lista de fundos excluídos do projeto.")
    return cnpj


def solicitar_fundos():
    fundos = {}
    while True:
        try:
            cnpj = validar_cnpj(input("CNPJ do fundo: "))
        except ValueError as erro:
            print(erro)
            continue
        nome = input("Nome do fundo: ").strip()
        while not nome:
            nome = input("O nome é obrigatório. Nome do fundo: ").strip()
        fundos[cnpj] = nome
        resposta = input("Deseja incluir outro CNPJ? [s/n]: ").strip().lower()
        while resposta not in ("s", "sim", "n", "não", "nao"):
            resposta = input("Responda s ou n: ").strip().lower()
        if resposta in ("n", "não", "nao"):
            return pd.DataFrame(fundos.items(), columns=["cnpj", "nome"])


def importar_historico(fundos):
    with operacao_banco() as conexao:
        sincronizar_fundos(conexao, fundos)
        print("Buscando todos os arquivos de Informe Diário disponíveis na CVM...", flush=True)
        arquivos = descobrir_arquivos()
        # Cada arquivo é baixado uma vez para todos os fundos informados.
        with TemporaryDirectory(prefix="fundos_cvm_") as pasta:
            for indice, arquivo in enumerate(arquivos, 1):
                print(f"[{indice}/{len(arquivos)}] {arquivo.nome}", flush=True)
                caminho = baixar_arquivo(arquivo, Path(pasta), sobrescrever=True)
                resultado = processar_arquivo(
                    conexao, arquivo, caminho, set(fundos["cnpj"]), 250_000,
                    registrar_controle=False,
                )
                # A carga de apenas estes fundos não conclui a carga geral.
                print(f"  {resultado.inseridas} cotas inseridas; {resultado.atualizadas} atualizadas.", flush=True)
                caminho.unlink()
        resumo = conexao.execute("""
            SELECT f.cnpj, f.nome, COUNT(c.data), MIN(c.data), MAX(c.data)
            FROM public.fundos f LEFT JOIN public.cotas_diarias c USING (cnpj)
            WHERE f.cnpj = ANY(%s) GROUP BY f.cnpj, f.nome ORDER BY f.nome
        """, [list(fundos["cnpj"])]).fetchall()
        for cnpj, nome, quantidade, inicio, fim in resumo:
            print(f"{nome} ({cnpj}): {quantidade} cotas; {inicio or '-'} a {fim or '-'}")
            if not quantidade:
                print("  Nenhuma cota encontrada nos Informes Diários para este CNPJ.")
    print("Importação concluída. Os fundos estão cadastrados para as próximas atualizações.")


def editar_cadastro(excluir=False):
    try:
        cnpj = validar_cnpj(input("CNPJ do fundo: "), permitir_excluido=True)
    except ValueError as erro:
        print(erro)
        return
    with operacao_banco() as conexao:
        registro = conexao.execute(
            "SELECT nome FROM public.fundos WHERE cnpj = %s", [cnpj]
        ).fetchone()
        if registro is None:
            print("CNPJ não encontrado no cadastro.")
            return
        print(f"Fundo: {registro[0]} ({cnpj})")
        if excluir:
            print("A exclusão remove o cadastro do aplicativo e das próximas coletas. As cotas históricas serão preservadas.")
            if input("Excluir este cadastro? [s/n]: ").strip().lower() not in ("s", "sim"):
                print("Exclusão cancelada.")
                return
            cursor = conexao.execute("DELETE FROM public.fundos WHERE cnpj = %s", [cnpj])
            print("Cadastro excluído." if cursor.rowcount else "Cadastro já removido.")
        else:
            nome = input("Novo nome do fundo: ").strip()
            while not nome:
                nome = input("O nome é obrigatório. Novo nome: ").strip()
            cursor = conexao.execute(
                "UPDATE public.fundos SET nome = %s, atualizado_em = CURRENT_TIMESTAMP WHERE cnpj = %s",
                [nome, cnpj],
            )
            print("Nome atualizado." if cursor.rowcount else "Cadastro não encontrado.")


def main():
    try:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        while True:
            print("\n1 - Incluir fundos e importar histórico\n2 - Alterar nome\n3 - Excluir cadastro (preservar cotas)\n0 - Sair")
            opcao = input("Escolha uma opção: ").strip()
            if opcao == "0":
                return 0
            if opcao == "1":
                fundos = solicitar_fundos()
                print("Se houver interrupção, execute novamente com os mesmos CNPJs: cotas já gravadas não serão duplicadas.")
                importar_historico(fundos)
            elif opcao in ("2", "3"):
                editar_cadastro(excluir=opcao == "3")
            else:
                print("Opção inválida.")
    except (KeyboardInterrupt, EOFError):
        print("\nExecução interrompida.")
        return 130
    except Exception as erro:
        print(f"Operação não concluída ({type(erro).__name__}). Verifique .env, permissões e conexão.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
