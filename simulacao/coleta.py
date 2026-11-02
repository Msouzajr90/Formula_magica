# -*- coding: utf-8 -*-
"""A única parte que toca a rede: Yahoo (preços) e Banco Central (CDI).

O download do Yahoo reaproveita `magicb3.prices.baixar_historico`, que já
sabe lidar com o bloqueio intermitente do Yahoo (lotes de 50, repescagem em
ondas, cache por lote, símbolos inexistentes anotados). Escrever outro seria
reaprender as mesmas lições.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd

log = logging.getLogger(__name__)


def _sem_sufixo(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [str(c).replace(".SA", "") for c in out.columns]
    out.index = pd.DatetimeIndex(out.index).tz_localize(None).normalize()
    return out


def baixar_precos(tickers: list[str], inicio: date, fim: date) -> dict[str, pd.DataFrame]:
    """{'preco': ajustado, 'fechamento', 'volume'}, colunas sem '.SA'.

    `fim` é inclusivo aqui; o yfinance trata o fim como exclusivo.
    """
    from magicb3 import prices

    if not tickers:
        vazio = pd.DataFrame()
        return {"preco": vazio, "fechamento": vazio, "volume": vazio}
    simbolos = [f"{t}.SA" for t in tickers]
    bruto = prices.baixar_historico(simbolos, inicio, fim + timedelta(days=1))
    return {k: _sem_sufixo(v) for k, v in bruto.items()}


def baixar_ibov(inicio: date, fim: date) -> pd.Series:
    """Fechamento do Ibovespa. Índice de retorno total por construção (a B3
    reinveste os proventos na carteira teórica), então o fechamento basta."""
    from magicb3 import prices

    bruto = prices.baixar_historico(["^BVSP"], inicio, fim + timedelta(days=1))
    f = bruto.get("fechamento")
    if f is None or f.empty:
        raise RuntimeError("O Yahoo não devolveu o Ibovespa (^BVSP). Sem ele "
                           "não há calendário de pregões — nada a fazer hoje.")
    s = f.iloc[:, 0]
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    return s.dropna()


def baixar_cdi(inicio: date, fim: date) -> dict[date, float]:
    """CDI diário (SGS 12), em % ao dia."""
    from magicb3 import rede
    from mercado import bcb

    from . import config as C

    return bcb.serie_sgs(C.SGS_CDI, inicio, fim, sessao=rede.sessao())
