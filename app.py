"""Aplicativo Streamlit para comparar fundos e analisar carteiras."""

from __future__ import annotations

from datetime import date

from html import escape

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from database import ErroBanco, total_simulacoes
from simulation_counter import contar_analise

from analytics import (
    ALOCACAO_MINIMA_FRONTEIRA,
    MINIMO_OBSERVACOES,
    calcular_fronteira_eficiente,
    validar_alocacoes_fixas,
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


CORES = ["#38BDF8", "#FB923C", "#A78BFA", "#34D399", "#F472B6", "#FACC15", "#2DD4BF", "#E879F9", "#A3E635", "#F87171"]
COR_CARTEIRA = "#F472B6"
COR_BENCHMARK = "#94A3B8"
COR_PAINEL = "#102B59"
COR_GRADE = "#294875"
COR_TEXTO = "#F1F5FF"
COR_TEXTO_SECUNDARIO = "#BDCCE5"

st.set_page_config(
    page_title="Fundos de Investimento | Performance e Carteiras",
    page_icon="📈",
    layout="wide",
)

# O Streamlit exporta secrets de nível raiz para o ambiente ao carregá-los.
# database.py continua lendo exclusivamente DATABASE_URL via os.environ.
try:
    st.secrets.get("DATABASE_URL")
except FileNotFoundError:
    pass

st.markdown(
    """
    <style>
    .stApp {
        background:
            radial-gradient(circle at 12% 0%, rgba(0,61,165,.36), transparent 28rem),
            #071A38;
    }
    [data-testid="stHeader"] { background: rgba(7,26,56,.95); }
    [data-testid="stToolbar"] { color: #bdcce5; }
    [data-testid="stMainBlockContainer"] { max-width: 1600px; padding-top: 1.2rem; }
    .hero {
        position: relative; overflow: hidden; padding: 1.15rem 1.5rem;
        border: 1px solid #294875; border-radius: 18px; color: #f1f5ff;
        background: linear-gradient(125deg, #003DA5 0%, #084CB8 62%, #1769D4 100%);
        box-shadow: 0 18px 42px rgba(10,13,16,.28); margin-bottom: 1.35rem;
    }
    .hero::after {
        content: ""; position: absolute; width: 220px; height: 220px;
        right: -72px; top: -112px; border: 38px solid rgba(255,255,255,.12);
        border-radius: 50%;
    }
    .hero-row { display: flex; justify-content: space-between; align-items: flex-start; gap: 2rem; }
    .hero h1 { margin: 0; font-size: 1.7rem; letter-spacing: -.025em; }
    .hero p { margin: .55rem 0 0; color: #bdcce5; }
    .hero-author { z-index: 1; text-align: right; font-size: .86rem; color: #bdcce5; white-space: nowrap; }
    .hero-author strong { color: #79BCFF; }
    @media (max-width: 700px) {
        .hero-row { flex-direction: column; gap: 1rem; }
        .hero-author { text-align: left; }
    }
    h1, h2, h3, h4 { color: #f4f6f6 !important; letter-spacing: -.015em; }
    p, label, [data-testid="stCaptionContainer"] { color: #bdcce5; }
    [data-testid="stWidgetLabel"] p { color: #E2ECFF; }
    button[data-baseweb="tab"] { color: #bdcce5; }
    button[data-baseweb="tab"][aria-selected="true"] { color: #79BCFF; }
    [data-baseweb="tab-highlight"] { background-color: #4A99FF; }
    [data-baseweb="input"], [data-baseweb="select"] > div,
    [data-testid="stNumberInputContainer"] {
        background: #102B59 !important; border-color: #42649A !important;
    }
    [data-baseweb="input"] input { color: #f1f5ff; }
    [data-testid="stDataFrame"] { border: 1px solid #294875; border-radius: 10px; overflow: hidden; }
    .disclaimer {
        padding: .9rem 1rem; border-left: 4px solid #f9a825;
        background: #34383a; border-radius: 8px; color: #d8d1b7;
    }
    .fontes-rodape {
        margin-top: 2.2rem; padding: 1rem 0 .25rem;
        border-top: 1px solid #294875; color: #A2B8DA;
        font-size: .82rem; line-height: 1.55;
    }
    .fontes-rodape strong { color: #bdcce5; }
    div[data-testid="stMetric"] {
        background: linear-gradient(145deg, #123570, #102B59);
        border: 1px solid #294875; padding: .85rem 1rem; border-radius: 12px;
        box-shadow: 0 8px 20px rgba(10,13,16,.12);
    }
    div[data-testid="stMetricValue"] { color: #79BCFF; }
    [data-testid="stAlert"] { background: #102B59; border: 1px solid #294875; }
    [data-testid="stVerticalBlockBorderWrapper"] { border-color: #294875 !important; }
    @media (max-width: 900px) {
        [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
        [data-testid="stColumn"] { min-width: 100% !important; flex: 1 1 100% !important; }
    }
    hr { border-color: #294875 !important; }
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


@st.cache_data(ttl=300, max_entries=128, show_spinner=False)
def obter_fundos() -> pd.DataFrame:
    return listar_fundos()


@st.cache_data(ttl=300, max_entries=128, show_spinner=False)
def obter_cotas(
    cnpjs: tuple[str, ...], inicio: date, fim: date, datas_comuns: bool
) -> pd.DataFrame:
    try:
        return carregar_cotas(
            cnpjs, pd.Timestamp(inicio), pd.Timestamp(fim), datas_comuns=datas_comuns
        )
    except (ErroBanco, ValueError) as erro:
        st.error(str(erro))
        st.stop()


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
    cores_series: dict[str, str] | None = None,
) -> go.Figure:
    longos = dados.rename_axis("Data").reset_index().melt(
        id_vars="Data", var_name="Série", value_name=eixo_y
    )
    figura = px.line(
        longos, x="Data", y=eixo_y, color="Série", title=titulo,
        color_discrete_sequence=CORES, color_discrete_map=cores_series or {},
    )
    figura.update_layout(
        hovermode="x unified", legend_title_text="", height=420,
        margin=dict(l=15, r=85, t=55, b=20), paper_bgcolor=COR_PAINEL,
        plot_bgcolor=COR_PAINEL, font=dict(color=COR_TEXTO_SECUNDARIO),
        title_font=dict(color=COR_TEXTO), legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", y=-0.2),
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
    # Rótulos em coordenadas de papel evitam cortes e separam valores próximos.
    finais = []
    for trace in figura.data:
        serie = dados[trace.name].dropna()
        if not serie.empty:
            finais.append((float(serie.iloc[-1]), trace, serie.index[-1]))
    valores = dados.to_numpy(dtype=float)
    minimo, maximo = float(np.nanmin(valores)), float(np.nanmax(valores))
    amplitude = max(maximo - minimo, 0.01)
    piso, teto = minimo - amplitude * .08, maximo + amplitude * .08
    figura.update_yaxes(range=[piso, teto])
    ordenados = sorted(finais, key=lambda item: item[0])
    distancia = min(.075, .85 / max(len(ordenados), 1))
    posicoes = []
    for valor, _, _ in ordenados:
        natural = (valor - piso) / (teto - piso)
        posicoes.append(max(natural, posicoes[-1] + distancia if posicoes else .04))
    if posicoes:
        posicoes[-1] = min(posicoes[-1], .96)
        for i in range(len(posicoes) - 2, -1, -1):
            posicoes[i] = min(posicoes[i], posicoes[i + 1] - distancia)
    for (valor, trace, data), posicao in zip(ordenados, posicoes):
        figura.add_annotation(
            x=1.01, xref="paper", y=posicao, yref="paper",
            text=f"{valor:.2%}".replace(".", ","), showarrow=False,
            xanchor="left", font=dict(color=trace.line.color, size=12),
            hovertext=escape(str(trace.name)),
        )
        figura.add_trace(go.Scatter(
            x=[data], y=[valor], mode="markers", showlegend=False,
            legendgroup=trace.legendgroup, marker=dict(color=trace.line.color, size=6),
            hoverinfo="skip",
        ))
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


@st.cache_data(ttl=300, show_spinner=False)
def obter_limites():
    return limites_do_banco()


@st.cache_data(ttl=60, show_spinner=False)
def obter_total_simulacoes():
    return total_simulacoes()


try:
    fundos = obter_fundos()
    inicio_banco, fim_banco = obter_limites()
except (ErroBanco, ValueError) as erro:
    st.error(str(erro))
    st.stop()
# Cada opção representa uma série (CNPJ + subclasse), com pesos independentes.
fundos = fundos.copy()
fundos['cnpj_original'] = fundos['cnpj']
if 'id_serie' in fundos:
    fundos['cnpj'] = fundos['id_serie']
nomes_por_cnpj = dict(zip(fundos["cnpj"], fundos["nome"]))
rotulos = {
    linha.cnpj: f"{linha.nome}  ·  {linha.cnpj_original}"
    for linha in fundos.itertuples(index=False)
}

def distribuir_igualmente(cnpjs: list[str]) -> None:
    """Distribui o saldo em centésimos de percentual, preservando fixações."""
    livres = [c for c in cnpjs if not st.session_state.get(f"fixar_{c}", False)]
    fixado = sum(round(st.session_state.get(f"peso_{c}", 0) * 100)
                 for c in cnpjs if c not in livres)
    if not livres or fixado > 10000:
        return
    base, resto = divmod(10000 - fixado, len(livres))
    for indice, cnpj in enumerate(livres):
        st.session_state[f"peso_{cnpj}"] = (base + (indice < resto)) / 100


with st.container(border=True):
    selecionados = st.multiselect(
        "Pesquise e selecione um ou mais fundos",
        options=fundos["cnpj"].tolist(),
        format_func=lambda valor: rotulos[valor],
        placeholder="Digite parte do nome do fundo…",
        key="fundos_performance",
    )
    benchmark_fundos = st.selectbox(
        "Benchmark compartilhado",
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

cores_grafico = {nomes_por_cnpj[c]: CORES[i % len(CORES)] for i, c in enumerate(selecionados)}
cores_grafico.update({nome: COR_BENCHMARK for nome in NOMES_SERIES.values()})
benchmark_carteira = benchmark_fundos
carteira = selecionados
with st.container():
    with st.container(border=True, key="painel_alocacao"):
        st.subheader("Monte sua carteira")
        st.caption("Alocação inicial • histórico sem rebalanceamento")
        st.markdown(
            "**Quer manter um percentual na otimização?** Marque **Travar na otimização** "
            "nos fundos desejados. O sistema calcula como distribuir o restante."
        )
        st.button("Distribuir igualmente", on_click=distribuir_igualmente,
                  args=(carteira,),
                  disabled=not any(not st.session_state.get(f"fixar_{c}", False) for c in carteira),
                  type="primary", help="Distribui o saldo entre os fundos livres, preservando os percentuais travados.")
        if not carteira:
            st.info("Selecione os fundos acima para definir os pesos.")
        if carteira and tuple(carteira) != st.session_state.get("selecao_pesos"):
            # Preserva edições dos fundos existentes; novos fundos começam em zero.
            if not any(f"peso_{c}" in st.session_state for c in carteira):
                distribuir_igualmente(carteira)
            st.session_state["selecao_pesos"] = tuple(carteira)
        pesos_percentuais = {}
        pesos_fixos = {}
        for inicio_linha in range(0, len(carteira), 3):
            campos = st.columns(3)
            for campo, cnpj in zip(campos, carteira[inicio_linha:inicio_linha + 3]):
                with campo:
                    pesos_percentuais[cnpj] = st.number_input(
                        nome_curto(nomes_por_cnpj[cnpj], 62), min_value=0.0, max_value=100.0,
                        step=0.5, format="%.2f", key=f"peso_{cnpj}", help=rotulos[cnpj],
                    )
                    if st.checkbox(
                        "Travar na otimização", key=f"fixar_{cnpj}",
                        help="Mantém este percentual nas carteiras otimizadas. Você pode editar o valor mesmo com a opção marcada.",
                    ):
                        pesos_fixos[cnpj] = pesos_percentuais[cnpj] / 100
        erro_fixacoes = None
        if pesos_fixos:
            total_fixo = sum(pesos_fixos.values())
            st.info(f"**{total_fixo:.2%} travados · {1 - total_fixo:.2%} de saldo para os fundos livres**")
            try:
                validar_alocacoes_fixas(carteira, pesos_fixos)
            except ValueError as erro:
                erro_fixacoes = str(erro)
                st.error(erro_fixacoes)
        total_pesos = sum(pesos_percentuais.values())
        valido = bool(carteira) and np.isclose(total_pesos, 100.0, atol=0.001, rtol=0)
        st.caption(f"Total alocado: {total_pesos:.2f}%")
        if carteira and not valido:
            diferenca = 100 - total_pesos
            st.warning(f"{'Faltam' if diferenca > 0 else 'Excedem'} {abs(diferenca):.2f}% para fechar 100%.")

with st.container():
    indicadores = st.container()
    with st.container():
        with st.container(border=True):
            st.subheader("Retorno dos fundos")
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
                    st.info(f"**Período efetivo dos fundos: {cotas.index.min():%d/%m/%Y} a {cotas.index.max():%d/%m/%Y}**")
                    retornos_grafico = retorno_acumulado_base_100(performance_exibida)
                    st.plotly_chart(
                        grafico_linhas(
                            retornos_grafico,
                            "Rentabilidade acumulada",
                            "Retorno acumulado",
                            benchmarks_tracejados,
                            cores_grafico,
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
                    with st.expander("Rentabilidade por fundo e benchmark"):
                        st.dataframe(
                            resumo.style.format(
                                {"Data inicial efetiva": "{:%d/%m/%Y}", "Rentabilidade na janela": "{:.2%}"}
                            ),
                            hide_index=True,
                            width="stretch",
                        )

    cotas_carteira = None
    with st.container():
        with st.container(border=True):
            st.subheader("Retorno da carteira")
            if not valido:
                st.info("Defina os pesos acima, totalizando 100%, para visualizar sua carteira.")
            else:
                cotas_carteira = obter_cotas(tuple(carteira), data_inicial, data_final, True)
                if cotas_carteira.empty or len(cotas_carteira.columns) != len(carteira) or len(cotas_carteira) < 2:
                    st.warning("Não há cotas comuns suficientes para simular a carteira neste período.")
                    cotas_carteira = None
                else:
                    pesos = pd.Series(pesos_percentuais).divide(total_pesos)
                    historico, pesos_dinamicos = historico_carteira_sem_rebalanceamento(cotas_carteira, pesos)
                    rentabilidade = historico.iloc[-1] / 100.0 - 1.0
                    with indicadores:
                        k1, k2, k3 = st.columns(3)
                        k1.metric("Retorno acumulado da carteira", f"{rentabilidade:.2%}")
                        risco_texto = "—"
                        if len(cotas_carteira) >= 3:
                            _, risco_historico = risco_retorno_carteira_estatica(cotas_carteira, pesos)
                            risco_texto = f"{risco_historico:.2%}"
                        k2.metric("Risco anualizado • pesos estáticos", risco_texto)
                        k3.metric("Total alocado", f"{total_pesos:.2f}%")
                    st.info(f"**Período efetivo da carteira: {historico.index.min():%d/%m/%Y} a {historico.index.max():%d/%m/%Y}**")
                    st.caption("Histórico sem rebalanceamento.")
                    performance_carteira, tracejados, erro_benchmark = incluir_benchmark(
                        historico.to_frame(), benchmark_carteira,
                        historico.index.min().date(), historico.index.max().date(),
                    )
                    if erro_benchmark:
                        st.warning(f"Benchmark indisponível: {erro_benchmark}")
                    st.plotly_chart(grafico_linhas(
                        retorno_acumulado_base_100(performance_carteira),
                        "Rentabilidade acumulada", "Retorno acumulado", tracejados,
                        {**cores_grafico, historico.name: COR_CARTEIRA},
                    ), width="stretch")
                    with st.expander("Alocação após a variação dos fundos"):
                        st.dataframe(tabela_alocacao(pesos_dinamicos.iloc[-1], nomes_por_cnpj)
                                     .style.format({"Alocação": "{:.2%}"}), hide_index=True, width="stretch")
    # Fixações podem ser otimizadas antes de preencher os pesos livres.
    if pesos_fixos and not valido and not erro_fixacoes:
        cotas_carteira = obter_cotas(tuple(carteira), data_inicial, data_final, True)
        if cotas_carteira.empty or len(cotas_carteira.columns) != len(carteira) or len(cotas_carteira) < 2:
            cotas_carteira = None
        pesos = pd.Series(pesos_percentuais).divide(100)
    with st.container(border=True):
        if cotas_carteira is None:
            st.subheader("Fronteira eficiente")
            st.info("Selecione pelo menos dois fundos e complete a alocação para analisar a fronteira.")
        else:
            st.subheader("Fronteira eficiente de Markowitz")
            st.info(
                f"**Período usado na fronteira: {cotas_carteira.index.min():%d/%m/%Y} "
                f"a {cotas_carteira.index.max():%d/%m/%Y}**"
            )
            st.caption(
                f"Modelo com pesos estáticos • As carteiras otimizadas mantêm no mínimo "
                f"{ALOCACAO_MINIMA_FRONTEIRA:.0%} em cada fundo selecionado."
            )
            if pesos_fixos:
                st.markdown("**Otimização com alocações travadas:** " + "; ".join(
                    f"{nomes_por_cnpj[c]}: {p:.2%}" for c, p in pesos_fixos.items()
                ))
            if erro_fixacoes:
                st.warning("Ajuste as alocações travadas conforme a mensagem acima.")
            elif len(carteira) < 2:
                st.info("Selecione pelo menos dois fundos para calcular a fronteira.")
            else:
                try:
                    fronteira = calcular_fronteira_eficiente(cotas_carteira, pesos_fixos=pesos_fixos)
                    if valido:
                        retorno_usuario, risco_usuario = risco_retorno_carteira_estatica(cotas_carteira, pesos)
                except (ValueError, RuntimeError) as erro:
                    st.warning(str(erro))
                else:
                    try:
                        if contar_analise(cotas_carteira, pesos, st.session_state, pesos_fixos=pesos_fixos):
                            obter_total_simulacoes.clear()
                    except ErroBanco:
                        st.caption("Contador temporariamente indisponível; a análise foi concluída.")
                    if fronteira.carteira_unica:
                        st.info("As restrições determinam uma única carteira possível. Menor risco e maior retorno coincidem; não há uma curva para otimizar.")
                    if not valido:
                        st.caption("A otimização já está disponível. Complete 100% para comparar também a sua carteira.")
                    figura = go.Figure()
                    figura.add_trace(go.Scattergl(
                        x=fronteira.carteiras_testadas["risco"],
                        y=fronteira.carteiras_testadas["retorno"],
                        mode="markers", name="Diversificações testadas",
                        marker=dict(
                            size=3, opacity=0.2, color="#6482AE", symbol="circle",
                        ),
                        hovertemplate="Risco: %{x:.2%}<br>Retorno esperado: %{y:.2%}<extra></extra>",
                    ))
                    # O ramo abaixo do mínimo global de risco é dominado e
                    # não deve receber o mesmo destaque da fronteira eficiente.
                    eficientes = fronteira.pontos[
                        fronteira.pontos["retorno"] >= fronteira.retorno_minimo_risco
                    ]
                    inferiores = fronteira.pontos[
                        fronteira.pontos["retorno"] <= fronteira.retorno_minimo_risco
                    ]
                    if len(inferiores) > 1:
                        figura.add_trace(go.Scatter(
                            x=inferiores["risco"], y=inferiores["retorno"],
                            mode="lines", name="Trecho não eficiente",
                            line=dict(color="#94A3B8", width=2, dash="dash"),
                            hovertemplate="Trecho não eficiente<br>Risco: %{x:.2%}<br>Retorno esperado: %{y:.2%}<extra></extra>",
                        ))
                    figura.add_trace(go.Scatter(
                        x=eficientes["risco"], y=eficientes["retorno"],
                        mode="markers" if len(eficientes) == 1 else "lines",
                        name="Carteira viável" if fronteira.carteira_unica else "Fronteira eficiente",
                        line=dict(color="#38BDF8", width=4),
                        marker=dict(color="#38BDF8", symbol="circle"),
                        hovertemplate="Risco: %{x:.2%}<br>Retorno esperado: %{y:.2%}<extra></extra>",
                    ))
                    figura.add_trace(go.Scatter(
                        x=fronteira.riscos_anuais_fundos,
                        y=fronteira.retornos_anuais_fundos,
                        mode="markers", name="Fundos individuais (referência)",
                        visible="legendonly" if pesos_fixos else True,
                        text=[nome_curto(nomes_por_cnpj[c], 24) for c in fronteira.riscos_anuais_fundos.index],
                        marker=dict(
                            size=9, color="#9CA3AF", symbol="circle",
                            line=dict(color=COR_PAINEL, width=1),
                        ),
                        hovertemplate="%{text}<br>Risco: %{x:.2%}<br>Retorno esperado: %{y:.2%}<extra></extra>",
                    ))
                    figura.add_trace(go.Scatter(
                        x=[fronteira.risco_minimo], y=[fronteira.retorno_minimo_risco],
                        mode="markers", name="Menor risco",
                        marker=dict(
                            size=10, color="#34D399", symbol="circle",
                            line=dict(color=COR_TEXTO, width=1.5),
                        ),
                        hovertemplate="Menor risco<br>Risco: %{x:.2%}<br>Retorno: %{y:.2%}<extra></extra>",
                    ))
                    figura.add_trace(go.Scatter(
                        x=[fronteira.risco_maximo_retorno], y=[fronteira.retorno_maximo],
                        mode="markers", name="Maior retorno",
                        marker=dict(
                            size=10, color="#FB923C", symbol="circle",
                            line=dict(color=COR_TEXTO, width=1.5),
                        ),
                        hovertemplate="Maior retorno<br>Risco: %{x:.2%}<br>Retorno: %{y:.2%}<extra></extra>",
                    ))
                    if valido:
                        figura.add_trace(go.Scatter(
                            x=[risco_usuario], y=[retorno_usuario], mode="markers",
                            name="Sua alocação", marker=dict(
                                size=14, color=COR_CARTEIRA, symbol="circle",
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
                        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", y=-0.2, x=0),
                        margin=dict(l=20, r=20, t=60, b=30),
                    )
                    figura.update_xaxes(gridcolor=COR_GRADE, zerolinecolor=COR_GRADE)
                    figura.update_yaxes(gridcolor=COR_GRADE, zerolinecolor=COR_GRADE)
                    st.plotly_chart(figura, width="stretch")

                    st.caption(
                        "A linha azul mostra o trecho eficiente a partir da carteira de menor risco. "
                        "O trecho cinza tracejado tem menor retorno e risco igual ou maior que essa carteira."
                    )
                    if pesos_fixos:
                        st.caption(
                            "Com alocações travadas, a curva representa somente as combinações permitidas. "
                            "Os fundos individuais estão ocultos para ampliar essa região; clique em "
                            "'Fundos individuais (referência)' na legenda para exibi-los. "
                            "Esses pontos representam 100% em cada fundo, sem as travas."
                        )
                        if len(carteira) - len(pesos_fixos) == 2 and not fronteira.carteira_unica:
                            st.info(
                                "Restam dois fundos livres: aumentar o peso de um reduz o do outro. "
                                "Por isso, as diversificações testadas se distribuem sobre uma curva, em vez de uma nuvem."
                            )

                    st.markdown("#### Alocações sugeridas por ativo")
                    st.caption("Compare os pesos da sua carteira com as duas carteiras de referência da fronteira.")
                    comparacao = pd.DataFrame({
                        "Fundo": [nomes_por_cnpj[c] for c in carteira],
                        "Restrição": ["Travado" if c in pesos_fixos else "Livre" for c in carteira],
                        "Sua carteira": pesos.reindex(carteira).to_numpy() if valido else np.nan,
                        "Menor risco": fronteira.pesos_minimo_risco.reindex(carteira).to_numpy(),
                        "Maior retorno": fronteira.pesos_maior_retorno.reindex(carteira).to_numpy(),
                    })
                    st.dataframe(
                        comparacao.style.format({
                            "Sua carteira": "{:.2%}", "Menor risco": "{:.2%}", "Maior retorno": "{:.2%}",
                        }, na_rep="—"),
                        column_config={"Fundo": st.column_config.TextColumn("Fundo", width="large")},
                        hide_index=True, width="stretch", height="content",
                    )
                    coluna_minimo, coluna_maximo = st.columns(2)
                    with coluna_minimo:
                        st.markdown("#### Carteira de menor risco")
                        st.metric("Risco anualizado", f"{fronteira.risco_minimo:.2%}")
                        st.metric("Retorno esperado", f"{fronteira.retorno_minimo_risco:.2%}")
                    with coluna_maximo:
                        st.markdown("#### Carteira de maior retorno na fronteira")
                        st.metric("Retorno esperado", f"{fronteira.retorno_maximo:.2%}")
                        st.metric("Risco anualizado", f"{fronteira.risco_maximo_retorno:.2%}")

                    st.subheader("Desempenho histórico das carteiras otimizadas")
                    st.info(
                        f"**Período efetivo: {cotas_carteira.index.min():%d/%m/%Y} "
                        f"a {cotas_carteira.index.max():%d/%m/%Y}**"
                    )
                    historico_minimo, _ = historico_carteira_sem_rebalanceamento(
                        cotas_carteira, fronteira.pesos_minimo_risco
                    )
                    historico_maximo, _ = historico_carteira_sem_rebalanceamento(
                        cotas_carteira, fronteira.pesos_maior_retorno
                    )
                    historicos_otimizados = pd.concat([
                        historico_minimo.rename("Menor risco"),
                        historico_maximo.rename("Maior retorno esperado"),
                    ], axis="columns", sort=False)
                    desempenho_otimizado, tracejados_otimizados, erro_benchmark_otimizado = incluir_benchmark(
                        historicos_otimizados, benchmark_carteira,
                        cotas_carteira.index.min().date(), cotas_carteira.index.max().date(),
                    )
                    if erro_benchmark_otimizado:
                        st.warning(
                            "Não foi possível carregar o benchmark. As carteiras otimizadas "
                            f"continuam disponíveis. Detalhe: {erro_benchmark_otimizado}"
                        )
                    st.plotly_chart(
                        grafico_linhas(
                            retorno_acumulado_base_100(desempenho_otimizado),
                            "Rentabilidade acumulada das carteiras otimizadas",
                            "Retorno acumulado", tracejados_otimizados,
                            {
                                "Menor risco": "#34D399",
                                "Maior retorno esperado": "#FB923C",
                                **{nome: COR_BENCHMARK for nome in NOMES_SERIES.values()},
                            },
                        ),
                        width="stretch",
                    )
                    st.caption(
                        "Simulação retrospectiva: os pesos foram calculados usando o próprio período exibido. "
                        "Os pesos otimizados, incluindo os travados, são as alocações iniciais, sem rebalanceamento; "
                        "os percentuais variam ao longo do histórico. "
                        "Maior retorno esperado não significa necessariamente maior retorno acumulado."
                    )

                    with st.expander("Metodologia e limitações"):
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

try:
    st.caption(f"Simulações de carteira concluídas no site: {obter_total_simulacoes():,}".replace(",", "."))
except ErroBanco:
    st.caption("Contador de simulações temporariamente indisponível.")
