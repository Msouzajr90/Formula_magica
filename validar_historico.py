# -*- coding: utf-8 -*-
"""Confere o historico.json antes de publicar.

Mesma ideia do validar_dados.py: melhor manter o arquivo antigo do que
sobrescrever com um histórico incompleto, que produziria um backtest bonito
e falso no site.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MIN_REBALANCES = 3
MIN_TICKERS = 15
MIN_PREGOES = 200


def main() -> int:
    caminho = Path(sys.argv[1] if len(sys.argv) > 1 else "web/public/historico.json")
    if not caminho.exists():
        print(f"ERRO: {caminho} nao foi gerado.")
        return 1
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERRO: JSON invalido: {exc}")
        return 1

    meta = d.get("meta") or {}
    reb = d.get("rebalances") or []
    ret = d.get("retornos") or {}
    pregoes = d.get("pregoes") or []
    bench = d.get("benchmark") or []

    print(f"gerado em   : {meta.get('geradoEm', '?')}")
    print(f"periodo     : {meta.get('inicio')} a {meta.get('fim')}")
    print(f"rebalances  : {len(reb)}")
    print(f"tickers     : {len(ret)}")
    print(f"pregoes     : {len(pregoes)}")
    print(f"tamanho     : {caminho.stat().st_size / 1024:.0f} KB")

    problemas = []
    if str(meta.get("modo", "")).upper().startswith("DEMONSTRA"):
        problemas.append("arquivo veio em modo demonstracao (dados sinteticos)")
    if len(reb) < MIN_REBALANCES:
        problemas.append(f"so {len(reb)} rebalanceamentos (minimo {MIN_REBALANCES})")
    if len(ret) < MIN_TICKERS:
        problemas.append(f"so {len(ret)} tickers (minimo {MIN_TICKERS})")
    if len(pregoes) < MIN_PREGOES:
        problemas.append(f"so {len(pregoes)} pregoes (minimo {MIN_PREGOES})")
    if len(bench) != len(pregoes):
        problemas.append("benchmark com tamanho diferente da serie de pregoes")

    for nome, serie in list(ret.items())[:2000]:
        if len(serie) != len(pregoes):
            problemas.append(f"serie de {nome} com tamanho incompativel")
            break

    vazios = [r["data"] for r in reb if not r.get("acoes")]
    if vazios:
        problemas.append(f"rebalanceamentos sem ranking: {vazios[:5]}")

    if not meta.get("pointInTime"):
        problemas.append("arquivo nao declara pointInTime — o backtest seria enviesado")

    if problemas:
        print("\nFALHOU. Nao vou publicar por cima do arquivo bom:")
        for p in problemas:
            print(f"  - {p}")
        return 1

    print("\nOK: historico valido, pode publicar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
