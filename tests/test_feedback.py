"""Avaliações sem acesso ao banco real ou publicação de comentários."""
import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import pandas as pd
from streamlit.testing.v1 import AppTest

from database import ErroBanco
from feedback import QUESTOES, exportar_avaliacoes, registrar_feedback


class FeedbackTest(unittest.TestCase):
    def test_validacao_nao_acessa_banco(self):
        casos = [({'facilidade': None, 'clareza': None, 'utilidade': None}, ''),
                 ({'facilidade': 0, 'clareza': 5, 'utilidade': 5}, ''),
                 ({'facilidade': True, 'clareza': 5, 'utilidade': 5}, ''),
                 ({'facilidade': 6, 'clareza': 5, 'utilidade': 5}, ''),
                 (dict.fromkeys(QUESTOES, 5), 'x' * 2001)]
        with patch('feedback.operacao_banco') as banco:
            for notas, comentario in casos:
                with self.subTest(notas=notas), self.assertRaises(ValueError):
                    registrar_feedback(uuid4(), notas, comentario)
            banco.assert_not_called()

    def test_insert_parametrizado_e_idempotente(self):
        with patch('feedback.operacao_banco') as banco:
            conexao = banco.return_value.__enter__.return_value
            identificador = uuid4()
            registrar_feedback(identificador, dict.fromkeys(QUESTOES, None), "Texto ' especial", True)
            sql, parametros = conexao.execute.call_args.args
            self.assertIn('ON CONFLICT DO NOTHING', sql)
            self.assertNotIn('Texto', sql)
            self.assertEqual(parametros, (identificador, None, None, None, "Texto ' especial", True))

    def test_exportacao_medias_parciais_e_formulas(self):
        dados = pd.DataFrame([
            ['a', '2026-09-23', 5, 3, None, '=HYPERLINK("teste")', True],
            ['b', '2026-09-23', 1, None, 4, 'Uma sugestão; com\nquebra', False],
        ], columns=['id', 'criado_em', *QUESTOES, 'comentario', 'autoriza_trecho'])
        with tempfile.TemporaryDirectory() as pasta, patch('feedback.operacao_banco'), \
                patch('feedback.consultar_dataframe', return_value=dados):
            self.assertEqual(exportar_avaliacoes(Path(pasta)), 2)
            with (Path(pasta) / 'avaliacoes.csv').open(encoding='utf-8-sig', newline='') as arquivo:
                linhas = list(csv.DictReader(arquivo, delimiter=';'))
            self.assertTrue(linhas[0]['comentario'].startswith("'="))
            self.assertEqual(linhas[1]['comentario'], 'Uma sugestão; com\nquebra')
            with (Path(pasta) / 'resumo.csv').open(encoding='utf-8-sig') as arquivo:
                resumo = list(csv.DictReader(arquivo, delimiter=';'))
            self.assertEqual(resumo[0]['Média'], '3,00')
            self.assertEqual(resumo[-1]['Média'], '3,25')
            self.assertEqual(resumo[-1]['Notas respondidas'], '4')
            self.assertEqual((Path(pasta) / 'avaliacoes.csv').stat().st_mode & 0o777, 0o600)

    def test_exportacao_vazia(self):
        dados = pd.DataFrame(columns=['id', 'criado_em', *QUESTOES, 'comentario', 'autoriza_trecho'])
        with tempfile.TemporaryDirectory() as pasta, patch('feedback.operacao_banco'), \
                patch('feedback.consultar_dataframe', return_value=dados):
            self.assertEqual(exportar_avaliacoes(Path(pasta)), 0)
            self.assertTrue((Path(pasta) / 'avaliacoes.csv').exists())

    def app(self):
        return AppTest.from_string('from rodape_feedback import exibir_rodape_feedback\nexibir_rodape_feedback()').run()

    def test_formulario_sem_identificacao_envio_e_sem_duplicacao(self):
        with patch('rodape_feedback.registrar_feedback') as salvar:
            app = self.app()
            self.assertFalse(app.text_input)
            app.button(key='abrir_feedback').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get('feedback')), 3)
            self.assertFalse(app.checkbox[0].value)
            self.assertTrue(all(g.value is None for g in app.get('feedback')))
            app.text_area[0].set_value('Gostaria de comparar outros períodos.')
            next(b for b in app.button if b.label == 'Enviar avaliação').click().run()
            self.assertFalse(app.exception)
            self.assertTrue(app.success)
            salvar.assert_called_once()
            self.assertEqual(salvar.call_args.args[1], dict.fromkeys(QUESTOES, None))
            self.assertFalse(salvar.call_args.args[3])
            app.button(key='abrir_feedback').click().run()
            salvar.assert_called_once()
            self.assertFalse(app.text_area)

    def test_erro_preserva_comentario_e_id_para_reenvio(self):
        with patch('rodape_feedback.registrar_feedback', side_effect=[ErroBanco('Falha'), None]) as salvar:
            app = self.app()
            app.button(key='abrir_feedback').click().run()
            app.text_area[0].set_value('Minha sugestão')
            next(b for b in app.button if b.label == 'Enviar avaliação').click().run()
            self.assertTrue(app.error)
            self.assertEqual(app.text_area[0].value, 'Minha sugestão')
            next(b for b in app.button if b.label == 'Enviar avaliação').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(salvar.call_args_list[0].args[0], salvar.call_args_list[1].args[0])
            self.assertTrue(app.success)

    def test_notas_estrelas_convertidas_e_autorizacao(self):
        with patch('rodape_feedback.registrar_feedback') as salvar:
            app = self.app()
            app.button(key='abrir_feedback').click().run()
            app.get('feedback')[0].set_value(0)
            app.get('feedback')[1].set_value(4)
            app.text_area[0].set_value('Sugestão autorizada')
            app.checkbox[0].check()
            next(b for b in app.button if b.label == 'Enviar avaliação').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(salvar.call_args.args[1], {'facilidade': 1, 'clareza': 5, 'utilidade': None})
            self.assertTrue(salvar.call_args.args[3])

    def test_envio_vazio_nao_grava(self):
        with patch('feedback.operacao_banco') as banco:
            app = self.app()
            app.button(key='abrir_feedback').click().run()
            next(b for b in app.button if b.label == 'Enviar avaliação').click().run()
            self.assertTrue(app.warning)
            banco.assert_not_called()


if __name__ == '__main__':
    unittest.main()
