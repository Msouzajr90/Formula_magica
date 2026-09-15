# -*- coding: utf-8 -*-
"""Confere o `mercado.json` antes de publicar.

Roda depois de `atualizar_mercado.py`, no robô e na mão. Não valida formato —
isso os testes já fazem. Valida se os NÚMEROS são possíveis, que é o erro que
passa despercebido: um arquivo bem formado com a curva no lugar errado publica
sem reclamar e fica meses no ar.

Sai com código 1 se algo estiver errado.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

PADRAO = Path(__file__).parent / "web" / "public" / "mercado.json"

# Faixas largas de propósito: não é para pegar variação de mercado, é para
# pegar erro de escala, de sinal e de unidade. Um juro prefixado brasileiro
# nunca foi 1,4% nem 140% — mas já foi 6% e já foi 25%.
FAIXAS = {
    "pre":  (5.0, 30.0, "juro prefixado brasileiro"),
    "ipca": (1.0, 14.0, "juro real brasileiro (NTN-B)"),
    "eua":  (0.0, 12.0, "juro nominal americano"),
    "tips": (-2.0, 8.0, "juro real americano (TIPS)"),
}
IDADE_MAXIMA_DIAS = 8
COBERTURA_MINIMA = 0.70


def conferir(caminho: Path) -> list[str]:
    erros: list[str] = []
    aviso: list[str] = []

    if not caminho.exists():
        return [f"{caminho} não existe."]
    dados = json.loads(caminho.read_text(encoding="utf-8"))

    meta = dados.get("meta") or {}
    if meta.get("demo"):
        aviso.append("O arquivo está em modo DEMONSTRAÇÃO — não publique assim.")

    juros = dados.get("juros") or {}
    grade = juros.get("grade") or []
    series = juros.get("series") or {}
    if "hoje" not in series:
        erros.append("Não há foto de 'hoje' nas curvas de juros.")
        return erros
    hoje = series["hoje"]

    def em(valores, prazo):
        try:
            return valores[grade.index(prazo)]
        except (ValueError, IndexError, TypeError):
            return None

    # 1. Idade
    try:
        d = datetime.strptime(hoje["dataBR"], "%Y-%m-%d").date()
        idade = (date.today() - d).days
        if idade > IDADE_MAXIMA_DIAS:
            erros.append(f"O último fechamento é de {d} — {idade} dias atrás. "
                         "A fonte parou de publicar ou a coleta está falhando.")
    except Exception:                                          # noqa: BLE001
        erros.append(f"Data do fechamento ilegível: {hoje.get('dataBR')!r}")

    # 2. Faixas das quatro curvas
    for chave, (minimo, maximo, nome) in FAIXAS.items():
        vals = [v for v in (hoje.get(chave, {}).get("grade") or []) if v is not None]
        if not vals:
            erros.append(f"A curva de {nome} saiu inteira vazia.")
            continue
        fora = [v for v in vals if not (minimo <= v <= maximo)]
        if fora:
            erros.append(f"{nome}: {len(fora)} ponto(s) fora da faixa "
                         f"{minimo}–{maximo}% (ex.: {fora[0]}). "
                         "Escala, sinal ou unidade trocados.")

    # 3. A regra que não pode ser afrouxada sem alguém notar
    if em(hoje["pre"]["grade"], 20.0) is not None:
        erros.append("A curva prefixada tem valor em 20 anos. Não existe título "
                     "prefixado brasileiro de 20 anos — isso é extrapolação, e "
                     "extrapolação neste gráfico é número inventado.")
    if em(hoje["pre"]["grade"], 10.0) is None:
        erros.append("A curva prefixada não chega a 10 anos; deveria (a NTN-F "
                     "mais longa passa disso).")
    if em(hoje["ipca"]["grade"], 10.0) is None:
        erros.append("A curva de NTN-B não chega a 10 anos.")

    # 4. Coerência interna: o spread tem que ser a diferença das duas curvas
    for campo, br, us in (("spreadNominal", "pre", "eua"),
                          ("spreadReal", "ipca", "tips")):
        for prazo in (5.0, 10.0):
            s, a, b = (em(hoje[campo], prazo), em(hoje[br]["grade"], prazo),
                       em(hoje[us]["grade"], prazo))
            if s is None or a is None or b is None:
                continue
            if abs(s - (a - b)) > 0.01:
                erros.append(f"{campo} em {prazo:g} anos vale {s}, mas "
                             f"{a} − {b} = {round(a - b, 3)}.")

    # 5. Ordem das fotos
    datas = juros.get("datas") or {}
    ordem = [datas.get(k) for k in ("semestre", "mes", "semana", "hoje")]
    limpa = [d for d in ordem if d]
    if limpa != sorted(limpa):
        erros.append(f"As quatro fotos estão fora de ordem no tempo: {ordem}")

    # 6. P/VP
    pvp = (dados.get("pvp") or {}).get("atual")
    if pvp and pvp.get("valor") is not None:
        v = pvp["valor"]
        if not (0.3 <= v <= 5.0):
            erros.append(f"P/VP do Ibovespa em {v}. Fora de qualquer faixa "
                         "histórica — provável erro de escala no nº de ações.")
        cob = pvp.get("cobertura") or 0
        if cob < COBERTURA_MINIMA:
            erros.append(f"O P/VP cobre só {cob:.0%} do peso do índice. "
                         "Abaixo disso o número não representa o Ibovespa.")
    else:
        aviso.append("Sem P/VP no arquivo — a aba mostra o cartão de indisponível.")

    for a in aviso:
        print("aviso:", a)
    return erros


def main(argv=None) -> int:
    caminho = Path(argv[0]) if argv else PADRAO
    erros = conferir(caminho)
    if erros:
        print(f"\n{len(erros)} problema(s) em {caminho}:", file=sys.stderr)
        for e in erros:
            print("  -", e, file=sys.stderr)
        return 1
    print(f"{caminho}: os números passaram na conferência.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
