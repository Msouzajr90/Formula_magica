# -*- coding: utf-8 -*-
"""P/VP do Ibovespa, calculado das empresas que formam o índice.

Por que calcular em vez de buscar pronto
----------------------------------------
Não existe série histórica gratuita e oficial do P/VP do Ibovespa. A B3
publica o indicador do dia na página do índice, sem histórico; os sites que
publicam a série não dizem como a calculam. Como o projeto já tem o
patrimônio líquido de 438 companhias vindo da CVM e as cotações, o número sai
daqui — e sai auditável.

A conta
-------
                  Σ  qtd_i × preço_i
    P/VP  =  ───────────────────────────
                  Σ  qtd_i × VPA_i

`qtd_i` é a quantidade teórica do papel no índice, já ajustada pelo free
float, e `VPA_i = patrimônio líquido ÷ ações da companhia`.

Somar numerador e denominador separadamente é o que torna isto o P/VP *do
índice*: é a média harmônica dos P/VP individuais ponderada pelo valor de
mercado, e não a média aritmética — que seria dominada pelas empresas
pequenas e caras, e não é o que "o índice está a tantas vezes o patrimônio"
quer dizer.

Empresas com duas classes (PETR3 e PETR4) entram como dois papéis, cada um
com a sua quantidade e o seu preço, contra o mesmo VPA. Não há dupla
contagem: as quantidades do índice são disjuntas.

Bancos entram. Para o ranking de Greenblatt eles são excluídos porque ROIC e
EV não significam a mesma coisa num banco; o patrimônio líquido, sim — e um
Ibovespa sem Itaú, Bradesco e Banco do Brasil não seria o Ibovespa.

O que este número não é
-----------------------
O patrimônio líquido é contábil: custo histórico corrigido, não valor de
reposição nem valor de mercado dos ativos. Em setores de ativo leve o
denominador é quase ficção — e a composição setorial do índice muda ao longo
do tempo, então comparar o P/VP de hoje com o de 2010 compara também dois
índices diferentes.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class Resultado:
    pvp: float | None
    valor_mercado: float
    patrimonio: float
    cobertura: float                 # fração do peso do índice com dado
    n_com_dado: int
    n_total: int
    faltando: list[str] = field(default_factory=list)
    detalhe: list[dict] = field(default_factory=list)


def _ok(x) -> bool:
    return x is not None and isinstance(x, (int, float)) \
        and not math.isnan(x) and not math.isinf(x)


def prefixo(ticker: str) -> str:
    """PETR4 -> PETR. Quatro caracteres; o da B3 e' B3SA, com digito."""
    return str(ticker).replace(".SA", "").strip().upper()[:4]


# Quantas ações formam uma unit. A quantidade teórica do índice para uma unit
# está em units, e cada unit carrega o patrimônio de várias ações — sem isto,
# o denominador sai dividido pelo fator e a KLBN11 aparece com P/VP 10 em vez
# de 2. Não há fonte pública desses fatores num arquivo só, e eles mudam
# raramente; ficam aqui, e uma unit fora da lista é EXCLUÍDA em vez de tratada
# como ação — o erro silencioso é pior que o buraco declarado.
ACOES_POR_UNIT = {
    "BPAC11": 3,    # BTG Pactual: 1 ON + 2 PN
    "ENGI11": 5,    # Energisa:    1 ON + 4 PN
    "IGTI11": 3,    # Iguatemi:    1 ON + 2 PN
    "KLBN11": 5,    # Klabin:      1 ON + 4 PN
    "SANB11": 2,    # Santander:   1 ON + 1 PN
    "TAEE11": 3,    # Taesa:       1 ON + 2 PN
}

# P/VP individual fora desta faixa não é notícia, é erro de escala. A Vivara
# apareceu com 2.016 na primeira execução real — o nº de ações vinha mil vezes
# maior que o verdadeiro. Um papel assim entra na soma e desloca o índice.
PVP_PLAUSIVEL = (0.02, 100.0)

# Acima deste fator, o nº de ações da CVM e o implícito no valor de mercado
# não podem estar os dois certos.
DIVERGENCIA_MAXIMA = 2.0


def acoes_da_empresa(acoes_cvm, acoes_implicitas) -> tuple[float | None, str]:
    """Escolhe o nº TOTAL de ações da companhia e diz de onde ele veio.

    Duas fontes, cada uma com o seu defeito:

    * a CVM publica `composicao_capital` **sem coluna de escala** — parte das
      empresas informa em unidades e parte em milhares. `magicb3.cvm` infere a
      escala pelo lucro por ação e devolve nulo quando não consegue confirmar.
      Na primeira execução real isso deixou 10 dos 76 papéis do Ibovespa sem
      número — Vale e Itaú entre eles, juntos 19% do índice — e deixou a Vivara
      com 235 bilhões de ações, mil vezes o verdadeiro.

    * o valor de mercado dividido pelo preço dá o total implícito. É estimativa,
      mas é independente e não tem problema de escala.

    Então: vale a da CVM quando as duas concordam; vale a implícita quando
    discordam por mais de duas vezes, ou quando a da CVM não existe. Duas
    fontes concordando é a maneira barata de saber que nenhuma errou por mil.
    """
    tem_cvm = _ok(acoes_cvm) and acoes_cvm > 0
    tem_imp = _ok(acoes_implicitas) and acoes_implicitas > 0
    if tem_cvm and tem_imp:
        razao = max(acoes_cvm, acoes_implicitas) / min(acoes_cvm, acoes_implicitas)
        if razao <= DIVERGENCIA_MAXIMA:
            return float(acoes_cvm), "cvm"
        return float(acoes_implicitas), f"mercado (a da CVM divergia {razao:.0f}x)"
    if tem_cvm:
        return float(acoes_cvm), "cvm"
    if tem_imp:
        return float(acoes_implicitas), "mercado"
    return None, "sem fonte"


def vpa_por_prefixo(empresas: list[dict], mapa_prefixo: dict[str, int],
                    acoes_implicitas: dict | None = None) -> dict[str, dict]:
    """{prefixo -> {vpa, pl, acoes, fonteAcoes, nome, dtBalanco}}.

    `mapa_prefixo` liga o prefixo do ticker ao código CVM — o fundamentos.json
    é indexado por código CVM e não carrega ticker nenhum. `acoes_implicitas`
    é {prefixo -> valor de mercado ÷ preço}, a segunda fonte do nº de ações.
    """
    implicitas = {str(k).upper(): v for k, v in (acoes_implicitas or {}).items()}

    por_cvm = {}
    for e in empresas:
        try:
            cvm = int(e["cvm"])
        except (KeyError, TypeError, ValueError):
            continue
        pl = e.get("pl")
        if not _ok(pl) or pl <= 0:
            continue
        por_cvm[cvm] = {"pl": float(pl), "acoesCvm": e.get("acoes"),
                        "nome": e.get("nome"), "dtBalanco": e.get("dtBalanco")}

    saida = {}
    for pref, cvm in mapa_prefixo.items():
        pref = str(pref).upper()
        base = por_cvm.get(cvm)
        if base is None:
            continue
        acoes, fonte = acoes_da_empresa(base["acoesCvm"], implicitas.get(pref))
        if acoes is None:
            continue
        saida[pref] = {"vpa": base["pl"] / acoes, "pl": base["pl"],
                       "acoes": acoes, "fonteAcoes": fonte,
                       "nome": base["nome"], "dtBalanco": base["dtBalanco"]}
    return saida


def calcular(papeis: list[dict], precos: dict[str, float],
             vpas: dict[str, dict],
             acoes_por_unit: dict | None = None) -> Resultado:
    """P/VP do índice. `papeis` vem de `ibov`, `precos` é {ticker: preço}."""
    unidades = ACOES_POR_UNIT if acoes_por_unit is None else acoes_por_unit
    soma_mercado = 0.0
    soma_patrimonio = 0.0
    peso_com_dado = 0.0
    peso_total = 0.0
    faltando, detalhe = [], []

    for p in papeis:
        t = p["ticker"]
        peso = p.get("part") or 0.0
        peso_total += peso
        qtd = p.get("qtd")
        preco = precos.get(t)
        info = vpas.get(prefixo(t))

        if not (_ok(qtd) and _ok(preco) and info and _ok(info["vpa"])
                and info["vpa"] > 0):
            faltando.append(t)
            continue

        # Uma unit vale várias ações; sem o fator, o patrimônio dela sai
        # dividido e o P/VP do papel sai multiplicado — a KLBN11 aparecia com
        # 10 em vez de 2.
        #
        # E numa unit o nº de ações TEM que vir da CVM. O implícito no valor de
        # mercado não diz se está contando units ou ações: para a BPAC11 os dois
        # candidatos dão P/VP 0,99 e 2,96, e não há como saber qual pelo próprio
        # número. Onde não dá para saber, o papel fica de fora e é declarado.
        e_unit = "UNT" in str(p.get("tipo", "")).upper() or t.endswith("11")
        fator = unidades.get(t)
        if e_unit and (fator is None or info.get("fonteAcoes") != "cvm"):
            faltando.append(t)
            continue
        fator = fator or 1

        vpa = info["vpa"] * fator
        pvp_papel = preco / vpa
        if not (PVP_PLAUSIVEL[0] <= pvp_papel <= PVP_PLAUSIVEL[1]):
            faltando.append(t)
            continue

        soma_mercado += qtd * preco
        soma_patrimonio += qtd * vpa
        peso_com_dado += peso
        detalhe.append({"ticker": t, "nome": info.get("nome"), "peso": peso,
                        "preco": preco, "vpa": vpa, "pvp": pvp_papel,
                        "fonteAcoes": info.get("fonteAcoes"),
                        "dtBalanco": info.get("dtBalanco")})

    pvp = (soma_mercado / soma_patrimonio) if soma_patrimonio > 0 else None
    cobertura = (peso_com_dado / peso_total) if peso_total > 0 else 0.0
    detalhe.sort(key=lambda d: -(d["peso"] or 0))
    return Resultado(pvp=pvp, valor_mercado=soma_mercado,
                     patrimonio=soma_patrimonio, cobertura=cobertura,
                     n_com_dado=len(detalhe), n_total=len(papeis),
                     faltando=faltando, detalhe=detalhe)


def vpa_na_data(painel, acoes_por_cvm: dict, mapa_prefixo: dict[str, int],
                quando, folga_dias: int = 90) -> dict[str, dict]:
    """{prefixo -> {vpa, ...}} com o que se sabia em `quando`.

    A versão de hoje lê o `fundamentos.json`, que só tem o balanço mais
    recente. Esta lê o painel de todas as datas e escolhe o último balanço já
    ENTREGUE à CVM naquele dia — a mesma disciplina do `backtest_historico.py`.

    `acoes_por_cvm` é {código CVM -> {"acoes": n, "fonte": texto, "nome": …}},
    vindo da mesma conciliação do cálculo diário. **A fonte tem que vir junto**:
    a regra das units exige nº de ações da CVM, e sem carregar essa informação
    até aqui uma unit entraria com o número implícito no valor de mercado — que
    não diz se está contando units ou ações.

    Segurar o número de ações constante no tempo é uma aproximação declarada:
    ele muda com recompras e ofertas, devagar, e a alternativa (o histórico do
    Yahoo) não distingue ação de unit nem classe de total — trocaria um erro
    pequeno e conhecido por um grande e invisível.
    """
    saida = {}
    for pref, cvm in mapa_prefixo.items():
        info = acoes_por_cvm.get(cvm)
        if not info:
            continue
        n = info.get("acoes")
        if not _ok(n) or n <= 0:
            continue
        pl = patrimonio_vigente(painel, cvm, quando, folga_dias)
        if pl is None or pl <= 0:
            continue
        saida[str(pref).upper()] = {
            "vpa": pl / n, "pl": pl, "acoes": float(n),
            "fonteAcoes": info.get("fonte") or "cvm",
            "nome": info.get("nome"), "dtBalanco": None,
        }
    return saida


# ---------------------------------------------------------------------------
# Patrimônio líquido no tempo, para a série histórica
# ---------------------------------------------------------------------------
def painel_patrimonio(bpp, ds_patrimonio: str):
    """Patrimônio líquido por empresa e por data, preservando a série.

    `magicb3.cvm.patrimonio_liquido` devolve uma linha por empresa — serve ao
    ranking, que só quer o balanço atual. A série histórica precisa de todas
    as datas, com a data de entrega junto: em 02/01/2022 o balanço de
    31/12/2021 ainda não tinha sido publicado e não pode entrar no cálculo
    daquele dia. É a mesma disciplina do `backtest_historico.py`, e é o que
    separa uma série de uma ilusão.

    A busca é pela DESCRIÇÃO da conta, nunca pelo código: em bancos o 2.03 é
    "Provisões" e o patrimônio está no 2.07. Ler o código devolveria R$ 40 bi
    de provisões no lugar dos R$ 190 bi de patrimônio do Banco do Brasil.
    """
    import pandas as pd

    if bpp is None or len(bpp) == 0:
        return pd.DataFrame(columns=["CD_CVM", "DT_REFER", "DT_RECEB", "PATRIMONIO"])

    ds = bpp["DS_CONTA"].astype("string").str.strip().str.lower()
    pl = bpp[ds.str.startswith(ds_patrimonio, na=False)].copy()
    if pl.empty:
        return pd.DataFrame(columns=["CD_CVM", "DT_REFER", "DT_RECEB", "PATRIMONIO"])

    # Entre "Patrimônio Líquido Consolidado" e "... Atribuído ao Controlador"
    # fica o de código mais curto, que é o consolidado.
    pl["_prof"] = pl["CD_CONTA"].astype(str).str.count(r"\.")
    pl = pl.sort_values(["CD_CVM", "DT_REFER", "_prof"])
    pl = pl.groupby(["CD_CVM", "DT_REFER"], as_index=False).first()

    cols = {"VL_CONTA": "PATRIMONIO"}
    pl = pl.rename(columns=cols)
    if "DT_RECEB" not in pl.columns:
        pl["DT_RECEB"] = pd.NaT
    return pl[["CD_CVM", "DT_REFER", "DT_RECEB", "PATRIMONIO"]].sort_values(
        ["CD_CVM", "DT_REFER"]).reset_index(drop=True)


def patrimonio_vigente(painel, cvm: int, quando, folga_dias: int = 90):
    """Último patrimônio que já havia sido ENTREGUE à CVM em `quando`.

    Quando a data de entrega não existe no arquivo, vale a data de referência
    mais `folga_dias` — o prazo regulatório da DFP é de três meses depois do
    encerramento. É uma aproximação conservadora: atrasa o dado, nunca o
    antecipa.
    """
    import pandas as pd

    sub = painel[painel["CD_CVM"] == cvm]
    if sub.empty:
        return None
    quando = pd.Timestamp(quando)
    entrega = sub["DT_RECEB"].fillna(
        sub["DT_REFER"] + pd.Timedelta(days=folga_dias))
    sub = sub[entrega <= quando]
    if sub.empty:
        return None
    linha = sub.sort_values("DT_REFER").iloc[-1]
    v = linha["PATRIMONIO"]
    return float(v) if _ok(v) else None
