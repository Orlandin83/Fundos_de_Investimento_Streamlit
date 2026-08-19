"""Consultas e cálculos financeiros usados pela aplicação Streamlit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import minimize


DIAS_UTEIS_ANO = 252
MINIMO_OBSERVACOES = 60
ALOCACAO_MINIMA_FRONTEIRA = 0.01


@dataclass(frozen=True)
class ResultadoFronteira:
    pontos: pd.DataFrame
    carteiras_testadas: pd.DataFrame
    pesos_minimo_risco: pd.Series
    pesos_maior_retorno: pd.Series
    retorno_minimo_risco: float
    risco_minimo: float
    retorno_maximo: float
    risco_maximo_retorno: float
    retornos_anuais_fundos: pd.Series
    riscos_anuais_fundos: pd.Series


def listar_fundos(banco: Path) -> pd.DataFrame:
    """Retorna o universo de fundos e sua cobertura no banco."""
    with duckdb.connect(str(banco), read_only=True) as conexao:
        return conexao.execute(
            """
            SELECT cnpj, nome, primeira_data_disponivel, ultima_data_disponivel,
                   quantidade_registros, status
            FROM fundos_controle
            ORDER BY nome
            """
        ).fetchdf()


def limites_do_banco(banco: Path) -> tuple[pd.Timestamp, pd.Timestamp]:
    with duckdb.connect(str(banco), read_only=True) as conexao:
        inicio, fim = conexao.execute(
            "SELECT MIN(data), MAX(data) FROM cotas_diarias"
        ).fetchone()
    if inicio is None or fim is None:
        raise ValueError("O banco ainda não possui cotas diárias.")
    return pd.Timestamp(inicio), pd.Timestamp(fim)


def carregar_cotas(
    banco: Path,
    cnpjs: list[str] | tuple[str, ...],
    inicio: pd.Timestamp,
    fim: pd.Timestamp,
    datas_comuns: bool = True,
) -> pd.DataFrame:
    """Carrega cotas; opcionalmente mantém somente datas comuns aos fundos."""
    if not cnpjs:
        return pd.DataFrame()
    with duckdb.connect(str(banco), read_only=True) as conexao:
        dados = conexao.execute(
            """
            SELECT data, cnpj, valor_cota
            FROM cotas_diarias
            WHERE cnpj IN (SELECT UNNEST(?::VARCHAR[]))
              AND data BETWEEN ? AND ?
            ORDER BY data, cnpj
            """,
            [list(cnpjs), inicio.date(), fim.date()],
        ).fetchdf()
    if dados.empty:
        return pd.DataFrame()
    cotas = dados.pivot(index="data", columns="cnpj", values="valor_cota").sort_index()
    cotas.index = pd.to_datetime(cotas.index)
    cotas = cotas.reindex(columns=list(cnpjs))
    return cotas.dropna(how="any") if datas_comuns else cotas.dropna(how="all")


def performance_base_100(cotas: pd.DataFrame) -> pd.DataFrame:
    if cotas.empty:
        return cotas.copy()
    resultado = cotas.copy()
    for coluna in resultado:
        serie = resultado[coluna].dropna()
        if not serie.empty:
            resultado[coluna] = resultado[coluna].divide(serie.iloc[0]).multiply(100.0)
    return resultado


def retorno_acumulado_base_100(
    valores: pd.DataFrame | pd.Series,
) -> pd.DataFrame | pd.Series:
    """Converte uma evolução base 100 em retorno acumulado decimal."""
    return valores.divide(100.0).subtract(1.0)


def historico_carteira_sem_rebalanceamento(
    cotas: pd.DataFrame, pesos: pd.Series
) -> tuple[pd.Series, pd.DataFrame]:
    """Simula compra inicial e deixa os pesos variarem com o preço das cotas."""
    if cotas.empty:
        raise ValueError("Não há cotas para calcular a carteira.")
    pesos = pesos.reindex(cotas.columns).astype(float)
    if pesos.isna().any() or (pesos < 0).any() or not np.isclose(pesos.sum(), 1.0):
        raise ValueError("Os pesos devem ser não negativos e totalizar 100%.")
    quantidades = pesos / cotas.iloc[0]
    valores = cotas.multiply(quantidades, axis="columns")
    total = valores.sum(axis="columns")
    pesos_ao_longo_do_tempo = valores.divide(total, axis="index")
    return total.divide(total.iloc[0]).multiply(100.0).rename("Carteira"), pesos_ao_longo_do_tempo


def _risco(pesos: np.ndarray, covariancia_anual: np.ndarray) -> float:
    variancia = float(pesos @ covariancia_anual @ pesos)
    return float(np.sqrt(max(variancia, 0.0)))


def _otimizar_minima_variancia(
    retornos_anuais: np.ndarray,
    covariancia_anual: np.ndarray,
    retorno_alvo: float | None = None,
    alocacao_minima: float = ALOCACAO_MINIMA_FRONTEIRA,
) -> np.ndarray:
    quantidade = len(retornos_anuais)
    escala_variancia = max(float(np.max(np.abs(covariancia_anual))), 1e-12)
    restricoes: list[dict[str, object]] = [
        {"type": "eq", "fun": lambda pesos: float(np.sum(pesos) - 1.0)}
    ]
    if retorno_alvo is not None:
        restricoes.append(
            {
                "type": "eq",
                "fun": lambda pesos, alvo=retorno_alvo: float(
                    pesos @ retornos_anuais - alvo
                ),
            }
        )
    resultado = minimize(
        lambda pesos: float(pesos @ covariancia_anual @ pesos) / escala_variancia,
        np.repeat(1.0 / quantidade, quantidade),
        method="SLSQP",
        bounds=[(alocacao_minima, 1.0)] * quantidade,
        constraints=restricoes,
        options={"ftol": 1e-12, "maxiter": 2_000},
    )
    if not resultado.success:
        raise RuntimeError(f"A otimização não convergiu: {resultado.message}")
    pesos = np.clip(resultado.x, alocacao_minima, 1.0)
    excedente = np.maximum(pesos - alocacao_minima, 0.0)
    restante = 1.0 - alocacao_minima * quantidade
    if excedente.sum() <= 0:
        return np.repeat(1.0 / quantidade, quantidade)
    return alocacao_minima + restante * excedente / excedente.sum()


def calcular_fronteira_eficiente(
    cotas: pd.DataFrame,
    quantidade_pontos: int = 60,
    quantidade_simulacoes: int = 3_000,
    alocacao_minima: float = ALOCACAO_MINIMA_FRONTEIRA,
) -> ResultadoFronteira:
    """Calcula a fronteira long-only com piso por fundo e dados anualizados."""
    if cotas.shape[1] < 2:
        raise ValueError("Selecione pelo menos dois fundos para a fronteira eficiente.")
    if alocacao_minima < 0 or alocacao_minima * cotas.shape[1] >= 1.0:
        raise ValueError(
            "A alocação mínima deve ser positiva e permitir que os pesos totalizem 100%."
        )
    retornos = cotas.pct_change(fill_method=None).dropna(how="any")
    if len(retornos) < MINIMO_OBSERVACOES:
        raise ValueError(
            f"São necessários pelo menos {MINIMO_OBSERVACOES} retornos diários comuns; "
            f"a janela possui {len(retornos)}."
        )

    nomes = retornos.columns
    medias = retornos.mean().to_numpy(dtype=float) * DIAS_UTEIS_ANO
    covariancia = retornos.cov().to_numpy(dtype=float) * DIAS_UTEIS_ANO
    if not np.isfinite(medias).all() or not np.isfinite(covariancia).all():
        raise ValueError("Os retornos não produziram estimativas financeiras válidas.")

    pesos_minimo = _otimizar_minima_variancia(
        medias, covariancia, alocacao_minima=alocacao_minima
    )
    retorno_minimo = float(pesos_minimo @ medias)
    risco_minimo = _risco(pesos_minimo, covariancia)

    indice_maior_retorno = int(np.argmax(medias))
    pesos_maximo = np.full(len(medias), alocacao_minima)
    pesos_maximo[indice_maior_retorno] += 1.0 - alocacao_minima * len(medias)
    retorno_maximo = float(pesos_maximo @ medias)
    risco_maximo = _risco(pesos_maximo, covariancia)

    # Percorre toda a curva de mínima variância: do ativo/carteira com menor
    # retorno esperado, passa pelo ponto de menor risco e segue até o maior retorno.
    # O ramo a partir do menor risco é a fronteira eficiente em sentido estrito.
    pesos_extremo_inferior = np.full(len(medias), alocacao_minima)
    pesos_extremo_inferior[int(np.argmin(medias))] += 1.0 - alocacao_minima * len(medias)
    retorno_extremo_inferior = float(pesos_extremo_inferior @ medias)
    alvos = np.linspace(
        retorno_extremo_inferior, retorno_maximo, max(3, quantidade_pontos)
    )
    pontos: list[dict[str, object]] = []
    for alvo in alvos:
        try:
            pesos = _otimizar_minima_variancia(
                medias, covariancia, float(alvo), alocacao_minima
            )
        except RuntimeError:
            continue
        pontos.append(
            {
                "risco": _risco(pesos, covariancia),
                "retorno": float(pesos @ medias),
                "pesos": pesos,
            }
        )
    if len(pontos) < 2:
        raise RuntimeError("Não foi possível construir pontos suficientes da fronteira.")

    riscos_fundos = pd.Series(np.sqrt(np.diag(covariancia)), index=nomes)
    retornos_fundos = pd.Series(medias, index=nomes)

    # Amostra reprodutível de outras alocações long-only para dar contexto
    # visual à fronteira otimizada, respeitando o mesmo piso de alocação.
    gerador = np.random.default_rng(42)
    pesos_testados = alocacao_minima + (
        1.0 - alocacao_minima * len(nomes)
    ) * gerador.dirichlet(np.ones(len(nomes)), size=quantidade_simulacoes)
    retornos_testados = pesos_testados @ medias
    variancias_testadas = np.einsum(
        "ij,jk,ik->i", pesos_testados, covariancia, pesos_testados
    )
    carteiras_testadas = pd.DataFrame(
        {
            "risco": np.sqrt(np.maximum(variancias_testadas, 0.0)),
            "retorno": retornos_testados,
        }
    )
    return ResultadoFronteira(
        pontos=pd.DataFrame(pontos),
        carteiras_testadas=carteiras_testadas,
        pesos_minimo_risco=pd.Series(pesos_minimo, index=nomes),
        pesos_maior_retorno=pd.Series(pesos_maximo, index=nomes),
        retorno_minimo_risco=retorno_minimo,
        risco_minimo=risco_minimo,
        retorno_maximo=retorno_maximo,
        risco_maximo_retorno=risco_maximo,
        retornos_anuais_fundos=retornos_fundos,
        riscos_anuais_fundos=riscos_fundos,
    )


def risco_retorno_carteira_estatica(
    cotas: pd.DataFrame, pesos: pd.Series
) -> tuple[float, float]:
    """Posiciona uma alocação informada no plano de média-variância."""
    retornos = cotas.pct_change(fill_method=None).dropna(how="any")
    pesos_array = pesos.reindex(cotas.columns).to_numpy(dtype=float)
    medias = retornos.mean().to_numpy(dtype=float) * DIAS_UTEIS_ANO
    covariancia = retornos.cov().to_numpy(dtype=float) * DIAS_UTEIS_ANO
    return float(pesos_array @ medias), _risco(pesos_array, covariancia)
