"""Motor de backtest e métricas de risco.

Correções em relação ao script do TCC:
  * o retorno da carteira é o retorno composto de uma cesta com pesos fixos
    e reinvestimento diário, não a soma de retornos acumulados individuais;
  * `beta` é calculado por regressão nos retornos, com os tickers alinhados
    por nome (o original alinhava por posição e trocava os betas de lugar);
  * a correlação usa retornos, não preços (correlação de séries de preço com
    tendência é espúria e sempre altíssima);
  * custo de transação em cada rebalanceamento;
  * métricas completas: vol, Sharpe, drawdown máximo, beta, alfa, tracking error.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DIAS_ANO = 252


# ---------------------------------------------------------------------------
# Retorno da carteira
# ---------------------------------------------------------------------------
def retorno_carteira(retornos: pd.DataFrame, pesos: pd.Series,
                     *, rebalancear: bool = False,
                     custo_bps: float = 0.0) -> pd.Series:
    """Série diária de retornos de uma carteira.

    `rebalancear=False` (buy-and-hold) deixa os pesos derivarem com o preço,
    que é o que de fato acontece quando se compra e segura por um ano.
    """
    ativos = [a for a in pesos.index if a in retornos.columns]
    if not ativos:
        return pd.Series(dtype=float)
    r = retornos[ativos].fillna(0.0)
    w = pesos[ativos].astype(float)
    w = w / w.sum() if w.sum() > 0 else w

    if rebalancear:
        rp = r @ w
    else:
        valores = (1.0 + r).cumprod().mul(w, axis=1)
        total = valores.sum(axis=1)
        rp = total.pct_change()
        rp.iloc[0] = total.iloc[0] - 1.0

    custo = custo_bps / 10_000.0
    if custo > 0 and len(rp):
        rp.iloc[0] = (1 + rp.iloc[0]) * (1 - custo) - 1        # compra
        rp.iloc[-1] = (1 + rp.iloc[-1]) * (1 - custo) - 1      # venda
    return rp.rename("carteira")


def acumulado(retornos_diarios: pd.Series | pd.DataFrame):
    return (1 + retornos_diarios).cumprod() - 1


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------
@dataclass
class Metricas:
    retorno_total: float
    retorno_anualizado: float
    volatilidade: float
    sharpe: float
    drawdown_maximo: float
    beta: float
    alfa_anual: float
    tracking_error: float
    information_ratio: float
    dias: int

    def to_dict(self) -> dict:
        return {
            "Retorno total": self.retorno_total,
            "Retorno anualizado": self.retorno_anualizado,
            "Volatilidade anual": self.volatilidade,
            "Sharpe": self.sharpe,
            "Drawdown máximo": self.drawdown_maximo,
            "Beta": self.beta,
            "Alfa anual": self.alfa_anual,
            "Tracking error": self.tracking_error,
            "Information ratio": self.information_ratio,
            "Pregões": self.dias,
        }


def drawdown_maximo(retornos: pd.Series) -> float:
    curva = (1 + retornos.fillna(0)).cumprod()
    pico = curva.cummax()
    return float((curva / pico - 1).min())


def calcular_metricas(rp: pd.Series, rb: pd.Series | None = None,
                      rf_aa: float = 0.0) -> Metricas:
    rp = rp.dropna()
    n = len(rp)
    if n == 0:
        return Metricas(*([float("nan")] * 9), dias=0)

    total = float((1 + rp).prod() - 1)
    anos = n / DIAS_ANO
    anual = float((1 + total) ** (1 / anos) - 1) if anos > 0 and total > -1 else float("nan")
    vol = float(rp.std(ddof=1) * np.sqrt(DIAS_ANO))
    sharpe = (anual - rf_aa) / vol if vol > 0 else float("nan")
    mdd = drawdown_maximo(rp)

    beta = alfa = te = ir = float("nan")
    if rb is not None and len(rb.dropna()) > 1:
        par = pd.concat([rp, rb.rename("bench")], axis=1).dropna()
        if len(par) > 2 and par["bench"].var() > 0:
            beta = float(par.iloc[:, 0].cov(par["bench"]) / par["bench"].var())
            rb_total = float((1 + par["bench"]).prod() - 1)
            rb_anual = ((1 + rb_total) ** (1 / (len(par) / DIAS_ANO)) - 1)
            alfa = anual - (rf_aa + beta * (rb_anual - rf_aa))
            ativo = par.iloc[:, 0] - par["bench"]
            te = float(ativo.std(ddof=1) * np.sqrt(DIAS_ANO))
            ir = float(ativo.mean() * DIAS_ANO / te) if te > 0 else float("nan")

    return Metricas(total, anual, vol, sharpe, mdd, beta, alfa, te, ir, n)


def betas_individuais(retornos: pd.DataFrame, retorno_bench: pd.Series) -> pd.Series:
    """Beta de cada ativo — alinhado por nome de coluna, não por posição."""
    par = retornos.join(retorno_bench.rename("_bench"), how="inner").dropna()
    if len(par) < 3 or par["_bench"].var() == 0:
        return pd.Series(dtype=float, index=retornos.columns)
    varb = par["_bench"].var()
    return pd.Series({c: par[c].cov(par["_bench"]) / varb
                      for c in par.columns if c != "_bench"})


def matriz_correlacao(retornos: pd.DataFrame, retorno_bench: pd.Series | None = None
                      ) -> pd.DataFrame:
    df = retornos.copy()
    if retorno_bench is not None:
        df = df.join(retorno_bench.rename("Ibovespa"), how="inner")
    return df.corr(method="pearson")


# ---------------------------------------------------------------------------
# Backtest com rebalanceamento periódico
# ---------------------------------------------------------------------------
@dataclass
class ResultadoBacktest:
    retornos_diarios: pd.Series
    retornos_bench: pd.Series
    metricas: Metricas
    metricas_bench: Metricas
    composicoes: dict = field(default_factory=dict)
    log: list = field(default_factory=list)


def rodar_backtest(
    montar_carteira,
    datas_rebalance: list[pd.Timestamp],
    retornos_todos: pd.DataFrame,
    retorno_bench: pd.Series,
    *,
    custo_bps: float = 15.0,
    rf_aa: float = 0.0,
) -> ResultadoBacktest:
    """`montar_carteira(data)` -> pd.Series de pesos indexada por ticker.

    Entre uma data de rebalanceamento e a próxima, a carteira é mantida
    (buy-and-hold), como manda a regra de Greenblatt de segurar por um ano.
    """
    trechos, composicoes, registro = [], {}, []
    datas = sorted(datas_rebalance)

    for i, dt in enumerate(datas):
        fim = datas[i + 1] if i + 1 < len(datas) else retornos_todos.index.max()
        janela = retornos_todos.loc[(retornos_todos.index > dt) & (retornos_todos.index <= fim)]
        if janela.empty:
            continue
        try:
            pesos = montar_carteira(dt)
        except Exception as exc:                              # noqa: BLE001
            registro.append(f"{dt:%Y-%m-%d}: falhou ao montar carteira ({exc})")
            continue
        if pesos is None or pesos.sum() == 0:
            registro.append(f"{dt:%Y-%m-%d}: nenhuma ação aprovada nos filtros")
            continue
        composicoes[pd.Timestamp(dt)] = pesos
        trechos.append(retorno_carteira(janela, pesos, custo_bps=custo_bps))
        registro.append(f"{dt:%Y-%m-%d}: {int((pesos > 0).sum())} ativos")

    rp = pd.concat(trechos).sort_index() if trechos else pd.Series(dtype=float)
    rb = retorno_bench.reindex(rp.index).fillna(0.0) if len(rp) else retorno_bench

    return ResultadoBacktest(
        retornos_diarios=rp,
        retornos_bench=rb,
        metricas=calcular_metricas(rp, rb, rf_aa),
        metricas_bench=calcular_metricas(rb, rb, rf_aa),
        composicoes=composicoes,
        log=registro,
    )
