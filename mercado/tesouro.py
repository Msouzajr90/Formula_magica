# -*- coding: utf-8 -*-
"""Curvas de juros brasileiras, a partir do Tesouro Transparente.

Por que esta fonte e não a ANBIMA
---------------------------------
A ANBIMA é a referência de mercado para taxas de títulos públicos, e foi a
primeira tentativa. Os endereços antigos (`merc-sec.asp`, `est-termo/CZ.asp`)
respondem 404 hoje: o formulário da página ainda aponta para eles, mas o
servidor não os serve mais. O portal novo (`data.anbima.com.br`) exige
credencial. Não há caminho gratuito e estável ali.

O Tesouro Transparente publica um CSV único, atualizado todo dia útil de
manhã com o fechamento do dia anterior, com a taxa de **todos** os títulos
ofertados desde 2004. Um arquivo, um formato, vinte e um anos de histórico —
e é dele que saem de graça as quatro fotos que a tela pede (hoje, uma semana,
um mês e seis meses atrás), sem precisar guardar nada.

O preço disso: são as taxas do Tesouro Direto, do varejo, não as indicativas
do mercado secundário. Ficam alguns poucos pontos-base distantes das da
ANBIMA, e os vencimentos são os que o Tesouro oferta ao varejo, não todos os
que existem em mercado.

O que a curva prefixada alcança
-------------------------------
O vencimento prefixado mais longo ofertado é a NTN-F de 2037 — cerca de onze
anos. Não existe título prefixado brasileiro de vinte anos, nem no varejo nem
no atacado. A curva prefixada da tela, portanto, **termina onde os dados
terminam** e não é esticada até 20 anos: preencher o vazio seria inventar
número. A de NTN-B vai a 2060 e cobre os 20 anos com folga.

Convenção das taxas
-------------------
São efetivas ao ano, capitalização anual — a convenção brasileira. Importa
quando se compara com a americana, que é semestral (ver `treasury.py`).
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

log = logging.getLogger(__name__)

# O endereço do recurso no CKAN do Tesouro. O `package_show` abaixo existe
# porque o id do recurso já mudou uma vez; resolver pelo nome do conjunto é
# mais estável que fixar a URL final.
CKAN_PACOTE = ("https://www.tesourotransparente.gov.br/ckan/api/3/action/"
               "package_show?id=taxas-dos-titulos-ofertados-pelo-tesouro-direto")
CSV_PADRAO = ("https://www.tesourotransparente.gov.br/ckan/dataset/"
              "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
              "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/"
              "precotaxatesourodireto.csv")

# Só os títulos que formam as duas curvas. Selic é pós-fixado (não tem curva),
# IGPM+ tem um só vencimento vivo, e Renda+/Educa+ são IPCA com fluxo de
# pagamento diferente — misturá-los com a NTN-B deslocaria a curva por causa
# da estrutura do fluxo, não do juro.
FAMILIAS = {
    "Tesouro Prefixado":                    ("pre",  "zero"),
    "Tesouro Prefixado com Juros Semestrais": ("pre",  "cupom"),
    "Tesouro IPCA+":                        ("ipca", "zero"),
    "Tesouro IPCA+ com Juros Semestrais":   ("ipca", "cupom"),
}

DIAS_NO_ANO = 365.25

# Prazo mínimo para um título entrar na curva — diferente por família, e as
# duas razões são diferentes.
#
# Prefixado, 3 meses: num papel prestes a vencer o preço é praticamente o de
# face, e um centavo de arredondamento vira pontos percentuais quando
# anualizado sobre poucos dias.
#
# NTN-B, 1 ano: além disso, a correção pelo IPCA é defasada. Boa parte da
# inflação do período de uma NTN-B curta já está conhecida e travada, então a
# "taxa real" cotada dela mede a defasagem do índice, não o juro real daquele
# prazo. O mercado nem quota a ponta curta da curva real por NTN-B — usa o
# cupom de IPCA nos futuros.
#
# As duas apareceram nos dados de verdade, não em teoria:
#   14/08/2026  NTN-B 15/08/2026 (1 dia)     13,32% real, contra 8,04% da seguinte
#   16/03/2026  NTN-B 15/08/2026 (5 meses)    9,88% real, contra 8,21% da seguinte
# Sem o corte, o vértice de 1 ano da curva real saía perto de 10% num gráfico
# em que todo o resto está entre 7% e 8% — e o desenho não denunciava nada.
PRAZO_MINIMO = {"pre": 0.25, "ipca": 1.0}


@dataclass(frozen=True)
class Vertice:
    """Um título: um ponto observado da curva."""
    vencimento: date
    prazo: float          # anos entre a data-base e o vencimento
    taxa: float           # % ao ano, efetiva
    cupom: bool           # True se a taxa é de um título com juros semestrais

    def como_dict(self) -> dict:
        return {"vencimento": self.vencimento.isoformat(),
                "prazo": round(self.prazo, 4),
                "taxa": round(self.taxa, 4),
                "cupom": self.cupom}


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
def endereco_do_csv(sessao=None) -> str:
    """Resolve o endereço do CSV pelo catálogo; cai no fixo se o catálogo falhar."""
    import requests

    s = sessao or requests
    try:
        r = s.get(CKAN_PACOTE, timeout=60)
        r.raise_for_status()
        recursos = r.json()["result"]["resources"]
        for rec in recursos:
            if str(rec.get("format", "")).upper() == "CSV":
                url = rec["url"]
                log.info("CSV do Tesouro: %s", url)
                return url
    except Exception as exc:                                   # noqa: BLE001
        log.warning("Catálogo do Tesouro indisponível (%s); usando o endereço fixo.", exc)
    return CSV_PADRAO


def baixar_csv(sessao=None, timeout: int = 300) -> str:
    """Baixa o CSV inteiro (~15 MB) e devolve como texto."""
    import requests

    s = sessao or requests
    url = endereco_do_csv(sessao)
    r = s.get(url, timeout=timeout)
    r.raise_for_status()
    # O arquivo é windows-1252: tem "Prefixado" sem acento mas "Título" com.
    return r.content.decode("windows-1252", errors="replace")


# ---------------------------------------------------------------------------
# Leitura (sem rede — é aqui que os testes batem)
# ---------------------------------------------------------------------------
def ler_csv(texto: str) -> pd.DataFrame:
    """Texto do CSV -> tabela com TIPO, FAMILIA, CUPOM, VENCIMENTO, DATA, TAXA.

    A taxa é a média entre compra e venda quando as duas existem. A de venda
    falta nos títulos que o Tesouro não recompra; nesses casos vale a de
    compra sozinha. Zero é ausência disfarçada de número e é tratado como
    ausência — um título não tem juro de 0,00% ao ano.
    """
    df = pd.read_csv(io.StringIO(texto), sep=";", decimal=",", dtype=str)
    df.columns = [c.strip() for c in df.columns]

    col = {c.lower(): c for c in df.columns}
    c_tipo = col["tipo titulo"]
    c_venc = col["data vencimento"]
    c_base = col["data base"]
    c_compra = col["taxa compra manha"]
    c_venda = col.get("taxa venda manha")

    df = df[df[c_tipo].isin(FAMILIAS)].copy()
    if df.empty:
        raise ValueError("Nenhum título prefixado ou IPCA+ no arquivo do Tesouro. "
                         "O vocabulário da coluna 'Tipo Titulo' provavelmente mudou; "
                         "os valores vistos foram: "
                         + ", ".join(sorted(set(pd.read_csv(
                             io.StringIO(texto), sep=";", dtype=str,
                             usecols=[0]).iloc[:, 0].dropna()))[:12]))

    def numero(serie):
        v = pd.to_numeric(serie.astype(str).str.replace(",", ".", regex=False),
                          errors="coerce")
        return v.where(v > 0)

    compra = numero(df[c_compra])
    venda = numero(df[c_venda]) if c_venda else pd.Series(index=df.index, dtype=float)
    df["TAXA"] = pd.concat([compra, venda], axis=1).mean(axis=1, skipna=True)

    df["VENCIMENTO"] = pd.to_datetime(df[c_venc], format="%d/%m/%Y", errors="coerce")
    df["DATA"] = pd.to_datetime(df[c_base], format="%d/%m/%Y", errors="coerce")
    df["FAMILIA"] = df[c_tipo].map(lambda t: FAMILIAS[t][0])
    df["CUPOM"] = df[c_tipo].map(lambda t: FAMILIAS[t][1] == "cupom")

    df = df.dropna(subset=["TAXA", "VENCIMENTO", "DATA"])
    # Só faz sentido o que ainda não venceu na data em que foi cotado.
    df = df[df["VENCIMENTO"] > df["DATA"]]
    return df[["FAMILIA", "CUPOM", "VENCIMENTO", "DATA", "TAXA"]].reset_index(drop=True)


def datas_disponiveis(df: pd.DataFrame) -> list[date]:
    return sorted({d.date() for d in df["DATA"].unique()})


def data_mais_proxima(datas: list[date], alvo: date) -> date | None:
    """Último pregão com dado em `alvo` ou antes.

    Nunca olha para a frente: uma foto de "seis meses atrás" que pegasse o
    pregão seguinte ao alvo estaria usando informação que não existia ali.
    """
    anteriores = [d for d in datas if d <= alvo]
    return max(anteriores) if anteriores else None


def curva(df: pd.DataFrame, familia: str, quando: date) -> list[Vertice]:
    """Pontos observados de uma família numa data.

    Quando o mesmo vencimento aparece nas duas versões — a zero-cupom e a de
    juros semestrais — fica a zero-cupom. A taxa de um título com cupom é uma
    TIR (mede o fluxo inteiro, não o prazo final), e a do zero-cupom é a taxa
    à vista daquele prazo, que é o que uma curva de juros quer dizer. As de
    cupom entram só onde não há zero-cupom, e a tela marca quais são.
    """
    sel = df[(df["FAMILIA"] == familia) & (df["DATA"] == pd.Timestamp(quando))]
    if sel.empty:
        return []
    sel = sel.sort_values(["VENCIMENTO", "CUPOM"])          # False < True: zero primeiro
    sel = sel.drop_duplicates(subset=["VENCIMENTO"], keep="first")

    minimo = PRAZO_MINIMO.get(familia, 0.25)
    saida = []
    for r in sel.itertuples():
        prazo = (r.VENCIMENTO.date() - quando).days / DIAS_NO_ANO
        if prazo < minimo:
            continue
        saida.append(Vertice(vencimento=r.VENCIMENTO.date(), prazo=prazo,
                             taxa=float(r.TAXA), cupom=bool(r.CUPOM)))
    return sorted(saida, key=lambda v: v.prazo)


def fotos(df: pd.DataFrame, hoje: date | None = None) -> dict[str, date]:
    """As quatro datas da tela: hoje, -1 semana, -1 mês, -6 meses.

    "Hoje" é o último pregão publicado, que normalmente é o de ontem: o
    Tesouro publica o fechamento de D-1 na manhã de D.
    """
    datas = datas_disponiveis(df)
    if not datas:
        return {}
    fim = data_mais_proxima(datas, hoje) if hoje else datas[-1]
    if fim is None:
        return {}
    alvos = {"hoje": fim,
             "semana": fim - pd.Timedelta(days=7).to_pytimedelta(),
             "mes": fim - pd.Timedelta(days=30).to_pytimedelta(),
             "semestre": fim - pd.Timedelta(days=182).to_pytimedelta()}
    saida = {}
    for nome, alvo in alvos.items():
        d = data_mais_proxima(datas, alvo)
        if d is not None:
            saida[nome] = d
    return saida


def _hoje_do_arquivo(texto: str) -> date:
    linhas = [l for l in texto.splitlines() if l.strip()][1:]
    return max(datetime.strptime(l.split(";")[2], "%d/%m/%Y").date() for l in linhas)
