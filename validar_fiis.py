# -*- coding: utf-8 -*-
"""Confere o fiis.json antes de publicar.

Roda no GitHub Actions logo depois do atualizar_fiis.py. Se o resultado vier
ruim, sai com erro e o robo para antes de sobrescrever o arquivo bom que ja
esta publicado. Melhor ficar com dado de ontem do que com dado quebrado.

Uso:
    python validar_fiis.py [caminho]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MIN_FUNDOS = 25
FRACAO_MINIMA_COM_INDICADOR = 0.80


def _preenchidos(fundos: list[dict], campo: str) -> float:
    if not fundos:
        return 0.0
    return sum(1 for f in fundos if f.get(campo) is not None) / len(fundos)


def main() -> int:
    caminho = Path(sys.argv[1] if len(sys.argv) > 1 else "web/public/fiis.json")

    if not caminho.exists():
        print(f"ERRO: {caminho} nao foi gerado.")
        return 1
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERRO: {caminho} nao e um JSON valido: {exc}")
        return 1

    fundos = d.get("fundos") or []
    meta = d.get("meta") or {}

    print(f"gerado em          : {meta.get('gerado_em', '?')}")
    print(f"competencia        : {meta.get('competencia_informe', '?')}")
    print(f"fundos no informe  : {meta.get('fundos_no_informe', '?')}")
    print(f"com codigo B3      : {meta.get('origem_ticker_b3', '?')}")
    print(f"elegiveis          : {len(fundos)}")
    print(f"excluidos          : {len(d.get('excluidos') or [])}")
    print(f"tamanho            : {caminho.stat().st_size / 1024:.0f} KB")

    problemas = []
    if meta.get("demo"):
        problemas.append("arquivo veio em modo demonstracao (numeros sorteados)")
    if len(fundos) < MIN_FUNDOS:
        problemas.append(f"so {len(fundos)} fundos elegiveis (minimo {MIN_FUNDOS})")

    # Um indicador vazio na maioria das linhas quase sempre significa que a CVM
    # renomeou a coluna de origem. Isso nao levanta excecao em lugar nenhum: o
    # arquivo sai completo, com a coluna toda em branco. Daí a checagem aqui.
    for campo, rotulo in (("preco", "preco"), ("pvp", "P/VP"),
                          ("dy12m", "dividend yield"), ("pl", "patrimonio"),
                          ("liquidez", "liquidez"), ("consistencia", "consistencia")):
        frac = _preenchidos(fundos, campo)
        print(f"  {rotulo:16s}: {frac * 100:5.1f}% preenchido")
        if frac < FRACAO_MINIMA_COM_INDICADOR:
            problemas.append(
                f"{rotulo} preenchido em so {frac * 100:.0f}% dos fundos "
                f"(minimo {FRACAO_MINIMA_COM_INDICADOR * 100:.0f}%) — "
                "provavel mudanca de coluna na CVM; rode verificar_fiis.py --colunas")

    negativos = [f["ticker"] for f in fundos
                 if (f.get("pvp") or 1) <= 0 or (f.get("preco") or 1) <= 0]
    if negativos:
        problemas.append(f"preco ou P/VP nao positivo em {negativos[:5]}")

    absurdos = [f["ticker"] for f in fundos if (f.get("dy12m") or 0) > 0.60]
    if len(absurdos) > 3:
        problemas.append(f"{len(absurdos)} fundos com DY acima de 60% ao ano — "
                         f"provavel erro de preco ou de provento: {absurdos[:5]}")

    if problemas:
        print("\nFALHOU. Nao vou publicar por cima do arquivo bom:")
        for p in problemas:
            print(f"  - {p}")
        return 1

    print("\nOK: dados validos, pode publicar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
