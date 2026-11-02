# -*- coding: utf-8 -*-
"""Confere a base de preços antes de o robô publicar.

Sai com código 1 se alguma coisa impede o uso (o robô não publica) e
com 0 se está boa — os avisos aparecem no log, mas não barram.

Uso:
    python validar_precos.py [pasta]          # padrão: web/public/precos
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np

from simulacao import arquivo, config as C, series as S


def conferir(pasta: Path, hoje: date | None = None) -> tuple[list[str], list[str]]:
    """(erros, avisos)."""
    hoje = hoje or C.hoje()
    erros, avisos = [], []
    ind = arquivo.ler_indice(pasta)
    if not ind:
        return [f"{pasta / C.ARQ_INDICE} não existe ou não é JSON"], avisos

    if ind.get("demo"):
        erros.append("a base é de DEMONSTRAÇÃO (números inventados) — não publicar")

    pregoes = ind.get("pregoes") or []
    if len(pregoes) < 500:
        erros.append(f"calendário com {len(pregoes)} pregões; esperava milhares")
    if pregoes != sorted(set(pregoes)):
        erros.append("calendário fora de ordem ou com data repetida")
    fds = [d for d in pregoes if date.fromisoformat(d).weekday() >= 5]
    if fds:
        erros.append(f"{len(fds)} pregões caem em fim de semana (ex.: {fds[0]})")
    if pregoes:
        idade = (hoje - date.fromisoformat(pregoes[-1])).days
        if idade > C.IDADE_MAXIMA_DIAS:
            erros.append(f"o último pregão é de {pregoes[-1]} — {idade} dias atrás")

    def conferir_serie(nome: str, arq: str, e: dict, esc_esperada: int) -> np.ndarray | None:
        s = arquivo.ler_serie(pasta, arq)
        if s is None:
            erros.append(f"{nome}: arquivo {arq} não existe ou está corrompido")
            return None
        if s["i0"] != e.get("i0") or len(s["r"]) != e.get("n"):
            erros.append(f"{nome}: índice diz i0={e.get('i0')}, n={e.get('n')}; "
                         f"arquivo tem i0={s['i0']}, n={len(s['r'])}")
        if s.get("esc") != esc_esperada:
            erros.append(f"{nome}: escala {s.get('esc')}, esperava {esc_esperada}")
        if s["i0"] < 1 or s["i0"] + len(s["r"]) > len(pregoes):
            erros.append(f"{nome}: série fora do calendário")
            return None
        if any(not isinstance(v, int) for v in s["r"][:50]):
            erros.append(f"{nome}: retornos não são inteiros")
            return None
        return np.asarray(s["r"], float) / esc_esperada

    bench = ind.get("bench") or {}
    for chave, esc in (("IBOV", C.ESCALA), ("CDI", C.ESCALA_CDI)):
        if chave not in bench:
            erros.append(f"falta a referência {chave}")
            continue
        r = conferir_serie(chave, bench[chave]["arquivo"], bench[chave], esc)
        if r is None:
            continue
        fim = bench[chave]["i0"] + len(r) - 1
        atraso = len(pregoes) - 1 - fim
        if chave == "IBOV" and atraso != 0:
            erros.append(f"Ibovespa termina {atraso} pregões antes do calendário")
        if chave == "CDI":
            if atraso > 5:
                erros.append(f"CDI parado há {atraso} pregões")
            elif atraso > 0:
                avisos.append(f"CDI {atraso} pregão(ões) atrás do calendário")
            a12 = S.anualizado(r[-252:])
            if not (0.005 <= a12 <= 0.40):
                erros.append(f"CDI dos últimos 12 meses = {a12:.2%}: fora de 0,5%–40%")
            if np.any(r < 0) or np.any(r > 0.002):
                erros.append("CDI com taxa diária negativa ou acima de 0,2% ao dia")
        if chave == "IBOV" and np.any(np.abs(r) > 0.25):
            erros.append("Ibovespa com variação diária acima de 25%")

    ativos = ind.get("ativos") or []
    if len(ativos) < C.MINIMO_ATIVOS and not ind.get("demo"):
        erros.append(f"só {len(ativos)} ativos na base (mínimo {C.MINIMO_ATIVOS})")
    vistos, atualizados = set(), 0
    for e in ativos:
        t = e.get("t", "?")
        if t in vistos:
            erros.append(f"{t} aparece duas vezes no índice")
        vistos.add(t)
        r = conferir_serie(t, t, e, C.ESCALA)
        if r is None:
            continue
        if e["i0"] + e["n"] == len(pregoes):
            atualizados += 1
        if np.any(r <= -1.0):
            erros.append(f"{t}: retorno de −100% ou pior")
        if e.get("liqMax") is None or e["liqMax"] < C.LIQUIDEZ_MINIMA:
            avisos.append(f"{t}: liquidez máxima {e.get('liqMax')} abaixo do corte")
        if e.get("saltos"):
            avisos.append(f"{t}: {len(e['saltos'])} pregão(ões) com variação acima de "
                          f"{C.SALTO_SUSPEITO:.0%} (ex.: {e['saltos'][0][0]} {e['saltos'][0][1]:+.0%})")
    if ativos:
        frac = atualizados / len(ativos)
        if frac < C.FRACAO_MINIMA_ATUALIZADA and not ind.get("demo"):
            erros.append(f"só {frac:.0%} dos ativos chegam ao último pregão "
                         f"(mínimo {C.FRACAO_MINIMA_ATUALIZADA:.0%})")
        elif frac < 1:
            avisos.append(f"{len(ativos) - atualizados} ativo(s) não chegam ao último "
                          "pregão (deslistados ou sem negócio recente)")

    arquivos = {p.stem for p in Path(pasta).glob("*.json")} - {"indice", "_IBOV", "_CDI"}
    orfaos = sorted(arquivos - vistos)
    if orfaos:
        avisos.append(f"{len(orfaos)} arquivo(s) sem entrada no índice: {', '.join(orfaos[:10])}")
    return erros, avisos


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    pasta = Path(argv[0]) if argv else C.PASTA_PRECOS
    erros, avisos = conferir(pasta)
    ind = arquivo.ler_indice(pasta) or {}
    print(f"Base: {len(ind.get('ativos') or [])} ativos, "
          f"{len(ind.get('pregoes') or [])} pregões "
          f"({(ind.get('pregoes') or ['—'])[0]} a {(ind.get('pregoes') or ['—'])[-1]})")
    for a in avisos[:40]:
        print("aviso:", a)
    if len(avisos) > 40:
        print(f"aviso: … e mais {len(avisos) - 40}")
    for e in erros:
        print("ERRO:", e)
    print("OK" if not erros else f"{len(erros)} erro(s) — não publicar")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
