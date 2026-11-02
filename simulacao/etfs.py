# -*- coding: utf-8 -*-
"""Aba ETFs: a referência em Python da conta que roda no navegador.

A tela calcula tudo em `web/public/etfs_motor.js`, sobre a mesma base de
preços da Simulação. Este módulo refaz a conta por outro caminho (numpy em vez
de laços) para os testes compararem os dois, e serve para conferir a tabela
sem abrir o site:

    python -m simulacao.etfs            # janela de risco de 3 anos
    python -m simulacao.etfs --janela 5a

As convenções estão explicadas no cabeçalho do motor JS; em resumo:

* Janela de N meses que termina no último pregão `e`: parte do fechamento `s`
  do último pregão com data <= data(e) − N meses. O ETF só tem número na
  janela se já tinha preço em `s`.
* Volatilidade, drawdown e Sharpe nos retornos diários (as fórmulas da
  Simulação). Correlação, beta e tracking error em blocos de 5 pregões,
  contados de trás para a frente: ETF de índice americano fecha em São Paulo
  com Nova York aberta, e no diário metade do movimento cai no dia seguinte.
* Lacuna do Yahoo (10+ retornos zero seguidos e o salto que devolve o preço):
  o retorno de ponta a ponta continua valendo, o que depende do caminho não.
  Salto isolado fora de lacuna, acima do limite da categoria (15% renda fixa,
  40% o resto), é desdobramento não ajustado e vira retorno zero.
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
from datetime import date
from pathlib import Path

import numpy as np

from . import config as C

DIAS_ANO = 252
SEMANAS_ANO = 52
BLOCO = 5
MIN_SEMANAS = 26
ATRASO_MAX = 10
LACUNA_MIN = 10
LACUNA_JUNTA = 3
JANELAS = {"1m": 1, "3m": 3, "6m": 6, "12m": 12, "3a": 36, "5a": 60, "10a": 120}
ANUALIZA = {"3a", "5a", "10a", "max"}
RETORNOS = ["1m", "12m", "ano", "3a", "5a"]


# ---------------------------------------------------------------------------
# Séries
# ---------------------------------------------------------------------------
class Serie:
    __slots__ = ("i0", "r", "lac", "s0")

    def __init__(self, i0: int, r, lac=None, s0=None):
        self.i0 = int(i0)
        self.r = np.asarray(r, dtype=float)
        self.lac = list(lac or [])               # [(a, c)] no calendário
        self.s0 = self.i0 - 1 if s0 is None else int(s0)

    @property
    def fim(self) -> int:
        return self.i0 + len(self.r) - 1

    def trecho(self, s: int, e: int) -> np.ndarray:
        """Retornos dos pregões s+1..e."""
        return self.r[s + 1 - self.i0:e + 1 - self.i0]


def ler_serie(arq: dict) -> Serie:
    return Serie(arq["i0"], np.asarray(arq["r"], dtype=float) / (arq.get("esc") or C.ESCALA))


def ate_o_fim(serie: Serie, fim: int) -> Serie | None:
    falta = fim - serie.fim
    if falta <= 0:
        return serie
    if falta > ATRASO_MAX:
        return None
    return Serie(serie.i0, np.concatenate([serie.r, np.zeros(falta)]))


def lacunas(serie: Serie) -> list[list]:
    """[[a, c, aberta]]: a = 1º pregão parado, c = pregão do salto (ou o
    último da série, se ainda parada)."""
    zero = np.concatenate([[False], serie.r == 0, [False]]).astype(int)
    d = np.diff(zero)
    inicios, fins = np.flatnonzero(d == 1), np.flatnonzero(d == -1)   # fins exclusivo
    n = len(serie.r)
    out: list[list] = []
    for k, j in zip(inicios, fins):
        if j - k < LACUNA_MIN:
            continue
        item = [serie.i0 + int(k), serie.i0 + int(min(j, n - 1)), bool(j >= n)]
        if out and item[0] - out[-1][1] <= LACUNA_JUNTA:
            out[-1][1], out[-1][2] = item[1], item[2]
        else:
            out.append(item)
    return out


def preparar(bruta: Serie, limite: float, pregoes: list[str], fim: int) -> dict:
    """{'serie', 'artefatos'} ou {'parado': data do último preço de verdade}."""
    cheia = ate_o_fim(bruta, fim)
    if cheia is None:
        return {"parado": pregoes[min(bruta.fim, len(pregoes) - 1)]}
    lac = lacunas(cheia)
    if lac and lac[-1][2]:
        return {"parado": pregoes[max(lac[-1][0] - 1, 0)]}
    r = cheia.r.copy()
    idx = cheia.i0 + np.arange(len(r))
    dentro = np.zeros(len(r), dtype=bool)
    for a, c, _ in lac:
        dentro |= (idx >= a) & (idx <= c)
    ruins = np.flatnonzero((np.abs(r) > limite) & ~dentro)
    artefatos = [[pregoes[cheia.i0 + k], round(float(r[k]) * 1e4) / 1e4] for k in ruins]
    r[ruins] = 0.0
    lac2 = [(a, c) for a, c, _ in lac]
    s0 = max(cheia.i0 - 1, lac2[-1][1]) if lac2 else cheia.i0 - 1
    return {"serie": Serie(cheia.i0, r, lac2, s0), "artefatos": artefatos}


def preco_real(serie: Serie, i: int) -> bool:
    return not any(a <= i <= c - 1 for a, c in serie.lac)


def limpo(serie: Serie, s: int, e: int) -> bool:
    return not any(a <= e and c >= s + 1 for a, c in serie.lac)


def preparar_bench(ibov: Serie, cdi: Serie, fim: int) -> tuple[Serie, Serie]:
    """CDI do último pregão sai no dia seguinte: repete a última taxa diária."""
    falta = fim - cdi.fim
    if 0 < falta <= ATRASO_MAX:
        cdi = Serie(cdi.i0, np.concatenate([cdi.r, np.full(falta, cdi.r[-1])]))
    return ate_o_fim(ibov, fim) or ibov, cdi


# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------
def meses_antes(d: str, meses: int) -> str:
    x = date.fromisoformat(d[:10])
    t = x.year * 12 + (x.month - 1) - meses
    a, m = divmod(t, 12)
    m += 1
    return date(a, m, min(x.day, calendar.monthrange(a, m)[1])).isoformat()


def ultimo_ate(pregoes: list[str], d: str) -> int:
    return int(np.searchsorted(np.array(pregoes), d, side="right")) - 1


def partida(pregoes: list[str], fim: int, janela: str) -> int | None:
    if janela == "max":
        return None
    corte = (f"{pregoes[fim][:4]}-01-01" if janela == "ano"
             else meses_antes(pregoes[fim], JANELAS[janela]))
    s = ultimo_ate(pregoes, corte)
    return None if s < 0 else s


def partida_retorno(serie: Serie, s: int | None, janela: str) -> int | None:
    if janela == "max":
        return serie.s0
    if s is None or serie.i0 - 1 > s or not preco_real(serie, s):
        return None
    return s


def partida_caminho(serie: Serie, s: int | None, e: int, janela: str) -> int | None:
    p = partida_retorno(serie, s, janela)
    return p if p is not None and limpo(serie, p, e) else None


# ---------------------------------------------------------------------------
# Contas
# ---------------------------------------------------------------------------
def composto(serie: Serie, s: int, e: int) -> float:
    return float(np.prod(1.0 + serie.trecho(s, e)) - 1.0)


def anualizar(total: float, n: int) -> float:
    if n <= 0 or total <= -1:
        return float("nan")
    return (1.0 + total) ** (DIAS_ANO / n) - 1.0


def risco(serie: Serie, cdi: Serie, s: int, e: int) -> dict | None:
    r = serie.trecho(s, e)
    n = len(r)
    if n < 2:
        return None
    curva = np.cumprod(1.0 + r)
    pico = np.maximum.accumulate(np.concatenate([[1.0], curva]))[1:]
    dd = curva / pico - 1.0
    mdd = float(min(dd.min(), 0.0))
    total = float(curva[-1] - 1.0)
    anual = anualizar(total, n)
    vol = float(np.std(r, ddof=1) * math.sqrt(DIAS_ANO))
    rf = anualizar(composto(cdi, s, e), n)
    return {"total": total, "anual": anual, "vol": vol, "mdd": mdd, "rf": rf,
            "sharpe": (anual - rf) / vol if vol > 0 else float("nan"), "dias": n}


def semanais(serie: Serie, s: int, e: int) -> np.ndarray:
    nb = (e - s) // BLOCO
    if nb <= 0:
        return np.zeros(0)
    r = serie.trecho(e - nb * BLOCO, e)
    return np.prod(1.0 + r.reshape(nb, BLOCO), axis=1) - 1.0


def correlacao(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def beta(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2 or np.var(y) == 0:
        return float("nan")
    return float(np.cov(x, y, ddof=1)[0, 1] / np.var(y, ddof=1))


def inicio_comum(x: Serie, y: Serie, s: int | None, e: int, janela: str) -> int | None:
    a = max(x.s0, y.s0)
    if janela != "max":
        if s is None:
            return None
        a = max(a, s)
    if (a >= e or not preco_real(x, a) or not preco_real(y, a)
            or not limpo(x, a, e) or not limpo(y, a, e)):
        return None
    return a


def aderencia(x: Serie, ref: Serie, s: int | None, e: int, janela: str) -> dict | None:
    a = inicio_comum(x, ref, s, e, janela)
    if a is None:
        return None
    wx, wy = semanais(x, a, e), semanais(ref, a, e)
    if len(wx) < MIN_SEMANAS:
        return None
    n = e - a
    return {
        "desde": a,
        "difAnual": anualizar(composto(x, a, e), n) - anualizar(composto(ref, a, e), n),
        "te": float(np.std(wx - wy, ddof=1) * math.sqrt(SEMANAS_ANO)),
        "corr": correlacao(wx, wy),
        "semanas": len(wx),
        "inteira": janela == "max" or a == s,
    }


def matriz_correlacao(series: list[Serie], s: int | None, e: int, janela: str) -> list[list]:
    p = len(series)
    M = [[None] * p for _ in range(p)]
    for i in range(p):
        M[i][i] = 1.0
        for j in range(i + 1, p):
            a = inicio_comum(series[i], series[j], s, e, janela)
            c = float("nan")
            if a is not None:
                wi, wj = semanais(series[i], a, e), semanais(series[j], a, e)
                if len(wi) >= MIN_SEMANAS:
                    c = correlacao(wi, wj)
            M[i][j] = M[j][i] = None if math.isnan(c) else c
    return M


def curva(serie: Serie, s: int, e: int) -> list:
    acc = np.cumprod(1.0 + serie.trecho(s, e)) - 1.0
    v = [0.0] + [float(x) for x in acc]
    for a, c in serie.lac:
        for i in range(max(a, s + 1), min(c - 1, e) + 1):
            v[i - s] = None
    return v


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


# ---------------------------------------------------------------------------
# A tabela
# ---------------------------------------------------------------------------
def preparar_todas(catalogo: dict, indice: dict, series: dict[str, Serie]) -> dict:
    P = indice["pregoes"]
    fim = len(P) - 1
    lim = catalogo.get("limiteSalto") or {}
    prontas, artefatos, parados = {}, {}, []
    for t, info in catalogo["etfs"].items():
        if t not in series:
            continue
        p = preparar(series[t], lim.get(info["cat"], lim.get("padrao", 0.40)), P, fim)
        if "parado" in p:
            parados.append({"t": t, "ate": p["parado"]})
            continue
        prontas[t], artefatos[t] = p["serie"], p["artefatos"]
    return {"prontas": prontas, "artefatos": artefatos, "parados": parados}


def avaliar(catalogo: dict, indice: dict, series: dict[str, Serie], ibov: Serie,
            cdi: Serie, janela: str = "3a") -> dict:
    P = indice["pregoes"]
    fim = len(P) - 1
    na_base = {a["t"]: a for a in indice["ativos"]}
    ibov, cdi = preparar_bench(ibov, cdi, fim)
    s_risco = partida(P, fim, janela)
    prep = preparar_todas(catalogo, indice, series)

    linhas, fora = [], []
    for t, info in catalogo["etfs"].items():
        ent, serie = na_base.get(t), prep["prontas"].get(t)
        if ent is None or t not in series:
            fora.append(t)
            continue
        if serie is None:
            continue
        rets = {}
        for j in RETORNOS:
            s = partida_retorno(serie, partida(P, fim, j), j)
            if s is None:
                rets[j] = None
                continue
            tot = composto(serie, s, fim)
            rets[j] = anualizar(tot, fim - s) if j in ANUALIZA else tot
        sR = partida_caminho(serie, s_risco, fim, janela)
        rk = risco(serie, cdi, sR, fim) if sR is not None else None
        corr = bt = None
        a = inicio_comum(serie, ibov, s_risco, fim, janela)
        if a is not None and sR is not None:
            wx, wy = semanais(serie, a, fim), semanais(ibov, a, fim)
            if len(wx) >= MIN_SEMANAS:
                corr, bt = correlacao(wx, wy), beta(wx, wy)
        linhas.append({
            "t": t, "nome": info["nome"], "cat": info["cat"], "indice": info["indice"],
            "grupo": info.get("grupo"), "desde": P[serie.i0 - 1],
            "liq": ent.get("liq"), "neg": ent.get("neg"), "ret": rets,
            "riscoDesde": None if sR is None else P[sR],
            "anual": rk["anual"] if rk else None, "vol": rk["vol"] if rk else None,
            "mdd": rk["mdd"] if rk else None, "sharpe": _num(rk["sharpe"]) if rk else None,
            "corrIbov": _num(corr), "betaIbov": _num(bt),
            "artefatos": prep["artefatos"].get(t, []),
            "lacunas": [[P[x - 1], P[c]] for x, c in serie.lac],
        })

    grupos = []
    for g, gi in (catalogo.get("grupos") or {}).items():
        membros = [l["t"] for l in linhas if l["grupo"] == g]
        if not membros:
            continue
        ref_t = None
        if gi.get("ref") == "IBOV":
            ref, ref_nome = ibov, "Ibovespa"
        elif gi.get("ref") == "CDI":
            ref, ref_nome = cdi, "CDI"
        else:
            if len(membros) < 2:
                continue
            pr = prep["prontas"]
            ref_t = sorted(membros, key=lambda t: (pr[t].s0, -(na_base[t].get("liq") or 0), t))[0]
            ref, ref_nome = pr[ref_t], ref_t
        itens = []
        for t in membros:
            if t == ref_t:
                continue
            ad = aderencia(prep["prontas"][t], ref, s_risco, fim, janela)
            itens.append({"t": t, **({**ad, "desde": P[ad["desde"]]} if ad else {"vazio": True})})
        grupos.append({"g": g, "nome": gi["nome"], "ref": ref_nome, "refT": ref_t,
                       "refNota": gi.get("refNota"), "itens": itens})
    return {"fim": P[fim], "janela": janela,
            "inicioRisco": None if s_risco is None else P[s_risco],
            "linhas": linhas, "grupos": grupos, "parados": prep["parados"], "fora": fora}


def carregar(pasta: Path = C.PASTA_PRECOS, catalogo: Path = C.ARQ_CATALOGO_ETFS):
    """(catalogo, indice, series, ibov, cdi) a partir dos arquivos publicados."""
    cat = json.loads(Path(catalogo).read_text(encoding="utf-8"))
    ind = json.loads((Path(pasta) / C.ARQ_INDICE).read_text(encoding="utf-8"))
    series = {}
    for a in ind["ativos"]:
        if a["t"] in cat["etfs"]:
            arq = Path(pasta) / f"{a['t']}.json"
            if arq.exists():
                series[a["t"]] = ler_serie(json.loads(arq.read_text(encoding="utf-8")))
    ibov = ler_serie(json.loads((Path(pasta) / ind["bench"]["IBOV"]["arquivo"]).read_text(encoding="utf-8")))
    cdi = ler_serie(json.loads((Path(pasta) / ind["bench"]["CDI"]["arquivo"]).read_text(encoding="utf-8")))
    return cat, ind, series, ibov, cdi


def _pct(v, d=1):
    return "—" if v is None else f"{v * 100:+.{d}f}%"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Tabela da aba ETFs, sem abrir o site.")
    ap.add_argument("--janela", default="3a", choices=["12m", "3a", "5a", "10a", "max"])
    a = ap.parse_args(argv)
    r = avaliar(*carregar(), janela=a.janela)
    print(f"Fechamento {r['fim']} · risco e aderência desde {r['inicioRisco']} ({a.janela})")
    print(f"{'ETF':8} {'12m':>8} {'3a a.a.':>8} {'vol':>7} {'MDD':>8} {'Sharpe':>7}  nome")
    for l in sorted(r["linhas"], key=lambda l: (l["cat"], l["t"])):
        print(f"{l['t']:8} {_pct(l['ret']['12m']):>8} {_pct(l['ret']['3a']):>8} "
              f"{_pct(l['vol']):>7} {_pct(l['mdd']):>8} "
              f"{'—' if l['sharpe'] is None else format(l['sharpe'], '.2f'):>7}  {l['nome']}")
    for g in r["grupos"]:
        print(f"\n{g['nome']} — referência {g['ref']}")
        for i in g["itens"]:
            if i.get("vazio"):
                print(f"  {i['t']:8} histórico curto")
            else:
                print(f"  {i['t']:8} diferença {i['difAnual'] * 100:+.2f} p.p./ano  "
                      f"TE {i['te'] * 100:.2f}%  corr {i['corr']:.3f}  desde {i['desde']}")
    if r["parados"]:
        print("\nParados:", ", ".join(f"{p['t']} ({p['ate']})" for p in r["parados"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
