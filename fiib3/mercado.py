"""Lado de mercado: cotação, liquidez e — o dado que define um FII — proventos.

Preço e volume saem de `magicb3.prices`, que já resolve os problemas do
`yf.download` (lotes, símbolos inexistentes, layout de colunas que muda). O que
precisa existir aqui é a **série de rendimentos por cota**, mês a mês: é dela
que saem o DY, a renda mensal estimada e a medida de consistência, e ela não
tem equivalente no lado das ações.

Sobre a escolha da fonte de proventos: o número oficial está nos comunicados de
rendimento no FNET da B3, um por fundo por mês, sem arquivo consolidado. O
Yahoo entrega a mesma série num pedido por ticker. Para uma tela de triagem
isso basta; para conferir um fundo específico antes de comprar, o FNET é a
fonte — e o site diz isso ao usuário em vez de fingir precisão que não tem.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import CACHE_DIR
from .cvm_fii import _cache

log = logging.getLogger(__name__)

try:
    from magicb3 import prices as _px
except ImportError:                                            # pragma: no cover
    _px = None


def _yf():
    import yfinance as yf
    return yf


# ---------------------------------------------------------------------------
# Preço e liquidez
# ---------------------------------------------------------------------------
def _adaptar_progresso(progresso):
    """Traduz o callback do `magicb3` para a convenção do `fiib3`.

    Os dois módulos combinaram sinais diferentes: `magicb3.prices` chama
    `progresso(mensagem, valor)` e aqui a convenção é `progresso(fracao, texto)`.
    Passar um pelo outro faz `0.30 * f` multiplicar uma string, e a coleta morre
    com `TypeError` no meio do download — foi o que aconteceu na primeira
    execução real. Como o `prices` não diz quantos lotes faltam, a fração é
    estimada pelo número de chamadas; serve para a barra andar, não para medir.
    """
    if progresso is None:
        return None
    estado = {"n": 0}

    def ponte(mensagem, valor=None):
        estado["n"] += 1
        progresso(min(0.95, estado["n"] / 12.0), str(mensagem))

    return ponte


def baixar_cotacoes(tickers: list[str], *, anos: float = 1.5,
                    usar_cache: bool = True, progresso=None) -> dict[str, pd.DataFrame]:
    """{'preco', 'fechamento', 'volume'} — reaproveita o downloader das ações."""
    if _px is None:                                            # pragma: no cover
        raise RuntimeError("magicb3.prices não está disponível.")
    fim = date.today() + timedelta(days=1)
    inicio = fim - timedelta(days=int(365 * anos) + 10)
    return _px.baixar_historico(tickers, inicio, fim, usar_cache=usar_cache,
                                progresso=_adaptar_progresso(progresso))


def liquidez(fechamento: pd.DataFrame, volume: pd.DataFrame,
             janela: int = 63) -> pd.Series:
    return _px.liquidez_media_diaria(fechamento, volume, janela)


def preco_atual(precos: pd.DataFrame) -> pd.Series:
    """Último preço com negócio de cada ticker."""
    if precos.empty:
        return pd.Series(dtype=float)
    return precos.ffill().iloc[-1]


def variacao(precos: pd.DataFrame, meses: int = 12) -> pd.Series:
    """Variação do preço no período, sem contar rendimentos."""
    if precos.empty:
        return pd.Series(dtype=float)
    px = precos.ffill()
    corte = px.index[-1] - pd.DateOffset(months=meses)
    base = px[px.index <= corte]
    if base.empty:
        return pd.Series(np.nan, index=px.columns)
    return px.iloc[-1] / base.iloc[-1] - 1.0


# ---------------------------------------------------------------------------
# Proventos
# ---------------------------------------------------------------------------
def baixar_proventos(tickers: list[str], *, meses: int = 36,
                     usar_cache: bool = True, progresso=None) -> pd.DataFrame:
    """Rendimentos por cota, um pedido por ticker.

    Devolve um DataFrame longo com TICKER, DATA e VALOR — um formato que
    sobrevive a fundos que pagam duas vezes no mesmo mês (amortização junto do
    rendimento), coisa que uma tabela mês x ticker esconderia.
    """
    tickers = sorted(set(tickers))
    arq = _cache(f"proventos_{meses}m_{date.today():%Y%m%d}.parquet")
    if usar_cache and arq.exists():
        cache = pd.read_parquet(arq)
        faltam = sorted(set(tickers) - set(cache["TICKER"].unique()))
        if not faltam:
            return cache[cache["TICKER"].isin(tickers)].reset_index(drop=True)
    else:
        cache, faltam = pd.DataFrame(columns=["TICKER", "DATA", "VALOR"]), tickers

    yf = _yf()
    corte = pd.Timestamp.today().normalize() - pd.DateOffset(months=meses)
    linhas = []
    for i, t in enumerate(faltam):
        if progresso:
            progresso(i / max(1, len(faltam)), f"Proventos {t}")
        try:
            serie = yf.Ticker(t).dividends
        except Exception as exc:                               # noqa: BLE001
            log.warning("Proventos de %s falharam: %s", t, str(exc)[:120])
            continue
        if serie is None or len(serie) == 0:
            continue
        s = serie.copy()
        s.index = pd.to_datetime(s.index).tz_localize(None)
        s = s[s.index >= corte]
        for data, valor in s.items():
            linhas.append({"TICKER": t, "DATA": data, "VALOR": float(valor)})

    novo = pd.DataFrame(linhas, columns=["TICKER", "DATA", "VALOR"])
    todo = pd.concat([cache, novo], ignore_index=True) if len(cache) else novo
    todo = todo.drop_duplicates(subset=["TICKER", "DATA"])
    if usar_cache and len(todo):
        todo.to_parquet(arq, index=False)
    return todo[todo["TICKER"].isin(tickers)].reset_index(drop=True)


def mensalizar(proventos: pd.DataFrame) -> pd.DataFrame:
    """Tabela mês (linha) x ticker (coluna) com a soma paga no mês."""
    if proventos.empty:
        return pd.DataFrame()
    df = proventos.copy()
    df["MES"] = pd.to_datetime(df["DATA"]).dt.to_period("M")
    tab = df.pivot_table(index="MES", columns="TICKER", values="VALOR",
                         aggfunc="sum")
    return tab.sort_index()


def resumo_proventos(proventos: pd.DataFrame, *, janela: int = 12,
                     janela_longa: int = 36) -> pd.DataFrame:
    """Estatísticas por ticker que alimentam o DY e o score de consistência.

    A distinção que mais importa aqui:

      `PROV_12M`     soma dos 12 meses — é o numerador do DY que o mercado usa,
                     e sobe junto com qualquer rendimento extraordinário.
      `PROV_MEDIANA` mediana dos meses pagos, anualizada — ignora o pico. Quando
                     as duas medidas divergem muito, o DY alto do fundo veio de
                     um evento, não da operação. A coluna `RAZAO_EXTRA` mede
                     essa divergência e o site a mostra como alerta.
    """
    if proventos.empty:
        return pd.DataFrame(columns=[
            "PROV_12M", "PROV_MEDIANA_12M", "MESES_PAGOS_12M",
            "MESES_PAGOS_36M", "CV_PROVENTOS", "RAZAO_EXTRA",
            "ULTIMO_PROVENTO", "DT_ULTIMO_PROVENTO"])

    tab = mensalizar(proventos)
    if tab.empty:
        return pd.DataFrame()
    fim = tab.index.max()
    jan12 = tab[tab.index > fim - janela]
    jan36 = tab[tab.index > fim - janela_longa]

    pagos12 = (jan12 > 0).sum()
    soma12 = jan12.sum(min_count=1)
    mediana = jan12.where(jan12 > 0).median()
    desvio = jan12.where(jan12 > 0).std()
    media = jan12.where(jan12 > 0).mean()

    out = pd.DataFrame({
        "PROV_12M": soma12,
        "PROV_MEDIANA_12M": mediana * 12,
        "MESES_PAGOS_12M": pagos12,
        "MESES_PAGOS_36M": (jan36 > 0).sum(),
        "CV_PROVENTOS": (desvio / media).replace([np.inf, -np.inf], np.nan),
        "ULTIMO_PROVENTO": tab.ffill().iloc[-1],
    })
    out["RAZAO_EXTRA"] = (out["PROV_12M"] / out["PROV_MEDIANA_12M"]
                          ).replace([np.inf, -np.inf], np.nan)

    ult = (proventos.sort_values("DATA").groupby("TICKER")["DATA"].last())
    out["DT_ULTIMO_PROVENTO"] = ult
    return out
