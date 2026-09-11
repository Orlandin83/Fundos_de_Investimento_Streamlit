"""Interações do dashboard com dados sintéticos, sem rede ou gravações."""
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest


class DashboardTest(unittest.TestCase):
    def setUp(self):
        st.cache_data.clear()

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

    def test_selecao_pesos_e_distribuicao(self):
        datas = pd.bdate_range('2024-01-02', periods=100)
        rng = np.random.default_rng(42)
        cotas = pd.DataFrame(100 * np.cumprod(1 + rng.normal(.0004, .007, (100, 3)), axis=0),
                             index=datas, columns=['a', 'b', 'c'])
        fundos = pd.DataFrame({'cnpj': ['a', 'b', 'c'], 'nome': ['Fundo A', 'Fundo B', 'Fundo C']})
        with (patch('analytics.listar_fundos', return_value=fundos),
              patch('analytics.limites_do_banco', return_value=(datas[0], datas[-1])),
              patch('analytics.carregar_cotas', side_effect=lambda ids, *a, **k: cotas[list(ids)]),
              patch('benchmarks.carregar_benchmark', return_value=pd.Series(np.linspace(100, 105, len(datas)), index=datas)),
              patch('database.total_simulacoes', return_value=0),
              patch('simulation_counter.contar_analise', return_value=False)):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(app.button[0].disabled)
            self.assertEqual(len(app.tabs), 0)
            app.multiselect[0].set_value(['a', 'b', 'c']).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertAlmostEqual(sum(n.value for n in app.number_input), 100)
            self.assertEqual(len(app.get('plotly_chart')), 4)
            app.selectbox[0].set_value('CDI').run(timeout=30)
            self.assertFalse(app.exception)
            grafico = json.loads(app.get('plotly_chart')[-1].proto.spec)
            linhas = [trace for trace in grafico['data'] if trace.get('mode') == 'lines']
            self.assertEqual(len(linhas), 3)
            self.assertEqual(linhas[0]['name'], 'Menor risco')
            self.assertEqual(linhas[1]['name'], 'Maior retorno esperado')
            self.assertEqual(linhas[2]['line']['dash'], 'dash')
            self.assertEqual(len(grafico['layout']['annotations']), 3)
            app.number_input[0].set_value(10).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(app.warning)
            self.assertEqual(len(app.get('plotly_chart')), 1)
            app.button[0].click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual([n.value for n in app.number_input], [33.34, 33.33, 33.33])
            self.assertEqual(len(app.get('plotly_chart')), 4)
            # Otimiza com 15% travados mesmo antes de completar os pesos livres.
            app.number_input[0].set_value(15).run(timeout=30)
            app.checkbox(key='fixar_a').check().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get('plotly_chart')), 3)
            tabela = next(d.value for d in app.dataframe if 'Restrição' in d.value.columns)
            self.assertAlmostEqual(tabela.iloc[0]['Menor risco'], .15)
            self.assertAlmostEqual(tabela.iloc[0]['Maior retorno'], .15)
            self.assertEqual(tabela.iloc[0]['Restrição'], 'Travado')
            app.button[0].click().run(timeout=30)
            self.assertEqual([n.value for n in app.number_input], [15, 42.5, 42.5])
            self.assertEqual(len(app.get('plotly_chart')), 4)
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
            self.assertEqual(len(app.get('plotly_chart')), 2)


if __name__ == '__main__':
    unittest.main()
