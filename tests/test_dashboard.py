"""Interações do dashboard com dados sintéticos, sem rede ou gravações."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest
from benchmarks import ErroBenchmark


class DashboardTest(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()
        # Nunca consulta o banco real quando o Sharpe carrega CDI automaticamente.
        benchmark = patch('benchmarks.carregar_benchmark', side_effect=ErroBenchmark('CDI indisponível'))
        benchmark.start()
        self.addCleanup(benchmark.stop)

    def test_linhas_estaveis_ao_ultrapassar_mil_pontos(self):
        datas = pd.bdate_range('2024-01-02', periods=501)
        ids = ['a', 'b', 'c']
        fundos = pd.DataFrame({'cnpj': ids, 'nome': ['Fundo A', 'Fundo B', 'Fundo C']})
        cotas = pd.DataFrame({c: np.linspace(100, 110 + i * 5, len(datas))
                              for i, c in enumerate(ids)}, index=datas)
        with (patch('analytics.listar_fundos', return_value=fundos),
              patch('analytics.limites_do_banco', return_value=(datas[0], datas[-1])),
              patch('analytics.carregar_cotas', side_effect=lambda ids, *a, **k: cotas[list(ids)]),
              patch('database.total_simulacoes', return_value=0),
              patch('simulation_counter.contar_analise', return_value=False)):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run(timeout=30)
            for quantidade in (1, 2, 3, 1):
                with self.subTest(quantidade=quantidade):
                    app.multiselect[0].set_value(ids[:quantidade]).run(timeout=30)
                    self.assertFalse(app.exception)
                    grafico = json.loads(app.get('plotly_chart')[0].proto.spec)
                    linhas = [t for t in grafico['data'] if t.get('mode') == 'lines']
                    self.assertEqual({t['name'] for t in linhas}, set(fundos.nome[:quantidade]))
                    self.assertTrue(all(t['type'] == 'scatter' for t in linhas))
                    self.assertTrue(all(len(t['x']) == len(datas) for t in linhas))
                    self.assertEqual(len(grafico['layout']['annotations']), quantidade)
                    if quantidade > 1:
                        final = json.loads(app.get('plotly_chart')[-1].proto.spec)
                        nomes = {t.get('name') for t in final['data'] if t.get('mode') == 'lines'}
                        self.assertEqual(nomes, {'Sua carteira', 'Menor risco', 'Maior retorno esperado'})
                        self.assertTrue(any('Carteira de maior Sharpe indisponível' in w.value for w in app.warning))
                        self.assertEqual([m.value for m in app.metric if m.label == 'Sharpe anualizado (CDI)'], ['—'] * 3)

    def test_duas_subclasses_do_mesmo_cnpj(self):
        datas = pd.bdate_range('2026-08-01', periods=25)
        ids = ['68258527000154::A', '68258527000154::B']
        fundos = pd.DataFrame({'cnpj': ['68258527000154'] * 2,
                               'id_serie': ids, 'nome': ['Fundo — Subclasse A', 'Fundo — Subclasse B']})
        cotas = pd.DataFrame({ids[0]: np.linspace(1, 1.1, 25), ids[1]: np.linspace(2, 2.3, 25)}, index=datas)
        with (patch('analytics.listar_fundos', return_value=fundos),
              patch('analytics.limites_do_banco', return_value=(datas[0], datas[-1])),
              patch('analytics.carregar_cotas', side_effect=lambda ids, *a, **k: cotas[list(ids)]),
              patch('database.total_simulacoes', return_value=0),
              patch('simulation_counter.contar_analise', return_value=False)):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run(timeout=30)
            app.multiselect[0].set_value(ids).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertFalse(app.error)
            self.assertEqual([n.value for n in app.number_input], [50, 50])
            grafico = json.loads(app.get('plotly_chart')[0].proto.spec)
            nomes = {t['name'] for t in grafico['data'] if t.get('mode') == 'lines'}
            self.assertEqual(nomes, set(fundos.nome))

    def test_subclasse_cadastrada_sem_cotas(self):
        datas = pd.bdate_range('2026-08-01', periods=25)
        chave = '68258527000154::E5NM31787344975'
        fundos = pd.DataFrame({'cnpj': ['68258527000154'], 'id_serie': [chave],
                               'nome': ['CAIXA Impulso — Geral']})
        with (patch('analytics.listar_fundos', return_value=fundos),
              patch('analytics.limites_do_banco', return_value=(datas[0], datas[-1])),
              patch('analytics.carregar_cotas', return_value=pd.DataFrame()),
              patch('database.total_simulacoes', return_value=0)):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run(timeout=30)
            app.multiselect[0].set_value([chave]).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(any('CAIXA Impulso — Geral' in w.value for w in app.warning))

    def test_selecao_pesos_e_distribuicao(self):
        datas = pd.bdate_range('2024-01-02', periods=100)
        rng = np.random.default_rng(42)
        cotas = pd.DataFrame(100 * np.cumprod(1 + rng.normal(.0004, .007, (100, 3)), axis=0),
                             index=datas, columns=['a', 'b', 'c'])
        fundos = pd.DataFrame({'cnpj': ['a', 'b', 'c'], 'nome': ['Fundo A', 'Fundo B', 'Fundo C']})
        with (patch('analytics.listar_fundos', return_value=fundos),
              patch('analytics.limites_do_banco', return_value=(datas[0], datas[-1])),
              patch('analytics.carregar_cotas', side_effect=lambda ids, *a, **k: cotas[list(ids)]),
              patch('benchmarks.carregar_benchmark', side_effect=lambda benchmark, *a: pd.Series(
                  np.linspace(100, 105 if benchmark == 'CDI' else 120, len(datas)), index=datas)),
              patch('database.total_simulacoes', return_value=0),
              patch('simulation_counter.contar_analise', return_value=False)):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(app.button[0].disabled)
            self.assertEqual(len(app.tabs), 0)
            app.multiselect[0].set_value(['a', 'b', 'c']).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertAlmostEqual(sum(n.value for n in app.number_input), 100)
            self.assertEqual(len(app.get('plotly_chart')), 5)
            rosca = json.loads(app.get('plotly_chart')[2].proto.spec)
            self.assertEqual(rosca['data'][0]['type'], 'pie')
            self.assertAlmostEqual(sum(rosca['data'][0]['values']), 100)
            valores = cotas.divide(cotas.iloc[0]).mean(axis=1)
            cdi = pd.Series(np.linspace(100, 105, len(datas)), index=datas)
            excessos = (valores.pct_change() - cdi.pct_change()).dropna()
            esperado = f'{excessos.mean() / excessos.std(ddof=1) * np.sqrt(252):.2f}'
            self.assertTrue(any(m.label == 'Índice de Sharpe' and m.value == esperado for m in app.metric))
            self.assertTrue(any('Fabricio Orlandin, CFP®' in m.value for m in app.markdown))
            alocacao_sharpe = next(d.value for d in app.dataframe if 'Restrição' in d.value.columns)['Maior Sharpe'].copy()
            app.selectbox[0].set_value('Ibovespa').run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(any(m.label == 'Índice de Sharpe' and m.value == esperado for m in app.metric))
            pd.testing.assert_series_equal(alocacao_sharpe, next(
                d.value for d in app.dataframe if 'Restrição' in d.value.columns)['Maior Sharpe'])
            app.selectbox[0].set_value('CDI').run(timeout=30)
            self.assertFalse(app.exception)
            grafico = json.loads(app.get('plotly_chart')[-1].proto.spec)
            linhas = [trace for trace in grafico['data'] if trace.get('mode') == 'lines']
            self.assertEqual(len(linhas), 5)
            self.assertEqual(linhas[0]['name'], 'Menor risco')
            self.assertEqual(linhas[1]['name'], 'Maior retorno esperado')
            self.assertEqual(linhas[2]['name'], 'Sua carteira')
            self.assertEqual(linhas[3]['name'], 'Maior Sharpe')
            self.assertEqual(linhas[4]['line']['dash'], 'dash')
            self.assertEqual(len(grafico['layout']['annotations']), 5)
            fronteira = json.loads(app.get('plotly_chart')[-2].proto.spec)
            self.assertTrue(any(t['name'] == 'Maior Sharpe' for t in fronteira['data']))
            tabela = next(d.value for d in app.dataframe if 'Restrição' in d.value.columns)
            esperados = []
            for coluna in ('Menor risco', 'Maior retorno', 'Maior Sharpe'):
                retornos_estaticos = cotas.pct_change().iloc[1:].to_numpy() @ tabela[coluna].to_numpy()
                excessos = retornos_estaticos - cdi.pct_change().iloc[1:].to_numpy()
                esperados.append(f'{excessos.mean() / excessos.std(ddof=1) * np.sqrt(252):.2f}')
            self.assertEqual([m.value for m in app.metric if m.label == 'Sharpe anualizado (CDI)'], esperados)
            app.number_input[0].set_value(10).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(app.warning)
            self.assertEqual(len(app.get('plotly_chart')), 1)
            app.button[0].click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual([n.value for n in app.number_input], [33.34, 33.33, 33.33])
            self.assertEqual(len(app.get('plotly_chart')), 5)
            # Otimiza com 15% travados mesmo antes de completar os pesos livres.
            app.number_input[0].set_value(15).run(timeout=30)
            app.checkbox(key='fixar_a').check().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get('plotly_chart')), 3)
            tabela = next(d.value for d in app.dataframe if 'Restrição' in d.value.columns)
            self.assertAlmostEqual(tabela.iloc[0]['Menor risco'], .15)
            self.assertAlmostEqual(tabela.iloc[0]['Maior retorno'], .15)
            self.assertAlmostEqual(tabela.iloc[0]['Maior Sharpe'], .15)
            grafico = json.loads(app.get('plotly_chart')[-1].proto.spec)
            nomes = {t.get('name') for t in grafico['data'] if t.get('mode') == 'lines'}
            self.assertNotIn('Sua carteira', nomes)
            self.assertIn('Maior Sharpe', nomes)
            self.assertEqual(tabela.iloc[0]['Restrição'], 'Travado')
            app.button[0].click().run(timeout=30)
            self.assertEqual([n.value for n in app.number_input], [15, 42.5, 42.5])
            self.assertEqual(len(app.get('plotly_chart')), 5)
            app.checkbox(key='fixar_b').check().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(any('única carteira' in i.value for i in app.info))
            app.checkbox(key='fixar_c').check().run(timeout=30)
            self.assertTrue(app.button[0].disabled)
            self.assertFalse(app.exception)
            # Restrições inviáveis não produzem uma falsa fronteira.
            app.number_input[0].set_value(16).run(timeout=30)
            self.assertTrue(app.error)
            self.assertEqual(len(app.get('plotly_chart')), 1)
            for c in ['a', 'b', 'c']:
                app.checkbox(key=f'fixar_{c}').uncheck().run(timeout=30)
            app.multiselect[0].set_value(['a']).run(timeout=30)
            app.button[0].click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.number_input[0].value, 100)
            self.assertEqual(len(app.get('plotly_chart')), 3)

    def test_sharpe_indisponivel_preserva_dashboard(self):
        datas = pd.bdate_range('2025-01-02', periods=80)
        fundos = pd.DataFrame({'cnpj': ['a'], 'nome': ['Fundo A']})
        cotas = pd.DataFrame({'a': np.linspace(100, 110, len(datas))}, index=datas)
        cdi = pd.Series(np.linspace(100, 104, len(datas)), index=datas)
        casos = [
            (ErroBenchmark('CDI indisponível'), 80, 'CDI indisponível'),
            (cdi.drop(datas[20]), 80, 'não cobre'),
            (cdi, 25, '60 retornos'),
            (cotas.a, 80, 'praticamente zero'),
        ]
        for resposta, quantidade, motivo in casos:
            with self.subTest(motivo=motivo):
                st.cache_data.clear()
                with (patch('analytics.listar_fundos', return_value=fundos),
                      patch('analytics.limites_do_banco', return_value=(datas[0], datas[quantidade - 1])),
                      patch('analytics.carregar_cotas', return_value=cotas.iloc[:quantidade]),
                      patch('benchmarks.carregar_benchmark',
                            side_effect=resposta if isinstance(resposta, Exception) else None,
                            return_value=resposta),
                      patch('database.total_simulacoes', return_value=0),
                      patch('simulation_counter.contar_analise', return_value=False)):
                    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run(timeout=30)
                    app.multiselect[0].set_value(['a']).run(timeout=30)
                    self.assertFalse(app.exception)
                    self.assertFalse(app.error)
                    self.assertTrue(any(m.label == 'Índice de Sharpe' and m.value == '—' for m in app.metric))
                    self.assertTrue(any(motivo in c.value for c in app.caption))
                    self.assertEqual(len(app.get('plotly_chart')), 3)


if __name__ == '__main__':
    unittest.main()
