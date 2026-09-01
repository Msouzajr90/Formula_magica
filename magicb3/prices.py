"""Cotações, liquidez e valor de mercado via Yahoo Finance, com cache em disco."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from contextlib import contextmanager
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


def _chave(*partes) -> str:
    """Identificador estável para nome de arquivo de cache.

    O `hash()` do Python é embaralhado a cada processo (PYTHONHASHSEED
    aleatório), então a chave antiga mudava a cada execução e o cache de
    cotações nunca era reaproveitado entre uma rodada e a seguinte. Com
    blake2b a mesma lista de tickers gera sempre o mesmo arquivo.
    """
    bruto = "|".join(str(p) for p in partes).encode("utf-8")
    return hashlib.blake2b(bruto, digest_size=8).hexdigest()


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
ESPERA_BLOQUEIO = (60.0, 180.0, 300.0)   # recuo real quando o Yahoo barra
LOTES_BLOQUEADOS_SEGUIDOS = 3            # depois disso, desistir da rodada


ARQ_INEXISTENTES = "tickers_inexistentes.json"


class BloqueioYahoo(RuntimeError):
    """O Yahoo está barrando as requisições — não adianta insistir agora."""


def _carregar_inexistentes() -> set[str]:
    """Símbolos que o Yahoo já confirmou não existir.

    A B3 devolve o prefixo do emissor, não os papéis negociados, então o
    código testa PREFIXO + 3/4/5/6/11 — cerca de 2.000 tentativas para ~400
    empresas. Guardar as que não existem evita repetir o mesmo desperdício a
    cada rodada, que é justamente o que atrai o bloqueio.
    """
    arq = _cache(ARQ_INEXISTENTES)
    if not arq.exists():
        return set()
    try:
        return set(json.loads(arq.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def _gravar_inexistentes(novos: set[str]) -> None:
    if not novos:
        return
    todos = _carregar_inexistentes() | set(novos)
    _cache(ARQ_INEXISTENTES).write_text(
        json.dumps(sorted(todos)), encoding="utf-8")
    log.info("%d símbolos inexistentes anotados (%d no total).",
             len(novos), len(todos))


# Um "429" solto não serve como sinal: a mensagem de erro traz a lista de
# símbolos, e tickers como Z0429 ou GLPO4 dariam falso positivo — foi assim que
# um lote de papéis inexistentes passou por bloqueio no teste.
_SINAL_BLOQUEIO = re.compile(
    r"too many requests|rate.?limit|\b(?:http|status|code|erro?r?)\D{0,12}429\b",
    re.IGNORECASE)


def _bloqueado(texto) -> bool:
    return bool(_SINAL_BLOQUEIO.search(str(texto)))


class _EscutaYF(logging.Handler):
    """Guarda o que o yfinance reclama durante um lote.

    Isto existe porque o `yf.download` NÃO levanta exceção quando o Yahoo
    bloqueia: ele registra "Failed downloads" no logger dele e devolve um
    DataFrame vazio. Sem ler esse log, um bloqueio fica indistinguível de um
    ticker que não existe — e era por isso que a espera longa nunca era
    aplicada: o código só olhava para exceções, que não vinham.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.linhas: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.linhas.append(record.getMessage())
        except Exception:                                   # noqa: BLE001
            pass

    @property
    def texto(self) -> str:
        return " ".join(self.linhas)


@contextmanager
def _escutando_yfinance():
    h = _EscutaYF()
    lg = logging.getLogger("yfinance")
    lg.addHandler(h)
    try:
        yield h
    finally:
        lg.removeHandler(h)


def _baixar_lote(tickers: list[str], inicio, fim, tentativas: int = 4):
    """Um lote. Devolve (dados, bloqueado).

    `bloqueado=True` significa que o Yahoo barrou a requisição — os papéis
    podem existir e vale tentar de novo. `bloqueado=False` com dados vazios
    significa que nenhum dos símbolos existe (combinações de sufixo que a B3
    nunca negociou); repetir não inventa cotação, então seguimos em frente.
    """
    yf = _yf()
    for n in range(tentativas):
        try:
            with _escutando_yfinance() as escuta:
                raw = yf.download(tickers, start=str(inicio), end=str(fim),
                                  auto_adjust=False, progress=False,
                                  group_by="column", threads=False)
            if raw is not None and not raw.empty:
                return raw, False
            barrado = _bloqueado(escuta.texto)
        except Exception as exc:                            # noqa: BLE001
            barrado = _bloqueado(exc)
            log.warning("Lote falhou: %s", str(exc)[:160])

        if not barrado:
            log.info("Lote sem cotação e sem bloqueio: %d símbolos inexistentes.",
                     len(tickers))
            return None, False

        espera = ESPERA_BLOQUEIO[min(n, len(ESPERA_BLOQUEIO) - 1)]
        if n == tentativas - 1:
            break
        log.warning("Yahoo bloqueou (tentativa %d/%d). Esperando %.0fs.",
                    n + 1, tentativas, espera)
        time.sleep(espera)
    return None, True


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

    arq = _cache(f"px_{_chave(tuple(tickers), inicio, fim)}.parquet")
    if usar_cache and arq.exists():
        raw = pd.read_parquet(arq)
        raw.columns = pd.MultiIndex.from_tuples(
            [tuple(c.split("|", 1)) for c in raw.columns])
    else:
        mortos = _carregar_inexistentes() if usar_cache else set()
        vivos = [t for t in tickers if t not in mortos]
        if mortos:
            log.info("Pulando %d símbolos já conhecidos como inexistentes.",
                     len(tickers) - len(vivos))

        lotes = [vivos[i:i + TAMANHO_LOTE]
                 for i in range(0, len(vivos), TAMANHO_LOTE)]
        partes, perdidos, bloqueados_seguidos, novos_mortos = [], 0, 0, set()
        for i, lote in enumerate(lotes):
            if progresso:
                progresso(f"Cotações: lote {i+1} de {len(lotes)}...", None)

            # Cache por lote: uma rodada interrompida (ou barrada no meio)
            # não joga fora o que já baixou. A seguinte continua de onde parou.
            arq_lote = _cache(f"lt_{_chave(tuple(lote), inicio, fim)}.parquet")
            if usar_cache and arq_lote.exists():
                bloco = pd.read_parquet(arq_lote)
                bloco.columns = pd.MultiIndex.from_tuples(
                    [tuple(c.split("|", 1)) for c in bloco.columns])
                partes.append(bloco)
                continue

            if i:
                time.sleep(PAUSA_ENTRE_LOTES)
            bloco, barrado = _baixar_lote(lote, inicio, fim)

            if bloco is None:
                perdidos += len(lote)
                if barrado:
                    bloqueados_seguidos += 1
                    log.warning("Lote %d de %d barrado pelo Yahoo (%d seguidos).",
                                i + 1, len(lotes), bloqueados_seguidos)
                    if bloqueados_seguidos >= LOTES_BLOQUEADOS_SEGUIDOS:
                        _gravar_inexistentes(novos_mortos)
                        raise BloqueioYahoo(
                            f"O Yahoo barrou {bloqueados_seguidos} lotes seguidos. "
                            f"Parei no lote {i+1} de {len(lotes)} em vez de gastar "
                            "horas coletando nada. O que já baixou ficou em cache: "
                            "rode de novo mais tarde e ele continua daqui.")
                else:
                    novos_mortos.update(lote)
                    bloqueados_seguidos = 0
                continue

            bloqueados_seguidos = 0
            if not isinstance(bloco.columns, pd.MultiIndex):
                bloco.columns = pd.MultiIndex.from_product([bloco.columns, [lote[0]]])
            partes.append(bloco)
            if usar_cache:
                plano = bloco.copy()
                plano.columns = ["|".join(map(str, c)) for c in plano.columns]
                plano.to_parquet(arq_lote)

        _gravar_inexistentes(novos_mortos)
        if perdidos:
            log.warning("%d de %d tickers ficaram sem cotação (%.0f%%).",
                        perdidos, len(vivos), 100 * perdidos / max(len(vivos), 1))
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
    novos, falhas_seguidas = {}, 0
    for i, t in enumerate(faltando):
        if i:
            time.sleep(0.35)                 # uma requisição por empresa: vá devagar
        try:
            fi = yf.Ticker(t).fast_info
            n = fi.get("shares") or fi.get("sharesOutstanding")
            mc = fi.get("market_cap") or fi.get("marketCap")
            px = fi.get("last_price") or fi.get("lastPrice")
            if not n and mc and px:
                n = mc / px
            novos[t] = float(n) if n else np.nan
            falhas_seguidas = 0
        except Exception as exc:                            # noqa: BLE001
            log.debug("sem ações em circulação para %s: %s", t, exc)
            novos[t] = np.nan
            falhas_seguidas += 1
            if _bloqueado(exc):
                log.warning("Yahoo limitou as requisições; pausando %.0fs",
                            PAUSA_APOS_BLOQUEIO)
                time.sleep(PAUSA_APOS_BLOQUEIO)
                falhas_seguidas = 0
            elif falhas_seguidas >= 25:
                log.warning("25 falhas seguidas no nº de ações; desistindo das "
                            "%d restantes.", len(faltando) - i - 1)
                break

    obtidos = sum(1 for v in novos.values() if v == v and v)
    log.info("nº de ações pelo Yahoo: %d de %d consultados", obtidos, len(faltando))

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
