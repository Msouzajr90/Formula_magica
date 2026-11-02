# -*- coding: utf-8 -*-
"""Leitura e gravação da base em `web/public/precos/`.

    precos/indice.json   calendário de pregões + lista de ativos + referências
    precos/PETR4.json    {"t", "i0", "esc", "r": [inteiros]}
    precos/_IBOV.json    mesmo formato
    precos/_CDI.json     mesmo formato, escala 1e8

Um arquivo por papel para o navegador baixar só o que vai usar: uma carteira
de dez ações lê dez arquivos de ~30 KB, não a base inteira de ~10 MB.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import config as C


def caminho_serie(pasta: Path, nome: str) -> Path:
    return Path(pasta) / (nome if nome.endswith(".json") else f"{nome}.json")


def ler_json(caminho: Path) -> dict | None:
    try:
        return json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def gravar_se_mudou(caminho: Path, dados: dict, *, compacto: bool = True) -> bool:
    """Grava só se o conteúdo mudou — papel deslistado não gera commit diário."""
    caminho = Path(caminho)
    if compacto:
        texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    else:
        texto = json.dumps(dados, ensure_ascii=False, indent=1)
    if caminho.exists():
        try:
            if caminho.read_text(encoding="utf-8") == texto:
                return False
        except OSError:
            pass
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")
    return True


def serie(ticker: str, i0: int, r: list[int], escala: int = C.ESCALA) -> dict:
    return {"t": ticker, "i0": int(i0), "esc": int(escala), "r": [int(v) for v in r]}


def ler_serie(pasta: Path, nome: str) -> dict | None:
    d = ler_json(caminho_serie(pasta, nome))
    if not d or "r" not in d or "i0" not in d:
        return None
    return d


def ler_indice(pasta: Path) -> dict | None:
    return ler_json(Path(pasta) / C.ARQ_INDICE)


def gravar_indice(pasta: Path, indice: dict) -> bool:
    # O índice vai indentado de leve: é o arquivo que se abre para conferir à
    # mão, e o tamanho dele é dominado pelo calendário, não pela indentação.
    return gravar_se_mudou(Path(pasta) / C.ARQ_INDICE, indice, compacto=False)
