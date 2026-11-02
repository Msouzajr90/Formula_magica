# -*- coding: utf-8 -*-
"""Quem é candidato a entrar na base de preços.

A base não sai de uma lista fechada: junta os papéis que as outras abas do
site já conhecem, mais os irmãos de classe das ações, os ETFs da B3 e o que o
Marco quiser acrescentar à mão em `simulacao/tickers_extras.txt`. Quem entra
de fato é decidido depois, pelo corte de liquidez.

A base é ACUMULATIVA: papel que entrou não sai porque deixou de aparecer nas
listas de hoje. É isso que mantém na base a ação que foi líquida em 2014 e
depois minguou ou fechou capital.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from . import config as C

log = logging.getLogger(__name__)

_VALIDO = re.compile(C.PADRAO_TICKER)


def valido(t: str) -> bool:
    return bool(_VALIDO.match(str(t or "").strip().upper()))


def _ler(caminho: Path) -> dict | None:
    try:
        return json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Não li %s (%s); segue sem ele.", caminho.name, exc)
        return None


def _nome(n) -> str:
    n = " ".join(str(n or "").split())
    return n[:80]


def ler_extras(caminho: Path = C.ARQ_EXTRAS) -> dict[str, dict]:
    """Uma linha por papel: `TICKER [classe] [nome livre]`. `#` comenta."""
    out: dict[str, dict] = {}
    if not caminho.exists():
        return out
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.split("#", 1)[0].strip()
        if not linha:
            continue
        partes = linha.split(maxsplit=2)
        t = partes[0].upper()
        if not valido(t):
            log.warning("tickers_extras.txt: '%s' não parece código da B3; ignorado.", t)
            continue
        classe = partes[1].lower() if len(partes) > 1 else "acao"
        if classe not in ("acao", "fii", "etf", "bdr", "outro"):
            nome = " ".join(partes[1:])
            classe = "acao"
        else:
            nome = partes[2] if len(partes) > 2 else ""
        out[t] = {"nome": _nome(nome), "classe": classe}
    return out


def candidatos(publico: Path = C.PUBLICO, extras: Path = C.ARQ_EXTRAS
               ) -> dict[str, dict]:
    """{ticker -> {'nome', 'classe'}} de todas as fontes, sem rede."""
    out: dict[str, dict] = {}

    def por(t, nome, classe, sobrescrever=False):
        t = str(t or "").strip().upper().replace(".SA", "")
        if not valido(t):
            return
        if t in out and not sobrescrever:
            if not out[t]["nome"] and nome:
                out[t]["nome"] = _nome(nome)
            return
        out[t] = {"nome": _nome(nome), "classe": classe}

    dados = _ler(publico / "dados.json") or {}
    for e in (dados.get("empresas") or []) + (dados.get("excluidas") or []):
        por(e.get("ticker"), e.get("nome"), "acao")

    ibov = _ler(publico / "ibov_carteira.json") or {}
    for p in ibov.get("papeis") or []:
        por(p.get("ticker"), p.get("nome"), "acao")

    pvp = _ler(publico / "pvp_papeis.json") or {}
    for t, info in (pvp.get("papeis") or {}).items():
        por(t, (info or {}).get("nome"), "acao")

    # Irmãos de classe das ações: PETR3 ao lado de PETR4. Os que não existem
    # caem na coleta (o Yahoo não devolve nada) e ficam anotados.
    for t in list(out):
        if out[t]["classe"] != "acao":
            continue
        prefixo = t[:4]
        for suf in C.SUFIXOS_IRMAOS:
            irmao = prefixo + suf
            if irmao not in out:
                por(irmao, out[t]["nome"], "acao")

    # FII depois das ações, sobrescrevendo: um "XPML11" que viesse como irmão
    # de classe de alguma ação com o mesmo prefixo é FII, não unit.
    fiis = _ler(publico / "fiis.json") or {}
    for f in fiis.get("fundos") or []:
        por(f.get("ticker"), f.get("nome"), "fii", sobrescrever=True)

    for t, nome in C.ETFS.items():
        por(t, nome, "etf", sobrescrever=True)

    for t, info in ler_extras(extras).items():
        por(t, info["nome"], info["classe"], sobrescrever=True)

    log.info("Candidatos: %d (%d ações, %d FII, %d ETF, %d outros)", len(out),
             sum(v["classe"] == "acao" for v in out.values()),
             sum(v["classe"] == "fii" for v in out.values()),
             sum(v["classe"] == "etf" for v in out.values()),
             sum(v["classe"] not in ("acao", "fii", "etf") for v in out.values()))
    return out
