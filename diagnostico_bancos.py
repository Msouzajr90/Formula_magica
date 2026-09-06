# -*- coding: utf-8 -*-
"""Descobre em qual conta Itaú, BTG e BMG informam o lucro líquido.

Roda no Brasil, onde a CVM responde. Não altera nada — só imprime.

    python diagnostico_bancos.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from magicb3 import cvm, rede

ALVOS = {19348: "ITAÚ UNIBANCO", 22616: "BTG PACTUAL",
         24600: "BANCO BMG", 80217: "INTER & CO",
         906: "BRADESCO (controle: este funciona)"}


def main() -> int:
    rede.forcar_ipv4()
    ano = pd.Timestamp.today().year
    print(f"Baixando DRE do ITR {ano} e do DFP {ano - 1}...\n")

    quadros = []
    for tipo, anos in (("itr", [ano]), ("dfp", [ano - 1])):
        try:
            # contas=None: traz TUDO da DRE, que é o ponto — queremos ver o que existe
            d = cvm.carregar_demonstracoes(anos, tipo=tipo, contas=None)
            dre = d.get("DRE", pd.DataFrame())
            if not dre.empty:
                quadros.append(dre.assign(FONTE=tipo.upper()))
        except Exception as exc:                                # noqa: BLE001
            print(f"  {tipo.upper()} falhou: {str(exc)[:150]}")

    if not quadros:
        print("Nenhuma demonstração baixada. A CVM não respondeu.")
        return 1

    dre = pd.concat(quadros, ignore_index=True)
    for cd, nome in ALVOS.items():
        print("=" * 72)
        print(f"{cd} — {nome}")
        print("=" * 72)
        emp = dre[dre["CD_CVM"] == cd]
        if emp.empty:
            print("  não aparece nos arquivos baixados\n")
            continue
        ult = emp["DT_REFER"].max()
        emp = emp[emp["DT_REFER"] == ult]
        # só o nível 2 da DRE (3.xx), que é onde mora o resultado
        emp = emp[emp["CD_CONTA"].astype(str).str.match(r"^3\.\d+$")]
        emp = emp.sort_values("CD_CONTA")
        print(f"  data-base {ult:%d/%m/%Y}  |  fonte {emp['FONTE'].iloc[0]}\n")
        for r in emp.itertuples():
            print(f"  {r.CD_CONTA:<8} {str(r.DS_CONTA)[:48]:<50} "
                  f"{r.VL_CONTA/1e9:>12,.2f} bi")
        print()

    print("Copie tudo acima e me mande.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
