# -*- coding: utf-8 -*-
"""Monta o `mercado.json` que a aba de indicadores consome.

Uma foto por data (hoje, uma semana, um mês, seis meses) e, dentro de cada
foto, as quatro curvas e os dois spreads já calculados. O site é estático: ele
desenha o que está aqui e não recalcula nada — diferente das abas de ações e
FIIs, onde o navegador refaz o ranking. Aqui não há parâmetro para o usuário
mexer, então pré-calcular é mais simples e o arquivo fica pequeno.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path

from . import curvas, tesouro, treasury

VERSAO = 1
NOMES = {"hoje": "hoje", "semana": "1 semana atrás",
         "mes": "1 mês atrás", "semestre": "6 meses atrás"}


def _n(x, casas: int = 4):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(v) or math.isinf(v)) else round(v, casas)


def _pontos(vertices: list[tesouro.Vertice]) -> list[tuple[float, float]]:
    return [(v.prazo, v.taxa) for v in vertices]


def montar_juros(td, us_nominal, us_real, hoje: date | None = None) -> dict:
    """`td` é a tabela do Tesouro; `us_*` as do Treasury já lidas."""
    datas = tesouro.fotos(td, hoje)
    series = {}

    for chave, dia in datas.items():
        pre = tesouro.curva(td, "pre", dia)
        ipca = tesouro.curva(td, "ipca", dia)
        eua = treasury.curva(us_nominal, dia)
        tips = treasury.curva(us_real, dia)

        g_pre = curvas.na_grade(_pontos(pre))
        g_ipca = curvas.na_grade(_pontos(ipca))
        g_eua = curvas.na_grade(eua)
        g_tips = curvas.na_grade(tips)

        series[chave] = {
            "rotulo": NOMES.get(chave, chave),
            "dataBR": dia.isoformat(),
            "dataEUA": (treasury.data_efetiva(us_nominal, dia) or dia).isoformat(),
            "pre": {"pontos": [v.como_dict() for v in pre],
                    "grade": [_n(x, 3) for x in g_pre],
                    "alcance": curvas.alcance(_pontos(pre))},
            "ipca": {"pontos": [v.como_dict() for v in ipca],
                     "grade": [_n(x, 3) for x in g_ipca],
                     "alcance": curvas.alcance(_pontos(ipca))},
            "eua": {"pontos": [[_n(p, 3), _n(t, 3)] for p, t in eua],
                    "grade": [_n(x, 3) for x in g_eua],
                    "alcance": curvas.alcance(eua)},
            "tips": {"pontos": [[_n(p, 3), _n(t, 3)] for p, t in tips],
                     "grade": [_n(x, 3) for x in g_tips],
                     "alcance": curvas.alcance(tips)},
            "spreadNominal": [_n(x, 3) for x in curvas.diferenca(g_pre, g_eua)],
            "spreadReal": [_n(x, 3) for x in curvas.diferenca(g_ipca, g_tips)],
        }

    return {"grade": curvas.GRADE, "datas": {k: v.isoformat() for k, v in datas.items()},
            "series": series,
            "verticesNominais": [2.0, 5.0, 10.0],
            "verticesReais": [5.0, 10.0, 20.0]}


def montar_pvp(resultado, quando: date, origem_carteira: str,
               historico: list[list] | None = None,
               data_carteira: str | None = None) -> dict:
    if resultado is None:
        return {"atual": None, "historico": historico or [], "empresas": []}
    return {
        "atual": {
            "data": quando.isoformat(),
            "valor": _n(resultado.pvp, 4),
            "valorMercado": _n(resultado.valor_mercado, 0),
            "patrimonio": _n(resultado.patrimonio, 0),
            "cobertura": _n(resultado.cobertura, 4),
            "nComDado": resultado.n_com_dado,
            "nTotal": resultado.n_total,
            "faltando": resultado.faltando,
            "carteiraDe": origem_carteira,
            "dataCarteira": data_carteira,
        },
        "historico": historico or [],
        "empresas": [{"ticker": d["ticker"], "nome": d["nome"],
                      "peso": _n(d["peso"], 3), "pvp": _n(d["pvp"], 3),
                      "preco": _n(d["preco"], 2), "vpa": _n(d["vpa"], 4),
                      "dtBalanco": d.get("dtBalanco"),
                      # De onde veio o nº de ações: a tabela mostra, porque é
                      # a informação que diz quanto confiar naquela linha.
                      "fonteAcoes": d.get("fonteAcoes")}
                     for d in resultado.detalhe],
    }


def montar(juros: dict, pvp: dict, *, demo: bool = False,
           avisos: list[str] | None = None) -> dict:
    return {
        "meta": {
            "versao": VERSAO,
            "geradoEm": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "demo": demo,
            "avisos": avisos or [],
            "fontes": {
                "jurosBR": "Tesouro Transparente — taxas dos títulos ofertados "
                           "pelo Tesouro Direto",
                "jurosEUA": "U.S. Department of the Treasury — daily par yield "
                            "curve (nominal e TIPS)",
                "carteira": "B3 — carteira teórica do Ibovespa",
                "patrimonio": "CVM — DFP e ITR, via fundamentos.json",
            },
        },
        "juros": juros,
        "pvp": pvp,
    }


def gravar(dados: dict, caminho: Path | str) -> Path:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
    return caminho


def carregar_historico_pvp(caminho: Path | str) -> list[list]:
    """Série de P/VP já gravada. Some sem reclamar se ainda não existir."""
    p = Path(caminho)
    if not p.exists():
        return []
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        return []
    if isinstance(dados, dict):
        dados = dados.get("serie") or []
    return [[str(d), float(v)] for d, v in dados
            if v is not None and not math.isnan(float(v))]


def juntar_historico(serie: list[list], quando: date, valor: float | None
                     ) -> list[list]:
    """Acrescenta o ponto do dia, substituindo o que já houver na mesma data."""
    if valor is None:
        return serie
    d = quando.isoformat()
    por_data = {str(x[0]): float(x[1]) for x in serie}
    por_data[d] = float(valor)
    return [[k, round(v, 4)] for k, v in sorted(por_data.items())]
