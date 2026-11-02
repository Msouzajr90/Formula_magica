# -*- coding: utf-8 -*-
"""simulacao — base de preços para a aba de Simulação do site.

Na aba de Simulação o Marco escolhe os ativos; o site faz o backtest e mostra
as métricas. Todo o cálculo roda no navegador (`web/public/simulacao_motor.js`).
Este pacote só produz o que o navegador precisa ler: o **retorno diário total**
(com proventos) de cada ativo da base, do Ibovespa e do CDI, alinhado a um
calendário único de pregões.

Separação habitual do projeto: `coleta` toca a rede; `series`, `universo` e
`arquivo` recebem dados e devolvem dados, e é sobre eles que os testes rodam.
"""
from __future__ import annotations

__version__ = "1.0.0"
