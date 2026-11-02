# -*- coding: utf-8 -*-
"""Parâmetros da base de preços da Simulação, cada um com o seu porquê."""
from __future__ import annotations

from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PUBLICO = RAIZ / "web" / "public"
PASTA_PRECOS = PUBLICO / "precos"
ARQ_INDICE = "indice.json"
ARQ_EXTRAS = Path(__file__).resolve().parent / "tickers_extras.txt"

VERSAO_FORMATO = 1

# Desde quando. 2010 dá dezesseis anos e pega dois ciclos completos de Selic
# (alta de 2010-11, queda a 7,25% em 2012, alta a 14,25% em 2015, 2% em 2020).
# Antes disso o Yahoo tem buracos grandes em boa parte dos papéis da B3.
INICIO = date(2010, 1, 1)

# Retornos são gravados como inteiros: 0,012345 -> 12345 com escala 1e6.
#
# Por que gravar RETORNO e não preço ajustado: o preço ajustado do Yahoo é
# reescalado inteiro a cada provento (todos os preços passados mudam), então
# cada pregão reescreveria o arquivo inteiro de cada papel com dividendo e o
# repositório cresceria alguns MB por dia. O retorno diário não muda quando a
# série é reescalada: o arquivo só cresce no fim, e o git guarda a diferença.
#
# Por que 1e6 e não 1e5 (a escala do historico.json): o erro de arredondamento
# é de até 5e-7 por pregão, aleatório, e some num backtest de dezesseis anos.
ESCALA = 1_000_000
# O CDI não usa a mesma escala. A taxa diária é quase constante (0,055131% ao
# dia com a Selic em 14,9%), então o arredondamento seria o MESMO erro todo
# dia, na mesma direção: com 1e6 fica 551 em vez de 551,31, um erro pequeno
# (~0,01 p.p. ao ano) mas sistemático, que se acumula em dezesseis anos e
# entra no Sharpe de toda carteira. O SGS publica 6 casas do percentual, ou
# seja 8 da fração: com 1e8 o número é guardado exato.
ESCALA_CDI = 100_000_000

# Liquidez: média móvel de 63 pregões (~3 meses) do volume financeiro,
# fechamento × volume. Entra na base quem passou do corte EM ALGUM MOMENTO
# desde o INICIO — senão uma ação que foi líquida em 2014 e deixou de ser não
# poderia ser testada em 2014, e é justamente o tipo de papel que some de uma
# base "de hoje" e infla o backtest (viés de sobrevivência). É o mesmo R$ 1
# milhão por dia do ranking da fórmula mágica.
LIQUIDEZ_MINIMA = 1_000_000.0
JANELA_LIQUIDEZ = 63
MIN_PREGOES_LIQUIDEZ = 42      # média de 63 com pelo menos 2/3 dos pregões

# Atualização diária: em vez de rebaixar dezesseis anos de 400 papéis todo dia
# (o que atrai bloqueio do Yahoo), baixa só a janela recente e emenda. 100 dias
# corridos (~68 pregões) cobrem a média de liquidez de 63 pregões e emendam um
# papel que ficou até ~2 meses sem atualizar por falha de coleta.
JANELA_INCREMENTAL_DIAS = 100

# Papel recusado pelo corte de liquidez é testado de novo depois deste prazo:
# rebaixar o histórico inteiro de quem foi recusado ontem seria desperdício.
REAVALIAR_RECUSADOS_DIAS = 30

# Variação diária acima disto é marcada no índice. Não é corrigida: pode ser
# verdadeira (Americanas, jan/2023: −77%) ou desdobramento que o Yahoo não
# ajustou (aparece como −50%, −90%). O site mostra a data para conferir.
SALTO_SUSPEITO = 0.40

# Mínimos para o validador aceitar a base.
MINIMO_ATIVOS = 100
FRACAO_MINIMA_ATUALIZADA = 0.80
IDADE_MAXIMA_DIAS = 8          # mesmo limite da aba de mercado

# Séries de referência.
SIMBOLO_IBOV = "^BVSP"
SGS_CDI = 12                   # CDI diário, % ao dia
ARQ_IBOV = "_IBOV.json"
ARQ_CDI = "_CDI.json"

# Formato de código de negociação que entra na base: 4 caracteres começando
# por letra (B3SA tem dígito) e o sufixo numérico da classe — 3 a 8 para
# ações, 11 para units, FII e ETF, 31 a 39 para BDR (só via tickers_extras).
PADRAO_TICKER = r"^[A-Z][A-Z0-9]{3}(3|4|5|6|7|8|11|3[1-59])$"

# Irmãos de classe testados para cada ação já conhecida. O ranking da fórmula
# mágica guarda só um papel por empresa (PETR4, não PETR3), mas na simulação
# a escolha da classe é do Marco.
SUFIXOS_IRMAOS = ("3", "4", "11")

# ETFs listados na B3. Os que não existirem no Yahoo simplesmente não entram;
# os sem liquidez caem no corte como qualquer papel.
ETFS = {
    "BOVA11": "iShares Ibovespa",
    "BOVV11": "It Now Ibovespa",
    "BOVX11": "Trend Ibovespa",
    "XBOV11": "Caixa Ibovespa",
    "BRAX11": "iShares IBrX-100",
    "PIBB11": "It Now IBrX-50",
    "SMAL11": "iShares Small Cap",
    "DIVO11": "It Now IDIV (dividendos)",
    "FIND11": "It Now financeiro",
    "MATB11": "It Now materiais básicos",
    "ECOO11": "iShares carbono eficiente",
    "IVVB11": "iShares S&P 500 (em reais)",
    "SPXI11": "It Now S&P 500 (em reais)",
    "NASD11": "Trend Nasdaq-100 (em reais)",
    "ACWI11": "iShares MSCI ACWI (em reais)",
    "WRLD11": "Investo mundo (em reais)",
    "EURP11": "Trend Europa (em reais)",
    "XINA11": "Trend China (em reais)",
    "GOLD11": "Trend ouro",
    "HASH11": "Hashdex cripto",
    "QBTC11": "QR bitcoin",
    "BITH11": "Hashdex bitcoin",
    "ETHE11": "Hashdex ethereum",
    "IMAB11": "It Now IMA-B (NTN-B)",
    "B5P211": "It Now IMA-B5 (NTN-B até 5 anos)",
    "IB5M11": "It Now IMA-B5+ (NTN-B longas)",
    "IRFM11": "It Now IRF-M (prefixados)",
    "FIXA11": "Mirae prefixado",
    "LFTS11": "Investo Tesouro Selic",
    "DEBB11": "BTG debêntures incentivadas",
}


def hoje() -> date:
    return date.today()
