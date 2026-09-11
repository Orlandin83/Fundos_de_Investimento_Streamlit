"""Consultas e cálculos financeiros usados pela aplicação Streamlit."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from database import consultar_cotas, limites_do_banco, listar_fundos


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
    carteira_unica: bool = False


def carregar_cotas(
    cnpjs: list[str] | tuple[str, ...],
    inicio: pd.Timestamp,
    fim: pd.Timestamp,
    datas_comuns: bool = True,
) -> pd.DataFrame:
    """Carrega cotas; opcionalmente mantém somente datas comuns aos fundos."""
    if not cnpjs:
        return pd.DataFrame()
    dados = consultar_cotas(cnpjs, inicio.date(), fim.date())
    if dados.empty:
        return pd.DataFrame()
    if dados.duplicated(['data', 'cnpj']).any():
        raise ValueError('Existem subclasses simultâneas para um fundo nesta janela. Selecione uma série por subclasse; a série não será agregada automaticamente.')
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


def validar_alocacoes_fixas(
    cnpjs: list[str],
    pesos_fixos: dict[str, float] | None = None,
    alocacao_minima: float = ALOCACAO_MINIMA_FRONTEIRA,
) -> tuple[np.ndarray, np.ndarray]:
    """Retorna pisos/fixações e índices livres; pesos são frações de 1."""
    fixos = pesos_fixos or {}
    if not np.isfinite(alocacao_minima) or not 0 <= alocacao_minima <= 1:
        raise ValueError("A alocação mínima deve estar entre 0% e 100%.")
    if set(fixos) - set(cnpjs):
        raise ValueError("Há uma alocação fixada para um fundo fora da seleção.")
    for valor in fixos.values():
        if not np.isfinite(valor) or not alocacao_minima <= valor <= 1:
            raise ValueError(
                f"Cada alocação fixada deve estar entre {alocacao_minima:.0%} e 100%. "
                "Ajuste o percentual ou desmarque a fixação."
            )
    base = np.array([fixos.get(c, alocacao_minima) for c in cnpjs], dtype=float)
    livres = np.array([i for i, c in enumerate(cnpjs) if c not in fixos], dtype=int)
    if base.sum() > 1 + 1e-10:
        raise ValueError(
            f"As alocações fixadas não deixam saldo suficiente para o mínimo de "
            f"{alocacao_minima:.0%} em cada fundo livre. Reduza ou libere uma alocação."
        )
    if not len(livres) and not np.isclose(base.sum(), 1, atol=1e-10, rtol=0):
        raise ValueError("Com todos os fundos fixados, as alocações devem totalizar 100%.")
    return base, livres


def _otimizar_minima_variancia(
    retornos_anuais: np.ndarray,
    covariancia_anual: np.ndarray,
    retorno_alvo: float | None = None,
    alocacao_minima: float = ALOCACAO_MINIMA_FRONTEIRA,
    pesos_base: np.ndarray | None = None,
    indices_livres: np.ndarray | None = None,
) -> np.ndarray:
    # Otimiza apenas o saldo dos ativos livres. A avaliação usa a carteira
    # completa para incluir as covariâncias com os ativos fixados.
    base = np.full(len(retornos_anuais), alocacao_minima) if pesos_base is None else pesos_base.copy()
    livres = np.arange(len(base)) if indices_livres is None else indices_livres
    saldo = max(0.0, 1.0 - base.sum())
    if len(livres) <= 1 or saldo <= 1e-10:
        if len(livres):
            base[livres[0]] += saldo
        return base

    def compor(distribuicao):
        pesos = base.copy()
        pesos[livres] += saldo * distribuicao
        return pesos

    escala = max(float(np.max(np.abs(covariancia_anual))), 1e-12)
    restricoes = [{"type": "eq", "fun": lambda q: float(q.sum() - 1), "jac": lambda q: np.ones(len(q))}]
    inicial = np.repeat(1.0 / len(livres), len(livres))
    medias_livres = retornos_anuais[livres]
    amplitude = float(np.ptp(medias_livres))
    if retorno_alvo is not None and amplitude > 1e-12:
        restricoes.append({
            "type": "eq",
            "fun": lambda q: float((compor(q) @ retornos_anuais - retorno_alvo) / (saldo * amplitude)),
            "jac": lambda q: medias_livres / amplitude,
        })
        fracao = np.clip((retorno_alvo - base @ retornos_anuais - saldo * medias_livres.min()) / (saldo * amplitude), 0, 1)
        inicial = np.zeros(len(livres))
        inicial[int(np.argmin(medias_livres))] = 1 - fracao
        inicial[int(np.argmax(medias_livres))] = fracao
    resultado = minimize(
        lambda q: float(compor(q) @ covariancia_anual @ compor(q)) / escala,
        inicial,
        jac=lambda q: 2 * saldo * (covariancia_anual @ compor(q))[livres] / escala,
        method="SLSQP", bounds=[(0.0, 1.0)] * len(livres), constraints=restricoes,
        options={"ftol": 1e-12, "maxiter": 2_000},
    )
    if not resultado.success:
        raise RuntimeError(f"A otimização não convergiu: {resultado.message}")
    q = np.clip(resultado.x, 0, 1)
    pesos = compor(q / q.sum())
    if retorno_alvo is not None and not np.isclose(pesos @ retornos_anuais, retorno_alvo, atol=1e-8, rtol=1e-7):
        raise RuntimeError("A otimização não atingiu o retorno solicitado.")
    return pesos


def calcular_fronteira_eficiente(
    cotas: pd.DataFrame,
    quantidade_pontos: int = 60,
    quantidade_simulacoes: int = 3_000,
    alocacao_minima: float = ALOCACAO_MINIMA_FRONTEIRA,
    pesos_fixos: dict[str, float] | None = None,
) -> ResultadoFronteira:
    """Calcula a fronteira long-only com piso por fundo e dados anualizados."""
    if cotas.shape[1] < 2:
        raise ValueError("Selecione pelo menos dois fundos para a fronteira eficiente.")
    base, livres = validar_alocacoes_fixas(list(cotas.columns), pesos_fixos, alocacao_minima)
    saldo = max(0.0, 1.0 - base.sum())
    carteira_unica = len(livres) <= 1 or saldo <= 1e-10
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
        medias, covariancia, alocacao_minima=alocacao_minima,
        pesos_base=base, indices_livres=livres
    )
    retorno_minimo = float(pesos_minimo @ medias)
    risco_minimo = _risco(pesos_minimo, covariancia)

    pesos_maximo = base.copy()
    pesos_extremo_inferior = base.copy()
    if len(livres):
        pesos_maximo[livres[int(np.argmax(medias[livres]))]] += saldo
        pesos_extremo_inferior[livres[int(np.argmin(medias[livres]))]] += saldo
    retorno_maximo = float(pesos_maximo @ medias)
    risco_maximo = _risco(pesos_maximo, covariancia)
    retorno_extremo_inferior = float(pesos_extremo_inferior @ medias)

    # Em empates de retorno, prefere a carteira de menor risco.
    retorno_constante = abs(retorno_maximo - retorno_extremo_inferior) <= 1e-12
    if retorno_constante:
        pesos_maximo = pesos_minimo.copy()
        retorno_maximo, risco_maximo = retorno_minimo, risco_minimo
    pontos = [{"risco": risco_minimo, "retorno": retorno_minimo, "pesos": pesos_minimo}]
    if not carteira_unica and not retorno_constante:
        pontos.extend([
            {"risco": _risco(pesos_extremo_inferior, covariancia),
             "retorno": retorno_extremo_inferior, "pesos": pesos_extremo_inferior},
            {"risco": risco_maximo, "retorno": retorno_maximo, "pesos": pesos_maximo},
        ])
        for alvo in np.linspace(retorno_extremo_inferior, retorno_maximo, max(3, quantidade_pontos))[1:-1]:
            pesos = _otimizar_minima_variancia(
                medias, covariancia, float(alvo), alocacao_minima, base, livres
            )
            pontos.append({"risco": _risco(pesos, covariancia), "retorno": float(pesos @ medias), "pesos": pesos})
    pontos.sort(key=lambda ponto: ponto["retorno"])

    riscos_fundos = pd.Series(np.sqrt(np.diag(covariancia)), index=nomes)
    retornos_fundos = pd.Series(medias, index=nomes)

    # Amostra reprodutível de outras alocações long-only para dar contexto
    # visual à fronteira otimizada, respeitando o mesmo piso de alocação.
    gerador = np.random.default_rng(42)
    pesos_testados = np.tile(base, (quantidade_simulacoes, 1))
    if len(livres):
        pesos_testados[:, livres] += saldo * gerador.dirichlet(np.ones(len(livres)), size=quantidade_simulacoes)
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
        carteira_unica=carteira_unica,
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
