"""Markowitz (média-variância) com restrições realistas.

Implementação própria com scipy (SLSQP) — sem depender do riskfolio-lib,
que é pesado e quebra com frequência entre versões do numpy/cvxpy.

Melhorias sobre o script do TCC:
  * matriz de covariância com encolhimento de Ledoit-Wolf (a covariância
    amostral de 252 dias para 30 ativos é muito ruidosa e gera pesos instáveis);
  * retorno esperado por média exponencial (dá mais peso ao passado recente)
    e com opção de encolhimento para a média do grupo;
  * teto de peso por ativo (evita carteiras com 60% em um papel);
  * fronteira eficiente parametrizada por retorno-alvo, com todos os pontos
    efetivamente resolvidos (o riskfolio devolve pontos inviáveis em silêncio).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize

DIAS_ANO = 252


# ---------------------------------------------------------------------------
# Estimadores
# ---------------------------------------------------------------------------
def cov_ledoit_wolf(returns: pd.DataFrame) -> pd.DataFrame:
    """Encolhimento para alvo de correlação constante (Ledoit & Wolf, 2003)."""
    X = returns.to_numpy(dtype=float)
    n, p = X.shape
    Xc = X - X.mean(axis=0)
    S = (Xc.T @ Xc) / n

    var = np.diag(S)
    std = np.sqrt(var)
    denom = np.outer(std, std)
    with np.errstate(divide="ignore", invalid="ignore"):
        R = np.where(denom > 0, S / denom, 0.0)
    r_bar = (R.sum() - p) / (p * (p - 1)) if p > 1 else 0.0
    F = r_bar * denom
    np.fill_diagonal(F, var)

    # intensidade do encolhimento
    y = Xc ** 2
    phi = float((y.T @ y / n - S ** 2).sum())
    gamma = float(((F - S) ** 2).sum())
    delta = 0.0 if gamma <= 0 else float(np.clip(phi / (n * gamma), 0.0, 1.0))

    Sigma = delta * F + (1 - delta) * S
    return pd.DataFrame(Sigma * DIAS_ANO, index=returns.columns, columns=returns.columns)


def cov_hist(returns: pd.DataFrame) -> pd.DataFrame:
    return returns.cov() * DIAS_ANO


def cov_ewma(returns: pd.DataFrame, lam: float = 0.94) -> pd.DataFrame:
    X = returns.to_numpy(dtype=float)
    n = X.shape[0]
    w = lam ** np.arange(n - 1, -1, -1)
    w = w / w.sum()
    mu = (w[:, None] * X).sum(axis=0)
    Xc = X - mu
    S = (Xc * w[:, None]).T @ Xc
    return pd.DataFrame(S * DIAS_ANO, index=returns.columns, columns=returns.columns)


def mu_hist(returns: pd.DataFrame) -> pd.Series:
    return returns.mean() * DIAS_ANO


def mu_ewma(returns: pd.DataFrame, lam: float = 0.97) -> pd.Series:
    n = len(returns)
    w = lam ** np.arange(n - 1, -1, -1)
    w = w / w.sum()
    return pd.Series((returns.to_numpy(dtype=float) * w[:, None]).sum(axis=0) * DIAS_ANO,
                     index=returns.columns)


def mu_shrink(returns: pd.DataFrame, intensidade: float = 0.5) -> pd.Series:
    """Encolhe a média histórica em direção à média do grupo (James-Stein simples)."""
    m = mu_hist(returns)
    return (1 - intensidade) * m + intensidade * m.mean()


def estimar(returns: pd.DataFrame, metodo_mu: str, metodo_cov: str
            ) -> tuple[pd.Series, pd.DataFrame]:
    mu = {"hist": mu_hist, "ewma": mu_ewma, "media_ponderada": mu_shrink}[metodo_mu](returns)
    cov = {"hist": cov_hist, "ewma": cov_ewma, "ledoit_wolf": cov_ledoit_wolf}[metodo_cov](returns)
    return mu, cov


# ---------------------------------------------------------------------------
# Otimização
# ---------------------------------------------------------------------------
@dataclass
class Fronteira:
    pesos: pd.DataFrame       # ativos x carteiras
    retorno: np.ndarray       # retorno esperado anual de cada carteira
    risco: np.ndarray         # volatilidade anual de cada carteira
    sharpe: np.ndarray


def _resolver(mu: np.ndarray, cov: np.ndarray, w_max: float, w_min: float,
              alvo: float | None) -> np.ndarray | None:
    n = len(mu)
    w_max = max(w_max, 1.0 / n + 1e-9)          # garante viabilidade
    x0 = np.full(n, 1.0 / n)
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    if alvo is not None:
        cons.append({"type": "eq", "fun": lambda w, a=alvo: float(w @ mu) - a})
    bounds = [(w_min, w_max)] * n

    res = minimize(lambda w: float(w @ cov @ w), x0, method="SLSQP",
                   bounds=bounds, constraints=cons,
                   options={"maxiter": 500, "ftol": 1e-12})
    if not res.success:
        return None
    w = np.clip(res.x, 0.0, None)
    s = w.sum()
    return w / s if s > 0 else None


def carteira_min_variancia(mu: pd.Series, cov: pd.DataFrame,
                           w_max: float = 1.0, w_min: float = 0.0) -> pd.Series:
    w = _resolver(mu.to_numpy(float), cov.to_numpy(float), w_max, w_min, None)
    if w is None:
        w = np.full(len(mu), 1.0 / len(mu))
    return pd.Series(w, index=mu.index)


def fronteira_eficiente(mu: pd.Series, cov: pd.DataFrame, *, pontos: int = 20,
                        w_max: float = 0.15, w_min: float = 0.0,
                        rf: float = 0.0) -> Fronteira:
    m = mu.to_numpy(float)
    S = cov.to_numpy(float)

    w_mv = _resolver(m, S, w_max, w_min, None)
    if w_mv is None:
        w_mv = np.full(len(m), 1.0 / len(m))
    r_min = float(w_mv @ m)

    # carteira de retorno máximo respeitando o teto de peso:
    # concentra nos melhores ativos até estourar o limite
    n = len(m)
    w_max_eff = max(w_max, 1.0 / n + 1e-9)
    ordem = np.argsort(-m)
    w_hi = np.zeros(n)
    restante = 1.0
    for i in ordem:
        aloc = min(w_max_eff, restante)
        w_hi[i] = aloc
        restante -= aloc
        if restante <= 1e-12:
            break
    r_max = float(w_hi @ m)

    alvos = np.linspace(r_min, r_max, pontos)
    cols, rets, riscos = [], [], []
    for k, alvo in enumerate(alvos):
        w = _resolver(m, S, w_max, w_min, None if k == 0 else float(alvo))
        if w is None:
            continue
        cols.append(w)
        rets.append(float(w @ m))
        riscos.append(float(np.sqrt(max(w @ S @ w, 0.0))))

    if not cols:
        w = np.full(n, 1.0 / n)
        cols, rets, riscos = [w], [float(w @ m)], [float(np.sqrt(w @ S @ w))]

    W = pd.DataFrame(np.array(cols).T, index=mu.index,
                     columns=[f"Carteira {i+1}" for i in range(len(cols))])
    rets_a = np.array(rets)
    riscos_a = np.array(riscos)
    sharpe = np.where(riscos_a > 0, (rets_a - rf) / riscos_a, np.nan)
    return Fronteira(pesos=W, retorno=rets_a, risco=riscos_a, sharpe=sharpe)


def limpar_pesos(w: pd.Series, minimo: float = 0.005) -> pd.Series:
    """Zera posições irrelevantes (<0,5%) e renormaliza — evita a 'poeira'
    de 40 ativos com 0,1% cada que aparecia nas carteiras do TCC."""
    w = w.where(w >= minimo, 0.0)
    total = w.sum()
    return w / total if total > 0 else w
