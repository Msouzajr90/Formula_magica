# -*- coding: utf-8 -*-
"""Gera web/public/historico.json — o backtest point-in-time que o site refaz.

O site não recebe um backtest pronto: recebe os ingredientes para refazê-lo no
navegador sempre que você mexe num controle. São dois blocos:

  1. `rebalances` — o ranking reconstruído em cada data de compra, usando
     SOMENTE demonstrações já entregues à CVM naquele dia (coluna DT_RECEB).
     É aqui que mora a honestidade do backtest: em 02/01/2022 o balanço de
     31/12/2021 ainda não existia, então ele não entra.

  2. `retornos` — a série de retornos diários de cada papel que apareceu em
     algum ranking, mais o Ibovespa.

Com isso o navegador escolhe as ações conforme os seus parâmetros, roda o
Markowitz e compõe o retorno — tudo sem servidor.

Uso:
    python gerar_historico.py --anos 5
    python gerar_historico.py --demo          # sintético, para testar o site
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from magicb3 import config as C, cvm, fundamentals, prices, ranking, tickers
from magicb3.pipeline import CONTAS_BP, CONTAS_USADAS

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("historico")

SAIDA = Path(__file__).parent / "web" / "public" / "historico.json"
ESCALA = 100_000          # retornos gravados como inteiros: 0,0123 -> 1230


def _datas_rebalance(inicio: date, fim: date, freq: str) -> list[pd.Timestamp]:
    meses = {"anual": [1], "semestral": [1, 7], "trimestral": [1, 4, 7, 10]}[freq]
    out = [pd.Timestamp(a, m, 1) for a in range(inicio.year, fim.year + 1) for m in meses]
    return [d for d in out if inicio <= d.date() <= fim]


def _compactar(serie: pd.Series) -> list[int | None]:
    """Retornos como inteiros escalados — corta o arquivo quase pela metade."""
    out = []
    for v in serie:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            out.append(None)
        else:
            out.append(int(round(float(v) * ESCALA)))
    return out


def gerar(anos: int, freq: str, pool: int, liquidez: float,
          saida: Path, usar_cache: bool = True) -> dict:
    hoje = date.today()
    inicio = date(hoje.year - anos, 1, 1)
    params = C.Params(n_acoes_ranking=pool, liquidez_minima_diaria=liquidez)
    anos_cvm = list(range(inicio.year - 1, hoje.year + 1))

    log.info("Baixando DFP %s-%s", anos_cvm[0], anos_cvm[-1])
    dfp = cvm.carregar_demonstracoes(anos_cvm, tipo="dfp", usar_cache=usar_cache,
                                     contas=CONTAS_USADAS)
    log.info("Baixando ITR %s-%s", anos_cvm[0], anos_cvm[-1])
    itr = cvm.carregar_demonstracoes(anos_cvm, tipo="itr", usar_cache=usar_cache,
                                     contas=CONTAS_USADAS)

    cadastro = cvm.carregar_cadastro(usar_cache=usar_cache)
    empresas = tickers.mapa_setorial(tickers.baixar_empresas_b3(usar_cache=usar_cache),
                                     cadastro)
    mapa = tickers.candidatos_de_ticker(empresas)

    log.info("Baixando cotações de %d candidatos desde %s", len(mapa), inicio)
    hist = prices.baixar_historico(mapa["TICKER"].tolist(),
                                   inicio - timedelta(days=420), hoje,
                                   usar_cache=usar_cache)
    px = hist["preco"]
    validos = prices.tickers_validos(px, min_pregoes=60, cobertura_minima=0.0)
    px = px[validos]
    fech, vol = hist["fechamento"][validos], hist["volume"][validos]
    retornos = prices.retornos(px)

    acoes = prices.acoes_em_circulacao(validos, usar_cache=usar_cache)
    mapa_v = mapa[mapa["TICKER"].isin(validos)].drop_duplicates("TICKER")

    bench_px = prices.baixar_historico([params.benchmark],
                                       inicio - timedelta(days=420), hoje,
                                       usar_cache=usar_cache)["preco"]
    bench = prices.retornos(bench_px).iloc[:, 0] if not bench_px.empty else pd.Series(dtype=float)

    datas = _datas_rebalance(inicio, hoje, freq)
    log.info("Reconstruindo o ranking em %d datas", len(datas))

    rebalances, usados = [], set()
    for d in datas:
        corte = d
        def disponivel(df: pd.DataFrame) -> pd.DataFrame:
            if df.empty:
                return df
            aprox = df["DT_REFER"] + pd.to_timedelta(
                np.where(df["DT_REFER"].dt.month == 12, 90, 45), unit="D")
            return df[df["DT_RECEB"].fillna(aprox) <= corte]

        dre = disponivel(pd.concat([dfp["DRE"], itr["DRE"]], ignore_index=True))
        bpa = disponivel(pd.concat([dfp["BPA"], itr["BPA"]], ignore_index=True))
        bpp = disponivel(pd.concat([dfp["BPP"], itr["BPP"]], ignore_index=True))
        if dre.empty:
            log.warning("%s: sem demonstrações publicadas", d.date())
            continue

        anual = dre[dre["DT_REFER"].dt.month == 12]
        trim = dre[dre["DT_REFER"].dt.month != 12]
        ebit = cvm.ebit_ltm(anual, trim, C.CD_EBIT)
        lucro = cvm.ebit_ltm(anual, trim, C.CD_LUCRO_LIQUIDO)[["CD_CVM", "EBIT_LTM"]]
        ebit = ebit.merge(lucro.rename(columns={"EBIT_LTM": "LUCRO_LTM"}),
                          on="CD_CVM", how="left")
        bp = cvm.balanco_mais_recente(bpa, bpp, CONTAS_BP)
        bp = bp.merge(cvm.patrimonio_liquido(bpp), on="CD_CVM", how="left")

        janela_liq = (fech.loc[:d].tail(params.janela_liquidez_dias) *
                      vol.loc[:d].tail(params.janela_liquidez_dias))
        if janela_liq.empty:
            continue
        preco_d = px.loc[:d].ffill().iloc[-1]
        mercado = pd.DataFrame({"TICKER": preco_d.index, "PRECO": preco_d.values,
                                "LIQUIDEZ_MEDIA": janela_liq.mean().reindex(preco_d.index).values})
        mercado = mercado.merge(mapa_v[["TICKER", "CD_CVM", "SETOR", "SEGMENTO"]],
                                on="TICKER", how="inner")
        mercado["ACOES"] = mercado["TICKER"].map(acoes)
        mercado["VALOR_MERCADO"] = mercado["PRECO"] * mercado["ACOES"]
        mercado = mercado.dropna(subset=["VALOR_MERCADO"])
        if mercado.empty:
            continue

        try:
            uni = fundamentals.montar_indicadores(ebit, bp, mercado, params)
        except ValueError as exc:
            log.warning("%s: %s", d.date(), exc)
            continue
        # sem cota aqui: o navegador aplica a dele sobre a lista completa
        p_aberto = C.Params(**{**params.to_dict(),
                              "excluir_setores": tuple(params.excluir_setores),
                              "vagas_financeiras": 1})
        aprov, _ = fundamentals.aplicar_filtros(uni, p_aberto)
        if aprov.empty:
            continue
        rk = ranking.ranquear(aprov, n=pool, vagas_financeiras=pool // 4)

        itens = []
        for r in rk.head(pool * 2).itertuples():
            t = str(r.TICKER)
            itens.append({"t": t.replace(".SA", ""), "yf": t,
                          "f": 1 if r.TIPO == "financeira" else 0,
                          "q": round(float(r.ROIC), 5) if pd.notna(r.ROIC) else None,
                          "p": round(float(r.EY), 5) if pd.notna(r.EY) else None})
            usados.add(t)
        rebalances.append({"data": d.strftime("%Y-%m-%d"), "acoes": itens})
        log.info("  %s: %d empresas no ranking", d.date(), len(itens))

    if not rebalances:
        raise RuntimeError("Nenhuma data de rebalanceamento produziu ranking.")

    usados = sorted(usados)
    ret = retornos.loc[str(inicio):, [t for t in usados if t in retornos.columns]]
    ret = ret.dropna(how="all")
    pregoes = [d.strftime("%Y-%m-%d") for d in ret.index]

    dados = {
        "meta": {
            "versao": 1,
            "geradoEm": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "inicio": str(inicio), "fim": str(hoje), "frequencia": freq,
            "escalaRetornos": ESCALA,
            "janelaRetornos": params.janela_retornos_dias,
            "custoBps": params.custo_transacao_bps,
            "taxaLivreRisco": params.taxa_livre_risco_aa,
            "nRebalances": len(rebalances), "nTickers": len(ret.columns),
            "pointInTime": True,
        },
        "pregoes": pregoes,
        "retornos": {c.replace(".SA", ""): _compactar(ret[c]) for c in ret.columns},
        "benchmark": _compactar(bench.reindex(ret.index)),
        "rebalances": rebalances,
    }
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")
    return dados


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--anos", type=int, default=5)
    ap.add_argument("--freq", default="anual",
                    choices=["anual", "semestral", "trimestral"])
    ap.add_argument("--pool", type=int, default=40,
                    help="tamanho do ranking gravado por data (o site corta dentro dele)")
    ap.add_argument("--liquidez", type=float, default=1_000_000)
    ap.add_argument("--saida", default=str(SAIDA))
    ap.add_argument("--demo", action="store_true")
    args = ap.parse_args()

    saida = Path(args.saida)
    if args.demo:
        from magicb3 import demo_historico
        dados = demo_historico.gerar(saida, anos=args.anos, freq=args.freq)
    else:
        try:
            dados = gerar(args.anos, args.freq, args.pool, args.liquidez, saida)
        except prices.BloqueioYahoo as exc:
            # Sair com erro é o comportamento certo: o arquivo bom que já está
            # publicado continua no ar, em vez de ser trocado por um histórico
            # furado que renderia um backtest bonito e falso.
            print(f"\nINTERROMPIDO: {exc}")
            return 2

    kb = saida.stat().st_size / 1024
    m = dados["meta"]
    print(f"\nGravado em {saida}")
    print(f"  {m['nRebalances']} datas de rebalanceamento | {m['nTickers']} papéis")
    print(f"  {len(dados['pregoes'])} pregões de {m['inicio']} a {m['fim']}")
    print(f"  {kb:,.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
