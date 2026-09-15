# -*- coding: utf-8 -*-
"""Interpolação das curvas e o spread entre Brasil e Estados Unidos.

Regra única, e ela é o ponto inteiro deste módulo: **interpola entre pontos
observados, nunca depois do último**. Fora do intervalo o valor é `None`, e o
gráfico simplesmente termina ali.

Isso não é preciosismo. A curva prefixada brasileira acaba em 2037 e a tela
mostra vinte anos. Esticar a última taxa até 2046 desenharia uma reta que
parece dado e não é — e é exatamente o tipo de coisa que alguém olha por seis
meses sem perceber. O gráfico com a linha curta diz a verdade: não existe
prefixado brasileiro de vinte anos.

Interpolação linear na taxa, não nos fatores de desconto. Entre vértices
vizinhos as duas dão quase o mesmo número, e a linear é a que o leitor
consegue conferir com uma régua.
"""
from __future__ import annotations

from bisect import bisect_left

# Grade da tela: de 1 a 20 anos, de meio em meio ano até 5 (é onde a curva
# tem curvatura) e de ano em ano depois.
GRADE = [round(x, 1) for x in
         [1 + 0.5 * i for i in range(9)]] + [float(a) for a in range(6, 21)]


def interpolar(pontos: list[tuple[float, float]], prazo: float) -> float | None:
    """Taxa em `prazo`, ou None se estiver fora do intervalo observado."""
    if not pontos:
        return None
    xs = [p[0] for p in pontos]
    ys = [p[1] for p in pontos]
    if prazo < xs[0] or prazo > xs[-1]:
        return None
    i = bisect_left(xs, prazo)
    if i < len(xs) and xs[i] == prazo:
        return ys[i]
    x0, y0 = xs[i - 1], ys[i - 1]
    x1, y1 = xs[i], ys[i]
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (prazo - x0) / (x1 - x0)


def na_grade(pontos: list[tuple[float, float]],
             grade: list[float] | None = None) -> list[float | None]:
    g = grade if grade is not None else GRADE
    return [interpolar(pontos, p) for p in g]


def diferenca(brasil: list[float | None],
              eua: list[float | None]) -> list[float | None]:
    """Spread ponto a ponto. Falta de um lado é falta do spread, não zero."""
    return [None if (b is None or e is None) else b - e
            for b, e in zip(brasil, eua)]


def em(grade_valores: list[float | None], prazo: float,
       grade: list[float] | None = None) -> float | None:
    """Valor da grade num prazo exato, para os vértices em destaque."""
    g = grade if grade is not None else GRADE
    try:
        return grade_valores[g.index(prazo)]
    except (ValueError, IndexError):
        return None


def alcance(pontos: list[tuple[float, float]]) -> tuple[float, float] | None:
    """Primeiro e último prazo observados — o que a tela usa para dizer
    até onde a curva existe de verdade."""
    if not pontos:
        return None
    return pontos[0][0], pontos[-1][0]
