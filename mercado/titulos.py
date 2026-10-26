# -*- coding: utf-8 -*-
"""Curvas brasileiras pela ANBIMA, e o acervo de curvas que o robô guarda.

Por que existe
--------------
Em 16/10/2026 o Tesouro Transparente parou de atualizar o CSV de taxas do
Tesouro Direto (o último pregão no arquivo é 15/10), e o download passou a
devolver uma página "429 – Muitas Requisições" no lugar do arquivo — também a
partir de um computador comum no Brasil, não só do GitHub. A coleta seguiu
publicando a curva de 15/10 até o validador barrar a idade, em 24/10.

A ANBIMA publica todo dia útil o `msAAMMDD.txt` do mercado secundário de
títulos públicos — o mesmo arquivo que o crédito privado já baixa para as
NTN-B de referência. Ele traz LTN, NTN-F e NTN-B com a taxa **indicativa**,
que é a referência de mercado (as do Tesouro Direto são de varejo e ficam
alguns pontos-base distantes).

O preço: a ANBIMA só mantém no ar os últimos sete ou oito pregões. Em
25/10/2026 o mais antigo disponível era 14/10. Com isso dá para fazer as fotos
de hoje e de uma semana atrás, mas não as de um mês e de seis meses.

O acervo
--------
Por isso o robô passa a guardar as curvas que vê, dentro do próprio
`mercado.json` (chave `juros.acervo`) — o arquivo que o workflow já publica,
sem mudar a lista de arquivos dele. Cada dia guarda os títulos das duas
famílias, de uma fonte só:

    {"2026-10-23": {"fonte": "anbima", "t": [["pre", 0, "2027-04-01", 13.2353], ...]}}

Precedência quando um dia aparece em mais de uma fonte: ANBIMA, depois
Tesouro, depois "foto" (pontos recuperados de um `mercado.json` anterior, que
também vieram do Tesouro). Nunca se misturam fontes dentro do mesmo dia.

Para não crescer sem fim: todos os pregões dos últimos 45 dias, um por semana
de 45 a 220 dias atrás, e — sempre — os dias que estão servindo de foto. Isso
dá algumas dezenas de KB.

Famílias
--------
LTN é prefixado sem cupom; NTN-F, prefixado com juros semestrais; NTN-B, IPCA+
com juros semestrais. A ANBIMA não traz a NTN-B Principal (o "Tesouro IPCA+"
sem cupom), então a curva real pela ANBIMA é feita de TIR de títulos com
cupom — a tela já marca esses pontos com a etiqueta "cupom".
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import pandas as pd

log = logging.getLogger(__name__)

# Título da ANBIMA -> (família, tem cupom)
TITULOS = {
    "LTN":   ("pre", False),
    "NTN-F": ("pre", True),
    "NTN-B": ("ipca", True),
}

PRECEDENCIA = {"anbima": 3, "tesouro": 2, "foto": 1}

# Os `ms*.txt` ficam no ar só sete ou oito pregões (em 25/10/2026, de 14/10
# em diante) — bem menos que os arquivos de debêntures. Doze dias corridos
# cobrem isso com um feriado no meio, sem pedir trinta arquivos que dão 404.
JANELA_DIAS = 12

DIAS_DIARIOS = 45       # até aqui, todos os pregões
DIAS_SEMANAIS = 220     # daqui até 45, um por semana; antes disso, só fotos

# Para o rótulo da foto: dentro destas faixas (em dias) vale o nome padrão.
FAIXA_ROTULO = {"semana": (5, 10), "mes": (26, 35), "semestre": (170, 195)}
NOMES = {"hoje": "hoje", "semana": "1 semana atrás",
         "mes": "1 mês atrás", "semestre": "6 meses atrás"}


# ---------------------------------------------------------------------------
# Leitura do arquivo da ANBIMA
# ---------------------------------------------------------------------------
def _num(txt: str) -> float | None:
    t = (txt or "").strip().replace(".", "").replace(",", ".")
    if not t or t == "--":
        return None
    try:
        return float(t)
    except ValueError:
        return None


def ler_ms(texto: str) -> tuple[date | None, list[list]]:
    """`msAAMMDD.txt` -> (data de referência, linhas do acervo).

    Cada linha: [família, cupom (0/1), vencimento ISO, taxa indicativa].
    Taxa zero ou ausente fica de fora — título não tem juro de 0,00%.
    """
    linhas = (texto or "").splitlines()
    cab = next((i for i, l in enumerate(linhas) if l.startswith("Titulo@")), None)
    if cab is None:
        raise ValueError("Cabeçalho do arquivo de títulos públicos da ANBIMA "
                         "não encontrado (linha começando por 'Titulo@').")
    nomes = [c.strip().lower() for c in linhas[cab].split("@")]
    try:
        c_ref = nomes.index("data referencia")
        c_venc = nomes.index("data vencimento")
        c_taxa = next(k for k, n in enumerate(nomes) if n.startswith("tx. indicativa"))
    except (ValueError, StopIteration) as exc:
        raise ValueError("Colunas do arquivo de títulos públicos da ANBIMA mudaram: "
                         f"{nomes}") from exc

    ref, saida = None, []
    for l in linhas[cab + 1:]:
        f = l.split("@")
        if len(f) <= max(c_ref, c_venc, c_taxa):
            continue
        tipo = f[0].strip()
        if tipo not in TITULOS:
            continue
        try:
            d = datetime.strptime(f[c_ref].strip(), "%Y%m%d").date()
            venc = datetime.strptime(f[c_venc].strip(), "%Y%m%d").date()
        except ValueError:
            continue
        tx = _num(f[c_taxa])
        if tx is None or tx <= 0:
            continue
        ref = ref or d
        fam, cupom = TITULOS[tipo]
        saida.append([fam, int(cupom), venc.isoformat(), round(tx, 4)])
    return ref, saida


# ---------------------------------------------------------------------------
# Outras fontes do acervo
# ---------------------------------------------------------------------------
def do_tesouro(td: pd.DataFrame, desde: date) -> dict:
    """Dias da tabela do Tesouro (`tesouro.ler_csv`) a partir de `desde`."""
    sel = td[td["DATA"] >= pd.Timestamp(desde)]
    saida: dict = {}
    for r in sel.itertuples():
        d = r.DATA.date().isoformat()
        saida.setdefault(d, {"fonte": "tesouro", "t": []})["t"].append(
            [r.FAMILIA, int(bool(r.CUPOM)), r.VENCIMENTO.date().isoformat(),
             round(float(r.TAXA), 4)])
    return saida


def das_fotos(juros: dict | None) -> dict:
    """Recupera os pontos das fotos de um `mercado.json` anterior.

    Serve para o primeiro dia sem o Tesouro: as fotos de um mês e de seis
    meses só existem ali. Os pontos de cada foto já passaram pelo prazo
    mínimo, o que não muda nada quando a curva é refeita a partir deles.
    """
    saida: dict = {}
    for s in ((juros or {}).get("series") or {}).values():
        d = s.get("dataBR")
        if not d:
            continue
        t = []
        for fam in ("pre", "ipca"):
            for p in (s.get(fam) or {}).get("pontos") or []:
                if p.get("vencimento") and p.get("taxa") is not None:
                    t.append([fam, int(bool(p.get("cupom"))), p["vencimento"],
                              round(float(p["taxa"]), 4)])
        if t:
            saida[d] = {"fonte": "foto", "t": t}
    return saida


# ---------------------------------------------------------------------------
# Acervo
# ---------------------------------------------------------------------------
def fundir(*acervos: dict) -> dict:
    """Junta acervos; num mesmo dia vence a fonte de maior precedência e,
    empatando, a que veio depois na lista (a mais nova)."""
    saida: dict = {}
    for a in acervos:
        for d, dia in (a or {}).items():
            if not dia or not dia.get("t"):
                continue
            atual = saida.get(d)
            if (atual is None or PRECEDENCIA.get(dia.get("fonte"), 0)
                    >= PRECEDENCIA.get(atual.get("fonte"), 0)):
                saida[d] = dia
    return dict(sorted(saida.items()))


def podar(acervo: dict, hoje: date, manter: set[date] | None = None) -> dict:
    """Todos os pregões dos últimos 45 dias, o último de cada semana entre 45
    e 220 dias, e sempre os dias em `manter` (as fotos em uso)."""
    manter = {d.isoformat() for d in (manter or set())}
    por_semana: dict = {}
    saida = {}
    for d in sorted(acervo):
        dia = date.fromisoformat(d)
        idade = (hoje - dia).days
        if d in manter or idade <= DIAS_DIARIOS:
            saida[d] = acervo[d]
        elif idade <= DIAS_SEMANAIS:
            por_semana[dia.isocalendar()[:2]] = d     # fica o último da semana
    for d in por_semana.values():
        saida[d] = acervo[d]
    return dict(sorted(saida.items()))


def tabela(acervo: dict) -> pd.DataFrame:
    """Acervo -> tabela no formato de `tesouro.ler_csv` (FAMILIA, CUPOM,
    VENCIMENTO, DATA, TAXA), para as mesmas funções de curva servirem."""
    linhas = [(fam, bool(cupom), venc, d, taxa)
              for d, dia in acervo.items() for fam, cupom, venc, taxa in dia["t"]]
    df = pd.DataFrame(linhas, columns=["FAMILIA", "CUPOM", "VENCIMENTO", "DATA", "TAXA"])
    df["VENCIMENTO"] = pd.to_datetime(df["VENCIMENTO"])
    df["DATA"] = pd.to_datetime(df["DATA"])
    df["TAXA"] = df["TAXA"].astype(float)
    df = df[df["VENCIMENTO"] > df["DATA"]]
    return df.reset_index(drop=True)


def juntar_com_tesouro(acervo: dict, td: pd.DataFrame | None) -> pd.DataFrame:
    """Tabela das fotos: o acervo, mais os dias do Tesouro que o acervo não tem.

    Com o Tesouro no ar, isso devolve os 21 anos dele e a foto de seis meses
    cai no pregão exato; sem ele, só o acervo.
    """
    base = tabela(acervo)
    if td is None or td.empty:
        return base
    tem = set(acervo)
    resto = td[~td["DATA"].dt.strftime("%Y-%m-%d").isin(tem)]
    return pd.concat([resto[base.columns], base], ignore_index=True)


def rotulo(chave: str, hoje: date, dia: date) -> str:
    """Nome da foto. Se o pregão escolhido está longe do alvo — porque o
    acervo ainda não tem o dia certo —, o nome diz a distância de verdade em
    vez de "1 mês atrás" para uma foto de cinco semanas."""
    if chave == "hoje":
        return NOMES["hoje"]
    gap = (hoje - dia).days
    lo, hi = FAIXA_ROTULO.get(chave, (0, 10**6))
    if lo <= gap <= hi:
        return NOMES[chave]
    if gap <= 13:
        return f"{gap} dias atrás"
    if gap < 60:
        return f"{round(gap / 7)} semanas atrás"
    meses = round(gap / 30.44)
    return "1 mês atrás" if meses == 1 else f"{meses} meses atrás"


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
def baixar_recentes(fim: date, sessao) -> dict:
    """Todos os `ms*.txt` que a ANBIMA ainda mantém, como acervo."""
    from mercado import credito

    saida: dict = {}
    for d in credito.dias_uteis_recentes(fim, JANELA_DIAS):
        try:
            texto = credito.baixar_titulos(d, sessao)
        except Exception as exc:                               # noqa: BLE001
            log.warning("Títulos públicos ANBIMA de %s: %s", d, exc)
            continue
        if not texto:
            continue
        ref, t = ler_ms(texto)
        if ref and t:
            saida[ref.isoformat()] = {"fonte": "anbima", "t": t}
    return saida
