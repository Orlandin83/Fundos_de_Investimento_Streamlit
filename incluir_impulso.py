"""Cadastra as quatro subclasses Impulso e importa cotas desde a constituição.

Execute: python incluir_impulso.py
Requer a migração supabase/nomes_subclasses.sql e DATABASE_URL no .env.
Os nomes comerciais e identificadores foram fornecidos pelo usuário.
"""
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from psycopg.types.json import Jsonb

from cnpj import baixar_arquivo, descobrir_arquivos, processar_arquivo
from database import listar_fundos, operacao_banco

CNPJ = '68258527000154'
NOMES = {
    '7TMPF1787344237': 'CAIXA Impulso — Singular',
    'E5NM31787344975': 'CAIXA Impulso — Geral',
    'AVTEN1785351970': 'CAIXA Impulso — Private',
    'IF0TS1785352445': 'CAIXA Impulso — Boreal (exclusivo)',
}


def executar():
    # Constituição da classe em 29/07/2026, conforme cadastro CVM.
    arquivos = [a for a in descobrir_arquivos() if a.periodo_final >= '2026-07']
    with operacao_banco() as conexao:
        conexao.execute('''
            INSERT INTO public.fundos (cnpj, nome, atualizado_em, nomes_subclasses)
            VALUES (%s, %s, CURRENT_TIMESTAMP, %s)
            ON CONFLICT (cnpj) DO UPDATE SET nome = EXCLUDED.nome,
                nomes_subclasses = fundos.nomes_subclasses || EXCLUDED.nomes_subclasses,
                atualizado_em = CURRENT_TIMESTAMP
        ''', [CNPJ, 'CAIXA Impulso Debêntures Incentivadas', Jsonb(NOMES)])
        with TemporaryDirectory(prefix='impulso_cvm_') as pasta:
            for arquivo in arquivos:
                print(f'Importando {arquivo.nome}...', flush=True)
                caminho = baixar_arquivo(arquivo, Path(pasta), sobrescrever=True)
                resultado = processar_arquivo(conexao, arquivo, caminho, {CNPJ}, 250_000,
                                             registrar_controle=False)
                print(f'{resultado.inseridas} cotas inseridas; {resultado.atualizadas} atualizadas.', flush=True)
                caminho.unlink()
    fundos = listar_fundos()
    resumo = fundos.loc[fundos.cnpj == CNPJ, ['nome', 'id_subclasse', 'quantidade_registros',
                                            'primeira_data_disponivel', 'ultima_data_disponivel', 'status']]
    print(resumo.to_string(index=False))
    print('Subclasses sem cotas permanecem cadastradas; a coleta regular buscará novas publicações.')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    try:
        executar()
    except KeyboardInterrupt:
        raise SystemExit('Interrompido. Execute novamente: cotas já gravadas não serão duplicadas.')
    except Exception as erro:
        raise SystemExit(f'Importação incompleta ({type(erro).__name__}). Verifique rede, configuração e migração; execute novamente.') from None
