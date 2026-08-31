"""Cotações, liquidez e valor de mercado via Yahoo Finance, com cache em disco."""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CACHE_DIR

log = logging.getLogger(__name__)
SUFIXO_B3 = ".SA"


def _yf():
    import yfinance as yf
    return yf


def _cache(nome: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / nome


def _achatar(df: pd.DataFrame, campo: str, tickers: list[str]) -> pd.DataFrame:
    """Extrai um campo do resultado do yf.download em qualquer layout de colunas."""
    if isinstance(df.columns, pd.MultiIndex):
        nivel0 = df.columns.get_level_values(0)
        if campo in set(nivel0):
            out = df.xs(campo, axis=1, level=0)
        else:                                   # layout (ticker, campo)
            out = df.xs(campo, axis=1, level=1)
    else:
        if campo not in df.columns:
            return pd.DataFrame()
        out = df[[campo]]
        out.columns = tickers[:1]
    return out.sort_index()


# O Yahoo devolve "Too Many Requests. Rate limited" quando o pedido é grande
# demais ou os lotes vêm rápido demais. Aconteceu em produção: 129 símbolos
# perdidos num lote só, o que esvaziou o cruzamento adiante.
TAMANHO_LOTE = 50
PAUSA_ENTRE_LOTES = 1.5          # segundos
PAUSA_APOS_BLOQUEIO = 20.0


def _bloqueado(exc: Exception) -> bool:
    t = str(exc).lower()
    return "too many requests" in t or "rate limit" in t or "429" in t


def _baixar_lote(tickers: list[str], inicio, fim, tentativas: int = 4):
    """Um lote, com nova tentativa e recuo maior quando o Yahoo bloqueia."""
    yf = _yf()
    for n in range(tentativas):
        try:
            raw = yf.download(tickers, start=str(inicio), end=str(fim),
                              auto_adjust=False, progress=False,
                              group_by="column", threads=False)
            if raw is not None and not raw.empty:
                return raw
            log.warning("Lote voltou vazio (tentativa %d/%d)", n + 1, tentativas)
            time.sleep(PAUSA_ENTRE_LOTES * (n + 1))
        except Exception as exc:                            # noqa: BLE001
            espera = PAUSA_APOS_BLOQUEIO if _bloqueado(exc) else 2 ** n
            log.warning("Lote falhou (tentativa %d/%d, esperando %.0fs): %s",
                        n + 1, tentativas, espera, str(exc)[:160])
            time.sleep(espera)
    return None


def baixar_historico(tickers: list[str], inicio: str | date, fim: str | date,
                     *, usar_cache: bool = True, progresso=None
                     ) -> dict[str, pd.DataFrame]:
    """Devolve {'preco': ajustado, 'fechamento': bruto, 'volume': em ações}.

    Baixa em lotes de 150 símbolos. Um lote que falhe não derruba os demais —
    os tickers dele simplesmente ficam de fora, e isso aparece no diagnóstico.
    """
    tickers = sorted(set(tickers))
    if not tickers:
        vazio = pd.DataFrame()
        return {"preco": vazio, "fechamento": vazio, "volume": vazio}

    chave = f"px_{hash((tuple(tickers), str(inicio), str(fim))) & 0xFFFFFFFF:x}.parquet"
    arq = _cache(chave)
    if usar_cache and arq.exists():
        raw = pd.read_parquet(arq)
        raw.columns = pd.MultiIndex.from_tuples(
            [tuple(c.split("|", 1)) for c in raw.columns])
    else:
        lotes = [tickers[i:i + TAMANHO_LOTE]
                 for i in range(0, len(tickers), TAMANHO_LOTE)]
        partes, perdidos = [], 0
        for i, lote in enumerate(lotes):
            if progresso:
                progresso(f"Cotações: lote {i+1} de {len(lotes)}...", None)
            if i:
                time.sleep(PAUSA_ENTRE_LOTES)
            bloco = _baixar_lote(lote, inicio, fim)
            if bloco is None:
                perdidos += len(lote)
                log.warning("Lote %d de %d sem dados (%d tickers perdidos)",
                            i + 1, len(lotes), len(lote))
                continue
            if not isinstance(bloco.columns, pd.MultiIndex):
                bloco.columns = pd.MultiIndex.from_product([bloco.columns, [lote[0]]])
            partes.append(bloco)

        if perdidos:
            log.warning("%d de %d tickers ficaram sem cotação (%.0f%%). "
                        "Se a proporção for alta, o Yahoo esta limitando as "
                        "requisicoes — rode de novo mais tarde.",
                        perdidos, len(tickers), 100 * perdidos / len(tickers))
        if not partes:
            vazio = pd.DataFrame()
            return {"preco": vazio, "fechamento": vazio, "volume": vazio}

        raw = pd.concat(partes, axis=1).sort_index()
        raw = raw.loc[:, ~raw.columns.duplicated()]
        if usar_cache:
            flat = raw.copy()
            flat.columns = ["|".join(map(str, c)) for c in flat.columns]
            flat.to_parquet(arq)

    campo_aj = "Adj Close" if "Adj Close" in set(
        raw.columns.get_level_values(0) if isinstance(raw.columns, pd.MultiIndex)
        else raw.columns) else "Close"

    return {
        "preco": _achatar(raw, campo_aj, tickers),
        "fechamento": _achatar(raw, "Close", tickers),
        "volume": _achatar(raw, "Volume", tickers),
    }


def liquidez_media_diaria(fechamento: pd.DataFrame, volume: pd.DataFrame,
                          janela: int = 63) -> pd.Series:
    """Volume financeiro médio (R$/dia) dos últimos `janela` pregões."""
    if fechamento.empty or volume.empty:
        return pd.Series(dtype=float)
    fin = (fechamento * volume).tail(janela)
    return fin.mean(skipna=True)


def tickers_validos(precos: pd.DataFrame, min_pregoes: int = 120,
                    cobertura_minima: float = 0.8) -> list[str]:
    """Descarta papéis com histórico curto demais para estimar covariância.

    O script original usava `prices.T.dropna().T`, que exclui qualquer ativo
    com um único dia faltante — inclusive por feriado ou leilão.
    """
    if precos.empty:
        return []
    validos = precos.notna().sum()
    n = len(precos)
    ok = (validos >= min_pregoes) & (validos >= cobertura_minima * n)
    return list(precos.columns[ok])


def retornos(precos: pd.DataFrame, *, log_ret: bool = False) -> pd.DataFrame:
    px = precos.ffill()
    r = np.log(px).diff() if log_ret else px.pct_change()
    return r.dropna(how="all").fillna(0.0)


# ---------------------------------------------------------------------------
# Valor de mercado
# ---------------------------------------------------------------------------
def acoes_em_circulacao(tickers: list[str], *, usar_cache: bool = True) -> pd.Series:
    """Número de ações por ticker (Yahoo). Cacheado por dia."""
    arq = _cache(f"shares_{date.today():%Y%m%d}.parquet")
    if usar_cache and arq.exists():
        s = pd.read_parquet(arq)["ACOES"]
        faltando = [t for t in tickers if t not in s.index]
        if not faltando:
            return s.reindex(tickers)
    else:
        s = pd.Series(dtype=float)
        faltando = tickers

    yf = _yf()
    novos = {}
    for t in faltando:
        try:
            fi = yf.Ticker(t).fast_info
            n = fi.get("shares") or fi.get("sharesOutstanding")
            mc = fi.get("market_cap") or fi.get("marketCap")
            px = fi.get("last_price") or fi.get("lastPrice")
            if not n and mc and px:
                n = mc / px
            novos[t] = float(n) if n else np.nan
        except Exception as exc:                            # noqa: BLE001
            log.debug("sem ações em circulação para %s: %s", t, exc)
            novos[t] = np.nan

    s = pd.concat([s, pd.Series(novos)]) if len(s) else pd.Series(novos)
    s = s[~s.index.duplicated(keep="last")]
    if usar_cache:
        s.rename("ACOES").to_frame().to_parquet(arq)
    return s.reindex(tickers)


def acoes_historicas(ticker: str, data_ref: pd.Timestamp) -> float:
    """Nº de ações vigente numa data passada (para backtest sem viés)."""
    yf = _yf()
    try:
        serie = yf.Ticker(ticker).get_shares_full(
            start=str((data_ref - timedelta(days=400)).date()),
            end=str(data_ref.date()))
        if serie is not None and len(serie):
            return float(serie.iloc[-1])
    except Exception:                                       # noqa: BLE001
        pass
    return float("nan")
