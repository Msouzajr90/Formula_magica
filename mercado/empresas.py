# -*- coding: utf-8 -*-
"""Mapa prefixo do ticker -> código CVM, para ligar a carteira ao patrimônio.

O `fundamentos.json` é indexado por código CVM e não carrega ticker nenhum; a
carteira do Ibovespa só tem ticker. Sem este mapa não há P/VP.

Por que não usar `magicb3.tickers.baixar_empresas_b3`
----------------------------------------------------
Ele existe e faz quase isto, mas depende de pandas, de parquet e do cache em
disco do pipeline de ações — peso que esta aba não precisa carregar para
montar um dicionário de 500 entradas. Aqui é requests e um `dict`.

As duas regras de filtragem, porém, são a mesma, e precisam continuar sendo:
quatro caracteres alfanuméricos começando por letra (o padrão real dos códigos
de negociação da B3) e fora os BDR. Quem usava `[A-Z]{4}` — quatro LETRAS —
derrubava a B3 S.A., prefixo `B3SA`, 3,3% do Ibovespa. Esta aba nasceu com a
regra certa; o caminho das ações foi corrigido em 15/09/2026, em
`magicb3/tickers.py`, e os testes em `tests/test_prefixos_b3.py` existem para
que ninguém reaperte a regra de novo.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

URL = ("https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy"
       "/CompanyCall/GetInitialCompanies/{p}")
PREFIXO = re.compile(r"^[A-Z][A-Z0-9]{3}$")


def _pagina(sessao, pagina: int, tamanho: int = 120) -> dict:
    p = base64.b64encode(json.dumps(
        {"language": "pt-br", "pageNumber": pagina, "pageSize": tamanho}
    ).encode()).decode()
    r = sessao.get(URL.format(p=p), timeout=120,
                   headers={"Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def ler_empresas(linhas: list[dict]) -> dict[str, int]:
    mapa: dict[str, int] = {}
    for r in linhas:
        pref = str(r.get("issuingCompany") or "").strip().upper()
        if not PREFIXO.match(pref) or pref in mapa:
            continue
        bdr = str(r.get("typeBDR") or "").strip()
        if bdr:                       # BDR tem lastro estrangeiro, sem DFP na CVM
            continue
        try:
            mapa[pref] = int(r["codeCVM"])
        except (KeyError, TypeError, ValueError):
            continue
    return mapa


def baixar_mapa(sessao) -> dict[str, int]:
    linhas, pagina, total = [], 1, 1
    while pagina <= total:
        js = _pagina(sessao, pagina)
        linhas.extend(js.get("results") or [])
        total = (js.get("page") or {}).get("totalPages", 1)
        pagina += 1
    mapa = ler_empresas(linhas)
    log.info("B3: %d emissores -> %d prefixos com código CVM", len(linhas), len(mapa))
    return mapa


def gravar(mapa: dict[str, int], caminho: Path | str) -> None:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(mapa, indent=0, sort_keys=True), encoding="utf-8")


def baixar_ou_carregar(caminho: Path | str, sessao) -> tuple[dict[str, int], str]:
    """Mesma defesa da carteira: um mapa de ontem vale muito mais que nenhum.

    Os prefixos da B3 mudam devagar — uma indisponibilidade da API não deve
    custar o indicador do dia."""
    try:
        mapa = baixar_mapa(sessao)
        if len(mapa) < 200:
            raise RuntimeError(f"só {len(mapa)} prefixos; a resposta veio curta")
        gravar(mapa, caminho)
        return mapa, "b3"
    except Exception as exc:                                   # noqa: BLE001
        if Path(caminho).exists():
            log.warning("Mapa da B3 indisponível (%s); usando o guardado.", exc)
            return {k: int(v) for k, v in
                    json.loads(Path(caminho).read_text(encoding="utf-8")).items()}, "arquivo"
        raise
