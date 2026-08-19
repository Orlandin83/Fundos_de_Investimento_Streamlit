"""Coleta e normaliza benchmarks usados nos gráficos da aplicação."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from bcb import sgs


BENCHMARK_NENHUM = "Nenhum"
BENCHMARK_CDI = "CDI"
BENCHMARK_IBOVESPA = "Ibovespa"
OPCOES_BENCHMARK = (BENCHMARK_NENHUM, BENCHMARK_CDI, BENCHMARK_IBOVESPA)
NOMES_SERIES = {
    BENCHMARK_CDI: "Benchmark: CDI",
    BENCHMARK_IBOVESPA: "Benchmark: Ibovespa",
}
FONTES_BENCHMARK = {
    BENCHMARK_CDI: "CDI: SGS 12 — Banco Central do Brasil.",
    BENCHMARK_IBOVESPA: "Ibovespa (^BVSP): Yahoo Finance, coluna Close.",
}

CODIGO_CDI_SGS = 12
TICKER_IBOVESPA = "^BVSP"


class ErroBenchmark(RuntimeError):
    """Erro de consulta ou estrutura inesperada em uma fonte de benchmark."""


def _validar_periodo(inicio: date, fim: date) -> None:
    if inicio > fim:
        raise ValueError("A data inicial do benchmark não pode ser posterior à final.")


def _serie_numerica(dados: pd.Series, nome: str) -> pd.Series:
    """Normaliza índice, valores e duplicidades de uma série temporal."""
    serie = pd.to_numeric(dados, errors="coerce").dropna().copy()
    if serie.empty:
        raise ErroBenchmark(f"A fonte não retornou observações válidas para {nome}.")
    indice = pd.to_datetime(serie.index, errors="coerce", utc=True)
    validos = ~indice.isna()
    serie = serie.loc[validos]
    indice = indice[validos].tz_convert(None).normalize()
    serie.index = indice
    serie = serie[~serie.index.duplicated(keep="last")].sort_index()
    if serie.empty:
        raise ErroBenchmark(f"A fonte não retornou datas válidas para {nome}.")
    return serie.astype(float)


def acumular_taxas_percentuais(taxas: pd.Series, nome: str) -> pd.Series:
    """Transforma taxas diárias percentuais em uma série base 100."""
    taxas = _serie_numerica(taxas, nome)
    fatores = 1.0 + taxas.divide(100.0)
    if (fatores <= 0).any():
        raise ErroBenchmark(f"{nome} contém uma taxa diária menor ou igual a -100%.")
    acumulado = fatores.cumprod()
    return acumulado.divide(acumulado.iloc[0]).multiply(100.0).rename(nome)


def acumular_variacoes_fechamento(fechamentos: pd.Series, nome: str) -> pd.Series:
    """Calcula o retorno acumulado base 100 pelas variações do fechamento."""
    fechamentos = _serie_numerica(fechamentos, nome)
    fechamentos = fechamentos[fechamentos > 0]
    if fechamentos.empty:
        raise ErroBenchmark(f"{nome} não possui fechamentos positivos.")
    variacoes = fechamentos.pct_change(fill_method=None).fillna(0.0)
    return (1.0 + variacoes).cumprod().multiply(100.0).rename(nome)


def _periodos_sgs(inicio: date, fim: date):
    """Divide consultas diárias do SGS em janelas inferiores a dez anos."""
    cursor = inicio
    while cursor <= fim:
        limite = (pd.Timestamp(cursor) + pd.DateOffset(years=9)).date() - timedelta(days=1)
        fim_janela = min(fim, limite)
        yield cursor, fim_janela
        cursor = fim_janela + timedelta(days=1)


def carregar_cdi(inicio: date, fim: date) -> pd.Series:
    """Obtém a taxa CDI diária (SGS 12) e devolve sua evolução base 100."""
    _validar_periodo(inicio, fim)
    partes: list[pd.Series] = []
    try:
        for inicio_janela, fim_janela in _periodos_sgs(inicio, fim):
            dados = sgs.get(
                {"CDI": CODIGO_CDI_SGS},
                start=inicio_janela,
                end=fim_janela,
                timeout=30,
            )
            if not dados.empty:
                partes.append(dados.iloc[:, 0])
    except Exception as erro:
        raise ErroBenchmark(f"Falha ao consultar o CDI no Banco Central: {erro}") from erro
    if not partes:
        raise ErroBenchmark("O Banco Central não retornou dados do CDI para o período.")
    taxas = pd.concat(partes)
    return acumular_taxas_percentuais(taxas, NOMES_SERIES[BENCHMARK_CDI])


def _coluna_close(dados: pd.DataFrame) -> pd.Series:
    if isinstance(dados.columns, pd.MultiIndex):
        if ("Close", TICKER_IBOVESPA) in dados.columns:
            return dados[("Close", TICKER_IBOVESPA)]
        colunas_close = [coluna for coluna in dados.columns if coluna[0] == "Close"]
        if colunas_close:
            return dados[colunas_close[0]]
    elif "Close" in dados.columns:
        return dados["Close"]
    raise ErroBenchmark("A resposta do Yahoo Finance não contém a coluna 'Close'.")


def carregar_ibovespa(inicio: date, fim: date) -> pd.Series:
    """Obtém o fechamento do Ibovespa e devolve suas variações acumuladas."""
    _validar_periodo(inicio, fim)
    try:
        dados = yf.download(
            TICKER_IBOVESPA,
            start=inicio.isoformat(),
            # No yfinance, ``end`` é exclusivo.
            end=(fim + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
            progress=False,
            threads=False,
            timeout=30,
            multi_level_index=False,
        )
    except Exception as erro:
        raise ErroBenchmark(f"Falha ao consultar o Ibovespa no Yahoo Finance: {erro}") from erro
    if dados is None or dados.empty:
        raise ErroBenchmark("O Yahoo Finance não retornou dados do Ibovespa para o período.")
    return acumular_variacoes_fechamento(
        _coluna_close(dados), NOMES_SERIES[BENCHMARK_IBOVESPA]
    )


def carregar_benchmark(benchmark: str, inicio: date, fim: date) -> pd.Series:
    """Carrega o benchmark selecionado em formato base 100."""
    if benchmark == BENCHMARK_CDI:
        return carregar_cdi(inicio, fim)
    if benchmark == BENCHMARK_IBOVESPA:
        return carregar_ibovespa(inicio, fim)
    if benchmark == BENCHMARK_NENHUM:
        return pd.Series(dtype=float, name=BENCHMARK_NENHUM)
    raise ValueError(f"Benchmark desconhecido: {benchmark}")
