"""Aplicativo Streamlit para comparar fundos e analisar carteiras."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analytics import (
    ALOCACAO_MINIMA_FRONTEIRA,
    MINIMO_OBSERVACOES,
    calcular_fronteira_eficiente,
    carregar_cotas,
    historico_carteira_sem_rebalanceamento,
    limites_do_banco,
    listar_fundos,
    performance_base_100,
    retorno_acumulado_base_100,
    risco_retorno_carteira_estatica,
)
from benchmarks import (
    BENCHMARK_NENHUM,
    FONTES_BENCHMARK,
    NOMES_SERIES,
    OPCOES_BENCHMARK,
    ErroBenchmark,
    carregar_benchmark,
)


BASE_DIR = Path(__file__).resolve().parent
BANCO = BASE_DIR / "dados" / "fundos.duckdb"
CORES = ["#66C3BC", "#A9D8D3", "#4A9F9A", "#D5DDDE", "#718A91", "#3A7D7A"]
COR_PAINEL = "#30363D"
COR_GRADE = "#444B53"
COR_TEXTO = "#EDF1F2"
COR_TEXTO_SECUNDARIO = "#AEB8BB"

st.set_page_config(
    page_title="Fundos de Investimento | Performance e Carteiras",
    page_icon="📈",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp {
        background:
            radial-gradient(circle at 12% 0%, rgba(102,195,188,.08), transparent 28rem),
            #252a30;
    }
    [data-testid="stHeader"] { background: rgba(37,42,48,.9); }
    [data-testid="stToolbar"] { color: #aeb8bb; }
    [data-testid="stMainBlockContainer"] { max-width: 1280px; padding-top: 2.2rem; }
    .hero {
        position: relative; overflow: hidden; padding: 2rem 2.2rem;
        border: 1px solid #454c54; border-radius: 18px; color: #edf1f2;
        background: linear-gradient(125deg, #343a41 0%, #2b3036 62%, #293b3d 100%);
        box-shadow: 0 18px 42px rgba(10,13,16,.28); margin-bottom: 1.35rem;
    }
    .hero::after {
        content: ""; position: absolute; width: 220px; height: 220px;
        right: -72px; top: -112px; border: 38px solid rgba(102,195,188,.12);
        border-radius: 50%;
    }
    .hero-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 2rem; }
    .hero h1 { margin: 0; font-size: 2rem; letter-spacing: -.025em; }
    .hero p { margin: .55rem 0 0; color: #aeb8bb; }
    .hero-author { z-index: 1; text-align: right; font-size: .86rem; color: #aeb8bb; white-space: nowrap; }
    .hero-author strong { color: #7fd0ca; }
    @media (max-width: 700px) {
        .hero-row { flex-direction: column; gap: 1rem; }
        .hero-author { text-align: left; }
    }
    h1, h2, h3, h4 { color: #f4f6f6 !important; letter-spacing: -.015em; }
    p, label, [data-testid="stCaptionContainer"] { color: #aeb8bb; }
    [data-testid="stWidgetLabel"] p { color: #dce2e3; }
    button[data-baseweb="tab"] { color: #aeb8bb; }
    button[data-baseweb="tab"][aria-selected="true"] { color: #7fd0ca; }
    [data-baseweb="tab-highlight"] { background-color: #66c3bc; }
    [data-baseweb="input"], [data-baseweb="select"] > div,
    [data-testid="stNumberInputContainer"] {
        background: #30363d !important; border-color: #4b535c !important;
    }
    [data-baseweb="input"] input { color: #edf1f2; }
    [data-testid="stDataFrame"] { border: 1px solid #414850; border-radius: 10px; overflow: hidden; }
    .disclaimer {
        padding: .9rem 1rem; border-left: 4px solid #f9a825;
        background: #34383a; border-radius: 8px; color: #d8d1b7;
    }
    .fontes-rodape {
        margin-top: 2.2rem; padding: 1rem 0 .25rem;
        border-top: 1px solid #414850; color: #8f9a9e;
        font-size: .82rem; line-height: 1.55;
    }
    .fontes-rodape strong { color: #aeb8bb; }
    div[data-testid="stMetric"] {
        background: linear-gradient(145deg, #343a41, #2d3339);
        border: 1px solid #454c54; padding: .85rem 1rem; border-radius: 12px;
        box-shadow: 0 8px 20px rgba(10,13,16,.12);
    }
    div[data-testid="stMetricValue"] { color: #7fd0ca; }
    [data-testid="stAlert"] { background: #30363d; border: 1px solid #454c54; }
    hr { border-color: #414850 !important; }
    </style>
    <div class="hero">
      <div class="hero-row">
        <div>
          <h1>Fundos de Investimento</h1>
          <p>Performance histórica, composição de carteiras e fronteira eficiente.</p>
        </div>
        <div class="hero-author">Elaborado por:<br><strong>Fabricio Orlandin, CFP®</strong></div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def obter_fundos() -> pd.DataFrame:
    return listar_fundos(BANCO)


@st.cache_data(show_spinner=False)
def obter_cotas(
    cnpjs: tuple[str, ...], inicio: date, fim: date, datas_comuns: bool
) -> pd.DataFrame:
    return carregar_cotas(
        BANCO, cnpjs, pd.Timestamp(inicio), pd.Timestamp(fim), datas_comuns=datas_comuns
    )


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def obter_benchmark(benchmark: str, inicio: date, fim: date) -> pd.Series:
    return carregar_benchmark(benchmark, inicio, fim)


def interpretar_data(texto: str, rotulo: str) -> date:
    try:
        return pd.to_datetime(texto, format="%d/%m/%Y", errors="raise").date()
    except (TypeError, ValueError) as erro:
        raise ValueError(f"{rotulo} inválida. Use o formato DD/MM/AAAA.") from erro


def nome_curto(nome: str, limite: int = 62) -> str:
    return nome if len(nome) <= limite else nome[: limite - 1] + "…"


def grafico_linhas(
    dados: pd.DataFrame,
    titulo: str,
    eixo_y: str,
    series_tracejadas: set[str] | None = None,
) -> go.Figure:
    longos = dados.rename_axis("Data").reset_index().melt(
        id_vars="Data", var_name="Série", value_name=eixo_y
    )
    figura = px.line(
        longos, x="Data", y=eixo_y, color="Série", title=titulo,
        color_discrete_sequence=CORES,
    )
    figura.update_layout(
        hovermode="x unified", legend_title_text="", height=510,
        margin=dict(l=20, r=20, t=60, b=20), paper_bgcolor=COR_PAINEL,
        plot_bgcolor=COR_PAINEL, font=dict(color=COR_TEXTO_SECUNDARIO),
        title_font=dict(color=COR_TEXTO), legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    figura.update_xaxes(showgrid=False, linecolor=COR_GRADE, zerolinecolor=COR_GRADE)
    figura.update_yaxes(
        showgrid=True, gridcolor=COR_GRADE, zerolinecolor=COR_GRADE,
        tickformat=".1%",
    )
    for trace in figura.data:
        trace.update(hovertemplate="%{fullData.name}: %{y:.2%}<extra></extra>")
        if trace.name in (series_tracejadas or set()):
            trace.update(line=dict(dash="dash", width=3))
    return figura


def incluir_benchmark(
    dados: pd.DataFrame, benchmark: str, inicio: date, fim: date
) -> tuple[pd.DataFrame, set[str], str | None]:
    """Anexa um benchmark apenas aos dados de exibição do gráfico."""
    if benchmark == BENCHMARK_NENHUM:
        return dados, set(), None
    try:
        serie = obter_benchmark(benchmark, inicio, fim)
    except (ErroBenchmark, ValueError) as erro:
        return dados, set(), str(erro)
    nome = NOMES_SERIES[benchmark]
    combinado = pd.concat(
        [dados, serie.rename(nome)], axis="columns", sort=False
    ).sort_index()
    return combinado, {nome}, None


def tabela_alocacao(pesos: pd.Series, nomes: dict[str, str]) -> pd.DataFrame:
    tabela = pd.DataFrame(
        {
            "Fundo": [nomes.get(cnpj, cnpj) for cnpj in pesos.index],
            "Alocação": pesos.to_numpy(),
        }
    )
    return tabela[tabela["Alocação"] > 0.00005].sort_values(
        "Alocação", ascending=False
    )


if not BANCO.exists():
    st.error("Banco de dados não encontrado. Execute primeiro o coletor cnpj.py.")
    st.stop()

fundos = obter_fundos()
inicio_banco, fim_banco = limites_do_banco(BANCO)
nomes_por_cnpj = dict(zip(fundos["cnpj"], fundos["nome"]))
rotulos = {
    linha.cnpj: f"{linha.nome}  ·  {linha.cnpj}"
    for linha in fundos.itertuples(index=False)
}

aba_fundos, aba_carteira = st.tabs(["Performance dos fundos", "Carteira e fronteira eficiente"])

with aba_fundos:
    st.subheader("Histórico de rentabilidade")
    selecionados = st.multiselect(
        "Pesquise e selecione um ou mais fundos",
        options=fundos["cnpj"].tolist(),
        format_func=lambda valor: rotulos[valor],
        placeholder="Digite parte do nome do fundo…",
        key="fundos_performance",
    )
    benchmark_fundos = st.selectbox(
        "Benchmark para comparação",
        options=OPCOES_BENCHMARK,
        key="benchmark_fundos",
        help="O benchmark é exibido como retorno acumulado e não altera os cálculos dos fundos.",
    )
    modo_periodo = st.radio(
        "Período considerado",
        ["Todo o histórico disponível", "Informar outro período"],
        horizontal=True,
        help=(
            "No histórico completo, um fundo usa sua primeira cota. Com dois ou mais, "
            "a comparação começa na data inicial do fundo mais novo."
        ),
    )
    erro_periodo: str | None = None
    if modo_periodo == "Informar outro período":
        coluna_inicio, coluna_fim = st.columns(2)
        with coluna_inicio:
            texto_inicio = st.text_input(
                "Data inicial", value="01/01/2023", placeholder="DD/MM/AAAA"
            )
        with coluna_fim:
            texto_fim = st.text_input(
                "Data final", value=f"{fim_banco:%d/%m/%Y}", placeholder="DD/MM/AAAA"
            )
        try:
            data_inicial = interpretar_data(texto_inicio, "Data inicial")
            data_final = interpretar_data(texto_fim, "Data final")
            if data_inicial >= data_final:
                erro_periodo = "A data inicial deve ser anterior à data final."
        except ValueError as erro:
            erro_periodo = str(erro)
            data_inicial, data_final = inicio_banco.date(), fim_banco.date()
    else:
        data_inicial, data_final = inicio_banco.date(), fim_banco.date()
    st.caption(
        f"Base atualizada até {fim_banco:%d/%m/%Y}. Se uma data informada não possuir "
        "cota, será usada a observação disponível mais próxima dentro do período. "
        "Fonte: Informe Diário — Portal de Dados Abertos CVM."
    )
    if erro_periodo:
        st.error(erro_periodo)
        st.stop()
    if not selecionados:
        st.info("Selecione um fundo para visualizar sua performance. Adicione outros para comparar.")
    else:
        cotas = obter_cotas(
            tuple(selecionados),
            data_inicial,
            data_final,
            datas_comuns=len(selecionados) > 1,
        )
        sem_dados = [cnpj for cnpj in selecionados if cotas.get(cnpj, pd.Series()).dropna().empty]
        if sem_dados or cotas.empty:
            st.warning(
                "Um ou mais fundos não possuem dados comuns na janela selecionada: "
                + ", ".join(nomes_por_cnpj[cnpj] for cnpj in sem_dados or selecionados)
            )
        elif len(cotas) < 2:
            st.warning("A janela selecionada não possui observações suficientes.")
        else:
            performance_cnpj = performance_base_100(cotas)
            performance = performance_cnpj.rename(columns=nomes_por_cnpj)
            performance_exibida, benchmarks_tracejados, erro_benchmark = incluir_benchmark(
                performance,
                benchmark_fundos,
                cotas.index.min().date(),
                cotas.index.max().date(),
            )
            if erro_benchmark:
                st.warning(
                    "Não foi possível carregar o benchmark selecionado. "
                    f"Os fundos continuam disponíveis. Detalhe: {erro_benchmark}"
                )
            retornos_totais = performance_exibida.apply(
                lambda serie: serie.dropna().iloc[-1] / 100.0 - 1.0
            )
            col1, col2, col3 = st.columns(3)
            primeiras_datas = [cotas[coluna].first_valid_index() for coluna in selecionados]
            col1.metric("Primeira data exibida", f"{min(primeiras_datas):%d/%m/%Y}")
            col2.metric("Fim efetivo", f"{cotas.index.max():%d/%m/%Y}")
            col3.metric("Fundos comparados", str(len(selecionados)))
            retornos_grafico = retorno_acumulado_base_100(performance_exibida)
            st.plotly_chart(
                grafico_linhas(
                    retornos_grafico,
                    "Rentabilidade acumulada",
                    "Retorno acumulado",
                    benchmarks_tracejados,
                ),
                width="stretch",
            )
            resumo = pd.DataFrame(
                {
                    "Série": retornos_totais.index,
                    "Data inicial efetiva": [
                        performance_exibida[coluna].first_valid_index()
                        for coluna in retornos_totais.index
                    ],
                    "Rentabilidade na janela": retornos_totais.values,
                }
            ).sort_values("Rentabilidade na janela", ascending=False)
            st.dataframe(
                resumo.style.format(
                    {"Data inicial efetiva": "{:%d/%m/%Y}", "Rentabilidade na janela": "{:.2%}"}
                ),
                hide_index=True,
                width="stretch",
            )

with aba_carteira:
    st.subheader("Monte sua carteira")
    benchmark_carteira = st.selectbox(
        "Benchmark para a performance da carteira",
        options=OPCOES_BENCHMARK,
        key="benchmark_carteira",
        help="O benchmark aparece somente no gráfico de performance, nunca na fronteira eficiente.",
    )
    carteira = selecionados
    if not carteira:
        st.info(
            "Selecione os fundos na aba 'Performance dos fundos'. "
            "A mesma seleção será usada para montar a carteira."
        )
    else:
        st.caption(
            f"Carteira composta pelos {len(carteira)} fundo(s) selecionado(s) "
            "na aba de performance."
        )
        st.caption("Informe a alocação inicial. A simulação não realiza rebalanceamentos.")
        colunas_pesos = st.columns(min(3, len(carteira)))
        pesos_percentuais: dict[str, float] = {}
        peso_padrao = 100.0 / len(carteira)
        for indice, cnpj_fundo in enumerate(carteira):
            with colunas_pesos[indice % len(colunas_pesos)]:
                pesos_percentuais[cnpj_fundo] = st.number_input(
                    nome_curto(nomes_por_cnpj[cnpj_fundo], 42),
                    min_value=0.0, max_value=100.0, value=float(round(peso_padrao, 2)),
                    step=0.5, format="%.2f", key=f"peso_{cnpj_fundo}",
                )
        total_pesos = sum(pesos_percentuais.values())
        st.metric("Total alocado", f"{total_pesos:.2f}%")
        if not np.isclose(total_pesos, 100.0, atol=0.01):
            st.error("As alocações precisam totalizar exatamente 100%.")
        else:
            cotas_carteira = obter_cotas(tuple(carteira), data_inicial, data_final, True)
            if cotas_carteira.empty or len(cotas_carteira.columns) != len(carteira):
                st.warning("Nem todos os fundos possuem cotas comuns na janela selecionada.")
            elif len(cotas_carteira) < 2:
                st.warning("A janela selecionada não possui observações suficientes.")
            else:
                pesos = pd.Series(pesos_percentuais).divide(total_pesos)
                historico, pesos_dinamicos = historico_carteira_sem_rebalanceamento(
                    cotas_carteira, pesos
                )
                rentabilidade = historico.iloc[-1] / 100.0 - 1.0
                col1, col2, col3 = st.columns(3)
                col1.metric("Rentabilidade da carteira", f"{rentabilidade:.2%}")
                col2.metric("Início efetivo", f"{historico.index.min():%d/%m/%Y}")
                col3.metric("Fim efetivo", f"{historico.index.max():%d/%m/%Y}")
                performance_carteira, benchmarks_tracejados, erro_benchmark = incluir_benchmark(
                    historico.to_frame(),
                    benchmark_carteira,
                    historico.index.min().date(),
                    historico.index.max().date(),
                )
                if erro_benchmark:
                    st.warning(
                        "Não foi possível carregar o benchmark selecionado. "
                        f"A carteira continua disponível. Detalhe: {erro_benchmark}"
                    )
                retornos_carteira_grafico = retorno_acumulado_base_100(
                    performance_carteira
                )
                st.plotly_chart(
                    grafico_linhas(
                        retornos_carteira_grafico,
                        "Rentabilidade acumulada da carteira",
                        "Retorno acumulado",
                        benchmarks_tracejados,
                    ),
                    width="stretch",
                )
                with st.expander("Alocação atual estimada após a variação dos fundos"):
                    alocacao_final = pesos_dinamicos.iloc[-1].rename(index=nomes_por_cnpj)
                    st.dataframe(
                        alocacao_final.rename("Alocação").reset_index(name="Alocação")
                        .rename(columns={"index": "Fundo"})
                        .style.format({"Alocação": "{:.2%}"}),
                        hide_index=True, width="stretch",
                    )

                st.divider()
                st.subheader("Fronteira eficiente de Markowitz")
                st.caption(
                    f"As carteiras otimizadas mantêm no mínimo "
                    f"{ALOCACAO_MINIMA_FRONTEIRA:.0%} em cada fundo selecionado."
                )
                if len(carteira) < 2:
                    st.info("Selecione pelo menos dois fundos para calcular a fronteira.")
                else:
                    try:
                        fronteira = calcular_fronteira_eficiente(cotas_carteira)
                        retorno_usuario, risco_usuario = risco_retorno_carteira_estatica(
                            cotas_carteira, pesos
                        )
                    except (ValueError, RuntimeError) as erro:
                        st.warning(str(erro))
                    else:
                        figura = go.Figure()
                        figura.add_trace(go.Scattergl(
                            x=fronteira.carteiras_testadas["risco"],
                            y=fronteira.carteiras_testadas["retorno"],
                            mode="markers", name="Diversificações testadas",
                            marker=dict(
                                size=3, opacity=0.2, color="#718A91", symbol="circle",
                            ),
                            hovertemplate="Risco: %{x:.2%}<br>Retorno esperado: %{y:.2%}<extra></extra>",
                        ))
                        figura.add_trace(go.Scatter(
                            x=fronteira.pontos["risco"], y=fronteira.pontos["retorno"],
                            mode="lines", name="Curva completa de mínima variância",
                            line=dict(color="#66C3BC", width=4),
                            hovertemplate="Risco: %{x:.2%}<br>Retorno esperado: %{y:.2%}<extra></extra>",
                        ))
                        figura.add_trace(go.Scatter(
                            x=fronteira.riscos_anuais_fundos,
                            y=fronteira.retornos_anuais_fundos,
                            mode="markers", name="Fundos",
                            text=[nome_curto(nomes_por_cnpj[c], 24) for c in fronteira.riscos_anuais_fundos.index],
                            marker=dict(
                                size=7, color="#A9D8D3", symbol="circle",
                                line=dict(color=COR_PAINEL, width=1),
                            ),
                            hovertemplate="%{text}<br>Risco: %{x:.2%}<br>Retorno esperado: %{y:.2%}<extra></extra>",
                        ))
                        figura.add_trace(go.Scatter(
                            x=[fronteira.risco_minimo], y=[fronteira.retorno_minimo_risco],
                            mode="markers", name="Menor risco",
                            marker=dict(
                                size=10, color="#3F7278", symbol="circle",
                                line=dict(color=COR_TEXTO, width=1.5),
                            ),
                            hovertemplate="Menor risco<br>Risco: %{x:.2%}<br>Retorno: %{y:.2%}<extra></extra>",
                        ))
                        figura.add_trace(go.Scatter(
                            x=[fronteira.risco_maximo_retorno], y=[fronteira.retorno_maximo],
                            mode="markers", name="Maior retorno",
                            marker=dict(
                                size=10, color="#8A7955", symbol="circle",
                                line=dict(color=COR_TEXTO, width=1.5),
                            ),
                            hovertemplate="Maior retorno<br>Risco: %{x:.2%}<br>Retorno: %{y:.2%}<extra></extra>",
                        ))
                        figura.add_trace(go.Scatter(
                            x=[risco_usuario], y=[retorno_usuario], mode="markers",
                            name="Sua alocação", marker=dict(
                                size=10, color="#D5DDDE", symbol="circle",
                                line=dict(color=COR_PAINEL, width=1.5),
                            ),
                            hovertemplate="Sua alocação<br>Risco: %{x:.2%}<br>Retorno: %{y:.2%}<extra></extra>",
                        ))
                        figura.update_layout(
                            height=590, title="Relação anualizada entre risco e retorno esperado",
                            xaxis_tickformat=".1%", yaxis_tickformat=".1%",
                            xaxis_title="Risco (volatilidade anualizada)",
                            yaxis_title="Retorno esperado anualizado", hovermode="closest",
                            paper_bgcolor=COR_PAINEL, plot_bgcolor=COR_PAINEL,
                            font=dict(color=COR_TEXTO_SECUNDARIO),
                            title_font=dict(color=COR_TEXTO),
                            legend=dict(bgcolor="rgba(0,0,0,0)"),
                            margin=dict(l=20, r=20, t=60, b=20),
                        )
                        figura.update_xaxes(gridcolor=COR_GRADE, zerolinecolor=COR_GRADE)
                        figura.update_yaxes(gridcolor=COR_GRADE, zerolinecolor=COR_GRADE)
                        st.plotly_chart(figura, width="stretch")

                        coluna_minimo, coluna_maximo = st.columns(2)
                        with coluna_minimo:
                            st.markdown("#### Carteira de menor risco")
                            st.metric("Risco anualizado", f"{fronteira.risco_minimo:.2%}")
                            st.metric("Retorno esperado", f"{fronteira.retorno_minimo_risco:.2%}")
                            st.dataframe(
                                tabela_alocacao(fronteira.pesos_minimo_risco, nomes_por_cnpj)
                                .style.format({"Alocação": "{:.2%}"}),
                                hide_index=True, width="stretch",
                            )
                        with coluna_maximo:
                            st.markdown("#### Carteira de maior retorno na fronteira")
                            st.metric("Retorno esperado", f"{fronteira.retorno_maximo:.2%}")
                            st.metric("Risco anualizado", f"{fronteira.risco_maximo_retorno:.2%}")
                            st.dataframe(
                                tabela_alocacao(fronteira.pesos_maior_retorno, nomes_por_cnpj)
                                .style.format({"Alocação": "{:.2%}"}),
                                hide_index=True, width="stretch",
                            )

                        st.markdown(
                            f"""
                            <div class="disclaimer">
                            <strong>Nota metodológica e disclaimer:</strong> o retorno esperado é a
                            média dos retornos diários simples observados na janela, anualizada por
                            252 dias úteis. O risco é o desvio-padrão da carteira calculado com a
                            matriz de covariância e anualizado por √252. As estimativas são muito
                            sensíveis ao período escolhido. Resultados passados não representam
                            previsão ou garantia de rentabilidade futura e esta ferramenta não
                            constitui recomendação de investimento. A fronteira considera pesos
                            estáticos, sem venda a descoberto, e alocação mínima de
                            {ALOCACAO_MINIMA_FRONTEIRA:.0%} por fundo; o histórico da carteira é uma
                            simulação sem rebalanceamento. Mínimo de {MINIMO_OBSERVACOES}
                            retornos diários comuns.
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

st.markdown(
    f"""
    <div class="fontes-rodape">
    <strong>Fontes de dados:</strong><br>
    Fundos de investimento: Informe Diário — Portal de Dados Abertos CVM.<br>
    {FONTES_BENCHMARK['CDI']}<br>
    {FONTES_BENCHMARK['Ibovespa']}
    </div>
    """,
    unsafe_allow_html=True,
)
