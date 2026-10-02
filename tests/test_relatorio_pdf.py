import unittest
import pandas as pd
import plotly.graph_objects as go
from relatorio_pdf import gerar_html, preparar_figura, script_botao


class RelatorioPDFTest(unittest.TestCase):
    def test_grafico_vetorial_sem_alterar_original(self):
        original = go.Figure(go.Scattergl(x=[1, 2], y=[3, 4]))
        original.update_layout(paper_bgcolor='#08294E')
        resultado = preparar_figura(original)
        self.assertEqual(resultado.data[0].type, 'scatter')
        self.assertEqual(resultado.layout.paper_bgcolor, 'white')
        self.assertEqual(original.data[0].type, 'scattergl')
        self.assertEqual(original.layout.paper_bgcolor, '#08294E')

    def test_relatorio_autonomo_e_escape(self):
        html = gerar_html(['Benchmark: CDI'], [], [('Alocação', pd.DataFrame({'Fundo': ['<script>'] }))], {})
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('A4 landscape', html)
        self.assertIn('plotly.js', html)
        self.assertNotIn('Fabricio Orlandin', html)
        self.assertIn('TextDecoder', script_botao(html))
