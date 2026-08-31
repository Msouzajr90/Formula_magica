# -*- coding: utf-8 -*-
"""Backtest point-in-time — reconstrói o ranking em cada data de rebalanceamento.

Este é o teste honesto da estratégia. Diferente do backtest do TCC:

  * em cada 1º de janeiro (ou trimestre), só usa demonstrações que já haviam
    sido **entregues à CVM** naquela data (coluna DT_RECEB), em vez do balanço
    de 31/12 que só seria publicado em março;
  * o filtro de liquidez é recalculado com o volume dos 3 meses anteriores
    àquela data, e não com um número fixo levantado em 2023;
  * o valor de mercado usa o preço e o número de ações vigentes na época;
  * o retorno da carteira é composto com os pesos, e há custo de transação.

Uso:
    python backtest_historico.py --inicio 2018 --fim 2025 --n 30
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

from magicb3 import (backtest, config as C, cvm, fundamentals, optimizer,
                     prices, ranking, tickers)
from magicb3.pipeline import CONTAS_BP, CONTAS_USADAS

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("backtest")


def datas_de_rebalance(ini: int, fim: int, freq: str) -> list[pd.Timestamp]:
    meses = {"anual": [1], "semestral": [1, 7], "trimestral": [1, 4, 7, 10]}[freq]
    out = [pd.Timestamp(ano, m, 1) for ano in range(ini, fim + 1) for m in meses]
    return [d for d in out if d <= pd.Timestamp(date.today())]


def universo_na_data(data: pd.Timestamp, dados: dict, params: C.Params,
                     px: dict) -> pd.DataFrame:
    """Recalcula ROIC e EY usando só informação disponível em `data`."""
    corte = data - timedelta(days=params.defasagem_publicacao_dias)

    def disponivel(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        d = df.copy()
        # sem DT_RECEB, aproxima a publicação: anual +90 dias, trimestral +45
        aprox = d["DT_REFER"] + pd.to_timedelta(
            np.where(d["DT_REFER"].dt.month == 12, 90, 45), unit="D")
        pub = d["DT_RECEB"].fillna(aprox)
        return d[pub <= corte]

    dre = disponivel(pd.concat([dados["dfp"]["DRE"], dados["itr"]["DRE"]], ignore_index=True))
    bpa = disponivel(pd.concat([dados["dfp"]["BPA"], dados["itr"]["BPA"]], ignore_index=True))
    bpp = disponivel(pd.concat([dados["dfp"]["BPP"], dados["itr"]["BPP"]], ignore_index=True))
    if dre.empty:
        return pd.DataFrame()

    dfp_dre = dre[dre["DT_REFER"].dt.month == 12]
    itr_dre = dre[dre["DT_REFER"].dt.month != 12]
    ebit = cvm.ebit_ltm(dfp_dre, itr_dre if params.usar_ltm else pd.DataFrame(), C.CD_EBIT)
    bp = cvm.balanco_mais_recente(bpa, bpp, CONTAS_BP)

    # --- dados de mercado na data ---------------------------------------
    janela = px["fechamento"].loc[:data].tail(params.janela_liquidez_dias)
    vol = px["volume"].loc[:data].tail(params.janela_liquidez_dias)
    if janela.empty:
        return pd.DataFrame()
    liq = (janela * vol).mean(skipna=True)
    preco = px["preco"].loc[:data].ffill().iloc[-1]

    mercado = pd.DataFrame({"TICKER": preco.index, "PRECO": preco.values,
                            "LIQUIDEZ_MEDIA": liq.reindex(preco.index).values})
    mercado = mercado.merge(px["mapa"], on="TICKER", how="inner")
    mercado["ACOES"] = mercado["TICKER"].map(px["acoes"])
    mercado["VALOR_MERCADO"] = mercado["PRECO"] * mercado["ACOES"]
    mercado = mercado.dropna(subset=["VALOR_MERCADO"])
    mercado = mercado[mercado["VALOR_MERCADO"] > 0]

    return fundamentals.montar_indicadores(ebit, bp, mercado, params)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inicio", type=int, default=2018)
    ap.add_argument("--fim", type=int, default=date.today().year)
    ap.add_argument("--n", type=int, default=30, help="ações no ranking")
    ap.add_argument("--peso-max", type=float, default=0.15)
    ap.add_argument("--freq", default="anual",
                    choices=["anual", "semestral", "trimestral"])
    ap.add_argument("--ey", default="ebit_ev",
                    choices=["ebit_ev", "lucro_preco", "lpa_original_tcc"])
    ap.add_argument("--roic", default="capital_tangivel",
                    choices=["capital_tangivel", "ativo_total", "patrimonio_liquido"])
    ap.add_argument("--custo-bps", type=float, default=15.0)
    ap.add_argument("--defasagem", type=int, default=0,
                    help="dias extras de defasagem além da data de entrega na CVM")
    ap.add_argument("--saida", default="backtest_historico.xlsx")
    args = ap.parse_args()

    params = C.Params(n_acoes_ranking=args.n, peso_maximo_ativo=args.peso_max,
                      base_ey=args.ey, base_roic=args.roic,
                      custo_transacao_bps=args.custo_bps,
                      defasagem_publicacao_dias=args.defasagem, rebalance=args.freq)

    anos = list(range(args.inicio - 2, args.fim + 1))
    log.info("Baixando DFP %s-%s ...", anos[0], anos[-1])
    dfp = cvm.carregar_demonstracoes(anos, tipo="dfp", contas=CONTAS_USADAS)
    log.info("Baixando ITR %s-%s ...", anos[0], anos[-1])
    itr = cvm.carregar_demonstracoes(anos, tipo="itr", contas=CONTAS_USADAS)
    dados = {"dfp": dfp, "itr": itr}

    log.info("Montando universo de tickers ...")
    cadastro = cvm.carregar_cadastro()
    empresas = tickers.mapa_setorial(tickers.baixar_empresas_b3(), cadastro)
    mapa = tickers.candidatos_de_ticker(empresas)

    ini_px = date(args.inicio - 2, 1, 1)
    log.info("Baixando cotações de %d candidatos (isso demora) ...", len(mapa))
    hist = prices.baixar_historico(mapa["TICKER"].tolist(), ini_px, date.today())
    validos = prices.tickers_validos(hist["preco"], min_pregoes=60, cobertura_minima=0.0)
    px = {k: hist[k][[c for c in validos if c in hist[k].columns]]
          for k in ("preco", "fechamento", "volume")}
    px["mapa"] = mapa[mapa["TICKER"].isin(validos)][
        ["TICKER", "CD_CVM", "SETOR", "SEGMENTO"]].drop_duplicates("TICKER") \
        if "SETOR" in mapa.columns else mapa[mapa["TICKER"].isin(validos)]
    px["acoes"] = prices.acoes_em_circulacao(validos)

    retornos_todos = prices.retornos(px["preco"])
    bench = prices.retornos(prices.baixar_historico(
        [params.benchmark], ini_px, date.today())["preco"]).iloc[:, 0]

    composicoes: dict = {}
    rankings: dict = {}

    def montar(data: pd.Timestamp) -> pd.Series | None:
        uni = universo_na_data(data, dados, params, px)
        if uni.empty:
            return None
        aprov, _ = fundamentals.aplicar_filtros(uni, params)
        rk = ranking.ranquear(aprov, n=params.n_acoes_ranking)
        sel = rk[rk["SELECIONADA"]]["TICKER"].tolist()
        rankings[data] = rk.head(params.n_acoes_ranking)
        hist_r = retornos_todos.loc[:data].tail(params.janela_retornos_dias)
        cols = [t for t in sel if t in hist_r.columns and hist_r[t].abs().sum() > 0]
        if len(cols) < 3:
            return None
        mu, cov = optimizer.estimar(hist_r[cols], params.metodo_retorno,
                                    params.metodo_covariancia)
        fr = optimizer.fronteira_eficiente(mu, cov, pontos=3,
                                           w_max=params.peso_maximo_ativo,
                                           rf=params.taxa_livre_risco_aa)
        w = optimizer.limpar_pesos(fr.pesos.iloc[:, 0])
        composicoes[data] = w
        return w

    datas = datas_de_rebalance(args.inicio, args.fim, args.freq)
    log.info("Rodando backtest em %d datas de rebalanceamento ...", len(datas))
    res = backtest.rodar_backtest(montar, datas, retornos_todos, bench,
                                  custo_bps=params.custo_transacao_bps,
                                  rf_aa=params.taxa_livre_risco_aa)

    print("\n" + "=" * 62)
    print(f"{'Métrica':<24}{'Carteira':>18}{'Ibovespa':>18}")
    print("-" * 62)
    for k in res.metricas.to_dict():
        a, b = res.metricas.to_dict()[k], res.metricas_bench.to_dict()[k]
        f = (lambda v: f"{v:,.0f}") if k == "Pregões" else (
            (lambda v: f"{v:.2f}") if k in ("Sharpe", "Beta", "Information ratio")
            else (lambda v: f"{v*100:.1f}%"))
        print(f"{k:<24}{f(a):>18}{f(b):>18}")
    print("=" * 62)
    for linha in res.log:
        print("  " + linha)

    with pd.ExcelWriter(args.saida, engine="xlsxwriter") as w:
        pd.DataFrame({"Carteira": res.metricas.to_dict(),
                      "Ibovespa": res.metricas_bench.to_dict()}).to_excel(w, "Métricas")
        pd.DataFrame({"Carteira": backtest.acumulado(res.retornos_diarios),
                      "Ibovespa": backtest.acumulado(res.retornos_bench)}
                     ).to_excel(w, "Retorno acumulado")
        if composicoes:
            pd.DataFrame(composicoes).fillna(0).to_excel(w, "Composições")
        for d, rk in rankings.items():
            rk.to_excel(w, f"Ranking {d:%Y-%m}"[:31], index=False)
    log.info("Planilha gravada em %s", args.saida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
