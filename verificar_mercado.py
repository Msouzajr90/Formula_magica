# -*- coding: utf-8 -*-
"""Testa as quatro fontes da aba de mercado, uma a uma, e diz o que está fora.

Existe pelo mesmo motivo do `verificar_fiis.py`: quando a coleta quebra, a
pergunta é sempre "qual das fontes?", e descobrir isso lendo o traceback de
uma coleta de dez minutos é caro. Isto responde em vinte segundos, e responde
também a pergunta que só aparece no GitHub Actions — se a fonte recusa
conexão de fora do Brasil.

Uso:
    python verificar_mercado.py
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def linha(nome, ok, detalhe=""):
    print(f"  {'OK   ' if ok else 'FALHA'}  {nome:<34} {detalhe}")
    return ok


def main() -> int:
    from magicb3 import rede
    from mercado import ibov, tesouro, treasury

    sessao = rede.sessao(tentativas=2, backoff=1.5)
    tudo = True

    print("\nTesouro Transparente — curvas brasileiras")
    try:
        texto = tesouro.baixar_csv(sessao)
        td = tesouro.ler_csv(texto)
        fotos = tesouro.fotos(td)
        pre = tesouro.curva(td, "pre", fotos["hoje"])
        ipca = tesouro.curva(td, "ipca", fotos["hoje"])
        tudo &= linha("download", True, f"{len(texto)/1e6:.1f} MB, {len(td)} linhas úteis")
        tudo &= linha("último fechamento", True, str(fotos["hoje"]))
        tudo &= linha("curva prefixada", bool(pre),
                      f"{len(pre)} vértices, até {pre[-1].prazo:.1f} anos" if pre else "vazia")
        tudo &= linha("curva de NTN-B", bool(ipca),
                      f"{len(ipca)} vértices, até {ipca[-1].prazo:.1f} anos" if ipca else "vazia")
        tudo &= linha("as quatro fotos", len(fotos) == 4,
                      ", ".join(f"{k}={v}" for k, v in fotos.items()))
    except Exception as exc:                                   # noqa: BLE001
        tudo &= linha("download", False, str(exc)[:110])
        print("\n  Diagnóstico de rede:")
        print("  " + rede.relatorio("www.tesourotransparente.gov.br").replace("\n", "\n  "))

    print("\nU.S. Treasury — curvas americanas")
    anos = sorted({date.today().year, (date.today() - timedelta(days=200)).year})
    for rotulo, tipo in (("nominal", treasury.TIPO_NOMINAL), ("TIPS", treasury.TIPO_REAL)):
        try:
            df = treasury.baixar(tipo, anos, sessao)
            ult = max(d.date() for d in df["DATA"].unique())
            tudo &= linha(rotulo, True, f"{len(df)} pontos, último pregão {ult}")
        except Exception as exc:                               # noqa: BLE001
            tudo &= linha(rotulo, False, str(exc)[:110])

    print("\nB3 — carteira teórica do Ibovespa")
    try:
        c = ibov.baixar(sessao)
        soma = sum(p["part"] or 0 for p in c["papeis"])
        tudo &= linha("carteira", True,
                      f"{len(c['papeis'])} papéis de {c['data']}, soma dos pesos {soma:.1f}%")
    except Exception as exc:                                   # noqa: BLE001
        tudo &= linha("carteira", False, str(exc)[:110])
        guardada = Path(__file__).parent / "web" / "public" / "ibov_carteira.json"
        linha("carteira guardada no repositório", guardada.exists(),
              str(guardada) if guardada.exists() else "não existe — o P/VP vai falhar")

    print("\nCVM — patrimônio líquido (arquivo local)")
    fund = Path(__file__).parent / "web" / "public" / "fundamentos.json"
    if fund.exists():
        import json
        d = json.loads(fund.read_text(encoding="utf-8"))
        n = len(d.get("empresas") or [])
        com_pl = sum(1 for e in d.get("empresas") or []
                     if e.get("pl") and e.get("acoes"))
        tudo &= linha("fundamentos.json", com_pl > 200,
                      f"{n} empresas, {com_pl} com patrimônio e nº de ações; "
                      f"gerado em {(d.get('meta') or {}).get('geradoEm')}")
    else:
        tudo &= linha("fundamentos.json", False,
                      "não existe — rode baixar_fundamentos.py no Brasil")

    print("\n" + ("Tudo respondendo." if tudo else
                  "Alguma fonte está fora. A coleta publica o que conseguir e "
                  "grava o aviso no arquivo; a aba mostra o aviso no topo."))
    return 0 if tudo else 1


if __name__ == "__main__":
    raise SystemExit(main())
