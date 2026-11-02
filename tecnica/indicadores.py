# -*- coding: utf-8 -*-
"""Indicadores técnicos — a referência em Python do `tecnica_motor.js`.

Escrito de propósito por outro caminho que o motor do navegador (pandas e
numpy onde dá, laço só onde a definição é recursiva), para os testes de
paridade pegarem erro de um lado ou do outro.

Convenções, iguais no motor JS
------------------------------
* Toda função recebe vetores numpy de um TRECHO LIMPO de preço (sem lacuna do
  Yahoo) e devolve vetores do mesmo tamanho, com NaN onde o indicador ainda
  não tem história suficiente ("aquecimento").
* Média exponencial e as suavizações de Wilder começam pela média simples dos
  `n` primeiros valores — a convenção de Appel e de Wilder, e a do TradingView.
  Começar pelo primeiro preço (o padrão do pandas `ewm`) dá outro número por
  meses, e cada site mostraria um MACD diferente.
* Bollinger usa desvio-padrão POPULACIONAL (divide por n), como no livro.
* Volume é o financeiro (R$). OBV sobre volume financeiro em vez de
  quantidade: com desdobramento a quantidade muda de escala, o financeiro não.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C

NAN = float("nan")


def _vazio(n: int) -> np.ndarray:
    return np.full(n, np.nan)


def _primeiro_valido(x: np.ndarray) -> int | None:
    ok = np.flatnonzero(np.isfinite(x))
    return int(ok[0]) if len(ok) else None


# ---------------------------------------------------------------------------
# Médias
# ---------------------------------------------------------------------------
def sma(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x, dtype=float).rolling(n, min_periods=n).mean().to_numpy()


def _recursiva(x: np.ndarray, n: int, alfa: float) -> np.ndarray:
    """Semente = média simples dos n primeiros valores válidos; depois
    y = y_anterior + alfa × (x − y_anterior)."""
    out = _vazio(len(x))
    f = _primeiro_valido(x)
    if f is None or f + n > len(x):
        return out
    y = float(np.mean(x[f:f + n]))
    out[f + n - 1] = y
    for i in range(f + n, len(x)):
        y = y + alfa * (x[i] - y)
        out[i] = y
    return out


def ema(x: np.ndarray, n: int) -> np.ndarray:
    return _recursiva(np.asarray(x, float), n, 2.0 / (n + 1))


def wilder(x: np.ndarray, n: int) -> np.ndarray:
    return _recursiva(np.asarray(x, float), n, 1.0 / n)


# ---------------------------------------------------------------------------
# Osciladores e faixas
# ---------------------------------------------------------------------------
def ifr(c: np.ndarray, n: int = C.IFR_N) -> np.ndarray:
    """Índice de força relativa de Wilder. Sem perda nenhuma na janela: 100;
    sem ganho nem perda (preço parado): 50."""
    c = np.asarray(c, float)
    d = np.diff(c, prepend=np.nan)
    ganho = np.where(d > 0, d, 0.0)
    perda = np.where(d < 0, -d, 0.0)
    ganho[0] = perda[0] = np.nan
    mg, mp = wilder(ganho, n), wilder(perda, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 100.0 - 100.0 / (1.0 + mg / mp)
    out = np.where((mp == 0) & (mg > 0), 100.0, out)
    out = np.where((mp == 0) & (mg == 0), 50.0, out)
    out[~np.isfinite(mg)] = np.nan
    return out


def bollinger(c: np.ndarray, n: int = C.BOLLINGER[0], k: float = C.BOLLINGER[1]):
    s = pd.Series(c, dtype=float)
    meio = s.rolling(n, min_periods=n).mean().to_numpy()
    dp = s.rolling(n, min_periods=n).std(ddof=0).to_numpy()
    sup, inf = meio + k * dp, meio - k * dp
    with np.errstate(divide="ignore", invalid="ignore"):
        pct_b = np.where(sup > inf, (np.asarray(c, float) - inf) / (sup - inf), 0.5)
    pct_b[~np.isfinite(meio)] = np.nan
    return meio, sup, inf, pct_b


def macd(c: np.ndarray, rapida: int = C.MACD[0], lenta: int = C.MACD[1], sinal: int = C.MACD[2]):
    linha = ema(c, rapida) - ema(c, lenta)
    sin = ema(linha, sinal)
    return linha, sin, linha - sin


def estocastico(h, l, c, n: int = C.ESTOCASTICO[0], k: int = C.ESTOCASTICO[1],
                d: int = C.ESTOCASTICO[2]):
    """Estocástico lento: %K = média de k do %K rápido; %D = média de d do %K.
    Máxima igual à mínima na janela (preço parado): 50."""
    hh = pd.Series(h, dtype=float).rolling(n, min_periods=n).max().to_numpy()
    ll = pd.Series(l, dtype=float).rolling(n, min_periods=n).min().to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        rapido = np.where(hh > ll, 100.0 * (np.asarray(c, float) - ll) / (hh - ll), 50.0)
    rapido[~np.isfinite(hh)] = np.nan
    pk = sma(rapido, k)
    return pk, sma(pk, d)


def true_range(h, l, c) -> np.ndarray:
    h, l, c = (np.asarray(v, float) for v in (h, l, c))
    ant = np.concatenate([[np.nan], c[:-1]])
    tr = np.maximum.reduce([h - l, np.abs(h - ant), np.abs(l - ant)])
    tr[0] = np.nan                     # sem fechamento anterior, sem TR
    return tr


def atr(h, l, c, n: int = C.ATR_N) -> np.ndarray:
    return wilder(true_range(h, l, c), n)


def adx(h, l, c, n: int = C.ADX_N):
    """(ADX, +DI, −DI) de Wilder. As somas suavizadas começam pela soma
    simples dos n primeiros valores; o ADX, pela média dos n primeiros DX."""
    h, l = np.asarray(h, float), np.asarray(l, float)
    tr = true_range(h, l, c)
    sobe = np.concatenate([[np.nan], h[1:] - h[:-1]])
    desce = np.concatenate([[np.nan], l[:-1] - l[1:]])
    pdm = np.where((sobe > desce) & (sobe > 0), sobe, 0.0)
    ndm = np.where((desce > sobe) & (desce > 0), desce, 0.0)
    pdm[0] = ndm[0] = np.nan
    # soma de Wilder = n × média de Wilder (mesma recursão, outra escala)
    s_tr, s_p, s_n = wilder(tr, n), wilder(pdm, n), wilder(ndm, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi = np.where(s_tr > 0, 100.0 * s_p / s_tr, 0.0)
        ndi = np.where(s_tr > 0, 100.0 * s_n / s_tr, 0.0)
        soma = pdi + ndi
        dx = np.where(soma > 0, 100.0 * np.abs(pdi - ndi) / soma, 0.0)
    for v in (pdi, ndi, dx):
        v[~np.isfinite(s_tr)] = np.nan
    return wilder(dx, n), pdi, ndi


def obv(c, vol) -> np.ndarray:
    c = np.asarray(c, float)
    v = np.nan_to_num(np.asarray(vol, float), nan=0.0)
    passo = np.sign(np.diff(c, prepend=c[0])) * v
    passo[0] = 0.0
    return np.cumsum(passo)


def maxima_movel(x, n: int) -> np.ndarray:
    return pd.Series(x, dtype=float).rolling(n, min_periods=n).max().to_numpy()


def minima_movel(x, n: int) -> np.ndarray:
    return pd.Series(x, dtype=float).rolling(n, min_periods=n).min().to_numpy()


def anterior(x: np.ndarray) -> np.ndarray:
    """Desloca um pregão: o valor de ontem no lugar de hoje."""
    return np.concatenate([[np.nan], np.asarray(x, float)[:-1]])


# ---------------------------------------------------------------------------
# Tudo de uma vez, num trecho limpo
# ---------------------------------------------------------------------------
def calcular(o, h, l, c, vol) -> dict[str, np.ndarray]:
    """Todos os indicadores da tela, no trecho [o, h, l, c, vol]."""
    ind: dict[str, np.ndarray] = {}
    for n in (C.MM_CURTA, C.MM_MEDIA, C.MM_LONGA):
        ind[f"mm{n}"] = sma(c, n)
    for n in (C.MME_RAPIDA, C.MME_LENTA):
        ind[f"mme{n}"] = ema(c, n)
    ind["bbMeio"], ind["bbSup"], ind["bbInf"], ind["pctB"] = bollinger(c)
    ind["ifr"] = ifr(c)
    ind["macd"], ind["macdSinal"], ind["macdHist"] = macd(c)
    ind["estK"], ind["estD"] = estocastico(h, l, c)
    ind["atr"] = atr(h, l, c)
    ind["adx"], ind["diMais"], ind["diMenos"] = adx(h, l, c)
    ind["obv"] = obv(c, vol)
    ind["max52"] = maxima_movel(h, C.ANO)
    ind["min52"] = minima_movel(l, C.ANO)
    ind["donchSup"] = anterior(maxima_movel(h, C.DONCHIAN_ENTRADA))
    ind["donchInf"] = anterior(minima_movel(l, C.DONCHIAN_SAIDA))
    vm = sma(vol, C.VOLUME_REL_N)
    ind["volMedia"] = anterior(vm)          # média dos 20 pregões ANTERIORES
    return ind
