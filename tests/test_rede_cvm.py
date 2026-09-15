import socket
import unittest
import urllib.error
from unittest.mock import patch

from cnpj import ErroCVM, URL_HISTORICO, _abrir_url, main


class RedeCVMTest(unittest.TestCase):
    def test_falhas_mostram_codigo_e_preservam_tentativas(self):
        casos = [
            (urllib.error.HTTPError(URL_HISTORICO, 403, 'detalhe privado', {}, None), 'HTTP 403'),
            (urllib.error.URLError(socket.gaierror(-2, 'detalhe privado')), 'gaierror (errno=-2)'),
            (urllib.error.URLError(ConnectionRefusedError(111, 'detalhe privado')), 'ConnectionRefusedError (errno=111)'),
            (TimeoutError('detalhe privado'), 'tempo de resposta esgotado'),
        ]
        for erro, esperado in casos:
            with self.subTest(esperado=esperado):
                with patch('cnpj.urllib.request.urlopen', side_effect=erro) as abrir, patch('cnpj.time.sleep') as pausa:
                    with self.assertLogs('cotas_cvm', level='WARNING') as logs:
                        with self.assertRaises(ErroCVM) as ctx:
                            _abrir_url(URL_HISTORICO)
                self.assertEqual(abrir.call_count, 4)
                self.assertEqual([c.args[0] for c in pausa.call_args_list], [1, 2, 4])
                self.assertIn(esperado, str(ctx.exception))
                self.assertNotIn('detalhe privado', str(ctx.exception) + str(logs.output))

    @patch('sys.argv', ['cnpj.py'])
    def test_main_exibe_causa_e_retorna_falha(self):
        with patch('cnpj.executar', side_effect=ErroCVM('HTTP 503')):
            with self.assertLogs('cotas_cvm', level='ERROR') as logs:
                self.assertEqual(main(), 1)
        self.assertIn('HTTP 503', logs.output[0])
