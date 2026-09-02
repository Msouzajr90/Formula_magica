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


def montar_json(res, params: C.Params, pool: int,
                vagas_padrao: int = 0, utilidades_padrao: int = 0) -> dict:
    """Empacota ranking, retornos esperados e covariância."""
    # NÃO usar head(pool): o ranking vem ordenado por grupo — operacionais,
    # depois financeiras, depois concessionárias. Como as operacionais sozinhas
    # passam de 80, o corte por posição decapitava os outros dois grupos, e o
    # arquivo saía só com operacionais mesmo tendo vagas reservadas. Foi assim
    # que os bancos continuaram sumidos do site depois de "corrigidos".
    # `SELECIONADA` já respeita a cota de cada grupo, que é o que queremos.
    rk = res.ranking
    sel = rk[rk["SELECIONADA"]] if "SELECIONADA" in rk.columns else rk.head(pool)
    rk = (sel if not sel.empty else rk.head(pool)).copy()

    empresas = []
    for r in rk.itertuples():
        empresas.append({
            "ticker": str(r.TICKER).replace(".SA", ""),
            "yf": str(r.TICKER),
            "nome": _texto(getattr(r, "DENOM_CIA", None)),
            "setor": _texto(getattr(r, "SETOR", None)),
            "tipo": _texto(getattr(r, "TIPO", None)) or "operacional",
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
            # quantas vagas o site sugere; o arquivo carrega mais que isso
            "vagasFinanceiras": vagas_padrao,
            "financeirasNoArquivo": params.vagas_financeiras,
            "vagasUtilidades": utilidades_padrao,
            "utilidadesNoArquivo": params.vagas_utilidades,
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


def _sem_carimbo(d: dict) -> dict:
    """Cópia sem os campos que mudam a cada execução mesmo sem dado novo."""
    fora = {"geradoEm", "diagnostico"}
    meta = {k: v for k, v in (d.get("meta") or {}).items() if k not in fora}
    return {**d, "meta": meta}


def _igual_ao_existente(dados: dict, saida: Path) -> bool:
    if not saida.exists():
        return False
    try:
        antigo = json.loads(saida.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return _sem_carimbo(antigo) == _sem_carimbo(dados)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="usa dados sintéticos (não acessa a rede)")
    ap.add_argument("--pool", type=int, default=80,
                    help="quantas empresas do ranking exportar")
    ap.add_argument("--liquidez", type=float, default=1_000_000)
    ap.add_argument("--vagas-financeiras", type=int, default=0,
                    help="quantas vagas da carteira ficam com bancos e seguradoras "
                         "(ranqueados por ROE e Lucro/Preco, nunca junto das demais)")
    ap.add_argument("--vagas-utilidades", type=int, default=0,
                    help="quantas vagas da carteira ficam com concessionarias "
                         "(energia, saneamento, gas) - ranqueadas entre si")
    ap.add_argument("--saida", default=str(SAIDA))
    ap.add_argument("--fundamentos", default=None,
                    help="caminho do fundamentos.json; com ele a CVM nao e acessada "
                         "(obrigatorio fora do Brasil, ver baixar_fundamentos.py)")
    args = ap.parse_args()

    # O arquivo exportado é matéria-prima, não decisão tomada: o site tem um
    # controle de "vagas para financeiras" e aplica a cota no navegador. Se a
    # coleta já excluísse bancos e seguradoras, esse controle não teria o que
    # selecionar — foi o que aconteceu, e o site voltou a ficar sem bancos.
    # Por isso a exportação sempre reserva parte do pool para financeiras;
    # quantas entram de fato na carteira continua sendo escolha de quem usa.
    vagas_no_arquivo = max(args.vagas_financeiras, args.pool // 4)
    utilidades_no_arquivo = max(args.vagas_utilidades, args.pool // 4)

    params = C.Params(n_acoes_ranking=args.pool,
                      liquidez_minima_diaria=args.liquidez,
                      vagas_financeiras=vagas_no_arquivo,
                      vagas_utilidades=utilidades_no_arquivo,
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

    dados = montar_json(res, params, args.pool,
                        vagas_padrao=args.vagas_financeiras,
                        utilidades_padrao=args.vagas_utilidades)

    saida = Path(args.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    if _igual_ao_existente(dados, saida):
        # Num pregão sem alteração de preço fechado — feriado, ou rodada
        # repetida no mesmo dia — só o carimbo de hora mudaria. Reescrever o
        # arquivo geraria um commit e um deploy por dia sem nenhum conteúdo
        # novo. Melhor não tocar nele.
        print(f"\nNada mudou desde a última coleta; {saida} ficou como estava.")
        return 0
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
