# -*- coding: utf-8 -*-
"""Segunda fonte para o número de ações: o valor de mercado dividido pelo preço.

Existe porque a primeira fonte falha de dois jeitos. O `composicao_capital` da
CVM não tem coluna de escala — parte das empresas informa em unidades, parte em
milhares — e `magicb3.cvm` devolve nulo quando não consegue confirmar qual é.
Na primeira coleta real do Ibovespa isso deixou 10 dos 76 papéis sem número
(Vale e Itaú entre eles, 19% do índice) e deixou a Vivara com 235 bilhões de
ações, mil vezes o verdadeiro.

O valor de mercado dividido pelo preço não resolve tudo — é estimativa, e para
uma unit nem dá para saber se está contando units ou ações — mas é
independente, não tem problema de escala, e concordar com a CVM já é motivo
suficiente para confiar nas duas. `mercado.pvp.acoes_da_empresa` faz essa
conciliação.

Por que não `magicb3.prices.acoes_em_circulacao`: ele prefere o campo `shares`
do Yahoo, que numa empresa com duas classes traz as ações **daquela classe**
(5,4 bi para PETR4) e não o total da companhia (13,7 bi). Para dividir o
patrimônio líquido é o total que serve.
"""
from __future__ import annotations

import logging
import time
from statistics import median

log = logging.getLogger(__name__)

PAUSA = 0.35


def _yf():
    import yfinance as yf
    return yf


def valor_de_mercado(tickers: list[str], pausa: float = PAUSA
                     ) -> dict[str, tuple[float, float]]:
    """{ticker sem .SA -> (valor de mercado, último preço)} pelo Yahoo."""
    yf = _yf()
    saida: dict[str, tuple[float, float]] = {}
    for i, t in enumerate(tickers):
        if i:
            time.sleep(pausa)
        try:
            fi = yf.Ticker(f"{t}.SA").fast_info
            mc = fi.get("market_cap") or fi.get("marketCap")
            px = fi.get("last_price") or fi.get("lastPrice")
            if mc and px and px > 0:
                saida[t] = (float(mc), float(px))
        except Exception as exc:                               # noqa: BLE001
            log.debug("sem valor de mercado para %s: %s", t, exc)
    log.info("Valor de mercado obtido para %d de %d papéis", len(saida), len(tickers))
    return saida


def implicitas_por_prefixo(dados: dict[str, tuple[float, float]]
                           ) -> dict[str, float]:
    """{prefixo -> ações implícitas}. Com duas classes, fica a mediana.

    PETR3 e PETR4 dão 12,89 e 13,66 bilhões — o Yahoo usa preços de momentos
    ligeiramente diferentes para a mesma companhia. A mediana evita que a
    escolha da classe mude o resultado.
    """
    por_prefixo: dict[str, list[float]] = {}
    for t, (mc, px) in dados.items():
        if px > 0:
            por_prefixo.setdefault(str(t).upper()[:4], []).append(mc / px)
    return {k: float(median(v)) for k, v in por_prefixo.items() if v}
