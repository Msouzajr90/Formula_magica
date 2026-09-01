"""Histórico sintético — permite testar a aba de backtest do site sem rede.

Gera séries com estrutura realista: um fator de mercado comum, betas distintos,
e um prêmio pequeno para quem está bem no ranking. Nada aqui é dado real.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ESCALA = 100_000

_TICKERS = [
    "PETR4", "VALE3", "WEGE3", "SUZB3", "GGBR4", "PRIO3", "RADL3", "LREN3",
    "EMBR3", "KLBN11", "CSNA3", "SLCE3", "UNIP6", "FESA4", "TASA4", "VULC3",
    "CMIN3", "RANI3", "LEVE3", "SMTO3", "ODPV3", "GRND3", "MYPK3", "POMO4",
    "TUPY3", "SHUL4", "EZTC3", "DIRR3", "CURY3", "PLPL3", "AGRO3", "JHSF3",
    "ALLD3", "CVCB3", "SYNE3", "ANIM3", "BEEF3", "VLID3", "SEER3", "ALOS3",
]
_FIN = ["BBAS3", "ITUB4", "BBDC4", "SANB11", "BRSR6", "PSSA3"]


def gerar(saida: Path, anos: int = 5, freq: str = "anual", seed: int = 17) -> dict:
    rng = np.random.default_rng(seed)
    hoje = date.today()
    inicio = date(hoje.year - anos, 1, 1)
    idx = pd.bdate_range(inicio, hoje)
    n = len(idx)

    todos = _TICKERS + _FIN
    p = len(todos)
    mercado = rng.normal(0.0004, 0.013, n)
    betas = rng.uniform(0.45, 1.6, p)
    vol = rng.uniform(0.010, 0.026, p)
    alfa = rng.normal(0.00015, 0.00035, p)
    X = (alfa[None, :] + mercado[:, None] * betas[None, :]
         + rng.normal(0, 1, (n, p)) * vol[None, :])
    ret = pd.DataFrame(X, index=idx, columns=todos)
    bench = pd.Series(mercado * 0.95, index=idx)

    meses = {"anual": [1], "semestral": [1, 7], "trimestral": [1, 4, 7, 10]}[freq]
    datas = [pd.Timestamp(a, m, 1) for a in range(inicio.year, hoje.year + 1)
             for m in meses]
    datas = [d for d in datas if inicio <= d.date() <= hoje]

    rebalances = []
    for k, d in enumerate(datas):
        r2 = np.random.default_rng(seed + k)
        ordem = r2.permutation(len(_TICKERS))
        ordem_f = r2.permutation(len(_FIN))
        itens = []
        for pos, i in enumerate(ordem):
            itens.append({"t": _TICKERS[i], "yf": _TICKERS[i] + ".SA", "f": 0,
                          "q": round(float(r2.uniform(0.08, 0.75)), 5),
                          "p": round(float(r2.uniform(0.05, 0.35)), 5)})
        for i in ordem_f:
            itens.append({"t": _FIN[i], "yf": _FIN[i] + ".SA", "f": 1,
                          "q": round(float(r2.uniform(0.06, 0.20)), 5),
                          "p": round(float(r2.uniform(0.05, 0.28)), 5)})
        rebalances.append({"data": d.strftime("%Y-%m-%d"), "acoes": itens})

    comp = lambda s: [None if pd.isna(v) else int(round(float(v) * ESCALA)) for v in s]
    dados = {
        "meta": {
            "versao": 1,
            "geradoEm": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "inicio": str(inicio), "fim": str(hoje), "frequencia": freq,
            "escalaRetornos": ESCALA, "janelaRetornos": 252,
            "custoBps": 15.0, "taxaLivreRisco": 0.105,
            "nRebalances": len(rebalances), "nTickers": p,
            "pointInTime": True,
            "modo": "DEMONSTRAÇÃO — dados sintéticos, não use para investir",
        },
        "pregoes": [d.strftime("%Y-%m-%d") for d in idx],
        "retornos": {t: comp(ret[t]) for t in todos},
        "benchmark": comp(bench),
        "rebalances": rebalances,
    }
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")
    return dados
