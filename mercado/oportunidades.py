# -*- coding: utf-8 -*-
"""P/VP muito abaixo da própria história: a conta da aba Oportunidades.

A aba roda inteira no navegador (`web/public/oportunidades_motor.js`). Este
módulo é a referência em Python da mesma conta: os testes comparam um com o
outro, e `listar_oportunidades.py` usa daqui para conferir a lista sem abrir o
site.

A regra
-------
Para cada papel do `pvp_papeis.json` (P/VP semanal desde 2015) e cada janela de
1, 5 ou 10 anos que termina na data mais recente:

    z = (ln P/VP hoje − média de ln P/VP na janela) / desvio de ln P/VP na janela

e o papel é oportunidade quando z < −k (k = 2 por padrão).

Por que o log
-------------
O P/VP não fica negativo e tem cauda longa para cima. Na escala original,
"média − 2 desvios" dá número negativo em boa parte dos papéis — uma regra que
nunca dispara. No log a distribuição fica perto de simétrica, e o gatilho vira
um fator: P/VP abaixo de média geométrica ÷ e^(k·desvio).

Escolhas, todas declaradas na tela
----------------------------------
* A janela INCLUI o ponto de hoje. Desvio amostral (n − 1).
* Janela = semanas com data > hoje − N anos e ≤ hoje.
* Cobertura mínima de 80%: das semanas da janela, ao menos 80% com P/VP. Papel
  que abriu capital há três anos não tem z de 5 nem de 10 anos, em vez de ter
  um z calculado sobre três anos e rotulado como de dez.
* Percentil = % das semanas da janela com P/VP ABAIXO do de hoje (a mesma
  definição do gráfico por papel da aba Mercado).
* O ponto de hoje é o preço do `dados.json` ÷ o VPA guardado. Se cai na mesma
  semana do último ponto gravado (ou no mesmo dia), substitui esse ponto; semana
  nova, acrescenta — a mesma regra do robô (`pvp_papeis.atualizar_semana`).
* A data do preço: a coleta roda de madrugada, então um `geradoEm` antes do
  meio-dia é o fechamento do dia útil anterior (sábado 02h → sexta).
* Salto de patrimônio: se dentro da janela o patrimônio por ação mudou 50% ou
  mais de um balanço para o outro (aumento de capital com o nº de ações de hoje
  aplicado ao passado, baixa contábil, fusão), a média mistura duas empresas e
  o z perde o sentido. O papel sai da lista principal e a tela mostra o salto;
  um botão traz de volta. Queda de PREÇO, por maior que seja, não é salto: é o
  que a aba procura.
  Os degraus do VPA vêm do campo `v` do `pvp_papeis.json`. Arquivo antigo, sem
  `v`: vale como salto o P/VP que dobrou ou caiu à metade em uma semana, menos
  depois do prazo de entrega do último balanço (data do balanço + 46 dias),
  quando o patrimônio já não muda e todo movimento é de preço.
* "Desde": de trás para a frente, quantas semanas seguidas o papel esteve com
  z < −k, cada semana medida com a janela que terminava NELA. Não olha o futuro.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

JANELAS = (1, 5, 10)
K_PADRAO = 2.0
FAIXA_QUASE = 0.5           # "quase lá": −k ≤ z < −k + 0,5
COBERTURA_MINIMA = 0.8
MINIMO_DE_PONTOS = 26       # meio ano de semanas, mesmo na janela de 1 ano
FATOR_SALTO_VPA = 1.5       # patrimônio por ação mudou 50% entre balanços
FATOR_SALTO = 2.0           # sem degraus: P/VP dobrou ou caiu à metade na semana
PRAZO_BALANCO_DIAS = 46     # ITR: 45 dias depois do trimestre


def _ok(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) \
        and math.isfinite(x) and x > 0


def _d(s) -> date:
    return date.fromisoformat(str(s)[:10])


def _semana(s) -> tuple[int, int]:
    iso = _d(s).isocalendar()
    return iso[0], iso[1]


def anos_antes(d: date, anos: int) -> date:
    """Mesmo dia, N anos antes; 29/02 vira 28/02."""
    try:
        return d.replace(year=d.year - anos)
    except ValueError:
        return d.replace(year=d.year - anos, day=28)


def com_hoje(datas: list[str], valores: list, vpa, preco, data_preco):
    """(datas, valores) com o ponto de hoje, pela regra da semana."""
    datas, valores = list(datas), list(valores)
    if not (_ok(vpa) and _ok(preco) and data_preco):
        return datas, valores
    data_preco = str(data_preco)[:10]
    if datas and data_preco < datas[-1]:
        return datas, valores
    v = preco / vpa
    if datas and _semana(datas[-1]) == _semana(data_preco):
        datas[-1], valores[-1] = data_preco, v
    else:
        datas.append(data_preco)
        valores.append(v)
    return datas, valores


def estatistica(datas: list[str], valores: list, fim: int, anos: int) -> dict | None:
    """Média e desvio do ln P/VP na janela de `anos` que termina em `fim`.

    None quando o ponto de `fim` não existe, a cobertura fica abaixo do mínimo
    ou há poucos pontos.
    """
    x = valores[fim]
    if not _ok(x):
        return None
    corte = anos_antes(_d(datas[fim]), anos).isoformat()
    if datas[0] > corte and (_d(datas[0]) - _d(corte)).days > 7:
        return None                        # a grade nem cobre a janela
    janela, total = [], 0
    i = fim
    while i >= 0 and datas[i] > corte:
        total += 1
        if _ok(valores[i]):
            janela.append(valores[i])
        i -= 1
    n = len(janela)
    if n < MINIMO_DE_PONTOS or n < COBERTURA_MINIMA * total:
        return None
    lns = [math.log(v) for v in janela]
    media = sum(lns) / n
    var = sum((l - media) ** 2 for l in lns) / (n - 1)
    dp = math.sqrt(var)
    if dp <= 0:
        return None
    return {
        "n": n,
        "cobertura": n / total,
        "media": media,
        "dp": dp,
        "z": (math.log(x) - media) / dp,
        "percentil": sum(1 for v in janela if v < x) / n,
        "mediaGeo": math.exp(media),
    }


def salto_vpa(datas: list[str], degraus: list, fim: int, anos: int) -> dict | None:
    """O maior degrau do patrimônio por ação dentro da janela, se for de
    FATOR_SALTO_VPA ou mais. `degraus` = [[índice da data, VPA], ...]."""
    corte = anos_antes(_d(datas[fim]), anos).isoformat()
    melhor, anterior = None, None
    for i, vpa in degraus or []:
        if i > fim:
            break
        if _ok(vpa):
            if anterior is not None and datas[i] > corte:
                fator = max(vpa / anterior, anterior / vpa)
                if fator >= FATOR_SALTO_VPA and (melhor is None or fator > melhor["fator"]):
                    melhor = {"tipo": "patrimonio", "data": datas[i], "de": anterior,
                              "para": vpa, "fator": fator}
            anterior = vpa
    return melhor


def salto_pvp(datas: list[str], valores: list, fim: int, anos: int,
              dt_balanco: str | None = None) -> dict | None:
    """Sem degraus do VPA: o maior salto semanal do P/VP (entre pontos válidos
    consecutivos) dentro da janela, se for de FATOR_SALTO ou mais. Saltos
    depois do prazo do último balanço são de preço e não contam."""
    corte = anos_antes(_d(datas[fim]), anos).isoformat()
    so_preco = ((_d(dt_balanco) + timedelta(days=PRAZO_BALANCO_DIAS)).isoformat()
                if dt_balanco else None)
    melhor, posterior = None, None
    i = fim
    while i >= 0 and datas[i] > corte:
        v = valores[i]
        if _ok(v):
            if posterior is not None and not (so_preco and datas[posterior[0]] > so_preco):
                fator = max(posterior[1] / v, v / posterior[1])
                if fator >= FATOR_SALTO and (melhor is None or fator > melhor["fator"]):
                    melhor = {"tipo": "pvp", "data": datas[posterior[0]], "de": v,
                              "para": posterior[1], "fator": fator}
            posterior = (i, v)
        i -= 1
    return melhor


def maior_salto(datas, valores, fim, anos, degraus=None, dt_balanco=None):
    if degraus:
        return salto_vpa(datas, degraus, fim, anos)
    return salto_pvp(datas, valores, fim, anos, dt_balanco)


def desde(datas: list[str], valores: list, anos: int, k: float) -> dict | None:
    """Início da sequência atual de semanas com z < −k (ou None)."""
    fim = len(valores) - 1
    inicio, semanas = None, 0
    i = fim
    while i >= 0:
        e = estatistica(datas, valores, i, anos)
        if e is None or e["z"] >= -k:
            break
        inicio, semanas = datas[i], semanas + 1
        i -= 1
    if not semanas:
        return None
    return {"data": inicio, "semanas": semanas}


def avaliar_papel(datas, valores, vpa, preco, data_preco, k: float = K_PADRAO,
                  degraus=None, dt_balanco=None) -> dict:
    datas, valores = com_hoje(datas, valores, vpa, preco, data_preco)
    fim = len(valores) - 1
    out = {"data": datas[fim] if datas else None,
           "pvp": valores[fim] if valores and _ok(valores[fim]) else None,
           "janelas": {}}
    for anos in JANELAS:
        e = estatistica(datas, valores, fim, anos) if valores else None
        if e is None:
            out["janelas"][anos] = None
            continue
        gatilho = math.exp(e["media"] - k * e["dp"])
        e = dict(e, gatilho=gatilho, salto=maior_salto(datas, valores, fim, anos, degraus, dt_balanco),
                 precoGatilho=gatilho * vpa if _ok(vpa) else None,
                 desde=desde(datas, valores, anos, k) if e["z"] < -k else None)
        out["janelas"][anos] = e
    return out


def precos_do_dia(dados: dict) -> tuple[dict[str, float], str | None]:
    precos = {}
    for e in (dados.get("empresas") or []) + (dados.get("excluidas") or []):
        t, p = e.get("ticker"), e.get("preco")
        if t and _ok(p):
            precos[str(t).upper()] = float(p)
    return precos, data_do_preco((dados.get("meta") or {}).get("geradoEm"))


def data_do_preco(gerado_em) -> str | None:
    """'2026-10-31 02:08' → '2026-10-30'. Antes do meio-dia, o dia útil anterior."""
    g = str(gerado_em or "")
    if len(g) < 10:
        return None
    d = _d(g)
    hora = int(g[11:13]) if len(g) >= 13 and g[11:13].isdigit() else 23
    if hora < 12:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def avaliar(pp: dict, dados: dict | None, k: float = K_PADRAO) -> dict[str, dict]:
    """{ticker: avaliação} para todos os papéis do `pvp_papeis.json`."""
    precos, quando = precos_do_dia(dados or {})
    datas = pp.get("datas") or []
    res = {}
    for t, info in (pp.get("papeis") or {}).items():
        r = avaliar_papel(datas, info.get("s") or [], info.get("vpa"),
                          precos.get(t), quando, k, info.get("v"), info.get("dtBalanco"))
        r["nome"] = info.get("nome")
        r["vpa"] = info.get("vpa")
        r["preco"] = precos.get(t)
        res[t] = r
    return res


def classificar(res: dict[str, dict], anos: int, k: float = K_PADRAO,
                faixa: float = FAIXA_QUASE,
                com_salto: bool = False) -> tuple[list[str], list[str]]:
    """(oportunidades, quase lá) na janela escolhida, do z mais baixo ao mais
    alto. Papéis com salto na janela ficam de fora, salvo `com_salto`."""
    def z(t):
        j = res[t]["janelas"].get(anos)
        if not j or (j.get("salto") and not com_salto):
            return None
        return j["z"]

    com = [t for t in res if z(t) is not None]
    op = sorted((t for t in com if z(t) < -k), key=z)
    quase = sorted((t for t in com if -k <= z(t) < -k + faixa), key=z)
    return op, quase
