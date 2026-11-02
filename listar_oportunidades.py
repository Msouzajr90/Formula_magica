# -*- coding: utf-8 -*-
"""Lista no terminal o que a aba Oportunidades mostra. Sem rede.

Lê `web/public/pvp_papeis.json` e `web/public/dados.json` e aplica a mesma
regra do site (`mercado/oportunidades.py`): P/VP de hoje mais de k
desvios-padrão abaixo da média do ln P/VP na janela.

    python listar_oportunidades.py                 # 5 anos, k = 2
    python listar_oportunidades.py --janela 10 --k 1.5
    python listar_oportunidades.py --com-salto     # inclui papéis com salto
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ))


def main(argv=None) -> int:
    from mercado import oportunidades as op

    try:                                   # console do Windows em cp1252
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--janela", type=int, choices=op.JANELAS, default=5)
    ap.add_argument("--k", type=float, default=op.K_PADRAO)
    ap.add_argument("--com-salto", action="store_true")
    ap.add_argument("--pvp", default=str(RAIZ / "web" / "public" / "pvp_papeis.json"))
    ap.add_argument("--dados", default=str(RAIZ / "web" / "public" / "dados.json"))
    a = ap.parse_args(argv)

    pp = json.loads(Path(a.pvp).read_text(encoding="utf-8"))
    arq_dados = Path(a.dados)
    dados = json.loads(arq_dados.read_text(encoding="utf-8")) if arq_dados.exists() else None
    res = op.avaliar(pp, dados, a.k)
    lista, quase = op.classificar(res, a.janela, a.k, com_salto=a.com_salto)

    def linha(t):
        r, j = res[t], res[t]["janelas"][a.janela]
        desde = f"desde {j['desde']['data']} ({j['desde']['semanas']} sem.)" if j.get("desde") else ""
        salto = " ⚠ salto" if j.get("salto") else ""
        pg = f"{j['precoGatilho']:.2f}" if j.get("precoGatilho") else "—"
        return (f"  {t:<7} P/VP {r['pvp']:5.2f}  média {j['mediaGeo']:5.2f}  z {j['z']:+5.2f}  "
                f"gatilho {j['gatilho']:5.2f} (R$ {pg})  {desde}{salto}")

    print(f"P/VP abaixo de −{a.k:g} desvios da média de {a.janela} anos: {len(lista)}")
    for t in lista:
        print(linha(t))
    print(f"\nQuase lá: {len(quase)}")
    for t in quase:
        print(linha(t))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
