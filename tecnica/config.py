# -*- coding: utf-8 -*-
"""Parâmetros da aba de análise técnica, cada um com o seu porquê."""
from __future__ import annotations

from simulacao import config as SC

# As velas moram dentro da pasta da base de preços: o robô que publica uma
# publica a outra, e o calendário (`precos/indice.json`) é o mesmo.
PASTA_VELAS = SC.PASTA_PRECOS / "ohlc"
ARQ_SINAIS = "_sinais.json"
VERSAO_VELAS = 1

# Só ações (inclui units como TAEE11, que o índice marca como "acao"). FII e
# ETF ficam de fora por decisão do Marco: análise técnica de FII com 0,3% de
# variação diária mede mais o spread de compra e venda que o fundo.
CLASSES = ("acao",)

# Abertura, máxima e mínima são gravadas como RAZÃO para o fechamento do mesmo
# dia, em pontos-base: (abertura / fechamento − 1) × 10.000. Por quê:
#
# * a razão não muda quando o Yahoo reajusta o histórico por provento ou
#   desdobramento (os quatro preços do dia são multiplicados pelo mesmo
#   fator), então o arquivo só cresce no fim, como o de retornos;
# * a abertura ajustada sai de graça: fechamento ajustado × (1 + razão).
#
# 1 ponto-base = 0,01% do preço: R$ 0,001 numa ação de R$ 10, abaixo do tick
# da B3. Mais casas só engordariam o arquivo.
ESCALA_RAZAO = 10_000

# Volume FINANCEIRO (fechamento bruto × quantidade), em R$ mil. O Yahoo ajusta
# a quantidade e o preço pelo mesmo desdobramento em sentidos opostos, então o
# produto não muda com desdobramento — de novo, o arquivo só cresce no fim.
ESCALA_VOLUME = 1_000

# Lacuna do Yahoo: as mesmas regras da aba de ETFs (`simulacao.etfs`):
# 10+ retornos zero seguidos, lacunas a até 3 pregões uma da outra se juntam.
LACUNA_MIN = 10
LACUNA_JUNTA = 3

# Indicadores: os parâmetros clássicos de cada autor.
MM_CURTA, MM_MEDIA, MM_LONGA = 20, 50, 200
MME_RAPIDA, MME_LENTA = 9, 21
IFR_N = 14                      # Wilder (1978)
MACD = (12, 26, 9)              # Appel
BOLLINGER = (20, 2.0)           # Bollinger: desvio POPULACIONAL (ddof=0)
ESTOCASTICO = (14, 3, 3)        # Lane, versão lenta
ATR_N = 14                      # Wilder
ADX_N = 14                      # Wilder
ANO = 252                       # máxima e mínima de 52 semanas
DONCHIAN_ENTRADA, DONCHIAN_SAIDA = 55, 20     # as "tartarugas" de Dennis
VOLUME_REL_N = 20

# Janelas de retorno do painel, em pregões (análise técnica conta pregão, não
# mês de calendário).
JANELAS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}

# Backtest: o mesmo custo da Simulação e do ranking (15 bps por ponta).
CUSTO_BPS = 15.0

# Painel: papel que parou de ter preço há mais que isto sai do painel.
ATRASO_MAX_PAINEL = 5
