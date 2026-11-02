# -*- coding: utf-8 -*-
"""tecnica — a aba de análise técnica do site.

O que este pacote faz:

* `velas`: guarda abertura, máxima, mínima e volume financeiro das ações, ao
  lado da base de retornos da Simulação (`web/public/precos/ohlc/`). Roda
  dentro do mesmo robô (`atualizar_precos.py`) e do mesmo download do Yahoo:
  nenhuma requisição a mais no dia a dia.
* `indicadores`: médias, IFR, MACD, Bollinger, estocástico, ATR, ADX, OBV,
  máximas e mínimas. É a referência em Python da conta que a tela faz em
  `web/public/tecnica_motor.js`; os testes comparam os dois.
* `sinais`: o painel de todas as ações (`precos/ohlc/_sinais.json`), que o
  robô grava para a tela não ter de baixar 200 arquivos.
* `backtest`: as regras de compra e venda testadas no passado.

O mesmo cuidado das outras abas: cálculo puro separado de rede e disco,
lacuna do Yahoo tratada como lacuna (não como preço parado de verdade).
"""
from __future__ import annotations

__version__ = "1.0.0"
