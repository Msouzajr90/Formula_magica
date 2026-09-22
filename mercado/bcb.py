# -*- coding: utf-8 -*-
"""Dólar, meta Selic e expectativa de inflação, do Banco Central.

Três séries que a aba Brasil × EUA precisa e que as fontes de curva não têm.
Todas do próprio BCB, sem credencial, e todas cobrindo o período inteiro da
série de juros (dez/2004 em diante):

  * **dólar**: SGS 1 — PTAX de venda, dia útil, em R$/US$. É a taxa que o
    Banco Central apura e publica, não a cotação de tela de uma corretora.
  * **meta Selic**: SGS 432 — a taxa que o Copom define. Existe em **todo dia
    do calendário**, inclusive fim de semana, e anda em degraus: é isso que
    faz dela a série certa para desenhar "ciclo". A Selic efetiva (SGS 11 ou
    4189) oscila alguns centésimos por dia e borra o degrau.
  * **expectativa de IPCA 12 meses**: Focus, pela API Olinda, versão
    **suavizada**. É o denominador do juro real ex-ante.

Duas armadilhas destas APIs, as duas encontradas nos dados
-----------------------------------------------------------
**O SGS recusa janela maior que 10 anos** em série diária, com HTTP 406 e uma
mensagem em português. Vinte e dois anos de dólar tem que ser pedido em
pedaços — daí o `_fatiar`.

**O Focus devolve cada data duas vezes.** A tabela tem uma coluna
`baseCalculo`: 0 usa só quem respondeu nos últimos 30 dias, 1 usa uma janela
maior. Pedir sem filtrar traz 8.892 linhas para 5.700 dias úteis, com
medianas diferentes no mesmo dia (em 15/09/2015, 5,74 e 5,71). O número que o
Relatório Focus publica, e o que se usa aqui, é o de `baseCalculo = 0`.

Sobre repetir valor
-------------------
O resto do projeto não carrega valor para a frente: buraco é buraco. Aqui há
uma exceção declarada, no Focus. Ele é apurado semanalmente e publicado com
alguns dias de atraso — em 22/09/2026 o dado mais recente era de 18/09. Não
carregar significaria perder a ponta da série toda semana. O limite está em
`TOLERANCIA_FOCUS` e é pequeno de propósito: passou disso, vira `None`.

O dólar e a meta Selic **não** são carregados. O dólar tem valor em todo dia
útil, que é exatamente quando a curva do Tesouro também tem; e a meta existe
em todo dia do calendário.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from urllib.parse import quote

log = logging.getLogger(__name__)

SGS = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
OLINDA = ("https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/"
          "odata/ExpectativasMercadoInflacao12Meses")

DOLAR = 1          # câmbio livre, dólar americano (venda) — PTAX
SELIC_META = 432   # meta Selic definida pelo Copom

# O SGS recusa mais que 10 anos numa consulta diária; 8 deixa folga para o
# caso de a regra apertar, e o custo de um pedido a mais é irrelevante.
ANOS_POR_PEDIDO = 8

# Quantos dias corridos o último Focus pode valer. Uma semana cobre o atraso
# normal de publicação; um feriado longo cabe. Duas semanas já seria esconder
# uma fonte parada.
TOLERANCIA_FOCUS = 10


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
def _fatiar(inicio: date, fim: date, anos: int = ANOS_POR_PEDIDO):
    """Quebra o período em janelas que o SGS aceita."""
    a = inicio
    while a <= fim:
        b = min(date(a.year + anos, a.month, a.day) - timedelta(days=1), fim)
        yield a, b
        a = b + timedelta(days=1)


def _numero(txt: str) -> float | None:
    try:
        v = float(str(txt).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return v


def serie_sgs(codigo: int, inicio: date, fim: date, sessao=None) -> dict[date, float]:
    """{data -> valor} de uma série diária do SGS, pedida em fatias."""
    import requests

    s = sessao or requests
    saida: dict[date, float] = {}
    for a, b in _fatiar(inicio, fim):
        r = s.get(SGS.format(codigo=codigo), timeout=120, params={
            "formato": "json",
            "dataInicial": a.strftime("%d/%m/%Y"),
            "dataFinal": b.strftime("%d/%m/%Y"),
        })
        # 404 com corpo vazio é o que o SGS responde quando a janela não tem
        # nenhum dado — normal no começo de uma série, não é erro.
        if r.status_code == 404:
            continue
        r.raise_for_status()
        for linha in r.json():
            v = _numero(linha.get("valor"))
            if v is None:
                continue
            try:
                d = date(*reversed([int(x) for x in linha["data"].split("/")]))
            except (KeyError, TypeError, ValueError):
                continue
            saida[d] = v
    log.info("SGS %d: %d pontos, de %s a %s", codigo, len(saida),
             min(saida) if saida else "—", max(saida) if saida else "—")
    return saida


def url_focus(inicio: date) -> str:
    """Monta a URL do Focus à mão, com espaço em %20.

    Não dá para passar isto em `params=` do requests. Ele monta a query com
    `urlencode`, que escreve espaço como `+` — a convenção de formulário. O
    Olinda não desfaz esse `+` dentro do `$filter`: ele lê
    `Indicador+eq+'IPCA'+and+...` como um nome de campo só e devolve

        HTTP 400  The types 'Edm.Boolean' and 'Edm.String' are not compatible.

    que não diz nada sobre espaço nenhum. O erro apareceu na primeira coleta
    de verdade: o dólar e a Selic vieram (o SGS usa parâmetros simples) e só o
    Focus faltou, sem nada no arquivo dizendo por quê.
    """
    partes = {
        "$format": "json",
        "$select": "Data,Mediana",
        "$filter": ("Indicador eq 'IPCA' and Suavizada eq 'S' "
                    f"and baseCalculo eq 0 and Data ge '{inicio.isoformat()}'"),
        "$orderby": "Data asc",
        "$top": "100000",
    }
    return OLINDA + "?" + "&".join(
        f"{quote(k, safe='$')}={quote(v, safe='')}" for k, v in partes.items())


def focus_ipca_12m(inicio: date, sessao=None) -> dict[date, float]:
    """Mediana suavizada da expectativa de IPCA para os 12 meses seguintes.

    `baseCalculo eq 0` é o que evita a duplicata explicada no topo do módulo.
    """
    import requests

    s = sessao or requests
    r = s.get(url_focus(inicio), timeout=180)
    if r.status_code >= 400:
        # O Olinda devolve o motivo no corpo, dentro de /*{...}*/; sem isto o
        # log fica só com "400 Client Error" e não se descobre o que houve.
        raise RuntimeError(f"Olinda respondeu {r.status_code}: "
                           f"{r.text[:200].strip()}")
    linhas = r.json().get("value") or []

    saida: dict[date, float] = {}
    for linha in linhas:
        try:
            d = date.fromisoformat(str(linha["Data"])[:10])
        except (KeyError, TypeError, ValueError):
            continue
        v = _numero(linha.get("Mediana"))
        if v is not None:
            saida[d] = v
    if len(saida) != len(linhas):
        log.warning("Focus: %d linhas viraram %d datas — há data repetida, o "
                    "filtro de baseCalculo pode ter parado de funcionar.",
                    len(linhas), len(saida))
    log.info("Focus IPCA 12m: %d pontos, de %s a %s", len(saida),
             min(saida) if saida else "—", max(saida) if saida else "—")
    return saida


# ---------------------------------------------------------------------------
# Alinhamento (sem rede — é aqui que os testes batem)
# ---------------------------------------------------------------------------
def alinhar(mapa: dict[date, float], datas: list[date],
            tolerancia: int = 0) -> list[float | None]:
    """Casa uma série do BCB com o calendário de pregões da curva.

    `tolerancia` é quantos dias corridos o último valor conhecido ainda vale.
    Zero — o padrão — exige o valor do próprio dia: é a regra do resto do
    projeto, e vale para o dólar e para a meta Selic. Só o Focus usa um valor
    maior, pela razão explicada no topo do módulo.
    """
    if not mapa:
        return [None] * len(datas)

    chaves = sorted(mapa)
    saida: list[float | None] = []
    i = 0
    for d in datas:
        # avança enquanto a próxima chave ainda não passou de `d`
        while i < len(chaves) and chaves[i] <= d:
            i += 1
        if i == 0:
            saida.append(None)
            continue
        anterior = chaves[i - 1]
        if (d - anterior).days > tolerancia:
            saida.append(None)
        else:
            saida.append(mapa[anterior])
    return saida


def juro_real_ex_ante(pre_1a: list[float | None],
                      focus_12m: list[float | None]) -> list[float | None]:
    """(1 + pré 1 ano) ÷ (1 + IPCA esperado 12m) − 1, em % ao ano.

    É a definição que o próprio Banco Central usa quando fala em juro real
    ex-ante: o juro nominal de um ano que o mercado está aceitando hoje,
    descontada a inflação que esse mesmo mercado espera para o mesmo ano.
    Nada de olhar para trás — não entra IPCA realizado.

    Divisão de Fisher, não subtração: com juro de 14% e inflação de 4,6%, a
    diferença dá 9,40 e a conta certa dá 8,99. Quatro décimos de ponto num
    número que se discute em décimos.
    """
    saida: list[float | None] = []
    for j, pi in zip(pre_1a, focus_12m):
        if j is None or pi is None or pi <= -100:
            saida.append(None)
        else:
            saida.append(round(((1 + j / 100) / (1 + pi / 100) - 1) * 100, 3))
    return saida


def ciclos_da_selic(datas: list[str], meta: list[float | None],
                    minimo_pp: float = 0.5) -> list[dict]:
    """Os trechos de alta e de queda da meta Selic, para sombrear o gráfico.

    Um ciclo vai de um ponto de virada ao seguinte. `minimo_pp` derruba o
    movimento pequeno demais para ser ciclo: um ajuste isolado de 0,25 p.p.
    revertido na reunião seguinte não é uma virada de política monetária, e
    sem esse filtro o gráfico ganharia faixas de duas semanas que não
    significam nada. O trecho pequeno não é apagado — é fundido com o
    vizinho, senão sobrariam buracos entre as faixas.
    """
    pontos = [(i, v) for i, v in enumerate(meta) if v is not None]
    if len(pontos) < 2:
        return []

    # 1. Comprime em degraus: só os dias em que a meta mudou de valor.
    degraus = [pontos[0]]
    for i, v in pontos[1:]:
        if abs(v - degraus[-1][1]) > 1e-9:
            degraus.append((i, v))
    if len(degraus) < 2:
        return []

    # 2. Viradas: as pontas, mais todo degrau em que o sinal do movimento
    #    inverte.
    viradas = [0]
    for k in range(1, len(degraus) - 1):
        antes = degraus[k][1] - degraus[k - 1][1]
        depois = degraus[k + 1][1] - degraus[k][1]
        if antes * depois < 0:
            viradas.append(k)
    viradas.append(len(degraus) - 1)

    # 3. Funde os trechos curtos, sempre começando pelo menor de todos.
    while len(viradas) > 2:
        tam = [abs(degraus[viradas[k + 1]][1] - degraus[viradas[k]][1])
               for k in range(len(viradas) - 1)]
        k = min(range(len(tam)), key=tam.__getitem__)
        if tam[k] >= minimo_pp:
            break
        # tira o extremo interno do trecho; no último trecho, o interno é o
        # começo dele, não o fim (o fim é a ponta da série)
        viradas.pop(k + 1 if k + 1 < len(viradas) - 1 else k)

    ciclos = []
    for k in range(len(viradas) - 1):
        ia, va = degraus[viradas[k]]
        ib, vb = degraus[viradas[k + 1]]
        if abs(vb - va) < minimo_pp:
            continue
        ciclos.append({"de": datas[ia], "ate": datas[ib],
                       "sentido": "alta" if vb > va else "queda",
                       "inicio": va, "fim": vb})

    # 4. Dois trechos seguidos no mesmo sentido são um movimento só. Isso
    #    acontece quando o passo 3 tirou o fundo de um respiro no meio de uma
    #    alta: ficam duas altas coladas onde o Copom fez uma.
    juntos: list[dict] = []
    for c in ciclos:
        if juntos and juntos[-1]["sentido"] == c["sentido"]:
            juntos[-1]["ate"] = c["ate"]
            juntos[-1]["fim"] = c["fim"]
        else:
            juntos.append(c)
    return juntos
