# -*- coding: utf-8 -*-
r"""Gera um `spread_historico.json` de MENTIRA, para ver a tela.

Existe por um motivo só: o ambiente da sessão não alcança o Tesouro nem o
Treasury, e eu não quero descobrir um erro de JavaScript depois de o Marco
esperar meia hora de coleta. Este arquivo tem a forma exata do de verdade.

O que aqui é REAL:
  * a meta Selic, dia a dia, reconstruída dos 120 degraus que o SGS 432
    devolve desde dez/2004 — então as faixas de ciclo do gráfico são as
    faixas de verdade;
  * o dólar e o Focus, interpolados de âncoras trimestrais verdadeiras.

O que é inventado: as curvas de NTN-B, TIPS e prefixado. São passeios
aleatórios com âncoras plausíveis, só para haver linha na tela.

    python tests/fixture_spread.py            # grava em web/public/
    python tests/fixture_spread.py --saida x.json

NUNCA rode isto contra um arquivo que vá ser publicado. O `validar_mercado.py`
não olha para o `spread_historico.json`, então não há rede de proteção aqui
além desta frase.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from mercado import bcb, historico          # noqa: E402

DADOS = Path(__file__).parent / "dados_bcb_reais.json"


def _br(d: str) -> date:
    return date(*reversed([int(x) for x in d.split("/")]))


def diario_degraus(pares, fim):
    """Degrau vale até o próximo: é assim que a meta Selic funciona."""
    saida, i, d = {}, 0, pares[0][0]
    while d <= fim:
        while i + 1 < len(pares) and pares[i + 1][0] <= d:
            i += 1
        saida[d] = pares[i][1]
        d += timedelta(days=1)
    return saida


def diario_interpolado(pares, fim):
    """Reta entre âncoras — o dólar e o Focus andam todo dia, não em degrau."""
    saida = {}
    for (d0, v0), (d1, v1) in zip(pares, pares[1:]):
        n = (d1 - d0).days or 1
        for k in range(n):
            saida[d0 + timedelta(days=k)] = v0 + (v1 - v0) * k / n
    d = pares[-1][0]
    while d <= fim:
        saida[d] = pares[-1][1]
        d += timedelta(days=1)
    return saida


def passeio(dias, inicio, fim_alvo, vol, piso=None, teto=None, semente=7):
    """Passeio aleatório que chega perto de `fim_alvo`, para a linha ter cara."""
    r = random.Random(semente)
    n = len(dias)
    v, saida = inicio, []
    for i in range(n):
        alvo = inicio + (fim_alvo - inicio) * (i / max(n - 1, 1))
        v += r.gauss(0, vol) + 0.02 * (alvo - v)
        if piso is not None:
            v = max(v, piso)
        if teto is not None:
            v = min(v, teto)
        saida.append(round(v, 3))
    return saida


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default=str(RAIZ / "web" / "public" / "spread_historico.json"))
    args = ap.parse_args(argv)

    reais = json.loads(DADOS.read_text(encoding="utf-8"))
    fim = date.fromisoformat(reais["ate"])

    selic = diario_degraus([(_br(d), v) for d, v in reais["selicDegraus"]], fim)
    dolar = diario_interpolado([(_br(d), v) for d, v in reais["dolarTrimestral"]], fim)
    focus = diario_interpolado([(date.fromisoformat(d), v)
                                for d, v in reais["focusTrimestral"]], fim)

    # Só dias úteis, como o Tesouro publica.
    dias = []
    d = min(selic)
    while d <= fim:
        if d.weekday() < 5:
            dias.append(d)
        d += timedelta(days=1)
    datas = [x.isoformat() for x in dias]

    # Curvas inventadas, com âncoras plausíveis (NTN-B 10a foi de ~8% em 2005
    # a 7,6% hoje, passando por 4,5% em 2020; TIPS 10a de 2% a 2,6%).
    ntnb = {"5.0": passeio(dias, 8.6, 7.4, .035, 2.5, 12, 1),
            "10.0": passeio(dias, 8.2, 7.6, .030, 2.5, 12, 2),
            "20.0": passeio(dias, 8.0, 7.5, .026, 2.5, 12, 3)}
    tips = {"5.0": passeio(dias, 1.6, 2.4, .022, -2.5, 4.5, 4),
            "10.0": passeio(dias, 2.0, 2.6, .020, -2.5, 4.5, 5),
            "20.0": passeio(dias, 2.3, 2.9, .018, -2.5, 4.5, 6)}
    pre = {"1.0": [round(selic[x] + random.Random(9 + i).gauss(0, .25), 3)
                   for i, x in enumerate(dias)],
           "2.0": passeio(dias, 17.6, 13.6, .05, 3, 22, 10),
           "5.0": passeio(dias, 16.5, 14.0, .05, 3, 22, 11),
           "10.0": passeio(dias, 15.5, 14.4, .05, 3, 22, 12)}
    us_nom = {"1.0": passeio(dias, 3.3, 4.4, .03, -0.2, 7, 13),
              "2.0": passeio(dias, 3.4, 4.7, .03, -0.2, 7, 14),
              "5.0": passeio(dias, 3.7, 4.8, .03, -0.2, 7, 15),
              "10.0": passeio(dias, 4.2, 5.0, .03, -0.2, 7, 16)}

    # Buracos onde o prefixado longo não existia — a série de verdade os tem.
    for i, x in enumerate(dias):
        if x.year < 2010:
            pre["10.0"][i] = None
        elif x.year < 2013 and i % 3:
            pre["10.0"][i] = None

    def menos(a, b):
        return [None if (p is None or q is None) else round(p - q, 3)
                for p, q in zip(a, b)]

    s = {
        # A marca que impede este arquivo de virar publicação por engano: a
        # tela mostra um aviso vermelho e o `validar_mercado.py` recusa o
        # arquivo com código 1. Sem isso, bastaria eu esquecer de apagar o
        # fixture uma vez para 21 anos de número inventado irem para o ar.
        "demo": True,
        "datas": datas,
        "nominal": {v: menos(pre[v], us_nom[v]) for v in pre},
        "real": {v: menos(ntnb[v], tips[v]) for v in ntnb},
        "brasilPre": pre,
        "brasilNtnb": ntnb,
        "euaNominal": us_nom,
        "euaReal": tips,
        "verticesNominais": list(pre),
        "verticesReais": list(ntnb),
    }
    s["dolar"] = [None if v is None else round(v, 4) for v in bcb.alinhar(dolar, dias)]
    meta = bcb.alinhar(selic, dias)
    s["selicMeta"] = meta
    s["ciclosSelic"] = bcb.ciclos_da_selic(datas, meta)
    exp = bcb.alinhar(focus, dias, tolerancia=bcb.TOLERANCIA_FOCUS)
    s["focusIpca12m"] = [None if v is None else round(v, 3) for v in exp]
    s["juroRealExAnte"] = bcb.juro_real_ex_ante(pre["1.0"], exp)

    Path(args.saida).write_text(json.dumps(s, separators=(",", ":")), encoding="utf-8")
    tam = Path(args.saida).stat().st_size / 1024
    print(f"{args.saida} — {len(datas)} pregões, {tam:.0f} KB, "
          f"{len(s['ciclosSelic'])} ciclos. CURVAS INVENTADAS.")
    for k, v in historico.resumo(s).items():
        print(f"  {k:16s} {v['n']:5d} dias  {v['inicio']} a {v['fim']}  "
              f"min {v['min']}  max {v['max']}  último {v['ultimo']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
