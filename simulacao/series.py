# -*- coding: utf-8 -*-
"""Cálculo puro: preço -> retorno no calendário, liquidez, emenda, CDI.

Nada aqui toca a rede nem o disco. Recebe pandas, devolve números.

Convenção de alinhamento, usada em toda a base e no motor do navegador
----------------------------------------------------------------------
Existe UM calendário de pregões (`pregoes`, as datas do Ibovespa). Uma série
é guardada como `i0` + lista `r`: `r[k]` é o retorno do pregão `pregoes[i0+k]`,
medido do fechamento do pregão anterior ao fechamento deste. Por isso `i0 >= 1`
sempre: o primeiro pregão com preço não tem retorno, só o seguinte.

Dentro da série, pregão sem negócio tem retorno 0 (o preço é carregado do dia
anterior) e o movimento inteiro cai no próximo pregão com negócio. Depois do
último preço a série ACABA — não se carrega preço de papel deslistado para a
frente, senão ele viraria um ativo de risco zero no backtest.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd

from . import config as C


# ---------------------------------------------------------------------------
# Calendário
# ---------------------------------------------------------------------------
def calendario_de(fechamentos: pd.Series) -> list[str]:
    """Datas com fechamento válido, em ISO, ordenadas e sem fim de semana."""
    s = pd.to_numeric(fechamentos, errors="coerce").dropna()
    s = s[s > 0]
    idx = pd.DatetimeIndex(s.index).normalize()
    idx = idx[idx.dayofweek < 5]
    return sorted({d.strftime("%Y-%m-%d") for d in idx})


def estender_calendario(antigo: list[str], novas: list[str]) -> list[str]:
    """Acrescenta só as datas posteriores à última. O passado não se reescreve.

    Reescrever o passado deslocaria o `i0` de todos os arquivos já gravados.
    Se o Yahoo passar a mostrar um pregão antigo que antes faltava, ele fica de
    fora até a próxima reconstrução completa — e o retorno daquele dia cai no
    pregão seguinte, sem se perder.
    """
    if not antigo:
        return sorted(set(novas))
    ultimo = antigo[-1]
    return antigo + sorted({d for d in novas if d > ultimo})


def sem_pregoes_incompletos(datas: list[str], precos: pd.DataFrame | None,
                            minimo: float, protegido: str | None = None,
                            janela_dias: int = 10) -> tuple[list[str], list[tuple[str, float]]]:
    """Tira do FIM do calendário os pregões em que poucos papéis têm preço.

    `datas` é o calendário candidato (as datas do Ibovespa). Para cada data do
    fim para trás, conta quantos papéis *ativos* — com preço em algum dia dos
    `janela_dias` corridos anteriores — têm preço nela. Abaixo de `minimo`, a
    data sai e o teste passa para a anterior; a primeira data boa encerra o
    corte (um buraco no meio não é este problema). Datas até `protegido`
    (o último pregão já gravado) nunca saem.

    Devolve (calendário, [(data adiada, fração com preço)]).
    """
    if precos is None or precos.empty or not datas:
        return list(datas), []
    px = precos.copy()
    px.index = pd.DatetimeIndex(px.index).tz_localize(None).normalize()
    px = px[~px.index.duplicated(keep="last")].sort_index()
    validos = px.notna() & (px > 0)
    out, adiados = list(datas), []
    while out and (protegido is None or out[-1] > protegido):
        d = pd.Timestamp(out[-1])
        recente = validos[(validos.index > d - pd.Timedelta(days=janela_dias))
                          & (validos.index < d)]
        ativos = recente.any(axis=0)
        if not ativos.any():
            break
        no_dia = (validos.loc[d] if d in validos.index
                  else pd.Series(False, index=validos.columns))
        frac = float((no_dia & ativos).sum() / ativos.sum())
        if frac >= minimo:
            break
        adiados.append((out.pop(), frac))
    return out, adiados


def _posicoes(datas: pd.DatetimeIndex, pregoes: list[str]) -> np.ndarray:
    """Posição de cada data no calendário; data fora do calendário vai para o
    pregão seguinte (o negócio feito num dia que o Ibovespa não tem conta como
    do pregão seguinte). Depois do último pregão: -1."""
    cal = np.array(pregoes, dtype="U10")
    iso = np.array([d.strftime("%Y-%m-%d") for d in datas], dtype="U10")
    pos = np.searchsorted(cal, iso, side="left")
    pos[pos >= len(cal)] = -1
    return pos


# ---------------------------------------------------------------------------
# Preço -> retornos no calendário
# ---------------------------------------------------------------------------
def retornos_no_calendario(precos: pd.Series, pregoes: list[str]
                           ) -> tuple[int, np.ndarray] | None:
    """(i0, retornos em fração) de uma série de preço ajustado.

    `None` se a série não tem dois pregões com preço dentro do calendário.
    """
    if not pregoes:
        return None
    s = pd.to_numeric(precos, errors="coerce").dropna()
    s = s[s > 0]
    if s.empty:
        return None
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s = s[s.index >= pd.Timestamp(pregoes[0])]
    pos = _posicoes(s.index, pregoes)
    ok = pos >= 0
    s, pos = s[ok], pos[ok]
    if len(s) == 0:
        return None
    # duas datas que caem no mesmo pregão: vale a última
    por_pos = pd.Series(s.to_numpy(float), index=pos)
    por_pos = por_pos[~por_pos.index.duplicated(keep="last")]
    p_ini, p_fim = int(por_pos.index.min()), int(por_pos.index.max())
    if p_fim - p_ini < 1:
        return None
    px = por_pos.reindex(range(p_ini, p_fim + 1)).ffill().to_numpy(float)
    r = px[1:] / px[:-1] - 1.0
    return p_ini + 1, r


def compactar(r: np.ndarray, escala: int = C.ESCALA) -> list[int]:
    """Fração -> inteiro escalado. NaN não deveria chegar aqui; vira 0."""
    out = []
    for v in np.asarray(r, dtype=float):
        out.append(0 if not math.isfinite(v) else int(round(v * escala)))
    return out


def descompactar(r: list[int], escala: int = C.ESCALA) -> np.ndarray:
    return np.asarray(r, dtype=float) / escala


# ---------------------------------------------------------------------------
# Emenda incremental
# ---------------------------------------------------------------------------
def emendar(i0_velho: int, r_velho: list[int], i0_novo: int, r_novo: list[int],
            tolerancia: int = 0) -> tuple[int, list[int], int] | None:
    """Emenda o trecho novo no fim do antigo. Devolve (i0, r, divergências).

    O trecho novo vence na sobreposição: o Yahoo corrige pregões recentes
    (negócio tardio, provento lançado com atraso), e o último dia gravado pode
    ter sido coletado antes do fechamento oficial. `divergências` conta quantos
    pregões sobrepostos mudaram mais que `tolerancia` — se forem muitos, algo
    maior que uma correção aconteceu (desdobramento ajustado retroativamente) e
    vale uma reconstrução completa.

    `None` se houver buraco entre os dois trechos: emendar por cima de um
    buraco inventaria retorno zero nos pregões que faltam.
    """
    if not r_velho:
        return i0_novo, list(r_novo), 0
    if not r_novo:
        return i0_velho, list(r_velho), 0
    a, b = i0_novo, i0_novo + len(r_novo)          # [a, b)
    c, d = i0_velho, i0_velho + len(r_velho)       # [c, d)
    if a > d or c > b:
        return None
    inicio, fim = min(a, c), max(b, d)
    mapa: dict[int, int] = {c + k: v for k, v in enumerate(r_velho)}
    div = 0
    for k, v in enumerate(r_novo):
        i = a + k
        if i in mapa and abs(mapa[i] - v) > tolerancia:
            div += 1
        mapa[i] = v
    return inicio, [mapa[i] for i in range(inicio, fim)], div


# ---------------------------------------------------------------------------
# Liquidez
# ---------------------------------------------------------------------------
def volume_financeiro(fechamento: pd.Series, volume: pd.Series) -> pd.Series:
    f = pd.to_numeric(fechamento, errors="coerce")
    v = pd.to_numeric(volume, errors="coerce")
    fin = (f * v).dropna()
    fin.index = pd.DatetimeIndex(fin.index).tz_localize(None).normalize()
    return fin.sort_index()


def liquidez(fechamento: pd.Series, volume: pd.Series,
             janela: int = C.JANELA_LIQUIDEZ,
             minimo: int = C.MIN_PREGOES_LIQUIDEZ) -> dict:
    """{'max', 'atual', 'neg'}: maior média móvel, a última, e a fração dos
    últimos `janela` pregões com negócio.

    Pregão sem negócio entra na média como zero: um papel que negocia R$ 3 mi
    um dia por semana não é um papel de R$ 3 mi por dia.
    """
    fin = volume_financeiro(fechamento, volume)
    if fin.empty:
        return {"max": None, "atual": None, "neg": None}
    media = fin.rolling(janela, min_periods=minimo).mean().dropna()
    cauda = fin.tail(janela)
    neg = float((cauda > 0).mean()) if len(cauda) else None
    if media.empty:
        return {"max": None, "atual": None, "neg": neg}
    return {"max": float(media.max()), "atual": float(media.iloc[-1]), "neg": neg}


# ---------------------------------------------------------------------------
# CDI
# ---------------------------------------------------------------------------
def cdi_no_calendario(cdi_pct_dia: dict[date, float], pregoes: list[str]
                      ) -> tuple[int, np.ndarray] | None:
    """CDI composto entre pregões consecutivos da B3.

    O calendário do CDI (dias úteis bancários) e o da B3 quase coincidem, mas
    não sempre. Compor tudo o que rendeu em (pregão anterior, pregão] faz o CDI
    de um dia sem pregão cair no pregão seguinte, sem perder nem duplicar dia.
    """
    if not cdi_pct_dia or len(pregoes) < 2:
        return None
    datas = sorted(cdi_pct_dia)
    iso = np.array([d.isoformat() for d in datas], dtype="U10")
    fatores = np.array([1.0 + cdi_pct_dia[d] / 100.0 for d in datas])
    cal = np.array(pregoes, dtype="U10")
    # índice do pregão que "recebe" cada dia de CDI: o primeiro pregão >= dia
    pos = np.searchsorted(cal, iso, side="left")
    acum = np.ones(len(pregoes))
    tem = np.zeros(len(pregoes), dtype=bool)
    for p, f in zip(pos, fatores):
        if 1 <= p < len(pregoes):
            acum[p] *= f
            tem[p] = True
    validos = np.flatnonzero(tem)
    if not len(validos):
        return None
    i0, i1 = int(validos[0]), int(validos[-1])
    return i0, acum[i0:i1 + 1] - 1.0


# ---------------------------------------------------------------------------
# Conferências
# ---------------------------------------------------------------------------
def saltos(i0: int, r: list[int], pregoes: list[str], escala: int = C.ESCALA,
           limite: float = C.SALTO_SUSPEITO) -> list[list]:
    """[[data, retorno]] dos pregões com |retorno| acima do limite."""
    out = []
    lim = limite * escala
    for k, v in enumerate(r):
        if abs(v) > lim and i0 + k < len(pregoes):
            out.append([pregoes[i0 + k], round(v / escala, 4)])
    return out


def anualizado(r: np.ndarray) -> float:
    """Retorno composto anualizado por 252 pregões."""
    r = np.asarray(r, dtype=float)
    if len(r) == 0:
        return float("nan")
    total = float(np.prod(1.0 + r))
    return total ** (252.0 / len(r)) - 1.0
