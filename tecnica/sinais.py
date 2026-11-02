# -*- coding: utf-8 -*-
"""Preparação da série de um papel e o painel de sinais de todas as ações.

`preparar` junta a base de retornos (`precos/PETR4.json`) e as velas
(`precos/ohlc/PETR4.json`) num só conjunto de vetores no calendário, acha as
lacunas do Yahoo e divide a história em TRECHOS LIMPOS. Cada indicador é
calculado dentro de um trecho e recomeça do zero no seguinte: uma média de
200 pregões que atravessa sete anos de preço parado (TEND3, 2010–2017) não é
média de nada.

`resumo` é a linha do painel de um papel no último pregão. `gerar` grava o
painel inteiro em `precos/ohlc/_sinais.json`, que a tela lê de uma vez.

    python -m tecnica.sinais            # grava o painel a partir da base local
    python -m tecnica.sinais --ver 20   # mostra as 20 primeiras linhas
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np

from simulacao import arquivo, config as SC
from simulacao import etfs as E

from . import config as C, indicadores as I, velas as V


# ---------------------------------------------------------------------------
# Preparação
# ---------------------------------------------------------------------------
def lacunas(i0: int, r: np.ndarray) -> list[list]:
    """[[a, c, aberta]] no calendário — a regra da aba de ETFs."""
    return E.lacunas(E.Serie(i0, r))


def trechos(s0: int, fim: int, lac: list[list]) -> list[list[int]]:
    """Trechos [ini, fim] de preço verdadeiro. Numa lacuna [a, c], o último
    preço real é o de a − 1 e o próximo é o de c (o pregão do salto)."""
    out, ini = [], s0
    for a, c, aberta in lac:
        if a - 1 >= ini:
            out.append([ini, a - 1])
        if aberta:
            return out
        ini = c
    if fim >= ini:
        out.append([ini, fim])
    return out


def preparar(ret: dict, vel: dict | None, pregoes: list[str]) -> dict:
    """Vetores no calendário, do pregão `s0` (primeiro preço) ao `fim`.

    `c` é o fechamento ajustado por proventos, em reais de hoje quando há o
    fechamento bruto do último pregão (`vel['ult']`); sem ele, em base 100 no
    último fechamento. `o`, `h`, `l` saem da razão gravada nas velas; sem
    velas, iguais a `c`. `vol` (R$) é NaN onde não há vela.
    """
    esc = ret.get("esc") or SC.ESCALA
    r = np.asarray(ret["r"], dtype=float) / esc
    i0 = int(ret["i0"])
    s0, fim = i0 - 1, i0 + len(r) - 1
    n = fim - s0 + 1
    cadj = np.concatenate([[1.0], np.cumprod(1.0 + r)])

    a = np.zeros(n)
    x = np.zeros(n)
    m = np.zeros(n)
    vol = np.full(n, np.nan)
    tem_vela = np.zeros(n, dtype=bool)
    k_escala, em_reais = None, False
    if vel:
        ve, vv = float(vel.get("esc") or C.ESCALA_RAZAO), float(vel.get("vesc") or C.ESCALA_VOLUME)
        lo, hi = max(s0, vel["i0"]), min(fim, vel["i0"] + len(vel["a"]) - 1)
        for i in range(lo, hi + 1):
            j, k = i - vel["i0"], i - s0
            a[k], x[k], m[k] = vel["a"][j] / ve, vel["x"][j] / ve, vel["m"][j] / ve
            vol[k] = vel["f"][j] * vv
            tem_vela[k] = True
        ult = vel.get("ult")
        if ult:
            d = bisect.bisect_left(pregoes, ult[0])
            if d < len(pregoes) and pregoes[d] == ult[0] and s0 <= d <= fim and ult[1] > 0:
                k_escala, em_reais = float(ult[1]) / cadj[d - s0], True
    if k_escala is None:
        k_escala = 100.0 / cadj[-1]
    c = cadj * k_escala
    lac = lacunas(i0, r)
    return {
        "s0": s0, "fim": fim, "r": np.concatenate([[np.nan], r]),
        "c": c, "o": c * (1 + a), "h": c * (1 + x), "l": c * (1 + m),
        "a": a, "vol": vol, "temVela": tem_vela, "emReais": em_reais,
        "lacunas": lac, "trechos": trechos(s0, fim, lac),
    }


def indicadores(prep: dict) -> dict[str, np.ndarray]:
    """Todos os indicadores, trecho a trecho, nos vetores de `preparar`."""
    n = len(prep["c"])
    s0 = prep["s0"]
    out: dict[str, np.ndarray] = {}
    for ini, fim in prep["trechos"]:
        p, q = ini - s0, fim - s0 + 1
        if q - p < 2:
            continue
        parte = I.calcular(prep["o"][p:q], prep["h"][p:q], prep["l"][p:q],
                           prep["c"][p:q], prep["vol"][p:q])
        for k, v in parte.items():
            if k not in out:
                out[k] = np.full(n, np.nan)
            out[k][p:q] = v
    return out


# ---------------------------------------------------------------------------
# Linha do painel
# ---------------------------------------------------------------------------
def _f(v) -> float | None:
    return float(v) if v is not None and math.isfinite(v) else None


def _regime_desde(dif: np.ndarray, k: int, p: int) -> int | None:
    """Índice do primeiro pregão do sinal atual de `dif` (contando de trás
    para a frente a partir de k, sem sair do trecho que começa em p). None se
    o sinal é o mesmo desde que o indicador existe."""
    if not math.isfinite(dif[k]):
        return None
    pos = dif[k] > 0
    j = k
    while j - 1 >= p and math.isfinite(dif[j - 1]) and (dif[j - 1] > 0) == pos:
        j -= 1
    if j - 1 >= p and math.isfinite(dif[j - 1]):
        return j
    return None


def resumo(prep: dict, ind: dict, ibov: dict | None, pregoes: list[str]) -> dict:
    """A linha do painel no último pregão do papel. `ibov` = {i0, r} em fração."""
    s0, fim = prep["s0"], prep["fim"]
    out: dict = {"ate": pregoes[fim], "atraso": len(pregoes) - 1 - fim,
                 "velas": bool(prep["temVela"][-1]), "emReais": prep["emReais"]}
    tr = prep["trechos"]
    if not tr or tr[-1][1] != fim:
        ult_real = tr[-1][1] if tr else s0
        out["parado"] = pregoes[ult_real]
        return out
    p = tr[-1][0] - s0
    k = fim - s0
    c = prep["c"]
    g = lambda nome: _f(ind[nome][k]) if nome in ind else None      # noqa: E731
    out["desde"] = pregoes[tr[-1][0]] if tr[-1][0] > s0 else None
    out["preco"] = _f(c[k]) if prep["emReais"] else None
    out["var1d"] = _f(c[k] / c[k - 1] - 1) if k - 1 >= p else None
    for nome, n in C.JANELAS.items():
        out[f"r{nome}"] = _f(c[k] / c[k - n] - 1) if k - n >= p else None
    for n in (C.MM_CURTA, C.MM_MEDIA, C.MM_LONGA):
        mm = g(f"mm{n}")
        out[f"dMm{n}"] = _f(c[k] / mm - 1) if mm else None
    dif = ind["mm50"] - ind["mm200"]
    out["tend"] = None if not math.isfinite(dif[k]) else ("alta" if dif[k] > 0 else "baixa")
    j = _regime_desde(dif, k, p)
    out["tendDesde"] = pregoes[s0 + j] if j is not None else None
    hist = ind["macdHist"]
    out["macdAcima"] = None if not math.isfinite(hist[k]) else bool(hist[k] > 0)
    j = _regime_desde(hist, k, p)
    out["macdDesde"] = pregoes[s0 + j] if j is not None else None
    for nome in ("ifr", "pctB", "estK", "estD", "adx", "diMais", "diMenos"):
        out[nome] = g(nome)
    atr = g("atr")
    out["atrPct"] = _f(atr / c[k]) if atr is not None else None
    mx, mn = g("max52"), g("min52")
    out["dMax52"] = _f(c[k] / mx - 1) if mx else None
    out["dMin52"] = _f(c[k] / mn - 1) if mn else None
    out["novaMax52"] = bool(prep["h"][k] >= mx) if mx else None
    out["novaMin52"] = bool(prep["l"][k] <= mn) if mn else None
    ds = g("donchSup")
    out["rompe55"] = bool(c[k] > ds) if ds else None
    vm, v = g("volMedia"), _f(prep["vol"][k])
    out["volRel"] = _f(v / vm) if (vm and v is not None and vm > 0) else None
    out["fr6m"] = None
    n6 = C.JANELAS["6m"]
    if ibov is not None and k - n6 >= p:
        a_, b_ = fim - n6 + 1, fim                       # retornos de a_ a b_
        if ibov["i0"] <= a_ and b_ <= ibov["i0"] + len(ibov["r"]) - 1:
            ri = float(np.prod(1 + np.asarray(ibov["r"][a_ - ibov["i0"]:b_ - ibov["i0"] + 1])))
            out["fr6m"] = _f((c[k] / c[k - n6]) / ri - 1)
    if not out["velas"]:
        # Sem máxima e mínima de verdade, estocástico, ATR e ADX viram contas
        # sobre o fechamento (o +DI fica igual ao IFR). Melhor vazio que errado.
        for nome in ("estK", "estD", "adx", "diMais", "diMenos", "atrPct", "volRel"):
            out[nome] = None
    return out


# ---------------------------------------------------------------------------
# Painel inteiro
# ---------------------------------------------------------------------------
def _ler_ibov(pasta: Path, indice: dict) -> dict | None:
    s = arquivo.ler_serie(pasta, indice["bench"]["IBOV"]["arquivo"])
    if s is None:
        return None
    return {"i0": s["i0"], "r": np.asarray(s["r"], float) / (s.get("esc") or SC.ESCALA)}


def _arredondar(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, float):
            out[k] = round(v, 6) if abs(v) < 1e4 else round(v, 2)
        else:
            out[k] = v
    return out


def gerar(pasta_precos: Path = SC.PASTA_PRECOS) -> dict | None:
    """Monta o painel de todas as ações da base. None se não há base."""
    pasta_precos = Path(pasta_precos)
    indice = arquivo.ler_indice(pasta_precos)
    if not indice:
        return None
    pregoes = indice["pregoes"]
    ibov = _ler_ibov(pasta_precos, indice)
    pasta_v = pasta_precos / C.PASTA_VELAS.name
    linhas = []
    for e in indice.get("ativos") or []:
        if e.get("classe") not in C.CLASSES:
            continue
        ret = arquivo.ler_serie(pasta_precos, e["t"])
        if ret is None or len(ret["r"]) < 2:
            continue
        vel = V.ler(pasta_v, e["t"])
        prep = preparar(ret, vel, pregoes)
        lin = {"t": e["t"], "nome": e.get("nome", ""), "liq": e.get("liq")}
        lin.update(resumo(prep, indicadores(prep), ibov, pregoes))
        linhas.append(_arredondar(lin))
    return {
        "v": 1,
        "geradoEm": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "demo": bool(indice.get("demo")),
        "pregao": pregoes[-1],
        "comVelas": sum(1 for x in linhas if x.get("velas")),
        "papeis": linhas,
    }


def gravar(pasta_precos: Path = SC.PASTA_PRECOS) -> dict | None:
    painel = gerar(pasta_precos)
    if painel is None:
        return None
    destino = Path(pasta_precos) / C.PASTA_VELAS.name / C.ARQ_SINAIS
    # o carimbo muda a cada execução; só grava se as LINHAS mudaram
    antigo = arquivo.ler_json(destino)
    if antigo and antigo.get("papeis") == painel["papeis"] and antigo.get("pregao") == painel["pregao"]:
        return painel
    arquivo.gravar_se_mudou(destino, painel)
    return painel


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pasta", default=str(SC.PASTA_PRECOS))
    ap.add_argument("--ver", type=int, default=0, help="mostra N linhas em vez de gravar")
    a = ap.parse_args(argv)
    if a.ver:
        painel = gerar(Path(a.pasta))
    else:
        painel = gravar(Path(a.pasta))
    if painel is None:
        print("Sem base de preços em", a.pasta)
        return 1
    print(f"{len(painel['papeis'])} ações, {painel['comVelas']} com velas, pregão {painel['pregao']}")
    for lin in painel["papeis"][:a.ver]:
        print(json.dumps(lin, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
