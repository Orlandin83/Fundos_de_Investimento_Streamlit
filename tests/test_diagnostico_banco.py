"""Diagnósticos do coletor sem conexão real nem exposição de credenciais."""
import unittest
from unittest.mock import MagicMock, patch

import psycopg

from cnpj import main
from database import ErroBanco, conectar_banco, diagnostico_banco, operacao_banco


class DiagnosticoBancoTest(unittest.TestCase):
    def test_classifica_falhas_sem_expor_mensagem_original(self):
        casos = [
            (psycopg.errors.InvalidPassword, '', 'Autenticação'),
            (psycopg.errors.InsufficientPrivilege, '', 'Permissão insuficiente'),
            (psycopg.errors.UndefinedTable, '', 'schema ausente'),
            (psycopg.errors.UndefinedColumn, '', 'schema ausente'),
            (psycopg.errors.InvalidCatalogName, '', 'inexistente'),
            (psycopg.OperationalError, 'password authentication failed', 'Autenticação'),
            (psycopg.OperationalError, 'Tenant or user not found', 'Pooler'),
            (psycopg.OperationalError, 'could not translate host name', 'DNS'),
            (psycopg.OperationalError, 'Network is unreachable', 'IPv4/IPv6'),
            (psycopg.OperationalError, 'connection timeout expired', 'esgotado'),
            (psycopg.OperationalError, 'Connection refused', 'recusada'),
            (psycopg.OperationalError, 'SSL certificate verify failed', 'TLS/SSL'),
            (psycopg.OperationalError, 'erro desconhecido', 'Verifique configuração'),
        ]
        for classe, mensagem, esperado in casos:
            with self.subTest(classe=classe, mensagem=mensagem):
                texto = diagnostico_banco(classe(mensagem + ' postgresql://usuario:segredo@servidor-privado/banco'))
                self.assertIn(esperado, texto)
                for sensivel in ('usuario', 'segredo', 'servidor-privado', 'postgresql://'):
                    self.assertNotIn(sensivel, texto)

    @patch('database.load_dotenv')
    @patch.dict('os.environ', {'DATABASE_URL': 'postgresql://usuario:segredo@localhost/banco'})
    def test_erro_conexao_preserva_diagnostico_seguro(self, _):
        with patch('database.psycopg.connect', side_effect=psycopg.OperationalError('password authentication failed segredo')):
            with self.assertRaisesRegex(ErroBanco, 'Não foi possível conectar.*Autenticação') as ctx:
                conectar_banco()
        self.assertNotIn('segredo', str(ctx.exception))
        self.assertTrue(ctx.exception.__suppress_context__)

    @patch('database.load_dotenv')
    @patch.dict('os.environ', {'DATABASE_URL': 'string-invalida-segredo'})
    def test_url_invalida_nao_expoe_segredo(self, _):
        with self.assertRaisesRegex(ErroBanco, 'DATABASE_URL inválida') as ctx:
            conectar_banco()
        self.assertNotIn('segredo', str(ctx.exception))

    def test_leitura_sem_permissao_distinta_de_falha_de_conexao(self):
        with patch('database.conectar_banco', return_value=MagicMock()):
            with self.assertRaisesRegex(ErroBanco, 'operação.*Permissão insuficiente'):
                with operacao_banco():
                    raise psycopg.errors.InsufficientPrivilege('segredo')

    @patch('sys.argv', ['cnpj.py'])
    def test_coletor_exibe_diagnostico_seguro_e_retorna_falha(self):
        with patch('cnpj.executar', side_effect=ErroBanco('Autenticação recusada.')):
            with self.assertLogs('cotas_cvm', level='ERROR') as logs:
                self.assertEqual(main(), 1)
        self.assertIn('Autenticação recusada.', logs.output[0])

    @patch('sys.argv', ['cnpj.py'])
    def test_erro_inesperado_continua_sem_expor_detalhes(self):
        with patch('cnpj.executar', side_effect=RuntimeError('segredo')):
            with self.assertLogs('cotas_cvm', level='ERROR') as logs:
                self.assertEqual(main(), 1)
        self.assertNotIn('segredo', '\n'.join(logs.output))
