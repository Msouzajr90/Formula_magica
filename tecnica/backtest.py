# -*- coding: utf-8 -*-
"""Backtest das regras de análise técnica — a referência do motor JS.

Convenções (as mesmas de `web/public/tecnica_motor.js`)
-------------------------------------------------------
* A regra olha o FECHAMENTO do pregão i e diz se quer estar comprada
  (alvo[i] = 1) ou fora (0). A ordem é executada na ABERTURA de i + 1. Nada de
  comprar no mesmo fechamento que gerou o sinal: isso é olhar o futuro.
* Fora do mercado o dinheiro rende CDI. O CDI é taxa de um dia para o outro,
  então rende quem dormiu fora: o CDI do pregão j vai para quem estava fora
  na abertura de j.
* O pregão j se divide em "noite" (fechamento de j − 1 até a abertura de j) e
  "dia" (abertura até o fechamento). Com a razão abertura ÷ fechamento das
  velas: noite = (1 + r_j)(1 + a_j) − 1, dia = 1 ÷ (1 + a_j) − 1. Sem velas,
  a_j = 0: a abertura vira o fechamento e a ordem sai um dia depois — o
  conservador.
* Custo de `custo_bps` em cada compra e cada venda (15 bps, o da Simulação),
  e a venda final no último pregão, se estiver comprado.
* O teste roda dentro de UM trecho limpo (sem lacuna do Yahoo). Se o período
  pedido atravessa uma lacuna, começa depois dela.

Este arquivo calcula por outro caminho que o JS (numpy deslocando vetores em
vez de um laço dia a dia) para a paridade pegar diferença de convenção.
"""
from __future__ import annotations

import math

import numpy as np

from . import config as C, indicadores as I

REGRAS = {
    "mm": {"rapida": 50, "lenta": 200, "tipo": "s"},
    "preco_mm": {"n": 200, "tipo": "s"},
    "macd": {"rapida": 12, "lenta": 26, "sinal": 9},
    "ifr": {"n": 14, "baixo": 30, "alto": 70},
    "bollinger": {"n": 20, "k": 2.0},
    "rompimento": {"entrada": 55, "saida": 20},
}


def _media(c, n, tipo):
    return I.ema(c, n) if tipo == "e" else I.sma(c, n)


def _maquina(entra: np.ndarray, sai: np.ndarray, pronto: np.ndarray) -> np.ndarray:
    """Regra com memória: compra quando `entra`, vende quando `sai`, senão
    mantém. Antes de `pronto`, sem decisão (NaN); no primeiro pregão pronto o
    estado de partida é fora."""
    out = np.full(len(entra), np.nan)
    estado = None
    for i in range(len(entra)):
        if not pronto[i]:
            continue
        if estado is None:
            estado = 0.0
        if entra[i]:
            estado = 1.0
        elif sai[i]:
            estado = 0.0
        out[i] = estado
    return out


def alvo(regra: str, p: dict, o, h, l, c) -> np.ndarray:
    """Vetor 1/0/NaN no trecho dado."""
    c = np.asarray(c, float)
    if regra == "mm":
        f, s = _media(c, int(p["rapida"]), p.get("tipo", "s")), _media(c, int(p["lenta"]), p.get("tipo", "s"))
        ok = np.isfinite(f) & np.isfinite(s)
        return np.where(ok, (f > s).astype(float), np.nan)
    if regra == "preco_mm":
        m = _media(c, int(p["n"]), p.get("tipo", "s"))
        return np.where(np.isfinite(m), (c > m).astype(float), np.nan)
    if regra == "macd":
        linha, sinal, _ = I.macd(c, int(p["rapida"]), int(p["lenta"]), int(p["sinal"]))
        ok = np.isfinite(linha) & np.isfinite(sinal)
        return np.where(ok, (linha > sinal).astype(float), np.nan)
    if regra == "ifr":
        v = I.ifr(c, int(p["n"]))
        ok = np.isfinite(v)
        return _maquina(ok & (v < p["baixo"]), ok & (v > p["alto"]), ok)
    if regra == "bollinger":
        meio, _, inf, _ = I.bollinger(c, int(p["n"]), float(p["k"]))
        ok = np.isfinite(meio)
        return _maquina(ok & (c < inf), ok & (c > meio), ok)
    if regra == "rompimento":
        sup = I.anterior(I.maxima_movel(h, int(p["entrada"])))
        inf = I.anterior(I.minima_movel(l, int(p["saida"])))
        ok = np.isfinite(sup) & np.isfinite(inf)
        return _maquina(ok & (c > sup), ok & (c < inf), ok)
    raise ValueError(f"regra desconhecida: {regra}")


def simular(prep: dict, regra: str, params: dict, cdi: dict, *,
            ini: int | None = None, fim: int | None = None,
            custo_bps: float = C.CUSTO_BPS) -> dict | None:
    """Backtest no calendário. `cdi` = {i0, r} em fração (já completado até o
    fim da base). Devolve os retornos diários da estratégia e do comprar e
    segurar, de s + 1 a e, e as operações."""
    s0 = prep["s0"]
    fim = prep["fim"] if fim is None else min(fim, prep["fim"])
    trecho = next((t for t in reversed(prep["trechos"]) if t[0] <= fim), None)
    if trecho is None:
        return None
    e = min(fim, trecho[1])
    ini_t = trecho[0] if ini is None else max(ini, trecho[0])
    if e - ini_t < 2:
        return None
    p, q = ini_t - s0, e - s0 + 1
    alv = np.full(len(prep["c"]), np.nan)
    alv[p:q] = alvo(regra, params, prep["o"][p:q], prep["h"][p:q], prep["l"][p:q], prep["c"][p:q])
    prontos = np.flatnonzero(np.isfinite(alv[p:q]))
    if not len(prontos):
        return None
    s = ini_t + int(prontos[0])                 # primeiro fechamento com decisão
    if e - s < 2:
        return None

    js = np.arange(s + 1, e + 1)                # pregões com retorno
    k = js - s0
    tau = np.nan_to_num(alv, nan=0.0)           # dentro de [s, e] não há NaN
    tau_dia = tau[k - 1]                        # alvo de j−1, executado na abertura de j
    tau_noite = np.where(js - 2 >= s, tau[np.maximum(k - 2, 0)], 0.0)
    r = prep["r"][k]
    a = prep["a"][k]
    noite = (1 + r) * (1 + a)
    dia = 1.0 / (1 + a)
    rc = np.array([cdi["r"][j - cdi["i0"]] if cdi["i0"] <= j < cdi["i0"] + len(cdi["r"]) else 0.0
                   for j in js])
    custo = custo_bps / 1e4
    troca = tau_dia != tau_noite
    fator = np.where(tau_noite == 1, noite, 1 + rc) * np.where(tau_dia == 1, dia, 1.0) \
        * np.where(troca, 1 - custo, 1.0)
    if tau_dia[-1] == 1:
        fator[-1] *= 1 - custo                 # venda final
    rp = fator - 1

    bh = r.copy()
    bh[0] = (1 + bh[0]) * (1 - custo) - 1
    bh[-1] = (1 + bh[-1]) * (1 - custo) - 1

    # operações: entra na abertura de j (tau_dia sobe), sai na abertura de j'
    ops = []
    entrada = None
    for idx in range(len(js)):
        if tau_dia[idx] == 1 and tau_noite[idx] == 0:
            entrada = idx
        sai_hoje = tau_dia[idx] == 0 and tau_noite[idx] == 1
        if entrada is not None and (sai_hoje or idx == len(js) - 1):
            fim_idx = idx
            if sai_hoje:
                pernas = [dia[entrada]] + list(noite[entrada + 1:idx] * dia[entrada + 1:idx]) + [noite[idx]]
            else:
                pernas = [dia[entrada]] + list(noite[entrada + 1:idx + 1] * dia[entrada + 1:idx + 1])
                if idx == entrada:
                    pernas = [dia[entrada]]
            ret = float(np.prod(pernas)) * (1 - custo) ** 2 - 1
            ops.append({"entrada": int(js[entrada]), "saida": int(js[fim_idx]),
                        "ret": ret, "aberta": not sai_hoje,
                        "pregoes": int(fim_idx - entrada + (0 if sai_hoje else 1))})
            entrada = None
    return {"s": int(s), "e": int(e), "ini": int(ini_t), "rp": rp, "bh": bh,
            "exposto": float(np.mean(tau_dia == 1)), "ops": ops}


def resumo_operacoes(ops: list[dict]) -> dict:
    if not ops:
        return {"n": 0, "acerto": None, "media": None, "ganhoMedio": None,
                "perdaMedia": None, "duracao": None}
    rs = np.array([o["ret"] for o in ops])
    g, pdas = rs[rs > 0], rs[rs <= 0]
    return {"n": len(ops), "acerto": float(np.mean(rs > 0)), "media": float(np.mean(rs)),
            "ganhoMedio": float(np.mean(g)) if len(g) else None,
            "perdaMedia": float(np.mean(pdas)) if len(pdas) else None,
            "duracao": float(np.mean([o["pregoes"] for o in ops]))}


def anual(rp: np.ndarray) -> float:
    t = float(np.prod(1 + np.asarray(rp)))
    return t ** (252 / len(rp)) - 1 if len(rp) and t > 0 else math.nan
