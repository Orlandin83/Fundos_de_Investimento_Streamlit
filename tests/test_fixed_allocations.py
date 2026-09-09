"""Valida restrições e compara o mínimo de risco com busca independente."""
import unittest

import numpy as np
import pandas as pd

from analytics import calcular_fronteira_eficiente, validar_alocacoes_fixas


class AlocacoesFixasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = np.random.default_rng(17)
        retornos = rng.normal([.0003, .0006, .0009], [.009, .013, .02], (180, 3))
        cls.cotas = pd.DataFrame(100 * np.cumprod(1 + retornos, axis=0),
                                index=pd.bdate_range('2024-01-01', periods=180), columns=['a', 'b', 'c'])

    def calcular(self, fixos=None, **kwargs):
        return calcular_fronteira_eficiente(self.cotas, quantidade_pontos=12,
                                            quantidade_simulacoes=100, pesos_fixos=fixos, **kwargs)

    def test_quinze_porcento_e_minimo_por_busca_independente(self):
        r = self.calcular({'a': .15})
        for p in [r.pesos_minimo_risco, r.pesos_maior_retorno, *r.pontos.pesos]:
            self.assertAlmostEqual(p[0] if isinstance(p, np.ndarray) else p['a'], .15, places=12)
            self.assertAlmostEqual(sum(p), 1, places=10)
            self.assertGreaterEqual(min(p), .01 - 1e-10)
        retornos = self.cotas.pct_change().dropna()
        cov = retornos.cov().to_numpy() * 252
        media = retornos.mean().to_numpy() * 252
        b = np.linspace(.01, .84, 10001)
        grade = np.column_stack([np.full(len(b), .15), b, .85 - b])
        variancias = np.einsum('ij,jk,ik->i', grade, cov, grade)
        self.assertLessEqual(r.risco_minimo ** 2, variancias.min() + 1e-9)
        self.assertAlmostEqual(r.retorno_maximo, (grade @ media).max(), places=10)
        # A nuvem deve ficar no intervalo de retornos permitido pelas travas.
        self.assertGreaterEqual(r.carteiras_testadas.retorno.min(), (grade @ media).min() - 1e-10)
        self.assertLessEqual(r.carteiras_testadas.retorno.max(), (grade @ media).max() + 1e-10)

    def test_duas_travas_deixam_uma_carteira(self):
        r = self.calcular({'a': .15, 'b': .25})
        self.assertTrue(r.carteira_unica)
        np.testing.assert_allclose(r.pesos_minimo_risco, [.15, .25, .60])
        np.testing.assert_allclose(r.pesos_maior_retorno, r.pesos_minimo_risco)
        self.assertEqual(len(r.pontos), 1)
        np.testing.assert_allclose(r.carteiras_testadas.risco, r.risco_minimo)

    def test_todos_travados(self):
        r = self.calcular({'a': .15, 'b': .25, 'c': .60})
        self.assertTrue(r.carteira_unica)
        np.testing.assert_allclose(r.pesos_minimo_risco, [.15, .25, .60])

    def test_saldo_exatamente_igual_aos_pisos(self):
        r = self.calcular({'a': .98})
        self.assertTrue(r.carteira_unica)
        np.testing.assert_allclose(r.pesos_minimo_risco, [.98, .01, .01])

    def test_restricoes_invalidas(self):
        for fixos in ({'a': .99}, {'a': .5, 'b': .6}, {'a': float('nan')},
                      {'a': -.1}, {'a': 0}, {'a': .15, 'b': .25, 'c': .5}, {'fora': .15}):
            with self.subTest(fixos=fixos), self.assertRaises(ValueError):
                validar_alocacoes_fixas(['a', 'b', 'c'], fixos)

    def test_sem_travas_e_dicionario_vazio_equivalentes(self):
        a, b = self.calcular(), self.calcular({})
        np.testing.assert_allclose(a.pesos_minimo_risco, b.pesos_minimo_risco)
        np.testing.assert_allclose(a.pesos_maior_retorno, b.pesos_maior_retorno)
        self.assertFalse(a.carteira_unica)

    def test_ordem_dos_fundos_nao_altera_resultado(self):
        a = self.calcular({'a': .15})
        b = calcular_fronteira_eficiente(self.cotas[['c', 'a', 'b']], quantidade_pontos=12, pesos_fixos={'a': .15})
        np.testing.assert_allclose(a.pesos_minimo_risco, b.pesos_minimo_risco.reindex(['a', 'b', 'c']), atol=1e-7)

    def test_retornos_iguais(self):
        cotas = self.cotas.assign(b=self.cotas.a, c=self.cotas.a)
        r = calcular_fronteira_eficiente(cotas, pesos_fixos={'a': .15})
        self.assertFalse(r.carteira_unica)
        self.assertEqual(len(r.pontos), 1)
        self.assertAlmostEqual(r.pesos_minimo_risco['a'], .15)
        self.assertAlmostEqual(r.retorno_maximo, r.retorno_minimo_risco)

    def test_quatro_fundos_com_duas_travas_de_quinze_porcento(self):
        rng = np.random.default_rng(82)
        retornos = rng.normal([.0007, .0004, .0003, .0002], [.014, .012, .003, .006], (250, 4))
        cotas = pd.DataFrame(100 * np.cumprod(1 + retornos, axis=0), columns=['a', 'b', 'c', 'd'])
        r = calcular_fronteira_eficiente(cotas, pesos_fixos={'a': .15, 'b': .15})
        observados = cotas.pct_change().dropna()
        media, cov = observados.mean().to_numpy() * 252, observados.cov().to_numpy() * 252
        c = np.linspace(.01, .69, 20001)
        grade = np.column_stack([np.full(len(c), .15), np.full(len(c), .15), c, .70 - c])
        risco_grade = np.sqrt(np.einsum('ij,jk,ik->i', grade, cov, grade))
        self.assertAlmostEqual(r.risco_minimo, risco_grade.min(), places=7)
        self.assertAlmostEqual(r.retorno_maximo, (grade @ media).max(), places=10)
        for pesos in r.pontos.pesos:
            np.testing.assert_allclose(pesos[:2], [.15, .15], atol=1e-12)
            self.assertAlmostEqual(sum(pesos[2:]), .70, places=12)
        # Com dois livres, cada retorno determina uma única divisão do saldo.
        # Confere também a nuvem independentemente, pelas duas equações de pesos.
        for pontos in (r.pontos, r.carteiras_testadas):
            peso_c = (pontos.retorno.to_numpy() - .15 * media[0] - .15 * media[1] - .70 * media[3]) / (media[2] - media[3])
            reconstruidos = np.column_stack([np.full(len(peso_c), .15), np.full(len(peso_c), .15), peso_c, .70 - peso_c])
            riscos = np.sqrt(np.einsum('ij,jk,ik->i', reconstruidos, cov, reconstruidos))
            np.testing.assert_allclose(pontos.risco, riscos, atol=1e-9)
        eficientes = r.pontos[r.pontos.retorno >= r.retorno_minimo_risco]
        self.assertTrue((np.diff(eficientes.risco) >= -1e-8).all())
