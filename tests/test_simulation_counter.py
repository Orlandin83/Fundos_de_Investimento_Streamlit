import unittest
from unittest.mock import patch

import pandas as pd

from database import ErroBanco
from simulation_counter import contar_analise


class ContadorTest(unittest.TestCase):
    def setUp(self):
        self.cotas = pd.DataFrame({'a': [1., 2.], 'b': [2., 3.]})
        self.pesos = pd.Series({'a': .5, 'b': .5})
        self.estado = {}

    @patch('simulation_counter.registrar_simulacao')
    def test_rerun_e_reordenacao_nao_contam_novamente(self, registrar):
        self.assertTrue(contar_analise(self.cotas, self.pesos, self.estado))
        self.assertFalse(contar_analise(self.cotas[['b', 'a']], self.pesos, self.estado))
        registrar.assert_called_once()

    @patch('simulation_counter.registrar_simulacao')
    def test_falha_repete_mesmo_uuid(self, registrar):
        registrar.side_effect = [ErroBanco('Indisponível'), None]
        with self.assertRaises(ErroBanco):
            contar_analise(self.cotas, self.pesos, self.estado)
        self.assertTrue(contar_analise(self.cotas, self.pesos, self.estado))
        self.assertEqual(registrar.call_args_list[0], registrar.call_args_list[1])

    @patch('simulation_counter.registrar_simulacao')
    def test_nova_carteira_e_nova_sessao_contam(self, registrar):
        contar_analise(self.cotas, self.pesos, self.estado)
        contar_analise(self.cotas, pd.Series({'a': .6, 'b': .4}), self.estado)
        contar_analise(self.cotas, self.pesos, {})
        self.assertEqual(registrar.call_count, 3)
        self.assertEqual(len({c.args[0] for c in registrar.call_args_list}), 3)

    @patch('simulation_counter.registrar_simulacao')
    def test_travas_fazem_parte_da_identidade(self, registrar):
        contar_analise(self.cotas, self.pesos, self.estado)
        contar_analise(self.cotas, self.pesos, self.estado, pesos_fixos={'a': .5, 'b': .5})
        contar_analise(self.cotas, self.pesos, self.estado, pesos_fixos={'b': .5, 'a': .5})
        self.assertEqual(registrar.call_count, 2)
