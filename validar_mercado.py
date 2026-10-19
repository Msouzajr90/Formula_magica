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

# Faixas do `spread_historico.json`. Os limites vêm do que as séries de
# verdade fizeram em 21 anos, com folga larga dos dois lados — é para pegar
# escala, sinal e unidade trocados, não variação de mercado.
#
#   dólar            1,5345 (jul/2011) a 6,2086 (jan/2025)
#   meta Selic       2,00 (ago/2020) a 19,75 (mai/2005)
#   Focus IPCA 12m   2,84 a 7,13
#   juro real 1 ano  cerca de −2 (2021) a +15 (2005)
FAIXAS_HISTORICO = {
    "dolar":          (0.8, 15.0, "dólar (R$/US$)"),
    "selicMeta":      (0.5, 50.0, "meta Selic"),
    "focusIpca12m":   (0.0, 30.0, "expectativa de IPCA 12m do Focus"),
    "juroRealExAnte": (-10.0, 25.0, "juro real ex-ante de 1 ano"),
}


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

    # 7. Série histórica do P/VP
    #
    # O denominador só muda a cada balanço, então a série anda com o preço.
    # Um salto diário grande demais não é mercado: é balanço entrando errado —
    # trocado de empresa, em escala errada, ou antes da data de entrega. O teto
    # é folgado de propósito: na reconstrução de 2015 a 2026 o maior salto real
    # foi de 14,4%, em 12/03/2020, quando o Ibovespa caiu com circuit breaker.
    serie = (dados.get("pvp") or {}).get("historico") or []
    if len(serie) > 30:
        vals = [float(x[1]) for x in serie if x[1] is not None]
        fora = [v for v in vals if not (0.3 <= v <= 5.0)]
        if fora:
            erros.append(f"A série do P/VP tem {len(fora)} ponto(s) fora da "
                         f"faixa 0,3–5,0 (ex.: {fora[0]}).")
        saltos = [(serie[i][0], vals[i - 1], vals[i])
                  for i in range(1, len(vals))
                  if vals[i - 1] > 0 and abs(vals[i] / vals[i - 1] - 1) > 0.30]
        if saltos:
            d, a, b = saltos[0]
            erros.append(f"A série do P/VP dá {len(saltos)} salto(s) diário(s) "
                         f"acima de 30% (em {d}, de {a} para {b}). O preço não "
                         "faz isso; um balanço entrando errado, sim.")
        ordem = [x[0] for x in serie]
        if ordem != sorted(ordem):
            erros.append("A série do P/VP está fora de ordem no tempo.")

    # 8. O arquivo do histórico, se existir
    erros += conferir_historico(caminho.parent / "spread_historico.json", aviso)

    # 9. Os spreads de crédito privado
    erros += conferir_credito(caminho.parent / "credito.json", aviso)

    for a in aviso:
        print("aviso:", a)
    return erros


def conferir_historico(caminho: Path, aviso: list[str]) -> list[str]:
    """Confere o `spread_historico.json` — a série que a aba Brasil × EUA lê.

    Ele ficou sem conferência nenhuma até ganhar dólar, Selic e juro real
    ex-ante. Três séries a mais são três jeitos a mais de publicar um número
    errado sem ninguém perceber, porque este arquivo não aparece em cartão
    nenhum: ele só vira linha num gráfico, e linha errada parece linha.
    """
    erros: list[str] = []
    if not caminho.exists():
        aviso.append(f"{caminho.name} não existe — a aba Brasil × EUA fica sem "
                     "gráfico. Ele é gerado junto com o mercado.json.")
        return erros

    try:
        h = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as exc:                                   # noqa: BLE001
        return [f"{caminho.name} está ilegível: {exc}"]

    if h.get("demo"):
        erros.append(f"{caminho.name} é o fixture de tela, com as curvas "
                     "inventadas (tests/fixture_spread.py). Apague e rode o "
                     "atualizar_mercado.py.")

    datas = h.get("datas") or []
    if len(datas) < 1000:
        erros.append(f"{caminho.name} tem só {len(datas)} pregões. A série "
                     "começa em dez/2004 e deveria ter milhares.")
        return erros
    if datas != sorted(datas):
        erros.append(f"{caminho.name}: as datas estão fora de ordem.")

    for chave, (minimo, maximo, nome) in FAIXAS_HISTORICO.items():
        vals = h.get(chave)
        if vals is None:
            aviso.append(f"Sem {nome} no {caminho.name} — o gráfico que depende "
                         "dela some da tela. A coleta do Banco Central falhou?")
            continue
        if len(vals) != len(datas):
            erros.append(f"{nome}: {len(vals)} valores para {len(datas)} datas.")
            continue
        vivos = [v for v in vals if v is not None]
        if not vivos:
            erros.append(f"A série de {nome} saiu inteira vazia.")
            continue
        fora = [v for v in vivos if not (minimo <= v <= maximo)]
        if fora:
            erros.append(f"{nome}: {len(fora)} ponto(s) fora da faixa "
                         f"{minimo}–{maximo} (ex.: {fora[0]}). Escala, sinal "
                         "ou unidade trocados.")

    # A meta Selic é degrau: ela não pode variar todo dia, e um salto de mais
    # de 3 p.p. de um pregão para o outro nunca aconteceu — o maior foi de
    # 1,5 p.p., em outubro de 2021.
    meta = [v for v in (h.get("selicMeta") or []) if v is not None]
    saltos = [abs(b - a) for a, b in zip(meta, meta[1:]) if abs(b - a) > 3.0]
    if saltos:
        erros.append(f"A meta Selic dá {len(saltos)} salto(s) de mais de 3 p.p. "
                     f"entre pregões (o maior, {max(saltos):.2f}). O Copom nunca "
                     "fez isso; é dado de outra série entrando no lugar.")

    ciclos = h.get("ciclosSelic")
    if ciclos is not None:
        if not ciclos:
            aviso.append("Nenhum ciclo de Selic identificado — o gráfico sai sem "
                         "as faixas de fundo.")
        for a, b in zip(ciclos, ciclos[1:]):
            if a["ate"] != b["de"]:
                erros.append(f"Os ciclos da Selic têm buraco ou sobreposição "
                             f"entre {a['ate']} e {b['de']}.")
                break

    print(f"{caminho.name}: {len(datas)} pregões, de {datas[0]} a {datas[-1]}"
          + (f", {len(ciclos)} ciclos de Selic" if ciclos else ""))
    return erros


# Faixas do `credito.json`, em pontos percentuais. Folga larga: é para pegar
# taxa no lugar de spread (8,5 em vez de 0,9), sinal trocado ou % do DI
# entrando como spread (102,9), não variação de mercado. Em 30/09/2026:
#   DI + spread, mediana              0,90   (497 papéis)
#   IPCA isentas sobre a NTN-B        0,43   (580)   — já foi negativa
#   IPCA não isentas sobre a NTN-B    1,77   (17)
#   AAA / AA / A em 3 anos            0,59 / 0,92 / 1,91
FAIXAS_CREDITO = {
    "diSpread":      (0.0, 6.0, "mediana do spread das DI+"),
    "ipcaIsenta":    (-3.0, 6.0, "mediana do spread das IPCA isentas"),
    "ipcaNaoIsenta": (-3.0, 10.0, "mediana do spread das IPCA não isentas"),
}
N_MINIMO_CREDITO = {"diSpread": 100, "ipcaIsenta": 100}


def conferir_credito(caminho: Path, aviso: list[str]) -> list[str]:
    """Confere o `credito.json`.

    O histórico deste arquivo é acumulado — não dá para refazer o passado
    como o do spread soberano. Um número errado gravado hoje fica lá. Por
    isso a conferência é mais dura com a ordem dos ratings e a escala do que
    com a idade.
    """
    erros: list[str] = []
    if not caminho.exists():
        aviso.append(f"{caminho.name} não existe — a aba de crédito privado fica "
                     "vazia. Ele é gerado junto com o mercado.json.")
        return erros
    try:
        c = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as exc:                                   # noqa: BLE001
        return [f"{caminho.name} está ilegível: {exc}"]

    if (c.get("meta") or {}).get("demo"):
        erros.append(f"{caminho.name} é o fixture de tela (tests/fixture_credito.py), "
                     "com papéis inventados. Apague e rode o atualizar_mercado.py.")

    hoje = c.get("hoje") or {}
    try:
        d = date.fromisoformat(hoje["data"])
        if (date.today() - d).days > IDADE_MAXIMA_DIAS:
            erros.append(f"O arquivo de debêntures mais novo é de {d}. A ANBIMA "
                         "parou de publicar ou a coleta está falhando.")
    except Exception:                                          # noqa: BLE001
        erros.append(f"Data das debêntures ilegível: {hoje.get('data')!r}")

    grupos = hoje.get("grupos") or {}
    for g, (lo, hi, nome) in FAIXAS_CREDITO.items():
        e = grupos.get(g) or {}
        if e.get("mediana") is None:
            if g in N_MINIMO_CREDITO:
                erros.append(f"Sem {nome} — o grupo saiu vazio.")
            continue
        if not (lo <= e["mediana"] <= hi):
            erros.append(f"{nome}: {e['mediana']} fora da faixa {lo}–{hi} p.p. "
                         "Taxa no lugar de spread, ou sinal trocado.")
        if e.get("n", 0) < N_MINIMO_CREDITO.get(g, 0):
            erros.append(f"{nome}: só {e.get('n')} papéis (o normal passa de "
                         f"{N_MINIMO_CREDITO[g] * 4}). O cadastro do SND ou o arquivo "
                         "da ANBIMA veio cortado.")
        if not (e.get("p25") is None or e["p25"] <= e["mediana"] <= e["p75"]):
            erros.append(f"{nome}: quartis fora de ordem ({e.get('p25')}, "
                         f"{e['mediana']}, {e.get('p75')}).")

    curvas = c.get("curvas")
    if curvas:
        ratings = [curvas.get(r) or [] for r in ("AAA", "AA", "A")]
        n = len(curvas.get("vertices") or [])
        if not n or any(len(x) != n for x in ratings):
            erros.append("Curvas de rating com tamanhos diferentes dos vértices.")
        else:
            fora = [v for x in ratings for v in x if not (-1.0 <= v <= 15.0)]
            if fora:
                erros.append(f"Curvas de rating: valor {fora[0]} fora de −1 a 15 p.p.")
            inv = [curvas["vertices"][i] for i in range(n)
                   if not (ratings[0][i] <= ratings[1][i] <= ratings[2][i])]
            if inv:
                erros.append(f"Curvas de rating fora de ordem (AAA ≤ AA ≤ A) em "
                             f"{len(inv)} vértice(s), o primeiro em {inv[0]:g} anos. "
                             "Colunas trocadas na leitura.")
    else:
        aviso.append("Sem curvas por rating no credito.json.")

    h = c.get("historico") or {}
    datas = h.get("datas") or []
    if datas != sorted(set(datas)):
        erros.append("O histórico de crédito tem datas fora de ordem ou repetidas.")
    for k, v in h.items():
        if k != "datas" and len(v) != len(datas):
            erros.append(f"Histórico de crédito: {k} tem {len(v)} valores para "
                         f"{len(datas)} datas.")
            break

    print(f"{caminho.name}: debêntures de {hoje.get('data')}, "
          + ", ".join(f"{g} {(grupos.get(g) or {}).get('mediana')} "
                      f"(n={(grupos.get(g) or {}).get('n')})" for g in FAIXAS_CREDITO)
          + f"; histórico com {len(datas)} dia(s)")
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
