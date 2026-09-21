"""Aba de fundos fechados: FII, Fiagro e FIP de oferta pública e balcão.

O que distingue esta aba das outras duas: aqui não há preço de mercado. O valor
da cota é o patrimonial apurado pelo administrador, o deságio do secundário não
existe em dado aberto, e por isso a aba entrega fundamento — prazo,
rentabilidade, cotistas, amortização, taxa — e não avaliação.
"""
from . import config, coleta, indicadores, arquivo   # noqa: F401
