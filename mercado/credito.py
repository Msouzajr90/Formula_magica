# -*- coding: utf-8 -*-
"""Spreads de crédito privado: isentos × não isentos, e por rating.

Três fontes públicas, nenhuma com login:

  * **ANBIMA — mercado secundário de debêntures** (`dbAAMMDD.txt`): a taxa
    indicativa de cada debênture precificada, todo dia útil. Para as atreladas
    ao DI a taxa já é o spread (`DI + x%`); para as de IPCA, é o juro real, e
    o arquivo diz contra qual NTN-B ela deve ser comparada (coluna
    "Referência NTN-B").
  * **ANBIMA — mercado secundário de títulos públicos** (`msAAMMDD.txt`): a
    taxa indicativa de cada NTN-B, para a conta acima. É a ANBIMA contra a
    ANBIMA, no mesmo fechamento — não o Tesouro Direto, que é varejo.
  * **SND (debentures.com.br)** — a exportação das características traz a
    coluna "Deb. Incent. (Lei 12.431)", S ou N. É ela que separa isento de
    não isento. O arquivo da ANBIMA não diz: os asteriscos ao lado do nome
    marcam cláusula de resgate antecipado, não incentivo fiscal (ver
    `MARCA_RESGATE`).

E uma quarta, para o rating:

  * **ANBIMA — curvas de crédito** (`curvas-debentures/CD.asp`): spread sobre
    o DI por prazo, para AAA, AA e A. A classificação é do comitê de
    precificação da ANBIMA, não de agência — e é a única segmentação por
    rating que existe em dado aberto. Rating de agência por papel não é
    publicado de graça em lugar nenhum (o próprio ANBIMA Data diz que "pode
    ser adquirido através das agências").

As quatro guardam só os últimos sete ou oito dias úteis. Não há série
histórica gratuita — por isso o histórico aqui é **acumulado**, como o do
P/VP: cada execução recolhe tudo o que ainda está no ar e funde no arquivo.
Um dia que o robô perder é recuperado na execução seguinte, desde que caia
dentro da janela.

Como os módulos vizinhos, separa rede de cálculo: `baixar_*` toca a rede;
`ler_*`, `calcular` e `resumir` recebem texto e devolvem números, e é sobre
eles que os testes rodam.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

log = logging.getLogger(__name__)

BASE_ANBIMA = "https://www.anbima.com.br"
URL_DEBENTURES = BASE_ANBIMA + "/informacoes/merc-sec-debentures/arqs/db{d:%y%m%d}.txt"
URL_TITULOS = BASE_ANBIMA + "/informacoes/merc-sec/arqs/ms{d:%y%m%d}.txt"
URL_CURVAS = BASE_ANBIMA + "/informacoes/curvas-debentures/CD.asp"
URL_SND = ("https://www.debentures.com.br/exploreosnd/consultaadados/"
           "emissoesdedebentures/caracteristicas_e.asp?tip_deb=&op_exc=False")

# O cadastro do SND tinha 4.810 debêntures registradas em 01/10/2026. Uma
# resposta com menos de mil é página de erro ou arquivo cortado, e trocaria o
# cadastro bom guardado por um ruim.
SND_MINIMO = 1000

# Quantos dias corridos para trás procurar. A ANBIMA mantém sete ou oito
# pregões no ar (em 01/10/2026 o mais antigo era 22/09); doze dias corridos
# cobrem isso com feriado no meio.
JANELA_DIAS = 12

# --- Regras de entrada na estatística -------------------------------------
# Cada corte tem um motivo, e a contagem de cada um vai para o arquivo.
#
# Duração mínima de meio ano. Uma debênture que vence em poucos meses tem
# taxa dominada por ruído de PU e pela defasagem do índice — o mesmo problema
# que tirou as NTN-B curtas da curva real (MERCADO.md, item 5).
DURACAO_MINIMA_ANOS = 0.5
DIAS_UTEIS_ANO = 252

# "(**) A cláusula já está no período de exercício." Com o resgate
# exercível, o preço passa a refletir a chance de o emissor recomprar ao par
# amanhã, não o risco de crédito até o vencimento. 132 das 1.291 linhas em
# 30/09/2026.
MARCA_EXERCICIO = "(**)"
# "(*) O papel tem cláusula de Resgate ou Amortização Antecipado." Fica:
# é a maioria do mercado (958 linhas) e a cláusula ainda não pode ser usada.
MARCA_RESGATE = "(*)"

# Faixas de duração para a comparação. As DI+ são curtas (mediana 2,5 anos)
# e as IPCA isentas longas (5,2 anos): comparar as medianas brutas misturaria
# prazo com tipo de papel. A tabela por faixa separa as duas coisas.
FAIXAS_DURACAO = [(DURACAO_MINIMA_ANOS, 3.0, "até 3 anos"),
                  (3.0, 6.0, "3 a 6 anos"),
                  (6.0, math.inf, "acima de 6 anos")]

# Alíquota de IR para o equivalente bruto: 15% é a de aplicações acima de
# 720 dias, que é o prazo de praticamente toda debênture incentivada.
ALIQUOTA_IR = 0.15

# Os grupos que a tela mostra. A chave é estável (vai para o histórico).
GRUPOS = {
    "diSpread": "DI + spread, não isentas",
    "ipcaIsenta": "IPCA + spread, isentas (Lei 12.431)",
    "ipcaNaoIsenta": "IPCA + spread, não isentas",
}
RATINGS = ("AAA", "AA", "A")
# Vértices das curvas de rating guardados no histórico.
VERTICES_HISTORICO = (1.0, 3.0, 5.0)


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def _num(s) -> float | None:
    s = (s or "").strip()
    if not s or s in ("--", "N/D", "-"):
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _data_br(s) -> date | None:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def indexador(texto: str) -> str:
    """'DI + 1,6%' → 'di'; '114,65% do DI' → 'diPercentual'; 'IPCA + …' → 'ipca'.

    IGP-M e prefixado ficam como 'outro': são dois ou três papéis no mercado
    inteiro e não formam grupo.
    """
    t = (texto or "").strip().upper()
    if t.startswith("DI +") or t.startswith("DI+"):
        return "di"
    if "% DO DI" in t:
        return "diPercentual"
    if t.startswith("IPCA"):
        return "ipca"
    return "outro"


@dataclass
class Papel:
    codigo: str
    emissor: str
    vencimento: date | None
    indice: str                 # texto original, ex.: "IPCA + 6,1774%"
    indexador: str              # di | diPercentual | ipca | outro
    taxa: float | None          # taxa indicativa ANBIMA, % a.a.
    duracao_du: float | None    # duration em dias úteis
    ref_ntnb: date | None
    resgate: bool               # (*)
    exercicio: bool             # (**)
    # Preenchidos por `calcular`:
    isenta: bool | None = None
    ntnb: float | None = None
    spread: float | None = None
    spread_bruto: float | None = None
    fora: str | None = None     # motivo de ter ficado fora da estatística
    extras: dict = field(default_factory=dict)

    @property
    def duracao(self) -> float | None:
        return None if self.duracao_du is None else self.duracao_du / DIAS_UTEIS_ANO


def ler_debentures(texto: str) -> list[Papel]:
    """Arquivo `dbAAMMDD.txt`: separado por @, uma debênture por linha.

    Lê pelo nome da coluna, não pela posição — a ANBIMA já acrescentou coluna
    uma vez (a "% Reune") e acrescenta de novo.
    """
    linhas = (texto or "").splitlines()
    cab = None
    for i, l in enumerate(linhas):
        if l.startswith("Código@") or l.startswith("Codigo@"):
            cab = i
            break
    if cab is None:
        raise ValueError("Cabeçalho do arquivo de debêntures não encontrado.")
    nomes = [re.sub(r"\s+", " ", c).strip().lower() for c in linhas[cab].split("@")]

    def col(*chaves):
        for k, n in enumerate(nomes):
            if all(c in n for c in chaves):
                return k
        raise ValueError(f"Coluna {' '.join(chaves)!r} sumiu do arquivo da ANBIMA.")

    c_cod = 0                       # "Código" — o acento depende da decodificação
    c_nome = col("nome")
    c_venc, c_ind = col("venc"), col("índice")
    c_taxa, c_dur, c_ref = col("taxa indicativa"), col("duration"), col("ntn-b")

    papeis = []
    for l in linhas[cab + 1:]:
        f = l.split("@")
        if len(f) <= max(c_ref, c_dur, c_taxa) or not re.fullmatch(r"[A-Z0-9]{4,8}", f[c_cod].strip()):
            continue
        nome = f[c_nome].strip()
        exercicio = MARCA_EXERCICIO in nome
        resgate = MARCA_RESGATE in nome
        emissor = re.sub(r"\s*\(\*+\)", "", nome).strip()
        papeis.append(Papel(
            codigo=f[c_cod].strip(), emissor=emissor,
            vencimento=_data_br(f[c_venc]), indice=f[c_ind].strip(),
            indexador=indexador(f[c_ind]), taxa=_num(f[c_taxa]),
            duracao_du=_num(f[c_dur]), ref_ntnb=_data_br(f[c_ref]),
            resgate=resgate, exercicio=exercicio))
    return papeis


def ler_titulos_publicos(texto: str) -> dict[date, float]:
    """Arquivo `msAAMMDD.txt`: taxa indicativa de cada NTN-B, por vencimento."""
    linhas = (texto or "").splitlines()
    cab = next((i for i, l in enumerate(linhas) if l.startswith("Titulo@")), None)
    if cab is None:
        raise ValueError("Cabeçalho do arquivo de títulos públicos não encontrado.")
    nomes = [c.strip().lower() for c in linhas[cab].split("@")]
    c_venc = nomes.index("data vencimento")
    c_taxa = next(k for k, n in enumerate(nomes) if n.startswith("tx. indicativa"))
    saida = {}
    for l in linhas[cab + 1:]:
        f = l.split("@")
        if len(f) <= max(c_venc, c_taxa) or f[0].strip() != "NTN-B":
            continue
        try:
            venc = datetime.strptime(f[c_venc].strip(), "%Y%m%d").date()
        except ValueError:
            continue
        tx = _num(f[c_taxa])
        if tx is not None:
            saida[venc] = tx
    return saida


def data_do_arquivo_titulos(texto: str) -> date | None:
    """A data de referência vem em cada linha (`Data Referencia`)."""
    m = re.search(r"\n(?:LTN|NTN-B|LFT|NTN-F)@(\d{8})@", texto or "")
    return datetime.strptime(m.group(1), "%Y%m%d").date() if m else None


def ler_snd(texto: str) -> dict[str, bool]:
    """Exportação de características do SND: código → incentivada (Lei 12.431).

    Separado por tabulação, com três linhas de aviso antes do cabeçalho, o
    código preenchido com espaços à direita ("ACRC21    ") e a coluna do
    incentivo com S ou N.
    """
    linhas = (texto or "").splitlines()
    cab = next((i for i, l in enumerate(linhas) if l.startswith("Codigo do Ativo")), None)
    if cab is None:
        raise ValueError("Cabeçalho da exportação do SND não encontrado.")
    nomes = [c.strip() for c in linhas[cab].split("\t")]
    try:
        c_inc = next(k for k, n in enumerate(nomes) if "12.431" in n)
    except StopIteration:
        raise ValueError("A coluna 'Deb. Incent. (Lei 12.431)' sumiu do SND.") from None
    saida = {}
    for l in linhas[cab + 1:]:
        f = l.split("\t")
        if len(f) <= c_inc:
            continue
        cod = f[0].strip()
        v = f[c_inc].strip().upper()
        if cod and v in ("S", "N"):
            saida[cod] = v == "S"
    return saida


def ler_curvas_credito(html: str) -> dict | None:
    """Tabela "Curvas de Crédito - Ratings" da página de consulta da ANBIMA.

    Devolve `None` quando a data não tem curva — a página responde 200 e
    simplesmente não traz a tabela (dia sem pregão, ou a curva do dia ainda
    não saiu: às 21h40 de 01/10/2026 a do próprio dia não estava publicada).
    """
    if not html or "Curvas de Crédito - Ratings" not in html:
        return None
    m = re.search(r"<td>\s*(\d{2}/\d{2}/\d{4})\s*</td>", html)
    data_ref = _data_br(m.group(1)) if m else None
    trecho = html[html.index("Curvas de Crédito - Ratings"):]
    fim = trecho.find("</table>")
    trecho = trecho[:fim if fim > 0 else None]
    # Cabeçalho: a ordem das colunas vem da própria tabela.
    ths = [re.sub(r"<[^>]+>|\s+", "", t) for t in re.findall(r"<th[^>]*>(.*?)</th>", trecho, re.S)]
    ordem = [t for t in ths if t in RATINGS]
    if ordem != list(RATINGS):
        raise ValueError(f"Colunas da curva de crédito mudaram: {ths}")
    vertices, cols = [], {r: [] for r in RATINGS}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", trecho, re.S):
        tds = [_num(re.sub(r"<[^>]+>", "", t)) for t in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(tds) != 1 + len(RATINGS) or any(v is None for v in tds):
            continue
        vertices.append(tds[0])
        for r, v in zip(RATINGS, tds[1:]):
            cols[r].append(v)
    if not vertices:
        return None
    return {"data": data_ref, "vertices": vertices, **cols}


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------
def equivalente_bruto(taxa_real: float, ntnb: float, ipca_esperado: float,
                      aliquota: float = ALIQUOTA_IR) -> float:
    """Spread sobre a NTN-B que um papel *tributado* teria de pagar para
    render, depois do IR, o mesmo que a isenta.

    O IR incide sobre o ganho nominal — inflação inclusive —, então a conta
    passa pelo nominal: real → nominal líquido → nominal bruto → real bruto.
    Tudo em % a.a.; a inflação é a esperada (Focus 12 meses), não a passada.
    """
    pi = ipca_esperado / 100
    nominal_liq = (1 + taxa_real / 100) * (1 + pi) - 1
    nominal_bruto = nominal_liq / (1 - aliquota)
    real_bruto = (1 + nominal_bruto) / (1 + pi) - 1
    return real_bruto * 100 - ntnb


def calcular(papeis: list[Papel], ntnb: dict[date, float],
             isentas: dict[str, bool], ipca_esperado: float | None = None
             ) -> list[Papel]:
    """Preenche spread, isenção e o motivo de exclusão de cada papel.

    Spread de DI+ é a própria taxa indicativa. Spread de IPCA+ é a taxa menos
    a NTN-B de referência, em pontos percentuais — subtração, que é como o
    mercado cota ("NTN-B + 40"). A ANBIMA escolhe a referência pela duration,
    e é ela que vale: interpolar uma curva por conta própria trocaria a
    escolha documentada da fonte por uma nossa.
    """
    for p in papeis:
        p.isenta = isentas.get(p.codigo)
        if p.indexador == "di":
            p.spread = p.taxa
        elif p.indexador == "ipca" and p.taxa is not None and p.ref_ntnb is not None:
            p.ntnb = ntnb.get(p.ref_ntnb)
            if p.ntnb is not None:
                p.spread = p.taxa - p.ntnb
                if p.isenta and ipca_esperado is not None:
                    p.spread_bruto = equivalente_bruto(p.taxa, p.ntnb, ipca_esperado)

        if p.indexador in ("diPercentual", "outro"):
            p.fora = "indexador"
        elif p.taxa is None:
            p.fora = "semTaxa"
        elif p.exercicio:
            p.fora = "resgateEmExercicio"
        elif p.duracao is None or p.duracao < DURACAO_MINIMA_ANOS:
            p.fora = "curta"
        elif p.spread is None:
            p.fora = "semNtnb"
        elif p.isenta is None:
            p.fora = "semCadastro"
        else:
            p.fora = None
    return papeis


def grupo(p: Papel) -> str | None:
    if p.fora:
        return None
    if p.indexador == "di":
        # DI+ incentivada praticamente não existe (uma no cadastro inteiro):
        # a lei exige remuneração prefixada ou por índice de preços.
        return "diSpread" if not p.isenta else None
    if p.indexador == "ipca":
        return "ipcaIsenta" if p.isenta else "ipcaNaoIsenta"
    return None


def quantil(v: list[float], q: float) -> float | None:
    """Quantil com interpolação linear — o mesmo do numpy por padrão."""
    if not v:
        return None
    s = sorted(v)
    i = (len(s) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def _estat(ps: list[Papel], campo: str = "spread") -> dict:
    v = [getattr(p, campo) for p in ps if getattr(p, campo) is not None]
    r = lambda x: None if x is None else round(x, 4)           # noqa: E731
    return {"n": len(v), "p25": r(quantil(v, .25)), "mediana": r(quantil(v, .5)),
            "p75": r(quantil(v, .75)),
            "duracaoMediana": r(quantil([p.duracao for p in ps if p.duracao], .5))}


def resumir(papeis: list[Papel], ipca_esperado: float | None = None) -> dict:
    """Mediana e quartis por grupo, no total e por faixa de duração.

    Mediana, não média: no mesmo dia convivem a Claro a DI + 0,36 e a
    Equipav a DI + 5,48, e meia dúzia de papéis em reestruturação arrastaria
    a média para onde não está nenhum papel típico.
    """
    por_grupo: dict[str, list[Papel]] = {g: [] for g in GRUPOS}
    for p in papeis:
        g = grupo(p)
        if g:
            por_grupo[g].append(p)

    grupos = {}
    for g, ps in por_grupo.items():
        e = _estat(ps)
        e["nome"] = GRUPOS[g]
        e["faixas"] = []
        for lo, hi, rot in FAIXAS_DURACAO:
            sub = [p for p in ps if p.duracao is not None and lo <= p.duracao < hi]
            e["faixas"].append({"faixa": rot, **_estat(sub)})
        if g == "ipcaIsenta":
            bruto = _estat(ps, "spread_bruto")
            e["bruto"] = {k: bruto[k] for k in ("n", "p25", "mediana", "p75")}
            for f, (lo, hi, _) in zip(e["faixas"], FAIXAS_DURACAO):
                sub = [p for p in ps if p.duracao is not None and lo <= p.duracao < hi]
                f["brutoMediana"] = _estat(sub, "spread_bruto")["mediana"]
        grupos[g] = e

    fora: dict[str, int] = {}
    for p in papeis:
        if p.fora:
            fora[p.fora] = fora.get(p.fora, 0) + 1
    # DI+ marcadas como isentas também não entram, e a contagem diz quantas.
    di_isentas = sum(1 for p in papeis if not p.fora and p.indexador == "di" and p.isenta)
    if di_isentas:
        fora["diIsenta"] = di_isentas

    return {"grupos": grupos, "excluidos": fora, "total": len(papeis),
            "ipcaEsperado": ipca_esperado,
            "aliquotaIR": ALIQUOTA_IR if ipca_esperado is not None else None}


def papeis_para_tabela(papeis: list[Papel]) -> dict:
    """Uma linha por papel que entrou na conta — o detalhe que a tela lista."""
    colunas = ["codigo", "emissor", "indice", "grupo", "vencimento",
               "duracao", "taxa", "ntnb", "spread", "spreadBruto", "resgate"]
    linhas = []
    r = lambda x, c=4: None if x is None else round(x, c)      # noqa: E731
    for p in sorted(papeis, key=lambda x: (x.spread is None, -(x.spread or 0))):
        g = grupo(p)
        if not g:
            continue
        linhas.append([p.codigo, p.emissor, p.indice, g,
                       p.vencimento.isoformat() if p.vencimento else None,
                       r(p.duracao, 2), r(p.taxa), r(p.ntnb), r(p.spread),
                       r(p.spread_bruto), 1 if p.resgate else 0])
    return {"colunas": colunas, "linhas": linhas}


def ponto_de_curva(curva: dict | None, prazo: float) -> dict[str, float | None]:
    """Spread de cada rating num vértice exato da tabela da ANBIMA."""
    if not curva or prazo not in curva["vertices"]:
        return {r: None for r in RATINGS}
    i = curva["vertices"].index(prazo)
    return {r: curva[r][i] for r in RATINGS}


# ---------------------------------------------------------------------------
# Histórico acumulado
# ---------------------------------------------------------------------------
def chaves_historico() -> list[str]:
    ch = list(GRUPOS) + ["ipcaIsentaBruta"]
    ch += [f"{r}_{int(v)}" for r in RATINGS for v in VERTICES_HISTORICO]
    return ch


def linha_historico(resumo: dict | None = None, curva: dict | None = None) -> dict:
    """O que um dia acrescenta ao histórico. Campo ausente é None, e None não
    apaga valor já gravado (ver `fundir_historico`)."""
    linha = {k: None for k in chaves_historico()}
    if resumo:
        for g in GRUPOS:
            e = resumo["grupos"].get(g) or {}
            linha[g] = e.get("mediana") if e.get("n", 0) >= N_MINIMO_HISTORICO else None
        b = (resumo["grupos"].get("ipcaIsenta") or {}).get("bruto") or {}
        linha["ipcaIsentaBruta"] = b.get("mediana") if b.get("n", 0) >= N_MINIMO_HISTORICO else None
    if curva:
        for v in VERTICES_HISTORICO:
            pt = ponto_de_curva(curva, v)
            for r in RATINGS:
                linha[f"{r}_{int(v)}"] = pt[r]
    return linha


# Mediana de três papéis não é indicador de mercado. As IPCA não isentas
# são 17 hoje — entram; um grupo que caia abaixo de 10 vira lacuna no
# histórico em vez de um ponto que oscila com a entrada de um papel.
N_MINIMO_HISTORICO = 10


def fundir_historico(hist: dict | None, novos: dict[date, dict]) -> dict:
    """Funde dias novos no histórico gravado.

    Por campo: um valor novo substitui o antigo da mesma data (a ANBIMA
    retifica), mas None nunca apaga um valor. A curva de rating de D só sai
    depois do robô de D rodar; ela entra na execução de D+1, na linha de D,
    sem mexer nas medianas que já estavam lá.
    """
    chaves = chaves_historico()
    por_data: dict[str, dict] = {}
    if hist and hist.get("datas"):
        for i, d in enumerate(hist["datas"]):
            por_data[d] = {k: (hist.get(k) or [None] * len(hist["datas"]))[i]
                           if i < len(hist.get(k) or []) else None for k in chaves}
    for d, linha in novos.items():
        chave = d.isoformat()
        atual = por_data.setdefault(chave, {k: None for k in chaves})
        for k in chaves:
            v = linha.get(k)
            if v is not None:
                atual[k] = round(v, 4)
    datas = sorted(por_data)
    saida = {"datas": datas}
    for k in chaves:
        saida[k] = [por_data[d].get(k) for d in datas]
    return saida


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
def _texto(r) -> str:
    return r.content.decode("latin-1")


def baixar_debentures(d: date, sessao) -> str | None:
    """None quando a data não está no ar (404 — fim de semana, feriado, ou
    mais velha que a janela da ANBIMA)."""
    r = sessao.get(URL_DEBENTURES.format(d=d), timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    t = _texto(r)
    return t if "@" in t else None


def baixar_titulos(d: date, sessao) -> str | None:
    r = sessao.get(URL_TITULOS.format(d=d), timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    t = _texto(r)
    return t if "@" in t else None


def baixar_curvas(d: date, sessao) -> str:
    """A consulta "em tela" — os downloads em CSV/XLS saem por um iframe e um
    nome de arquivo gerado, e a tabela da tela tem o mesmo número."""
    r = sessao.post(URL_CURVAS, timeout=60, data={
        "escolha": "1", "Idioma": "PT", "saida": "csv",
        "Dt_Ref_Ver": (d - timedelta(days=JANELA_DIAS)).strftime("%Y%m%d"),
        "Dt_Ref": d.strftime("%d/%m/%Y")})
    r.raise_for_status()
    return _texto(r)


def baixar_snd(sessao) -> str:
    r = sessao.get(URL_SND, timeout=180)
    r.raise_for_status()
    return _texto(r)


def dias_uteis_recentes(hoje: date, janela: int = JANELA_DIAS) -> list[date]:
    """Dias de semana da janela, do mais antigo ao mais novo. Feriado não é
    tratado aqui: a ANBIMA responde 404 e o dia é pulado."""
    return [hoje - timedelta(days=k) for k in range(janela, -1, -1)
            if (hoje - timedelta(days=k)).weekday() < 5]
