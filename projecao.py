"""Projeção paramétrica de carteiras; não representa garantia de retorno."""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.stats import norm

PRAZOS = {"12 meses": 12, "24 meses": 24, "36 meses": 36, "5 anos": 60, "10 anos": 120}


@dataclass(frozen=True)
class Projecao:
    media_log: float
    desvio_log: float
    observacoes: int
    inicio: pd.Timestamp
    fim: pd.Timestamp

    def limites(self, cobertura):
        z = norm.ppf((1 + cobertura) / 2)
        return tuple(np.expm1(self.media_log + np.array([-z, z]) * self.desvio_log))


def recortar_historico(cotas, meses=None):
    """Janela encerrada na última cota, com uma cota base anterior ao corte."""
    cotas = cotas.sort_index().dropna(how="any")
    if cotas.empty:
        raise ValueError("Não há histórico comum disponível.")
    if meses is None:
        return cotas
    corte = cotas.index[-1] - pd.DateOffset(months=meses)
    if cotas.index[0] > corte:
        raise ValueError("O histórico comum não cobre esse período completo.")
    base = cotas.index.searchsorted(corte, side="right") - 1
    return cotas.iloc[base:]


def calcular_projecao(cotas, pesos, meses):
    """Normal dos log-retornos da carteira com rebalanceamento nas observações.

    O tempo é medido em anos de 365,25 dias para acomodar intervalos irregulares,
    sem preencher lacunas com retornos zero. Incrementos independentes e parâmetros
    constantes são hipóteses do modelo. A incerteza dos parâmetros não é incluída.
    """
    if meses not in PRAZOS.values():
        raise ValueError("Prazo de projeção inválido.")
    if not isinstance(cotas.index, pd.DatetimeIndex) or cotas.index.hasnans or cotas.index.has_duplicates:
        raise ValueError("As datas devem ser válidas e únicas.")
    cotas = cotas.sort_index()
    if len(cotas) < 61:
        raise ValueError("São necessários ao menos 60 retornos comuns para projetar.")
    if not np.isfinite(cotas.to_numpy()).all() or (cotas <= 0).any().any():
        raise ValueError("As cotas devem ser positivas e finitas.")
    pesos = pesos.reindex(cotas.columns)
    if not np.isfinite(pesos).all() or (pesos < 0).any() or not np.isclose(pesos.sum(), 1):
        raise ValueError("Os pesos devem ser não negativos e somar 100%.")
    retornos = cotas.pct_change(fill_method=None).iloc[1:].dot(pesos)
    logs = np.log1p(retornos).to_numpy()
    dt = np.diff(cotas.index.as_unit("ns").asi8) / (86400 * 1e9 * 365.25)
    media = logs.sum() / dt.sum()
    variancia = np.sum((logs - media * dt) ** 2 / dt) / (len(logs) - 1)
    desvio = np.sqrt(variancia * meses / 12)
    media = media * meses / 12
    if not np.isfinite([media, desvio]).all() or abs(media) + 4 * desvio > 600:
        raise ValueError("Parâmetros extremos impedem uma projeção numericamente estável.")
    if desvio < 1e-8:
        raise ValueError("Volatilidade praticamente nula: não é possível estimar uma distribuição confiável.")
    return Projecao(float(media), float(desvio), len(logs), cotas.index[0], cotas.index[-1])


def grafico_projecao(resultado, titulo):
    fig = go.Figure()
    # Normal no log-retorno; transformação completa da densidade para retorno %.
    for cobertura, cor in [(0.99, "rgba(167,139,250,.25)"), (0.95, "rgba(56,189,248,.35)"), (0.90, "rgba(52,211,153,.5)")]:
        z = norm.ppf((1 + cobertura) / 2)
        logs = np.linspace(resultado.media_log - z * resultado.desvio_log,
                           resultado.media_log + z * resultado.desvio_log, 401)
        x = np.expm1(logs)
        y = norm.pdf(logs, resultado.media_log, resultado.desvio_log) / np.exp(logs)
        fig.add_trace(go.Scatter(x=x, y=y, fill="tozeroy", fillcolor=cor,
                                line=dict(width=0), name=f"Faixa central {cobertura:.0%}",
                                hovertemplate="Retorno: %{x:.2%}<extra>%{fullData.name}</extra>"))
    logs = np.linspace(resultado.media_log - 3.5 * resultado.desvio_log,
                       resultado.media_log + 3.5 * resultado.desvio_log, 801)
    fig.add_trace(go.Scatter(x=np.expm1(logs),
                            y=norm.pdf(logs, resultado.media_log, resultado.desvio_log) / np.exp(logs),
                            name="Distribuição estimada", line=dict(color="#38BDF8"),
                            hovertemplate="Retorno: %{x:.2%}<extra></extra>"))
    fig.add_vline(x=0, line_dash="dash", line_color="#94A3B8")
    fig.update_layout(title=titulo, xaxis_title="Retorno acumulado projetado", xaxis_tickformat=".0%",
                      yaxis_title="Densidade de probabilidade", template="plotly_dark", height=460,
                      legend=dict(orientation="h", y=-.25), margin=dict(b=110))
    return fig


def exibir_projecao(cotas, carteiras, exibir_grafico, tabelas_pdf, figuras_pdf):
    import streamlit as st

    st.subheader("Distribuição dos resultados projetados")
    st.caption("Escolha o histórico para estimar os parâmetros e o prazo do retorno acumulado projetado.")
    cotas = recortar_historico(cotas)
    disponiveis = {}
    for nome, meses in PRAZOS.items():
        try:
            recortar_historico(cotas, meses)
            disponiveis[nome] = meses
        except ValueError:
            pass
    disponiveis["Desde o início"] = None
    a, b, c = st.columns(3)
    nome = a.selectbox("Carteira para projeção", list(carteiras), key="projecao_carteira")
    janela = b.selectbox("Histórico para análise", list(disponiveis), key="projecao_historico")
    if st.session_state.get("projecao_janela_anterior") != janela:
        st.session_state["projecao_prazo"] = janela if janela in PRAZOS else "12 meses"
        st.session_state["projecao_janela_anterior"] = janela
    prazo = c.selectbox("Prazo da projeção", list(PRAZOS), key="projecao_prazo")
    st.caption("Janelas sem histórico completo não aparecem. Em ‘Desde o início’, o prazo inicial é 12 meses; você pode ajustá-lo.")
    try:
        historico = recortar_historico(cotas, disponiveis[janela])
        resultado = calcular_projecao(historico, carteiras[nome], PRAZOS[prazo])
    except ValueError as erro:
        st.info(f"Projeção indisponível: {erro}")
        return
    contexto = (f"{nome} · Histórico: {resultado.inicio:%d/%m/%Y} a {resultado.fim:%d/%m/%Y} "
                f"({resultado.observacoes} retornos) · Projeção: {prazo} após a última cota, "
                f"até {resultado.fim + pd.DateOffset(months=PRAZOS[prazo]):%d/%m/%Y}.")
    st.info(contexto)
    if PRAZOS[prazo] >= 60:
        st.warning("Projeção de longo prazo: pequenas mudanças no retorno e no risco estimados podem alterar muito os resultados.")
    if resultado.fim - resultado.inicio < pd.Timedelta(days=365.25 * PRAZOS[prazo] / 12):
        st.caption("O prazo projetado supera a duração do histórico analisado.")
    exibir_grafico(grafico_projecao(resultado, f"Resultados projetados — {nome} — {prazo}"), width="stretch", key="grafico_projecao")
    nota = ("Modelo normal dos log-retornos, convertido em rentabilidade percentual (curva lognormal). "
            "Pesos mantidos por rebalanceamento nas observações; sem custos de negociação, tributos ou novos aportes. "
            "Faixas centrais de 90%, 95% e 99% condicionadas ao modelo, sem incorporar incerteza dos parâmetros. "
            "Não são garantias nem intervalos de confiança da média. O modelo supõe incrementos independentes "
            "e parâmetros constantes e pode subestimar eventos extremos. As alocações otimizadas foram escolhidas "
            "com dados históricos, o que pode favorecer suas estimativas. Resultados passados não garantem resultados futuros.")
    titulo, figura, _ = figuras_pdf[-1]
    figuras_pdf[-1] = (titulo, figura, contexto + " " + nota)
    tabela = pd.DataFrame([{"Faixa central do modelo": f"{p:.0%}", "Limite inferior": f"{resultado.limites(p)[0]:.2%}",
                            "Limite superior": f"{resultado.limites(p)[1]:.2%}"} for p in (.90, .95, .99)])
    st.dataframe(tabela, hide_index=True, width="stretch")
    tabelas_pdf.append((f"Faixas de resultados — {nome} — {prazo}", tabela))
    st.caption(nota)
