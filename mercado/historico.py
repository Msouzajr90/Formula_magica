# -*- coding: utf-8 -*-
"""Spread Brasil × EUA ao longo do tempo, um ponto por pregão desde 2004.

A aba já mostrava a diferença de juros prazo a prazo num dia. Isto é a outra
metade: a diferença num prazo fixo, dia a dia, desde que o dado existe.

Sai de graça das mesmas duas fontes. O CSV do Tesouro Transparente tem 21 anos
num arquivo só, e o Treasury publica um CSV por ano desde 1990 — não há nada a
guardar entre execuções, a série é recalculada inteira toda vez. Isso também
quer dizer que ela se conserta sozinha: um erro corrigido no cálculo reescreve
o passado todo na execução seguinte, em vez de ficar preso num arquivo
acumulado.

Onde cada linha começa
----------------------
Não é o mesmo ponto para todas, e isso é dado, não defeito:

  * o prefixado do Tesouro Direto começa em dez/2004;
  * a NTN-B aparece em 2005;
  * o TIPS de 20 anos só existe a partir de 2004 (o Treasury interrompeu a
    série de 30 anos entre 2002 e 2006);
  * e o vértice de 20 anos do lado brasileiro só existe em NTN-B — não há, e
    nunca houve, prefixado tão longo.

Cada série começa onde os dois lados dela existem, e `None` antes disso.

Custo
-----
Percorrer 5.000 pregões refazendo a curva em cada um é a parte cara da coleta
diária (dezenas de segundos). Por isso as tabelas são indexadas por data uma
vez só, antes do laço — sem isso são minutos, e o robô tem um teto de tempo.
"""
from __future__ import annotations

import logging
from bisect import bisect_right
from datetime import date

from . import curvas, tesouro, treasury

log = logging.getLogger(__name__)

# Vértices da série no tempo. O de 20 anos existe só do lado real: não há
# prefixado brasileiro de 20 anos, então o spread nominal ali seria inventado.
VERTICES_NOMINAIS = (2.0, 5.0, 10.0)
VERTICES_REAIS = (5.0, 10.0, 20.0)


def _indexar_tesouro(td) -> dict[date, dict[str, list[tuple[float, float]]]]:
    """{data -> {familia -> [(prazo, taxa)]}}, já ordenado e sem duplicatas.

    Repete a regra de `tesouro.curva` — zero-cupom na frente, prazo mínimo por
    família — mas de uma vez para todas as datas. Chamar `tesouro.curva` num
    laço de 5.000 datas filtra a tabela inteira 5.000 vezes.
    """
    import pandas as pd

    saida: dict[date, dict[str, list[tuple[float, float]]]] = {}
    # False (zero-cupom) antes de True: o `drop_duplicates` abaixo fica com o
    # primeiro, e é o zero-cupom que queremos.
    td = td.sort_values(["DATA", "FAMILIA", "VENCIMENTO", "CUPOM"])
    td = td.drop_duplicates(subset=["DATA", "FAMILIA", "VENCIMENTO"], keep="first")

    dias = td["DATA"].dt.date.to_numpy()
    familias = td["FAMILIA"].to_numpy()
    vencs = td["VENCIMENTO"].dt.date.to_numpy()
    taxas = td["TAXA"].to_numpy()

    for dia, fam, venc, taxa in zip(dias, familias, vencs, taxas):
        prazo = (venc - dia).days / tesouro.DIAS_NO_ANO
        if prazo < tesouro.PRAZO_MINIMO.get(fam, 0.25):
            continue
        saida.setdefault(dia, {}).setdefault(fam, []).append((prazo, float(taxa)))

    for por_familia in saida.values():
        for pontos in por_familia.values():
            pontos.sort()
    return saida


def _indexar_treasury(df) -> tuple[list[date], dict[date, list[tuple[float, float]]]]:
    por_data: dict[date, list[tuple[float, float]]] = {}
    for d, prazo, taxa in zip(df["DATA"].dt.date.to_numpy(),
                              df["PRAZO"].to_numpy(), df["TAXA"].to_numpy()):
        por_data.setdefault(d, []).append((float(prazo), float(taxa)))
    for pontos in por_data.values():
        pontos.sort()
    return sorted(por_data), por_data


def _ultimo_ate(datas: list[date], alvo: date) -> date | None:
    """Último pregão americano até a data brasileira.

    Os feriados não coincidem — 7 de setembro fecha o Brasil e não os Estados
    Unidos, o Memorial Day o contrário. Casar por data exata abriria buracos
    na série que não são do mercado, são do calendário.
    """
    i = bisect_right(datas, alvo)
    return datas[i - 1] if i else None


def serie(td, us_nominal, us_real, *, desde: date | None = None,
          progresso=None) -> dict:
    """Spread por pregão. Devolve datas e uma lista por vértice.

    O valor é `None` no dia em que faltar qualquer um dos dois lados — nunca
    zero, e nunca o último valor repetido. Uma série de spread com o valor de
    ontem carregado para a frente parece estabilidade e é ausência de dado.
    """
    por_dia = _indexar_tesouro(td)
    datas_nom, nom_por_data = _indexar_treasury(us_nominal)
    datas_real, real_por_data = _indexar_treasury(us_real)

    dias = sorted(d for d in por_dia if desde is None or d >= desde)
    log.info("Spread histórico: %d pregões, de %s a %s",
             len(dias), dias[0] if dias else "—", dias[-1] if dias else "—")

    saida_datas: list[str] = []
    nominal = {v: [] for v in VERTICES_NOMINAIS}
    real = {v: [] for v in VERTICES_REAIS}
    brasil_pre = {v: [] for v in VERTICES_NOMINAIS}
    brasil_ntnb = {v: [] for v in VERTICES_REAIS}

    for n, dia in enumerate(dias):
        if progresso and n % 250 == 0:
            progresso(n / len(dias), f"{dia}")

        fam = por_dia[dia]
        pre = fam.get("pre") or []
        ipca = fam.get("ipca") or []

        d_nom = _ultimo_ate(datas_nom, dia)
        d_real = _ultimo_ate(datas_real, dia)
        us_n = nom_por_data.get(d_nom, []) if d_nom else []
        us_r = real_por_data.get(d_real, []) if d_real else []

        saida_datas.append(dia.isoformat())
        for v in VERTICES_NOMINAIS:
            a = curvas.interpolar(pre, v)
            b = curvas.interpolar(us_n, v)
            brasil_pre[v].append(None if a is None else round(a, 3))
            nominal[v].append(None if (a is None or b is None) else round(a - b, 3))
        for v in VERTICES_REAIS:
            a = curvas.interpolar(ipca, v)
            b = curvas.interpolar(us_r, v)
            brasil_ntnb[v].append(None if a is None else round(a, 3))
            real[v].append(None if (a is None or b is None) else round(a - b, 3))

    return {
        "datas": saida_datas,
        "nominal": {str(v): nominal[v] for v in VERTICES_NOMINAIS},
        "real": {str(v): real[v] for v in VERTICES_REAIS},
        # As curvas brasileiras sozinhas: o spread pode subir porque o Brasil
        # piorou ou porque os Estados Unidos melhoraram, e sem o nível de um
        # dos lados não dá para saber qual.
        "brasilPre": {str(v): brasil_pre[v] for v in VERTICES_NOMINAIS},
        "brasilNtnb": {str(v): brasil_ntnb[v] for v in VERTICES_REAIS},
        "verticesNominais": [str(v) for v in VERTICES_NOMINAIS],
        "verticesReais": [str(v) for v in VERTICES_REAIS],
    }


def resumo(s: dict) -> dict:
    """Primeiro e último valor de cada série, e quantos dias têm dado.

    É o que o `validar_mercado.py` olha: uma série que ficou vazia, ou que
    começa num ano impossível, aparece aqui sem precisar abrir o gráfico.
    """
    out = {}
    for grupo in ("nominal", "real"):
        for v, vals in (s.get(grupo) or {}).items():
            com = [(d, x) for d, x in zip(s["datas"], vals) if x is not None]
            out[f"{grupo}{v}"] = {
                "n": len(com),
                "inicio": com[0][0] if com else None,
                "fim": com[-1][0] if com else None,
                "min": min(x for _, x in com) if com else None,
                "max": max(x for _, x in com) if com else None,
                "ultimo": com[-1][1] if com else None,
            }
    return out
