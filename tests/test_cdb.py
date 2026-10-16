"""Cálculo e alinhamento do ativo simulado, sem acesso ao banco."""
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from benchmarks import ErroBenchmark, acumular_taxas_percentuais
from cdb import CDB_ID, incluir_cdb, simular_cdb


class CDBTest(unittest.TestCase):
    def setUp(self):
        self.taxas = pd.Series([.04, .05, .06, .07], index=pd.bdate_range('2026-10-05', periods=4))

    def test_cem_porcento_reproduz_benchmark(self):
        pd.testing.assert_series_equal(simular_cdb(self.taxas, 100), acumular_taxas_percentuais(self.taxas, CDB_ID))

    def test_percentual_aplicado_antes_de_capitalizar(self):
        esperado = 100 * (1 + .0005 * 1.1) * (1 + .0006 * 1.1) * (1 + .0007 * 1.1)
        self.assertAlmostEqual(simular_cdb(self.taxas, 110).iloc[-1], esperado)

    def test_acumula_dias_entre_cotas_do_fundo(self):
        cotas = pd.DataFrame({'fundo': [1., 1.01]}, index=self.taxas.index[[0, 3]])
        with patch('cdb.consultar_benchmark', return_value=self.taxas):
            r = incluir_cdb(cotas, ['fundo', CDB_ID], None, None, 110)
        self.assertEqual(len(r), 2)
        self.assertAlmostEqual(r[CDB_ID].iloc[-1], simular_cdb(self.taxas, 110).iloc[-1])

    def test_fundo_sem_cotas_nao_vira_carteira_so_cdb(self):
        with patch('cdb.consultar_benchmark', return_value=self.taxas):
            self.assertTrue(incluir_cdb(pd.DataFrame(), ['ausente', CDB_ID], None, None, 100).empty)
            r = incluir_cdb(pd.DataFrame(), [CDB_ID], None, None, 100)
            self.assertEqual(len(r), 4)

    def test_dados_invalidos(self):
        for taxa in [0, -1, np.nan, np.inf]:
            with self.assertRaises(ValueError):
                simular_cdb(self.taxas, taxa)
        for serie in [pd.Series(dtype=float), pd.Series([np.nan]), pd.Series([np.inf])]:
            with self.assertRaises(ErroBenchmark):
                simular_cdb(serie, 100)
