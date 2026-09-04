"""CNPJ do fundo <-> código de negociação na B3.

A fonte é o **ISIN do informe mensal da CVM**. O ISIN brasileiro embute o
prefixo do código de negociação (BR**MXRF**CTF008 -> MXRF11), vem junto com os
dados que já baixamos e é oficial.

A API de fundos listados da B3 continua implementada, mas desligada por padrão.
Ela mudou de contrato: o endereço responde 200 e devolve `totalRecords: 0` para
todo `typeFund` de 1 a 40. Mais importante — ela deixou de fazer falta: na
competência 07/2026, os 674 fundos marcados como negociados em bolsa têm ISIN,
sem exceção. O que era fonte de reserva virou fonte principal.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path

import pandas as pd

from . import config as C
from .cvm_fii import _cache, _cnpj_limpo, _sessao, ticker_do_isin

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
ESPERAS = (3.0, 12.0, 40.0)


def _pagina(pagina: int, tamanho: int = 120) -> dict:
    ultimo = None
    for n, espera in enumerate((0.0,) + ESPERAS):
        if espera:
            time.sleep(espera)
        payload = base64.b64encode(json.dumps({
            "typeFund": C.B3_TIPO_FII, "pageNumber": pagina,
            "pageSize": tamanho if n < 2 else max(30, tamanho // 2),
        }).encode()).decode()
        try:
            r = _sessao().get(C.B3_FUNDS_URL.format(payload=payload),
                              headers=HEADERS, timeout=90)
            r.raise_for_status()
            return r.json()
        except Exception as exc:                               # noqa: BLE001
            ultimo = exc
            log.warning("B3 não respondeu (página %d, tentativa %d): %s",
                        pagina, n + 1, str(exc)[:140])
    raise RuntimeError(f"B3 não respondeu na página {pagina}: {ultimo}")


def baixar_fundos_b3(*, usar_cache: bool = True) -> pd.DataFrame:
    """CNPJ, sigla e segmento dos FII listados. DataFrame vazio se a B3 cair."""
    arq = _cache("b3_fiis.parquet")
    if usar_cache and arq.exists():
        return pd.read_parquet(arq)

    linhas, pagina = [], 1
    try:
        while True:
            js = _pagina(pagina)
            linhas.extend(js.get("results", []))
            total = js.get("page", {}).get("totalPages", 1)
            if pagina >= total:
                break
            pagina += 1
    except Exception as exc:                                   # noqa: BLE001
        if arq.exists():
            log.warning("%s — usando o cache anterior.", exc)
            return pd.read_parquet(arq)
        log.warning("%s — seguindo apenas com o ISIN da CVM.", exc)
        return pd.DataFrame(columns=["CNPJ", "SIGLA", "SEGMENTO_B3", "NOME_B3"])

    df = pd.DataFrame(linhas)
    if df.empty:
        return pd.DataFrame(columns=["CNPJ", "SIGLA", "SEGMENTO_B3", "NOME_B3"])

    ren = {"acronym": "SIGLA", "cnpj": "CNPJ", "companyName": "NOME_B3",
           "fundName": "NOME_B3", "segment": "SEGMENTO_B3",
           "typeName": "SEGMENTO_B3"}
    df = df.rename(columns={k: v for k, v in ren.items() if k in df.columns})
    for c in ("CNPJ", "SIGLA", "SEGMENTO_B3", "NOME_B3"):
        if c not in df.columns:
            df[c] = pd.NA
    df["CNPJ"] = _cnpj_limpo(df["CNPJ"])
    df["SIGLA"] = df["SIGLA"].astype("string").str.strip().str.upper()
    df = df[df["SIGLA"].str.fullmatch(r"[A-Z0-9]{4}", na=False)]
    df = df[["CNPJ", "SIGLA", "SEGMENTO_B3", "NOME_B3"]].drop_duplicates(
        subset=["CNPJ"], keep="first")
    if usar_cache:
        df.to_parquet(arq, index=False)
    log.info("B3: %d FII listados.", len(df))
    return df


def montar_mapa(informe: pd.DataFrame, *, usar_b3: bool = False,
                usar_cache: bool = True) -> pd.DataFrame:
    """Acrescenta TICKER (e a origem dele) ao informe mensal.

    `usar_b3` vem desligado. A API de fundos listados mudou de contrato: o
    endereço ainda responde 200, mas devolve `totalRecords: 0` para todo
    `typeFund` de 1 a 40 — testado um a um. Consultá-la só gastaria quatro
    tentativas com espera crescente para receber uma lista vazia.

    E não faz falta: na competência 07/2026, **os 674 fundos marcados como
    negociados em bolsa têm ISIN no informe da CVM**, sem exceção. A fonte de
    reserva virou a fonte principal, e é oficial. Ligue `usar_b3=True` se a
    API voltar — o cruzamento continua implementado.
    """
    df = informe.copy()
    b3 = baixar_fundos_b3(usar_cache=usar_cache) if usar_b3 else pd.DataFrame()

    if not b3.empty:
        df = df.merge(b3, on="CNPJ", how="left")
        log.info("B3: %d fundos cruzados por CNPJ.", int(b3["SIGLA"].notna().sum()))
    else:
        df["SIGLA"] = pd.NA
        df["SEGMENTO_B3"] = pd.NA
        df["NOME_B3"] = pd.NA

    do_isin = df["ISIN"].map(ticker_do_isin) if "ISIN" in df.columns else pd.NA
    sigla_b3 = df["SIGLA"].astype("string")
    df["ORIGEM_TICKER"] = sigla_b3.notna().map({True: "b3", False: "isin"})
    df["SIGLA"] = sigla_b3.fillna(pd.Series(do_isin, index=df.index, dtype="string"))
    df.loc[df["SIGLA"].isna(), "ORIGEM_TICKER"] = pd.NA
    df["TICKER"] = df["SIGLA"].where(df["SIGLA"].isna(), df["SIGLA"] + "11")
    return df


def para_yahoo(tickers) -> list[str]:
    """MXRF11 -> MXRF11.SA (idempotente)."""
    out = []
    for t in tickers:
        if t is None or pd.isna(t):
            continue
        s = str(t).strip().upper()
        out.append(s if s.endswith(".SA") else s + ".SA")
    return out


def sem_sufixo(ticker: str) -> str:
    return str(ticker).upper().removesuffix(".SA")
