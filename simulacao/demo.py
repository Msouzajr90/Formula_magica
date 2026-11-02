# -*- coding: utf-8 -*-
"""Base de demonstração: fontes falsas que passam pelo MESMO `base.atualizar`.

Serve para ver a aba sem esperar a primeira coleta e para os testes
percorrerem o caminho inteiro em segundos. Os códigos são reais para a tela
parecer o que vai ser; os números são inventados. O índice sai marcado
`"demo": true`: a tela avisa em vermelho e o `validar_precos.py` recusa.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd

# (ticker, nome, classe, beta, vol idiossincrática anual, início, fim, liquidez R$/dia, dividend yield)
ATIVOS = [
    ("PETR4", "PETROBRAS", "acao", 1.35, 0.30, None, None, 1.5e9, 0.08),
    ("PETR3", "PETROBRAS", "acao", 1.30, 0.30, None, None, 4e8, 0.08),
    ("VALE3", "VALE", "acao", 1.05, 0.28, None, None, 1.6e9, 0.07),
    ("ITUB4", "ITAU UNIBANCO", "acao", 1.00, 0.18, None, None, 9e8, 0.05),
    ("BBDC4", "BRADESCO", "acao", 1.05, 0.20, None, None, 7e8, 0.05),
    ("BBAS3", "BANCO DO BRASIL", "acao", 1.25, 0.24, None, None, 6e8, 0.07),
    ("ABEV3", "AMBEV", "acao", 0.65, 0.18, None, None, 4e8, 0.04),
    ("WEGE3", "WEG", "acao", 0.75, 0.22, None, None, 3e8, 0.015),
    ("RENT3", "LOCALIZA", "acao", 1.20, 0.26, None, None, 4e8, 0.01),
    ("SUZB3", "SUZANO", "acao", 0.55, 0.26, None, None, 3e8, 0.02),
    ("EGIE3", "ENGIE BRASIL", "acao", 0.55, 0.16, None, None, 1e8, 0.06),
    ("TAEE11", "TAESA", "acao", 0.45, 0.16, None, None, 9e7, 0.09),
    ("RADL3", "RAIA DROGASIL", "acao", 0.70, 0.22, None, None, 2e8, 0.01),
    ("LREN3", "LOJAS RENNER", "acao", 1.20, 0.26, None, None, 2.5e8, 0.02),
    ("PRIO3", "PRIO", "acao", 1.10, 0.40, "2011-03-01", None, 5e8, 0.0),
    ("B3SA3", "B3", "acao", 1.15, 0.22, None, None, 6e8, 0.04),
    ("MGLU3", "MAGAZINE LUIZA", "acao", 1.50, 0.50, "2011-05-02", None, 5e8, 0.005),
    ("GGBR4", "GERDAU", "acao", 1.20, 0.28, None, None, 2.5e8, 0.04),
    ("TOTS3", "TOTVS", "acao", 0.90, 0.24, None, None, 1.2e8, 0.01),
    ("CASH3", "MELIUZ", "acao", 1.60, 0.70, "2020-11-05", None, 6e7, 0.0),
    ("BRML3", "BR MALLS", "acao", 1.15, 0.26, None, "2023-08-18", 1.5e8, 0.02),
    ("AMER3", "AMERICANAS", "acao", 1.40, 0.40, None, None, 3e8, 0.005),
    ("MTSA4", "METISA", "acao", 0.60, 0.25, None, None, 2e5, 0.04),
    ("HGLG11", "CSHG LOGISTICA FII", "fii", 0.25, 0.12, None, None, 6e6, 0.08),
    ("KNRI11", "KINEA RENDA IMOBILIARIA FII", "fii", 0.20, 0.10, None, None, 5e6, 0.075),
    ("MXRF11", "MAXI RENDA FII", "fii", 0.20, 0.10, "2012-09-03", None, 1.2e7, 0.11),
    ("XPML11", "XP MALLS FII", "fii", 0.35, 0.14, "2018-01-02", None, 8e6, 0.085),
    ("BOVA11", "iShares Ibovespa", "etf", 1.00, 0.01, None, None, 1.2e9, 0.0),
    ("SMAL11", "iShares Small Cap", "etf", 1.10, 0.08, None, None, 6e7, 0.0),
    ("IVVB11", "iShares S&P 500 (em reais)", "etf", -0.15, 0.16, "2014-10-20", None, 2e8, 0.0),
    ("GOLD11", "Trend ouro", "etf", -0.20, 0.17, "2021-03-01", None, 2e7, 0.0),
]

# Selic aproximada, % a.a., nos pontos do tempo — interpolada entre eles.
SELIC = [("2010-01-01", 8.75), ("2010-07-01", 10.75), ("2011-08-01", 12.5),
         ("2012-10-15", 7.25), ("2013-04-15", 7.25), ("2014-04-01", 11.0),
         ("2015-08-01", 14.25), ("2016-10-15", 14.25), ("2017-12-01", 7.0),
         ("2018-03-20", 6.5), ("2019-07-31", 6.5), ("2020-08-05", 2.0),
         ("2021-03-17", 2.0), ("2022-08-03", 13.75), ("2023-08-02", 13.75),
         ("2024-05-08", 10.5), ("2024-09-18", 10.75), ("2025-06-18", 15.0),
         ("2026-03-18", 15.0), ("2026-10-30", 13.75)]

FERIADOS_FIXOS = {(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (12, 25)}


def _calendario(hoje: date) -> pd.DatetimeIndex:
    d = pd.bdate_range("2010-01-04", pd.Timestamp(hoje))
    return d[[(x.month, x.day) not in FERIADOS_FIXOS for x in d]]


def fontes_falsas(hoje: date, semente: int = 7) -> SimpleNamespace:
    rng = np.random.default_rng(semente)
    cal = _calendario(hoje)
    n = len(cal)
    mkt = rng.normal(0.07 / 252, 0.24 / np.sqrt(252), n)
    # dois regimes de queda forte, para o drawdown ter o que mostrar
    for ini, dias, choque in (("2015-01-02", 250, -0.0012), ("2020-02-20", 25, -0.012)):
        i = int(np.searchsorted(cal, pd.Timestamp(ini)))
        mkt[i:i + dias] += choque
    usd = rng.normal(0.10 / 252, 0.16 / np.sqrt(252), n)

    ajustado, fechamento, volume = {}, {}, {}
    for t, _nome, classe, beta, idio, ini, fim, liq, dy in ATIVOS:
        e = rng.normal(0, idio / np.sqrt(252), n)
        if t == "IVVB11" or t == "GOLD11":
            r = usd + beta * mkt + e
        else:
            r = beta * mkt + e + 0.01 / 252
        if t == "AMER3":
            i = int(np.searchsorted(cal, pd.Timestamp("2023-01-12")))
            r[i] = -0.77
            r[i + 1:] = r[i + 1:] * 1.8 - 0.002
        r = np.clip(r, -0.9, 1.0)
        aj = 20.0 * np.cumprod(1 + r)
        div = np.cumprod(np.full(n, 1 + dy / 252))
        px = aj / div
        vol = liq / px * rng.lognormal(0, 0.35, n)
        serie_aj = pd.Series(aj, index=cal)
        mascara = np.ones(n, dtype=bool)
        if ini:
            mascara &= cal >= pd.Timestamp(ini)
        if fim:
            mascara &= cal <= pd.Timestamp(fim)
        ajustado[t] = serie_aj.where(mascara)
        fechamento[t] = pd.Series(px, index=cal).where(mascara)
        volume[t] = pd.Series(vol, index=cal).where(mascara)

    ibov = pd.Series(68_000 * np.cumprod(1 + mkt), index=cal)

    d_selic = [pd.Timestamp(d) for d, _ in SELIC]
    v_selic = [v for _, v in SELIC]
    todos_dias = pd.bdate_range("2009-12-01", pd.Timestamp(hoje))
    x = (todos_dias - d_selic[0]).days.to_numpy(float)
    xp = np.array([(d - d_selic[0]).days for d in d_selic], float)
    selic_aa = np.interp(x, xp, v_selic)
    cdi_dia = np.round(((1 + (selic_aa - 0.10) / 100) ** (1 / 252) - 1) * 100, 6)
    cdi = {d.date(): float(v) for d, v in zip(todos_dias, cdi_dia)}

    def _recorte(df: pd.DataFrame, inicio, fim) -> pd.DataFrame:
        return df.loc[(df.index >= pd.Timestamp(inicio)) & (df.index <= pd.Timestamp(fim))]

    def precos(tickers, inicio, fim):
        cols = [t for t in tickers if t in ajustado]
        out = {}
        for k, fonte in (("preco", ajustado), ("fechamento", fechamento), ("volume", volume)):
            df = pd.DataFrame({t: fonte[t] for t in cols}, index=cal)
            out[k] = _recorte(df, inicio, fim).dropna(how="all", axis=1)
        return out

    return SimpleNamespace(
        precos=precos,
        ibov=lambda inicio, fim: ibov.loc[(ibov.index >= pd.Timestamp(inicio))
                                          & (ibov.index <= pd.Timestamp(fim))],
        cdi=lambda inicio, fim: {d: v for d, v in cdi.items() if inicio <= d <= fim},
    )


def candidatos_demo() -> dict[str, dict]:
    return {t: {"nome": nome, "classe": classe} for t, nome, classe, *_ in ATIVOS}
