"""Relatório de impressão independente do DOM e dos controles do Streamlit."""
from base64 import b64encode
from html import escape
import json

import plotly.graph_objects as go
from plotly.offline import get_plotlyjs
from avisos import aviso_investimento_html


def preparar_figura(figura):
    dados = figura.to_plotly_json()
    for trace in dados['data']:
        if trace['type'] == 'scattergl':
            trace['type'] = 'scatter'
        if len(trace.get('name', '')) > 48:
            trace['name'] = trace['name'][:45] + '…'
    fig = go.Figure(dados)
    fig.update_layout(
        template='plotly_white', width=1000, height=490,
        paper_bgcolor='white', plot_bgcolor='white',
        font=dict(color='#172b45', size=13), title_font=dict(color='#172b45'),
        margin=dict(l=65, r=90, t=65, b=130),
        legend=dict(orientation='h', x=0, y=-.2, font=dict(size=11, color='#172b45')),
    )
    fig.update_xaxes(gridcolor='#e2e8f0', zerolinecolor='#cbd5e1')
    fig.update_yaxes(gridcolor='#e2e8f0', zerolinecolor='#cbd5e1')
    fig.update_annotations(font_color='#172b45')
    return fig


def tabela_html(tabela):
    return tabela.to_html(index=False, escape=True, border=0, na_rep='—')


def gerar_html(contexto, figuras, tabelas, indicadores):
    partes = ['<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">',
              '<title>Fundos de Investimento</title>', '''<style>
      @page { size:A4 landscape; margin:12mm; }
      * { box-sizing:border-box; }
      body { margin:0; font:13px Arial,sans-serif; color:#172b45; background:white; }
      main { width:1000px; margin:auto; }
      section { break-before:page; padding:8px 0; }
      section:first-child { break-before:auto; }
      h1 { font-size:25px; margin:0 0 12px; } h2 { font-size:19px; }
      p { line-height:1.5; } table { border-collapse:collapse; width:100%; font-size:12px; }
      th,td { text-align:left; padding:8px; border-bottom:1px solid #dce3ec; }
      th { background:#eaf1fa; } tr { break-inside:avoid; } h2 { break-after:avoid; }
      thead { display:table-header-group; }
      .metricas { display:flex; gap:20px; margin:20px 0; }
      .metrica { flex:1; padding:16px; border:1px solid #dce3ec; }
      .metrica strong { display:block; font-size:23px; margin-top:8px; }
      .nota { color:#425570; font-size:12px; }
      .toolbar { padding:12px; background:#eaf1fa; text-align:center; }
      @media print { .toolbar { display:none; } main { width:100%; } }
    </style></head><body>
    <div class="toolbar"><button onclick="window.print()">Salvar como PDF / Imprimir</button>
    Selecione A4 horizontal e desative cabeçalhos e rodapés do navegador.</div><main>
    <section><h1>Fundos de Investimento</h1><p>Análise de fundos e construção de carteiras</p>''']
    partes.append('<p>' + '<br>'.join(escape(linha) for linha in contexto) + '</p>')
    if indicadores:
        partes.append('<div class="metricas">' + ''.join(
            f'<div class="metrica">{escape(k)}<strong>{escape(v)}</strong></div>'
            for k, v in indicadores.items()) + '</div>')
    for titulo, tabela in tabelas:
        partes.append(f'<h2>{escape(titulo)}</h2>{tabela_html(tabela)}')
    partes.append('</section>')
    for indice, (titulo, figura, nota) in enumerate(figuras):
        if any(trace.type == 'pie' for trace in figura.data):
            continue  # A composição completa já consta da tabela inicial.
        div_id = f'chart-{indice}'
        partes.append(f'<section><h1>{escape(titulo)}</h1>')
        partes.append(preparar_figura(figura).to_html(
            full_html=False, include_plotlyjs=False, div_id=div_id,
            config=dict(displayModeBar=False, responsive=False)))
        partes.append(f'<p class="nota">{escape(nota)}</p></section>')
    partes.append('''<section><h1>Metodologia e fontes</h1>
    <p>O histórico simula alocações iniciais sem rebalanceamento. Os percentuais dos
    fundos variam ao longo do tempo. A otimização considera pesos estáticos, sem
    venda a descoberto, mínimo de 1% por fundo e as alocações travadas informadas.</p>
    <p>Retorno esperado: média dos retornos diários simples, anualizada por 252 dias úteis.
    Risco: desvio-padrão calculado com a matriz de covariância, anualizado por √252.
    O Sharpe histórico e o Sharpe com pesos estáticos podem diferir.</p>
    <p>A otimização utiliza o próprio período exibido: trata-se de simulação retrospectiva.
    Resultados passados não representam previsão ou garantia de rentabilidade futura.
    Esta ferramenta não constitui recomendação de investimento.</p>
    <h2>Fontes</h2><p>Fundos: Informe Diário - Portal de Dados Abertos CVM.<br>
    CDI: SGS 12 - Banco Central do Brasil.<br>Ibovespa (^BVSP): Yahoo Finance, coluna Close.</p>
    ''')
    partes.append('<h2>Aviso importante</h2>' + aviso_investimento_html())
    partes.append('</section></main></body></html>')
    # Biblioteca local embutida: não depende de CDN nem dos canvases do site.
    partes.insert(2, '<script>' + get_plotlyjs() + '</script>')
    return ''.join(partes)


def script_botao(html):
    payload = b64encode(html.encode('utf-8')).decode('ascii')
    return '''<script>(() => {
      const button = document.getElementById('gerar-pdf');
      if (!button) return;
      button.disabled = false;
      button.onclick = () => {
        const popup = window.open('', '_blank');
        if (!popup) {
          document.getElementById('pdf-status').textContent = ' Permita a abertura de janelas para gerar o relatório.';
          return;
        }
        const bytes = Uint8Array.from(atob(PAYLOAD), c => c.charCodeAt(0));
        popup.document.open();
        popup.document.write(new TextDecoder().decode(bytes));
        popup.document.close();
      };
    })();</script>'''.replace('PAYLOAD', json.dumps(payload))
