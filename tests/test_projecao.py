import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import streamlit as st
from scipy.stats import norm
from streamlit.testing.v1 import AppTest

from projecao import calcular_projecao, recortar_historico, grafico_projecao
from benchmarks import ErroBenchmark


class ProjecaoTest(unittest.TestCase):
    def setUp(self):
        self.datas = pd.date_range('2014-01-01', periods=4400)
        self.logs = np.random.default_rng(42).normal(.0002, .008, len(self.datas) - 1)
        self.cotas = pd.DataFrame({'a': 100 * np.exp(np.r_[0, self.logs.cumsum()])}, index=self.datas)
        self.pesos = pd.Series({'a': 1.})

    def test_quantis_e_capitalizacao(self):
        r = calcular_projecao(self.cotas, self.pesos, 12)
        self.assertAlmostEqual(r.media_log, self.logs.mean() * 365.25)
        self.assertAlmostEqual(r.desvio_log, self.logs.std(ddof=1) * np.sqrt(365.25))
        anterior = (np.inf, -np.inf)
        for p in (.9, .95, .99):
            baixo, alto = r.limites(p)
            cobertura = norm.cdf(np.log1p(alto), r.media_log, r.desvio_log) - norm.cdf(np.log1p(baixo), r.media_log, r.desvio_log)
            self.assertAlmostEqual(cobertura, p)
            self.assertGreater(baixo, -1)
            self.assertLess(baixo, anterior[0])
            self.assertGreater(alto, anterior[1])
            anterior = baixo, alto
        longo = calcular_projecao(self.cotas, self.pesos, 120)
        self.assertAlmostEqual(longo.media_log, 10 * r.media_log)
        self.assertAlmostEqual(longo.desvio_log, np.sqrt(10) * r.desvio_log)
        fig = grafico_projecao(r, 'Teste')
        self.assertEqual(len(fig.data), 4)
        self.assertTrue(all(np.isfinite(t.y).all() for t in fig.data))

    def test_carteira_preserva_correlacao(self):
        cotas = self.cotas.copy()
        cotas['b'] = cotas.a * 3
        r = calcular_projecao(cotas, pd.Series({'a': .5, 'b': .5}), 24)
        unico = calcular_projecao(self.cotas, self.pesos, 24)
        self.assertAlmostEqual(r.desvio_log, unico.desvio_log)

    def test_janelas_e_validacoes(self):
        for meses in (12, 24, 36, 60, 120):
            janela = recortar_historico(self.cotas, meses)
            self.assertEqual(janela.index[-1], self.datas[-1])
            self.assertLessEqual(janela.index[0], self.datas[-1] - pd.DateOffset(months=meses))
        with self.assertRaisesRegex(ValueError, 'completo'):
            recortar_historico(self.cotas.iloc[-100:], 12)
        with self.assertRaisesRegex(ValueError, '60 retornos'):
            calcular_projecao(self.cotas.iloc[:60], self.pesos, 12)
        with self.assertRaisesRegex(ValueError, '100%'):
            calcular_projecao(self.cotas, self.pesos * .5, 12)
        with self.assertRaisesRegex(ValueError, 'nula'):
            calcular_projecao(self.cotas * 0 + 100, self.pesos, 12)
        with self.assertRaisesRegex(ValueError, 'positivas'):
            calcular_projecao(self.cotas * -1, self.pesos, 12)
        irregular = calcular_projecao(self.cotas.iloc[::3], self.pesos, 12)
        self.assertTrue(np.isfinite(irregular.desvio_log))

    def test_dashboard_controles_e_alocacoes(self):
        st.cache_data.clear()
        cotas = self.cotas.copy()
        cotas['b'] = 100 * np.exp(np.r_[0, np.random.default_rng(8).normal(.00015, .005, len(cotas)-1).cumsum()])
        fundos = pd.DataFrame({'cnpj': ['a', 'b'], 'nome': ['A', 'B']})
        with (patch('analytics.listar_fundos', return_value=fundos),
              patch('analytics.limites_do_banco', return_value=(self.datas[0], self.datas[-1])),
              patch('analytics.carregar_cotas', side_effect=lambda ids, *a, **k: cotas[list(ids)]),
              patch('benchmarks.carregar_benchmark', side_effect=ErroBenchmark('Sem CDI')),
              patch('database.total_simulacoes', return_value=0),
              patch('simulation_counter.contar_analise', return_value=False)):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run(timeout=30)
            app.multiselect[0].set_value(['a', 'b']).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox(key='projecao_prazo').value, '12 meses')
            self.assertIn('10 anos', app.selectbox(key='projecao_historico').options)
            self.assertNotIn('Maior Sharpe', app.selectbox(key='projecao_carteira').options)
            pesos = next(d.value for d in app.dataframe if 'Restrição' in d.value.columns).copy()
            app.selectbox(key='projecao_historico').set_value('24 meses').run(timeout=30)
            self.assertEqual(app.selectbox(key='projecao_prazo').value, '24 meses')
            app.selectbox(key='projecao_historico').set_value('Desde o início').run(timeout=30)
            self.assertEqual(app.selectbox(key='projecao_prazo').value, '12 meses')
            app.selectbox(key='projecao_prazo').set_value('10 anos').run(timeout=30)
            app.selectbox(key='projecao_carteira').set_value('Menor risco').run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(any('longo prazo' in w.value for w in app.warning))
            self.assertEqual(app.selectbox(key='projecao_prazo').value, '10 anos')
            pd.testing.assert_frame_equal(pesos, next(d.value for d in app.dataframe if 'Restrição' in d.value.columns))
            self.assertTrue(any('Faixa central do modelo' in d.value.columns for d in app.dataframe))


if __name__ == '__main__':
    unittest.main()
