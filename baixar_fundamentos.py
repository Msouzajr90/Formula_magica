# -*- coding: utf-8 -*-
"""Baixa as demonstrações da CVM e grava web/public/fundamentos.json.

PRECISA RODAR NUM COMPUTADOR NO BRASIL.

O servidor `dados.cvm.gov.br` recusa conexões vindas do exterior. Isso foi
confirmado em produção: a partir do GitHub Actions, o IPv4 expira por descarte
de pacotes e o IPv6 sequer tem rota. Como Yahoo Finance e a API da B3 funcionam
de qualquer lugar, a divisão ficou assim:

    este script (no seu PC)  ->  fundamentos.json  ->  versionado no repositório
    robô do GitHub           ->  lê o arquivo + busca preços  ->  dados.json

Balanços mudam quatro vezes por ano, então rodar isto uma vez por trimestre
basta — depois das temporadas de resultados: março, maio, agosto e novembro.

Uso:
    python baixar_fundamentos.py
    python baixar_fundamentos.py --anos 2024 2025 2026
    python baixar_fundamentos.py --sem-cache
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from magicb3 import arquivo_fundamentos as arqf
from magicb3 import config as C, cvm, rede, tickers
from magicb3.pipeline import CONTAS_BP, CONTAS_USADAS

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("fundamentos")

SAIDA = Path(__file__).parent / "web" / "public" / "fundamentos.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--anos", type=int, nargs="+", default=None,
                    help="anos a baixar (padrão: os três últimos)")
    ap.add_argument("--saida", default=str(SAIDA))
    ap.add_argument("--sem-cache", action="store_true",
                    help="rebaixa tudo, ignorando ~/.magicb3_cache")
    ap.add_argument("--sem-itr", action="store_true",
                    help="só o balanço anual, sem os 12 meses móveis")
    ap.add_argument("--zips", default=None,
                    help="pasta com os zips da CVM já baixados; usa os arquivos "
                         "locais em vez de acessar a rede")
    ap.add_argument("--cadastro", default=None,
                    help="caminho do cad_cia_aberta.csv já baixado")
    args = ap.parse_args()

    hoje = date.today()
    anos = args.anos or [hoje.year, hoje.year - 1, hoje.year - 2]
    cache = not args.sem_cache

    print("=" * 68)
    print("  BAIXANDO FUNDAMENTOS DA CVM")
    print(f"  anos: {anos}")
    print("=" * 68)

    local = bool(args.zips)
    if local:
        print(f"\nLendo arquivos locais de {args.zips} (sem acessar a rede).")
        cache = False
    else:
        print("\nTestando a rota até a CVM...")
        diag = rede.diagnosticar("dados.cvm.gov.br", timeout=15.0)
        print(rede.relatorio_de(diag))
        if not (diag["ipv4"] or diag["ipv6"]):
            print("\nNão consigo alcançar a CVM desta máquina.")
            print("Se você está no Brasil, verifique firewall, antivírus ou VPN —")
            print("uma VPN com saída no exterior causa exatamente este erro.")
            print("Alternativa: baixe os zips manualmente e use --zips <pasta>.")
            return 1

    print("\nCarregando cadastro de companhias...")
    cadastro = cvm.carregar_cadastro(usar_cache=cache, arquivo_local=args.cadastro)
    setores = tickers.mapa_setorial(
        pd.DataFrame({"CD_CVM": pd.to_numeric(cadastro.get("CD_CVM"),
                                              errors="coerce").dropna().astype(int)}),
        cadastro)[["CD_CVM", "SETOR"]].dropna().drop_duplicates("CD_CVM")
    print(f"  {len(cadastro):,} companhias, {len(setores):,} com setor")

    print("\nBaixando demonstrações anuais (DFP)... isso demora alguns minutos.")
    dfp = cvm.carregar_demonstracoes(anos, tipo="dfp", usar_cache=cache,
                                     contas=CONTAS_USADAS, pasta_zips=args.zips)
    print(f"  DRE: {len(dfp['DRE']):,} linhas | BPA: {len(dfp['BPA']):,} | "
          f"BPP: {len(dfp['BPP']):,}")

    if args.sem_itr:
        itr = {"DRE": pd.DataFrame(), "BPA": pd.DataFrame(), "BPP": pd.DataFrame()}
    else:
        print("\nBaixando demonstrações trimestrais (ITR)...")
        itr = cvm.carregar_demonstracoes(anos, tipo="itr", usar_cache=cache,
                                         contas=CONTAS_USADAS, pasta_zips=args.zips)
        print(f"  DRE: {len(itr['DRE']):,} linhas")

    print("\nCalculando EBIT dos últimos 12 meses...")
    ebit = cvm.ebit_ltm(dfp["DRE"], itr.get("DRE", pd.DataFrame()), C.CD_EBIT)
    ebit = ebit.dropna(subset=["EBIT_LTM"])
    print(f"  {len(ebit):,} empresas com EBIT")

    print("Consolidando balanços...")
    bpa = pd.concat([dfp["BPA"], itr.get("BPA", pd.DataFrame())], ignore_index=True)
    bpp = pd.concat([dfp["BPP"], itr.get("BPP", pd.DataFrame())], ignore_index=True)
    bp = cvm.balanco_mais_recente(bpa, bpp, CONTAS_BP)
    print(f"  {len(bp):,} empresas com balanço")

    lucro = cvm.ebit_ltm(cvm.marcar_lucro_liquido(dfp["DRE"]),
                         cvm.marcar_lucro_liquido(itr.get("DRE", pd.DataFrame())),
                         "LL")[["CD_CVM", "EBIT_LTM"]]
    ebit = ebit.merge(lucro.rename(columns={"EBIT_LTM": "LUCRO_LTM"}),
                      on="CD_CVM", how="left")
    bp = bp.merge(cvm.patrimonio_liquido(bpp), on="CD_CVM", how="left")
    n_pl = int(bp["PATRIMONIO"].notna().sum())
    print(f"  {n_pl:,} com patrimônio líquido localizado")

    print("Lendo composição do capital (número de ações)...")
    acoes = cvm.composicao_capital(anos, pasta_zips=args.zips, usar_cache=cache)
    n_ok = int(acoes["ACOES"].notna().sum()) if len(acoes) else 0
    print(f"  {len(acoes):,} empresas, {n_ok:,} com escala confirmada")

    if len(ebit) < 100:
        print(f"\nSó {len(ebit)} empresas com EBIT — esperado 300 ou mais.")
        print("Algo saiu errado. Rode com --sem-cache e veja se muda.")
        return 1

    dados = arqf.exportar(ebit, bp, setores, args.saida, anos=anos, acoes=acoes)
    kb = Path(args.saida).stat().st_size / 1024
    com_ltm = sum(1 for e in dados["empresas"] if (e.get("fonte") or "").startswith("DFP+ITR"))

    print("\n" + "=" * 68)
    print(f"  Gravado em {args.saida}")
    print(f"  {len(dados['empresas']):,} empresas | {kb:,.0f} KB")
    print(f"  {com_ltm:,} com 12 meses móveis (DFP+ITR); "
          f"{len(dados['empresas']) - com_ltm:,} só com o anual")
    print("=" * 68)
    print("\nPróximo passo: suba este arquivo para o GitHub, na pasta web/public.")
    print("Depois rode a ação 'Atualizar dados' — agora ela vai funcionar,")
    print("porque não precisa mais falar com a CVM.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrompido.")
        sys.exit(130)
