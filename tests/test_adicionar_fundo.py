import unittest
from unittest.mock import MagicMock, patch

from adicionar_fundo import editar_cadastro, solicitar_fundos, validar_cnpj
from cnpj import carregar_fundos, processar_arquivo


class AdicionarFundoTest(unittest.TestCase):
    def test_editar_e_excluir_cadastro(self):
        for excluir, resposta, comando in ((False, 'Novo nome', 'UPDATE'), (True, 's', 'DELETE'), (True, 'n', None)):
            with self.subTest(excluir=excluir, resposta=resposta), \
                 patch('adicionar_fundo.operacao_banco') as banco, \
                 patch('builtins.input', side_effect=['00360305000104', resposta]), \
                 patch('builtins.print'):
                conexao = banco.return_value.__enter__.return_value
                conexao.execute.return_value.fetchone.return_value = ('Nome atual',)
                editar_cadastro(excluir=excluir)
                self.assertEqual(conexao.execute.call_count, 2 if comando else 1)
                if comando:
                    consulta, parametros = conexao.execute.call_args.args
                    self.assertTrue(consulta.startswith(comando))
                    self.assertIn('public.fundos', consulta)
                    self.assertNotIn('cotas_diarias', consulta)
                    self.assertEqual(parametros, ['00360305000104'] if excluir else ['Novo nome', '00360305000104'])

    def test_cadastro_ausente_nao_altera_banco(self):
        with patch('adicionar_fundo.operacao_banco') as banco, \
             patch('builtins.input', return_value='00360305000104'), patch('builtins.print'):
            conexao = banco.return_value.__enter__.return_value
            conexao.execute.return_value.fetchone.return_value = None
            editar_cadastro(excluir=True)
            self.assertEqual(conexao.execute.call_count, 1)

    def test_validacao(self):
        self.assertEqual(validar_cnpj('00.360.305/0001-04'), '00360305000104')
        for texto in ('00.360.305/0001-05', '11111111111111', '123', 'abc00360305000104'):
            with self.assertRaises(ValueError):
                validar_cnpj(texto)

    def test_inputs_repeticao_e_correcao(self):
        respostas = ['123', '00360305000104', '', 'Fundo A', 'talvez', 's',
                     '00360305000104', 'Nome corrigido', 'n']
        with patch('builtins.input', side_effect=respostas), patch('builtins.print'):
            fundos = solicitar_fundos()
        self.assertEqual(fundos.to_dict('records'), [{'cnpj': '00360305000104', 'nome': 'Nome corrigido'}])

    def test_cadastro_padrao_vem_do_banco(self):
        with patch('cnpj.listar_cadastro') as listar, patch('cnpj._ler_tabela_fundos_numbers') as numbers:
            listar.return_value.empty = False
            self.assertIs(carregar_fundos(), listar.return_value)
            numbers.assert_not_called()

    def test_importacao_parcial_nao_altera_controle_global(self):
        with patch('cnpj.upsert_lote') as upsert, patch('cnpj.registrar_carga') as registrar:
            resultado = processar_arquivo(MagicMock(), MagicMock(), MagicMock(), {'00360305000104'}, 10,
                                         registrar_controle=False)
            self.assertIs(resultado, upsert.return_value)
            registrar.assert_not_called()


if __name__ == '__main__':
    unittest.main()
