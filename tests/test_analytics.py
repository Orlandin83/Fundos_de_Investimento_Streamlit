from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from analytics import calcular_sharpe, historico_carteira_sem_rebalanceamento, retorno_acumulado_base_100


class SharpeTest(unittest.TestCase):
    def setUp(self):
        self.datas = pd.bdate_range('2025-01-02', periods=61)
        self.taxas_cdi = np.linspace(.0003, .0006, 60)
        self.excessos = np.tile([-.002, .004, .001], 20)
        self.cdi = pd.Series(100 * np.r_[1, np.cumprod(1 + self.taxas_cdi)], index=self.datas)
        self.historico = pd.Series(
            100 * np.r_[1, np.cumprod(1 + self.taxas_cdi + self.excessos)], index=self.datas)

    def test_formula_diaria_e_invariancia_de_escala(self):
        esperado = self.excessos.mean() / self.excessos.std(ddof=1) * np.sqrt(252)
        self.assertAlmostEqual(calcular_sharpe(self.historico, self.cdi), esperado)
        self.assertAlmostEqual(calcular_sharpe(self.historico * 7, self.cdi * 2), esperado)

    def test_excesso_negativo(self):
        retornos = self.taxas_cdi - self.excessos
        historico = pd.Series(100 * np.r_[1, np.cumprod(1 + retornos)], index=self.datas)
        esperado = -self.excessos.mean() / self.excessos.std(ddof=1) * np.sqrt(252)
        self.assertAlmostEqual(calcular_sharpe(historico, self.cdi), esperado)

    def test_lacunas_acumulam_cdi_e_ajustam_anualizacao(self):
        datas = pd.bdate_range('2025-01-02', periods=121)
        taxas = np.linspace(.0001, .0009, 120)
        cdi = pd.Series(100 * np.r_[1, np.cumprod(1 + taxas)], index=datas)
        taxas_intervalos = np.prod((1 + taxas).reshape(60, 2), axis=1) - 1
        historico = pd.Series(100 * np.r_[1, np.cumprod(1 + taxas_intervalos + self.excessos)],
                              index=datas[::2])
        esperado = self.excessos.mean() / self.excessos.std(ddof=1) * np.sqrt(252 / 2)
        self.assertAlmostEqual(calcular_sharpe(historico, cdi), esperado)

    def test_carteira_usa_pesos_que_variam_no_tempo(self):
        cotas = pd.DataFrame({'a': self.historico, 'b': self.cdi})
        historico, _ = historico_carteira_sem_rebalanceamento(cotas, pd.Series({'a': .4, 'b': .6}))
        valores = .4 * self.historico.to_numpy() + .6 * self.cdi.to_numpy()
        excessos = valores[1:] / valores[:-1] - 1 - self.taxas_cdi
        esperado = excessos.mean() / excessos.std(ddof=1) * np.sqrt(252)
        self.assertAlmostEqual(calcular_sharpe(historico, self.cdi), esperado)

    def test_amostra_insuficiente(self):
        with self.assertRaisesRegex(ValueError, '60 retornos'):
            calcular_sharpe(self.historico.iloc[:-1], self.cdi)

    def test_volatilidade_zero(self):
        with self.assertRaisesRegex(ValueError, 'praticamente zero'):
            calcular_sharpe(self.cdi, self.cdi)

    def test_cdi_sem_cobertura_nao_preenche_nem_descarta_datas(self):
        for indice in (0, 30, 60):
            with self.subTest(indice=indice), self.assertRaisesRegex(ValueError, 'não cobre'):
                calcular_sharpe(self.historico, self.cdi.drop(self.datas[indice]))

    def test_valores_invalidos(self):
        for valor in (np.nan, np.inf, 0, -1):
            cdi = self.cdi.copy()
            cdi.iloc[30] = valor
            with self.subTest(valor=valor), self.assertRaisesRegex(ValueError, 'positivos e finitos'):
                calcular_sharpe(self.historico, cdi)

    def test_datas_duplicadas(self):
        with self.assertRaisesRegex(ValueError, 'únicas'):
            calcular_sharpe(self.historico, pd.concat([self.cdi, self.cdi.iloc[:1]]))


class RetornoAcumuladoTest(unittest.TestCase):
    def test_converte_base_cem_em_percentual_decimal(self) -> None:
        base_100 = pd.Series([100.0, 125.0, 185.0])

        retorno = retorno_acumulado_base_100(base_100)

        for observado, esperado in zip(retorno, [0.0, 0.25, 0.85], strict=True):
            self.assertAlmostEqual(observado, esperado)


if __name__ == "__main__":
    unittest.main()
