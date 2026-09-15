"""mercado — indicadores de mercado para a terceira aba do site.

Três coisas, de três fontes independentes:

  * a curva de juros brasileira, prefixada e de NTN-B, do Tesouro Transparente;
  * a curva americana, nominal e de TIPS, do Tesouro dos Estados Unidos;
  * o P/VP da carteira do Ibovespa, calculado das próprias empresas.

Nenhuma delas é tempo real, porque nenhuma fonte oficial gratuita publica
essas curvas em tempo real: todas divulgam no fechamento. O que o site mostra
é o último fechamento disponível, sempre com a data ao lado do número.

Os módulos separam rede de cálculo de propósito. `baixar_*` toca a rede;
`ler_*`, `curva_*` e `montar_*` recebem texto e devolvem números, e é sobre
essas que os testes rodam — sem acessar nada.
"""
from __future__ import annotations

__version__ = "1.0.0"
