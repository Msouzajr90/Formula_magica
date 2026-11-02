# -*- coding: utf-8 -*-
"""Gera e atualiza a base de preços da aba Simulação (web/public/precos/).

Roda no GitHub Actions (o Yahoo e o Banco Central respondem de fora do
Brasil). A primeira execução baixa tudo desde 2010; as seguintes só emendam
os pregões novos.

Uso:
    python atualizar_precos.py                # incremental (ou completo, se não houver base)
    python atualizar_precos.py --completo     # rebaixa tudo desde 2010
    python atualizar_precos.py --demo         # base inventada, para ver o site sem coletar
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from simulacao import arquivo, base, config as C, demo


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--completo", action="store_true",
                    help="rebaixa o histórico inteiro de todos os papéis")
    ap.add_argument("--demo", action="store_true",
                    help="grava uma base inventada, marcada como demonstração")
    ap.add_argument("--pasta", default=str(C.PASTA_PRECOS))
    ap.add_argument("--hoje", default=None, help="AAAA-MM-DD (para testes)")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                        datefmt="%H:%M:%S")
    hoje = date.fromisoformat(a.hoje) if a.hoje else C.hoje()
    pasta = Path(a.pasta)

    if a.demo:
        rel = base.atualizar(pasta, completo=True, hoje=hoje,
                             fontes=demo.fontes_falsas(hoje),
                             candidatos=demo.candidatos_demo())
        indice = arquivo.ler_indice(pasta)
        indice["demo"] = True
        indice["avisos"] = ["DEMONSTRAÇÃO: números inventados, não use para decidir nada."]
        arquivo.gravar_indice(pasta, indice)
    else:
        rel = base.atualizar(pasta, completo=a.completo, hoje=hoje)

    print(rel.texto())
    return 0


if __name__ == "__main__":
    sys.exit(main())
