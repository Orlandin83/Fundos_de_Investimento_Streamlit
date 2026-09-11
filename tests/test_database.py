"""Integração apenas em PostgreSQL LOCAL descartável: TEST_DATABASE_URL.

O nome do banco deve começar com fundos_test. Nunca usa DATABASE_URL de produção.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

import pandas as pd
import psycopg
from psycopg.conninfo import conninfo_to_dict

from analytics import carregar_cotas
from cnpj import ArquivoCVM, carregar_fundos, criar_parser, executar, processar_arquivo
from database import aplicar_schema, conectar_banco, listar_fundos, registrar_simulacao, total_simulacoes, upsert_lote


@unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'Defina TEST_DATABASE_URL para PostgreSQL local descartável')
class PostgreSQLTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ['TEST_DATABASE_URL']
        p = conninfo_to_dict(url)
        if not p.get('dbname', '').startswith('fundos_test') or not (p.get('host') in ('localhost', '127.0.0.1', '::1') or p.get('host', '').startswith('/tmp/')):
            raise RuntimeError('Testes exigem banco local descartável chamado fundos_test*.')
        cls.ambiente = patch.dict(os.environ, {'DATABASE_URL': url})
        cls.ambiente.start()
        cls.addClassCleanup(cls.ambiente.stop)
        aplicar_schema()

    def setUp(self):
        self.conexao = conectar_banco()
        self.addCleanup(self.conexao.close)
        self.conexao.execute('TRUNCATE public.cotas_diarias, public.fundos, public.cargas, public.simulacoes')
        self.agora = datetime.now(timezone.utc)
        self.cnpj = '00000000000001'
        upsert_lote(self.conexao, 'fundos', [(self.cnpj, 'Fundo teste', self.agora)])

    def registro(self, valor=1.2345678901234567, dia=1, subclasse=''):
        return (self.cnpj, subclasse, date(2026, 1, dia), valor, 'teste.zip', self.agora)

    def test_upsert_idempotencia_correcao_subclasse_e_precisao(self):
        r = upsert_lote(self.conexao, 'cotas_diarias', [self.registro()])
        self.assertEqual((r.inseridas, r.atualizadas), (1, 0))
        antes = self.conexao.execute('SELECT * FROM public.cotas_diarias').fetchall()
        r = upsert_lote(self.conexao, 'cotas_diarias', [self.registro()])
        self.assertEqual((r.inseridas, r.atualizadas), (0, 0))
        self.assertEqual(antes, self.conexao.execute('SELECT * FROM public.cotas_diarias').fetchall())
        r = upsert_lote(self.conexao, 'cotas_diarias', [self.registro(2), self.registro(3, subclasse='A')])
        self.assertEqual((r.inseridas, r.atualizadas), (1, 1))
        with self.assertRaisesRegex(ValueError, 'subclasses'):
            carregar_cotas([self.cnpj], pd.Timestamp('2026-01-01'), pd.Timestamp('2026-01-02'))

    def test_duplicatas_lote_ultima_ocorrencia(self):
        r = upsert_lote(self.conexao, 'cotas_diarias', [self.registro(2), self.registro(3)])
        self.assertEqual((r.inseridas, r.atualizadas), (1, 0))
        self.assertEqual(self.conexao.execute('SELECT valor_cota FROM public.cotas_diarias').fetchone()[0], 3)

    def test_series_separadas_por_subclasse(self):
        upsert_lote(self.conexao, 'cotas_diarias', [self.registro(1), self.registro(2, subclasse='A'),
                                                   self.registro(3, dia=2, subclasse='A')])
        fundos = listar_fundos()
        self.assertEqual(set(fundos.id_serie), {self.cnpj + '::', self.cnpj + '::A'})
        series = [self.cnpj + '::', self.cnpj + '::A']
        cotas = carregar_cotas(series, pd.Timestamp('2026-01-01'), pd.Timestamp('2026-01-02'), datas_comuns=False)
        self.assertEqual(cotas.iloc[0].tolist(), [1, 2])
        self.assertTrue(pd.isna(cotas.iloc[1, 0]))
        self.assertEqual(cotas.iloc[1, 1], 3)

    def test_transacao_desfaz_todos_lotes(self):
        arquivo = ArquivoCVM('teste.zip', 'https://exemplo.invalid/teste.zip', '2026-01', '2026-01', True)
        upsert_lote(self.conexao, 'cotas_diarias', [self.registro(1)])
        def lotes(*args):
            yield pd.DataFrame([(self.cnpj, '', pd.Timestamp('2026-01-01'), 2.)], columns=['cnpj', 'id_subclasse', 'data', 'valor_cota'])
            raise ValueError('Arquivo interrompido')
        with patch('cnpj.ler_lotes_filtrados', side_effect=lotes), self.assertRaises(ValueError):
            processar_arquivo(self.conexao, arquivo, Path('teste.zip'), {self.cnpj}, 10)
        self.assertEqual(self.conexao.execute('SELECT valor_cota FROM public.cotas_diarias').fetchone()[0], 1)
        self.assertEqual(self.conexao.execute('SELECT count(*) FROM public.cargas').fetchone()[0], 0)

    def test_reprocessamento_preserva_ausentes_e_filtra_consulta(self):
        arquivo = ArquivoCVM('teste.zip', 'https://exemplo.invalid/teste.zip', '2026-01', '2026-01', True)
        upsert_lote(self.conexao, 'cotas_diarias', [self.registro(dia=1), self.registro(dia=2)])
        lote = pd.DataFrame([(self.cnpj, '', pd.Timestamp('2026-01-02'), 3.)], columns=['cnpj', 'id_subclasse', 'data', 'valor_cota'])
        with patch('cnpj.ler_lotes_filtrados', return_value=[lote]):
            r = processar_arquivo(self.conexao, arquivo, Path('teste.zip'), {self.cnpj}, 10)
        self.assertEqual((r.inseridas, r.atualizadas), (0, 1))
        self.assertEqual(self.conexao.execute('SELECT count(*) FROM public.cotas_diarias').fetchone()[0], 2)
        cotas = carregar_cotas([self.cnpj], pd.Timestamp('2026-01-02'), pd.Timestamp('2026-01-02'))
        self.assertEqual(cotas.shape, (1, 1))
        self.assertEqual(str(cotas.index.dtype), "datetime64[us]")
        self.assertEqual(cotas.iloc[0, 0], 3.)

    def test_contador_concorrente_idempotente(self):
        ids = [uuid4() for _ in range(5)]
        with ThreadPoolExecutor(max_workers=5) as pool:
            list(pool.map(registrar_simulacao, ids * 3))
        self.assertEqual(total_simulacoes(), 5)

    def test_duplicata_entre_lotes_e_idempotencia_do_arquivo(self):
        arquivo = ArquivoCVM('teste.zip', 'https://exemplo.invalid/teste.zip', '2026-01', '2026-01', True)
        colunas = ['cnpj', 'id_subclasse', 'data', 'valor_cota']
        lotes = [pd.DataFrame([(self.cnpj, '', pd.Timestamp('2026-01-01'), v)], columns=colunas) for v in (2., 3.)]
        with patch('cnpj.ler_lotes_filtrados', return_value=lotes):
            primeiro = processar_arquivo(self.conexao, arquivo, Path('teste.zip'), {self.cnpj}, 1)
            antes = self.conexao.execute('SELECT * FROM public.cotas_diarias').fetchall()
            segundo = processar_arquivo(self.conexao, arquivo, Path('teste.zip'), {self.cnpj}, 1)
        self.assertEqual((primeiro.inseridas, primeiro.atualizadas), (1, 0))
        self.assertEqual((segundo.inseridas, segundo.atualizadas), (0, 0))
        self.assertEqual(antes, self.conexao.execute('SELECT * FROM public.cotas_diarias').fetchall())

    def test_papeis_backend_com_rls(self):
        self.conexao.execute((Path(__file__).resolve().parents[1] / 'supabase/backend_roles.sql').read_text())
        self.conexao.execute('SET ROLE fundos_coletor')
        try:
            upsert_lote(self.conexao, 'cotas_diarias', [self.registro()])
        finally:
            self.conexao.execute('RESET ROLE')

        self.conexao.execute('SET ROLE fundos_app')
        try:
            self.assertEqual(self.conexao.execute('SELECT count(*) FROM public.fundos_controle').fetchone()[0], 1)
            evento = uuid4()
            for _ in range(2):
                self.conexao.execute('INSERT INTO public.simulacoes (id) VALUES (%s) ON CONFLICT DO NOTHING', [evento])
            self.assertEqual(self.conexao.execute('SELECT count(*) FROM public.simulacoes').fetchone()[0], 1)
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.conexao.execute('UPDATE public.cotas_diarias SET valor_cota=0')
        finally:
            self.conexao.execute('RESET ROLE')

    def test_coletor_com_zip_cvm_e_cadastro_postgres(self):
        with tempfile.TemporaryDirectory() as pasta:
            cadastro = carregar_fundos(Path(pasta) / 'ausente.numbers')
            self.assertEqual(cadastro['cnpj'].tolist(), [self.cnpj])
            arquivo = ArquivoCVM('teste.zip', 'https://exemplo.invalid/teste.zip', '2026-01', '2026-01', True)
            with ZipFile(Path(pasta) / arquivo.nome, 'w') as zipado:
                zipado.writestr('informe.csv', 'CNPJ_FUNDO_CLASSE;ID_SUBCLASSE;DT_COMPTC;VL_QUOTA\n'
                    f'{self.cnpj};;2026-01-01;1.2345678901234567\n'
                    f'{self.cnpj};;2026-01-02;2.5\n'
                    f'{self.cnpj};A;2026-01-03;3.5\n'
                    f'{self.cnpj};;2026-01-04;inf\n'
                    f'{self.cnpj};;invalida;4.5\n'
                    '99999999999999;;2026-01-01;1\n')
            args = criar_parser().parse_args(['--cache', pasta, '--manter-cache', '--forcar', '--meses-reprocessar', '0', '--tamanho-lote', '1'])
            with patch('cnpj.carregar_fundos', return_value=cadastro), patch('cnpj.descobrir_arquivos', return_value=[arquivo]):
                self.assertEqual(executar(args), 0)
                self.assertEqual(executar(args), 0)
            self.assertEqual(self.conexao.execute('SELECT count(*) FROM public.cotas_diarias').fetchone()[0], 3)
            self.assertEqual(self.conexao.execute('SELECT status, linhas_inseridas, linhas_atualizadas FROM public.cargas').fetchone(), ('OK', 0, 0))

    def test_schema_reexecutavel_e_rls(self):
        upsert_lote(self.conexao, 'cotas_diarias', [self.registro()])
        aplicar_schema()
        self.assertEqual(self.conexao.execute('SELECT count(*) FROM public.cotas_diarias').fetchone()[0], 1)
        self.assertTrue(self.conexao.execute("SELECT bool_and(relrowsecurity) FROM pg_class WHERE oid IN ('public.fundos'::regclass, 'public.cotas_diarias'::regclass, 'public.cargas'::regclass, 'public.simulacoes'::regclass)").fetchone()[0])
