"""Migração inicial atômica, reiniciável e verificada. DuckDB é somente leitura."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
import random
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import duckdb
import numpy as np
import pandas as pd

from analytics import performance_base_100
from database import CHAVES, COLUNAS, aplicar_schema, conectar_banco, upsert_lote

LOG = logging.getLogger('migracao')
ORIGEM_PADRAO = Path(__file__).resolve().parents[1] / 'dados' / 'fundos.duckdb'
# Metadados de execução/timestamps podem mudar sem alterar o histórico financeiro.
COMPARAR = {
    'fundos': ('cnpj', 'nome'),
    'cotas_diarias': ('cnpj', 'id_subclasse', 'data', 'valor_cota', 'arquivo_origem'),
    'cargas': ('arquivo', 'url', 'periodo_inicial', 'periodo_final', 'linhas_inseridas', 'status', 'erro'),
}


def validar(origem, destino, tamanho_lote=25_000):
    """Compara TODAS as chaves/cotas, além de agregados e retornos amostrados."""
    relatorio = {}
    for tabela, campos in COMPARAR.items():
        quantidade = origem.execute(f'SELECT count(*) FROM {tabela}').fetchone()[0]
        recebidas = destino.execute(f'SELECT count(*) FROM public.{tabela}').fetchone()[0]
        if quantidade != recebidas:
            raise ValueError(f'{tabela}: contagem divergente: origem={quantidade}, destino={recebidas}')
        consulta = f'SELECT {", ".join(campos)} FROM {{prefixo}}{tabela} ORDER BY {", ".join(CHAVES[tabela])}'
        leitor = origem.execute(consulta.format(prefixo=''))
        with destino.cursor(name=f'validar_{tabela}') as cursor:
            cursor.execute(consulta.format(prefixo='public.'))
            while True:
                esperado = leitor.fetchmany(tamanho_lote)
                observado = cursor.fetchmany(tamanho_lote)
                if esperado != observado:
                    raise ValueError(f'{tabela}: conteúdo divergente; migração não validada.')
                if not esperado:
                    break
        relatorio[tabela] = quantidade
        LOG.info('%s: %s registros; todas as chaves e valores conferidos', tabela, quantidade)
    consulta = 'SELECT cnpj, count(*), min(data), max(data) FROM {prefixo}cotas_diarias GROUP BY cnpj ORDER BY cnpj'
    estatisticas = origem.execute(consulta.format(prefixo='')).fetchall()
    if estatisticas != destino.execute(consulta.format(prefixo='public.')).fetchall():
        raise ValueError('Cobertura por CNPJ divergente.')
    LOG.info('%s fundos com cotas; contagens e limites por CNPJ conferidos', len(estatisticas))
    amostra = random.Random(42).sample(estatisticas, min(5, len(estatisticas)))
    for cnpj, quantidade, primeira, ultima in amostra:
        # Cada subclasse permanece separada, inclusive ao comparar retornos.
        consulta = 'SELECT data, id_subclasse, valor_cota FROM {prefixo}cotas_diarias WHERE cnpj = {param} ORDER BY data, id_subclasse'
        antes = pd.DataFrame(origem.execute(consulta.format(prefixo='', param='?'), [cnpj]).fetchall(), columns=['data', 'subclasse', 'cota'])
        depois = pd.DataFrame(destino.execute(consulta.format(prefixo='public.', param='%s'), [cnpj]).fetchall(), columns=['data', 'subclasse', 'cota'])
        for subclasse in antes['subclasse'].unique():
            a = antes[antes.subclasse == subclasse].set_index('data')[['cota']]
            b = depois[depois.subclasse == subclasse].set_index('data')[['cota']]
            np.testing.assert_array_equal(a.pct_change(fill_method=None).to_numpy(), b.pct_change(fill_method=None).to_numpy())
            np.testing.assert_array_equal(performance_base_100(a).to_numpy(), performance_base_100(b).to_numpy())
        LOG.info('CNPJ %s: %s cotas, %s a %s; retornos e base 100 idênticos', cnpj, quantidade, primeira, ultima)
    return relatorio


def migrar(origem, destino, tamanho_lote=25_000):
    existentes = {r[0] for r in origem.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE'").fetchall()}
    if existentes != set(COLUNAS):
        raise ValueError('Tabelas da origem diferentes do esquema esperado; revise antes de migrar.')
    # Uma única transação impede cadastro/cargas parcialmente publicados.
    with destino.transaction():
        destino.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        for tabela, campos in COLUNAS.items():
            colunas_origem = {r[0] for r in origem.execute(f"DESCRIBE {tabela}").fetchall()}
            esperadas = set(campos) - ({'linhas_atualizadas'} if tabela == 'cargas' else set())
            if colunas_origem != esperadas:
                raise ValueError(f'{tabela}: colunas inesperadas; revise o mapeamento.')
            total = origem.execute(f'SELECT count(*) FROM {tabela}').fetchone()[0]
            expressao = ', '.join(c if c in colunas_origem else '0 AS linhas_atualizadas' for c in campos)
            leitor = origem.execute(f'SELECT {expressao} FROM {tabela} ORDER BY {", ".join(CHAVES[tabela])}')
            processadas = 0
            while lote := leitor.fetchmany(tamanho_lote):
                resultado = upsert_lote(destino, tabela, lote, preservar_mais_recentes=True)
                processadas += len(lote)
                LOG.info('%s: %s/%s; lote: %s inseridas, %s atualizadas', tabela, processadas, total, resultado.inseridas, resultado.atualizadas)
        relatorio = validar(origem, destino, tamanho_lote)
    LOG.info('COMMIT concluído: migração validada e persistida.')
    return relatorio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origem', type=Path, default=ORIGEM_PADRAO)
    parser.add_argument('--tamanho-lote', type=int, default=25_000)
    parser.add_argument('--aplicar-schema', action='store_true')
    parser.add_argument('--validar-apenas', action='store_true')
    args = parser.parse_args()
    if args.tamanho_lote <= 0:
        parser.error('--tamanho-lote deve ser positivo')
    if args.aplicar_schema and args.validar_apenas:
        parser.error('--validar-apenas não pode aplicar schema')
    logging.basicConfig(level=logging.INFO, format='%(levelname)s | %(message)s')
    try:
        if not args.origem.is_file():
            raise ValueError('Arquivo DuckDB de origem não encontrado.')
        if args.aplicar_schema:
            aplicar_schema()
        with duckdb.connect(str(args.origem), read_only=True) as origem, conectar_banco() as destino:
            if args.validar_apenas:
                with destino.transaction():
                    destino.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                    validar(origem, destino, args.tamanho_lote)
            else:
                migrar(origem, destino, args.tamanho_lote)
        return 0
    except (ValueError, AssertionError) as erro:
        LOG.error('%s', erro)
    except Exception as erro:
        LOG.error('Migração não concluída (%s). Verifique conexão e schema; credenciais omitidas.', type(erro).__name__)
    return 1


if __name__ == '__main__':
    sys.exit(main())
