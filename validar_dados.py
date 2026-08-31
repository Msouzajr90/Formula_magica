# -*- coding: utf-8 -*-
"""Confere o dados.json antes de publicar.

Roda no GitHub Actions logo depois do atualizar_dados.py. Se o resultado vier
ruim, sai com erro e o robô para antes de sobrescrever o arquivo bom que já
está publicado. Melhor ficar com dado de ontem do que com dado quebrado.

Uso:
    python validar_dados.py [caminho]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

MIN_EMPRESAS = 15
MIN_COM_PRECO = 10


def main() -> int:
    caminho = Path(sys.argv[1] if len(sys.argv) > 1 else "web/public/dados.json")

    if not caminho.exists():
        print(f"ERRO: {caminho} nao foi gerado.")
        return 1

    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERRO: {caminho} nao e um JSON valido: {exc}")
        return 1

    empresas = d.get("empresas") or []
    tickers = (d.get("estatisticas") or {}).get("tickers") or []
    meta = d.get("meta") or {}
    modo = str((meta.get("diagnostico") or {}).get("modo", ""))

    print(f"gerado em     : {meta.get('geradoEm', '?')}")
    print(f"empresas      : {len(empresas)}")
    print(f"com preco     : {len(tickers)}")
    print(f"tamanho       : {caminho.stat().st_size / 1024:.0f} KB")
    print(f"metodo EY     : {meta.get('baseEy', '?')}")
    print(f"metodo ROIC   : {meta.get('baseRoic', '?')}")

    problemas = []
    if modo.upper().startswith("DEMONSTRA"):
        problemas.append("arquivo veio em modo demonstracao (dados sinteticos)")
    if len(empresas) < MIN_EMPRESAS:
        problemas.append(f"so {len(empresas)} empresas (minimo {MIN_EMPRESAS})")
    if len(tickers) < MIN_COM_PRECO:
        problemas.append(f"so {len(tickers)} com serie de precos (minimo {MIN_COM_PRECO})")

    cov = (d.get("estatisticas") or {}).get("cov") or []
    if cov and len(cov) != len(tickers):
        problemas.append("matriz de covariancia com tamanho incompativel")

    sem_preco = [e.get("ticker") for e in empresas[:30] if not e.get("preco")]
    if len(sem_preco) > 10:
        problemas.append(f"{len(sem_preco)} das 30 primeiras sem preco")

    if problemas:
        print("\nFALHOU. Nao vou publicar por cima do arquivo bom:")
        for p in problemas:
            print(f"  - {p}")
        print("\nVeja o passo 'Verificar as fontes de dados' acima no log.")
        return 1

    print("\nOK: dados validos, pode publicar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
