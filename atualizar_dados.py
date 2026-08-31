# -*- coding: utf-8 -*-
"""Gera o arquivo de dados que o site na Vercel consome.

Roda o pipeline completo em Python (CVM + B3 + Yahoo) e grava um JSON
compacto em `web/public/dados.json`. O site é estático: ele lê esse arquivo e
refaz ranking e otimização no navegador, sem servidor nenhum.

Por que essa separação: a Vercel roda funções de curta duração, não um
processo contínuo. Baixar e processar centenas de MB da CVM não cabe ali.
No GitHub Actions cabe com folga — 16 GB de RAM e até 6 horas.

Uso:
    python atualizar_dados.py                # dados reais
    python atualizar_dados.py --demo         # dados sintéticos, para testar o site
    python atualizar_dados.py --pool 80      # nº de ações exportadas
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from magicb3 import config as C, optimizer, prices, ranking

SAIDA = Path(__file__).parent / "web" / "public" / "dados.json"


def _num(x):
    """JSON não aceita NaN nem Infinity — vira null."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(v) or math.isinf(v)) else round(v, 8)


def _texto(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    s = str(x).strip()
    return s if s and s.lower() != "nan" else None


def montar_json(res, params: C.Params, pool: int) -> dict:
    """Empacota ranking, retornos esperados e covariância."""
    rk = res.ranking.head(pool).copy()

    empresas = []
    for r in rk.itertuples():
        empresas.append({
            "ticker": str(r.TICKER).replace(".SA", ""),
            "yf": str(r.TICKER),
            "nome": _texto(getattr(r, "DENOM_CIA", None)),
            "setor": _texto(getattr(r, "SETOR", None)),
            "roic": _num(r.ROIC),
            "ey": _num(r.EY),
            "posRoic": int(r.POS_ROIC),
            "posEy": int(r.POS_EY),
            "rank": int(r.RANK_FINAL),
            "preco": _num(getattr(r, "PRECO", None)),
            "valorMercado": _num(getattr(r, "VALOR_MERCADO", None)),
            "ev": _num(getattr(r, "EV", None)),
            "ebit": _num(getattr(r, "EBIT_LTM", None)),
            "liquidez": _num(getattr(r, "LIQUIDEZ_MEDIA", None)),
            "dataBase": _texto(getattr(r, "DT_BASE", None))[:10]
                        if _texto(getattr(r, "DT_BASE", None)) else None,
        })

    # Só exporta estatísticas dos papéis que têm série de preços.
    tickers = [e["yf"] for e in empresas if e["yf"] in res.cov.columns]
    mu = res.mu.reindex(tickers)
    cov = res.cov.reindex(index=tickers, columns=tickers)

    excluidas = []
    if len(res.rejeitadas):
        for r in res.rejeitadas.head(400).itertuples():
            excluidas.append({
                "ticker": str(getattr(r, "TICKER", "")).replace(".SA", ""),
                "nome": _texto(getattr(r, "DENOM_CIA", None)),
                "setor": _texto(getattr(r, "SETOR", None)),
                "motivo": _texto(getattr(r, "MOTIVO_EXCLUSAO", None)),
            })

    return {
        "meta": {
            "geradoEm": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "versao": 2,
            "baseEy": params.base_ey,
            "baseRoic": params.base_roic,
            "janelaRetornos": params.janela_retornos_dias,
            "taxaLivreRisco": params.taxa_livre_risco_aa,
            "custoBps": params.custo_transacao_bps,
            "diagnostico": {k: (str(v) if not isinstance(v, (int, float, type(None))) else v)
                            for k, v in res.diagnostico.items()},
        },
        "empresas": empresas,
        "estatisticas": {
            "tickers": [t.replace(".SA", "") for t in tickers],
            "mu": [_num(v) for v in mu.to_numpy()],
            "cov": [[_num(v) for v in linha] for linha in cov.to_numpy()],
        },
        "excluidas": excluidas,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="usa dados sintéticos (não acessa a rede)")
    ap.add_argument("--pool", type=int, default=80,
                    help="quantas empresas do ranking exportar")
    ap.add_argument("--liquidez", type=float, default=1_000_000)
    ap.add_argument("--saida", default=str(SAIDA))
    ap.add_argument("--fundamentos", default=None,
                    help="caminho do fundamentos.json; com ele a CVM nao e acessada "
                         "(obrigatorio fora do Brasil, ver baixar_fundamentos.py)")
    args = ap.parse_args()

    params = C.Params(n_acoes_ranking=args.pool,
                      liquidez_minima_diaria=args.liquidez,
                      n_carteiras_fronteira=5)

    if args.demo:
        from magicb3 import demo
        print("Modo demonstração: gerando dados sintéticos...")
        res = demo.resultado_demo(params)
    else:
        from magicb3 import pipeline
        res = pipeline.montar_carteira(
            params, progresso=lambda m, v=None: print(f"  {m}", flush=True),
            arquivo_fundamentos=args.fundamentos)

    dados = montar_json(res, params, args.pool)

    saida = Path(args.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")

    n_emp = len(dados["empresas"])
    n_est = len(dados["estatisticas"]["tickers"])
    kb = saida.stat().st_size / 1024
    print(f"\nGravado em {saida}")
    print(f"  {n_emp} empresas no ranking")
    print(f"  {n_est} com série de preços (matriz {n_est}x{n_est})")
    print(f"  {kb:,.0f} KB")
    if n_est < 10:
        print("\n  AVISO: pouquíssimas empresas com preço. Rode verificar_dados.py.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
