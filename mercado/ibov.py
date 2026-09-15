# -*- coding: utf-8 -*-
"""Carteira teórica do Ibovespa, da B3.

A B3 serve a carteira por um endereço em que o parâmetro é um JSON em base64:

    /indexProxy/indexCall/GetPortfolioDay/<base64({"index":"IBOV",...})>

De cada papel interessam duas colunas:

  * `theoricalQty` — a quantidade teórica, já ajustada pelo free float. É ela
    que pondera o índice, e é por ela que o P/VP tem que ser somado: usar o
    capital total de cada empresa daria o P/VP do mercado, não o do índice.
  * `part` — a participação em %, usada só para dizer quanto da carteira o
    cálculo conseguiu cobrir.

A API de fundos listados da B3 já mudou de contrato sem aviso uma vez neste
projeto (respondia 200 com zero registros). Por isso há duas defesas: um
arquivo de carteira guardado no repositório, que vale quando a B3 não
responde, e uma conferência do tamanho — uma carteira com menos de 50 papéis
não é o Ibovespa, e é melhor parar do que publicar um índice pela metade.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

BASE = "https://sistemaswebb3-listados.b3.com.br/indexProxy/indexCall/GetPortfolioDay/"
MINIMO_DE_PAPEIS = 50


def _parametro(indice: str = "IBOV", pagina: int = 1, tamanho: int = 200) -> str:
    corpo = {"language": "pt-br", "pageNumber": pagina,
             "pageSize": tamanho, "index": indice, "segment": "1"}
    return base64.b64encode(json.dumps(corpo).encode()).decode()


def _numero(texto: str | None) -> float | None:
    """'478.975.645' e '0,523' no formato brasileiro -> float."""
    if texto is None:
        return None
    t = str(texto).strip().replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def ler_resposta(bruto: dict) -> dict:
    """JSON da B3 -> {'data': 'AAAA-MM-DD', 'papeis': [...]}"""
    cab = bruto.get("header") or {}
    linhas = bruto.get("results") or []

    data = None
    if cab.get("date"):                      # vem como '15/09/26'
        d, m, a = str(cab["date"]).split("/")
        data = f"20{a}-{m}-{d}" if len(a) == 2 else f"{a}-{m}-{d}"

    papeis = []
    for r in linhas:
        cod = str(r.get("cod") or "").strip().upper()
        if not cod:
            continue
        papeis.append({
            "ticker": cod,
            "nome": str(r.get("asset") or "").strip(),
            "tipo": " ".join(str(r.get("type") or "").split()),
            "part": _numero(r.get("part")),
            "qtd": _numero(r.get("theoricalQty")),
        })
    return {"data": data, "papeis": papeis}


def baixar(sessao=None, indice: str = "IBOV") -> dict:
    import requests

    s = sessao or requests
    r = s.get(BASE + _parametro(indice), timeout=90)
    r.raise_for_status()
    dados = ler_resposta(r.json())
    if len(dados["papeis"]) < MINIMO_DE_PAPEIS:
        raise RuntimeError(
            f"A B3 devolveu {len(dados['papeis'])} papéis para o {indice}. "
            "O índice tem por volta de 80 — a resposta veio vazia ou o contrato "
            "da API mudou. Não dá para publicar um P/VP de índice incompleto."
        )
    return dados


def carregar(caminho: Path | str) -> dict:
    return json.loads(Path(caminho).read_text(encoding="utf-8"))


def gravar(dados: dict, caminho: Path | str) -> None:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=1),
                       encoding="utf-8")


def baixar_ou_carregar(caminho: Path | str, sessao=None) -> tuple[dict, str]:
    """Tenta a B3; se falhar, usa o arquivo guardado. Diz qual dos dois usou."""
    try:
        dados = baixar(sessao)
        gravar(dados, caminho)
        return dados, "b3"
    except Exception as exc:                                   # noqa: BLE001
        if Path(caminho).exists():
            log.warning("B3 indisponível (%s); usando a carteira guardada.", exc)
            return carregar(caminho), "arquivo"
        raise
