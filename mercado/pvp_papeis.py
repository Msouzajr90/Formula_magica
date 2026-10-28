# -*- coding: utf-8 -*-
"""Histórico do P/VP de cada papel, para o gráfico individual do site.

O irmão de `pvp.py`: lá o P/VP é o do índice inteiro, aqui é o de cada ação,
semana a semana. As peças são as mesmas — patrimônio líquido da CVM com a data
de entrega, nº de ações conciliado entre CVM e valor de mercado, fechamento do
Yahoo — e a disciplina também: em cada semana só entra o balanço que já tinha
sido ENTREGUE à CVM naquela data.

A conta
-------
              preço de fechamento × ações por papel
    P/VP  =  ────────────────────────────────────────
               patrimônio dos controladores ÷ ações

Duas escolhas diferentes do P/VP do índice, ambas porque aqui o número é de
UMA empresa e vai ser lido sozinho:

* **Patrimônio dos controladores**, não o consolidado. O consolidado inclui a
  parte dos sócios minoritários nas controladas, que não pertence a quem
  compra a ação. Na Cury, em 30/06/2026, são R$ 394 mi de R$ 2.049 mi — usar
  o consolidado tiraria quase 20% do P/VP dela. No índice a diferença se dilui
  entre 76 empresas; numa empresa sozinha, não.

* **Semanal**, o último pregão de cada semana. Diário daria 170 papéis × 2.900
  pregões num arquivo que o navegador baixa inteiro; semanal tem o mesmo
  desenho com um quinto do tamanho.

O que esta série NÃO é
----------------------
O nº de ações é o de HOJE, aplicado ao passado. O fechamento do Yahoo já vem
ajustado por desdobramento e grupamento, então essa parte bate; o que não bate
são as emissões e recompras. Uma empresa que emitiu 30% de ações novas em 2021
aparece, antes disso, com patrimônio por ação 30% menor do que era e P/VP 30%
maior. É a mesma aproximação declarada do P/VP do índice, e a tela declara.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import date

from .pvp import ACOES_POR_UNIT, PVP_PLAUSIVEL, data_efetiva, painel_patrimonio

log = logging.getLogger(__name__)

VERSAO = 1
# Descrição da conta de minoritários dentro do PL. Os textos variam ("Participação
# dos Acionistas Não Controladores", "Participação de Não Controladores", "Part.
# dos não controladores"); todos têm "não controlador".
_NAO_CONTROLADOR = re.compile(r"n[ãa]o[\s-]*controlador", re.IGNORECASE)
# Ações por papel quando ele é uma unit. As do P/VP do índice e mais as que só
# aparecem no ranking. Unit fora da lista fica fora do gráfico — dividir o
# patrimônio de uma ação pelo preço de uma unit daria um número várias vezes
# maior, e plausível o bastante para ninguém desconfiar.
ACOES_POR_UNIT_PAPEIS = ACOES_POR_UNIT


def _ok(x) -> bool:
    return x is not None and isinstance(x, (int, float)) \
        and not math.isnan(x) and not math.isinf(x)


def _ns(x):
    """Datas sempre em nanossegundos.

    O pandas 2+ guarda datas em resoluções diferentes conforme a origem: o
    parquet do cache da CVM volta em milissegundos, o Yahoo em micro e um
    `pd.Timestamp` digitado em nano. Comparar ou reindexar mistura sem erro,
    mas o `merge_asof` recusa ("incompatible merge keys ... <M8[ms] and <M8[us]")
    — foi o que derrubou a primeira rodada real. Padronizar na entrada de cada
    função resolve a classe inteira.
    """
    import pandas as pd

    if isinstance(x, pd.Series):
        return pd.to_datetime(x, errors="coerce").astype("datetime64[ns]")
    return pd.DatetimeIndex(pd.to_datetime(x, errors="coerce")).astype("datetime64[ns]")


def eh_unit(ticker: str) -> bool:
    return str(ticker).upper().endswith("11")


# ---------------------------------------------------------------------------
# Patrimônio dos controladores no tempo
# ---------------------------------------------------------------------------
def painel_controladores(bpp, ds_patrimonio: str):
    """Painel de `pvp.painel_patrimonio` com os minoritários descontados.

    O PL consolidado é localizado pela descrição, como lá (em bancos o código
    muda). Os minoritários são a conta, DENTRO dele, cuja descrição fala em
    "não controladores": em empresa comum é a 2.03.09, em banco fica sob o
    2.07 ou o 2.08. Sem a conta, a empresa não tem minoritários e o PL fica.
    """
    import pandas as pd

    base = painel_patrimonio(bpp, ds_patrimonio)
    if base.empty:
        return base.assign(MINORITARIOS=pd.Series(dtype=float))

    ds = bpp["DS_CONTA"].astype("string").str.strip().str.lower()
    pl_rows = bpp[ds.str.startswith(ds_patrimonio, na=False)].copy()
    pl_rows["_prof"] = pl_rows["CD_CONTA"].astype(str).str.count(r"\.")
    cod_pl = (pl_rows.sort_values(["CD_CVM", "DT_REFER", "_prof"])
              .groupby(["CD_CVM", "DT_REFER"], as_index=False).first()
              [["CD_CVM", "DT_REFER", "CD_CONTA"]]
              .rename(columns={"CD_CONTA": "_COD_PL"}))

    mino = bpp[bpp["DS_CONTA"].astype("string").str.contains(
        _NAO_CONTROLADOR, na=False)].copy()
    if mino.empty:
        return base.assign(MINORITARIOS=0.0)
    mino = mino.merge(cod_pl, on=["CD_CVM", "DT_REFER"], how="inner")
    dentro = mino.apply(lambda r: str(r["CD_CONTA"]).startswith(str(r["_COD_PL"]) + "."),
                        axis=1) if len(mino) else pd.Series(dtype=bool)
    mino = mino[dentro] if len(mino) else mino
    if not mino.empty:
        # A mais rasa: "Participação dos Não Controladores" pode ter filhas
        # (por controlada), e somar mãe e filhas contaria duas vezes.
        mino["_prof"] = mino["CD_CONTA"].astype(str).str.count(r"\.")
        mino = (mino.sort_values(["CD_CVM", "DT_REFER", "_prof"])
                .groupby(["CD_CVM", "DT_REFER"], as_index=False).first()
                [["CD_CVM", "DT_REFER", "VL_CONTA"]]
                .rename(columns={"VL_CONTA": "MINORITARIOS"}))
        out = base.merge(mino, on=["CD_CVM", "DT_REFER"], how="left")
    else:
        out = base.assign(MINORITARIOS=pd.NA)
    out["MINORITARIOS"] = pd.to_numeric(out["MINORITARIOS"], errors="coerce").fillna(0.0)
    out["PATRIMONIO"] = out["PATRIMONIO"] - out["MINORITARIOS"]
    return out


# Balanço mais velho que isto não vale para a data: é empresa que parou de
# publicar no formato lido (a Sendas deixou de consolidar em 2021, a Bradespar
# em 2023) e o último PL ficaria valendo para sempre. Quinze meses cobrem o
# prazo da DFP (três meses) sobre um ano inteiro sem ITR.
IDADE_MAXIMA_DIAS = 460


def _vigente_por_data(painel_cvm, datas, folga_dias: int = 90):
    """Para cada data, o PL do último balanço já entregue até ali.

    Reapresentações complicam o "último entregue": a DFP de 2023 refeita em
    2025 é a entrega mais recente, mas não é o balanço mais recente. Por isso,
    em ordem de entrega, só valem as linhas que avançam a data de referência —
    uma reapresentação de balanço velho não faz o PL voltar no tempo.
    """
    import pandas as pd

    if painel_cvm.empty:
        return pd.Series([float("nan")] * len(datas), index=datas), \
            pd.Series([None] * len(datas), index=datas)
    p = painel_cvm.copy()
    p["DT_REFER"] = _ns(p["DT_REFER"])
    p["_EFETIVA"] = _ns(data_efetiva(p, folga_dias))
    p = p.sort_values(["_EFETIVA", "DT_REFER"])
    p = p[p["DT_REFER"] >= p["DT_REFER"].cummax()]
    p = p.drop_duplicates(subset=["DT_REFER"], keep="last")

    alvo = pd.DataFrame({"_DATA": _ns(pd.Index(datas))}).sort_values("_DATA")
    junta = pd.merge_asof(alvo, p[["_EFETIVA", "DT_REFER", "PATRIMONIO"]],
                          left_on="_DATA", right_on="_EFETIVA", direction="backward")
    velho = (junta["_DATA"] - junta["DT_REFER"]) > pd.Timedelta(days=IDADE_MAXIMA_DIAS)
    junta.loc[velho, ["PATRIMONIO", "DT_REFER"]] = pd.NA
    junta.index = pd.Index(datas)
    return pd.to_numeric(junta["PATRIMONIO"], errors="coerce"), junta["DT_REFER"]


# ---------------------------------------------------------------------------
# Datas e série
# ---------------------------------------------------------------------------
def datas_semanais(indice) -> list:
    """O último pregão de cada semana (segunda a domingo), em ordem."""
    import pandas as pd

    idx = _ns(sorted(set(_ns(indice)))).normalize()
    if not len(idx):
        return []
    s = pd.Series(idx, index=idx)
    ultimos = s.groupby(idx.to_period("W-SUN")).max()
    return list(_ns(ultimos.values))


def construir(painel, papeis: dict[str, dict], fechamentos, datas,
              folga_dias: int = 90, casas: int = 2) -> dict[str, dict]:
    """{ticker -> {nome, cvm, s: [P/VP por data], vpa, dtBalanco, fonteAcoes}}.

    `papeis` = {ticker: {"cvm", "acoes", "fonte", "nome"}}; `fechamentos` =
    DataFrame de fechamentos (colunas = tickers sem .SA); `datas` = as datas da
    série (de `datas_semanais`). `vpa` é o patrimônio por PAPEL no fim da série
    (para uma unit, já multiplicado pelas ações que ela carrega): é com ele que
    o site calcula o ponto de hoje a partir do preço do dia.
    """
    import pandas as pd

    datas = list(_ns(datas))
    fech = fechamentos.copy()
    fech.index = _ns(fech.index).normalize()
    fech = fech.reindex(_ns(datas))

    saida: dict[str, dict] = {}
    fora: dict[str, str] = {}
    for ticker, info in sorted(papeis.items()):
        acoes = info.get("acoes")
        if not _ok(acoes) or acoes <= 0:
            fora[ticker] = "sem nº de ações"
            continue
        fator = 1
        if eh_unit(ticker):
            fator = ACOES_POR_UNIT_PAPEIS.get(ticker)
            if fator is None or info.get("fonte") != "cvm":
                fora[ticker] = ("unit sem fator conhecido" if fator is None
                                else "unit sem nº de ações confirmado pela CVM")
                continue
        if ticker not in fech.columns:
            fora[ticker] = "sem cotação"
            continue

        sub = painel[painel["CD_CVM"] == info["cvm"]]
        pl, ref = _vigente_por_data(sub, datas, folga_dias)
        precos = fech[ticker]
        valores = []
        for d in datas:
            px, v = precos.get(d), pl.get(d)
            if not (_ok(px) and _ok(v)) or v <= 0 or px <= 0:
                valores.append(None)
                continue
            p = px / (v / acoes * fator)
            valores.append(round(p, casas) if PVP_PLAUSIVEL[0] <= p <= PVP_PLAUSIVEL[1]
                           else None)
        if not any(x is not None for x in valores):
            fora[ticker] = "sem patrimônio positivo no período"
            continue

        pl_fim = pl.iloc[-1] if len(pl) else None
        ref_fim = ref.iloc[-1] if len(ref) else None
        saida[ticker] = {
            "nome": info.get("nome"),
            "cvm": int(info["cvm"]),
            "s": valores,
            "vpa": (round(pl_fim / acoes * fator, 4)
                    if _ok(pl_fim) and pl_fim > 0 else None),
            "dtBalanco": (pd.Timestamp(ref_fim).date().isoformat()
                          if ref_fim is not None and not pd.isna(ref_fim) else None),
            "fonteAcoes": info.get("fonte") or "cvm",
        }
    if fora:
        log.info("%d papéis ficaram fora do histórico: %s", len(fora),
                 "; ".join(f"{k} ({v})" for k, v in list(fora.items())[:30]))
    return {"papeis": saida, "fora": fora}


def montar_arquivo(resultado: dict, datas, desde: int,
                   gerado_em: str | None = None) -> dict:
    import pandas as pd

    return {
        "meta": {
            "versao": VERSAO,
            "geradoEm": gerado_em or pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "desde": desde,
            "frequencia": "semanal (último pregão da semana)",
            "patrimonio": "controladores (consolidado menos minoritários)",
            "acoes": "nº de ações de hoje aplicado ao passado",
            "fora": resultado.get("fora", {}),
        },
        "datas": [pd.Timestamp(d).date().isoformat() for d in datas],
        "papeis": resultado["papeis"],
    }


# ---------------------------------------------------------------------------
# O ponto da semana, pelo robô
# ---------------------------------------------------------------------------
def _semana(d) -> tuple[int, int]:
    iso = date.fromisoformat(str(d)[:10]).isocalendar()
    return iso[0], iso[1]


def atualizar_semana(dados: dict, precos: dict[str, float], quando: date) -> bool:
    """Grava o ponto da semana de `quando` com o VPA guardado. True se mudou.

    O robô não alcança a CVM (ver `gerar_pvp_papeis.py`), então não sabe de
    balanço novo: ele só move o preço. O VPA é o do último balanço que o
    script local processou, e a tela diz de quando ele é.

    Mesma semana do último ponto → substitui; semana nova → acrescenta. Papel
    sem preço hoje fica com null nessa semana, em vez de repetir o anterior.
    """
    datas = dados.get("datas") or []
    papeis = dados.get("papeis") or {}
    if not papeis:
        return False
    hoje = quando.isoformat()
    if datas and _semana(datas[-1]) > _semana(hoje):
        return False                       # data velha: não reescreve o passado
    nova = not datas or _semana(datas[-1]) != _semana(hoje)
    mudou = False
    if nova:
        datas.append(hoje)
        mudou = True
    elif datas[-1] != hoje:
        datas[-1] = hoje
        mudou = True
    for t, info in papeis.items():
        s = info.setdefault("s", [])
        while len(s) < len(datas) - (1 if nova else 0):
            s.append(None)
        px, vpa = precos.get(t), info.get("vpa")
        v = None
        if _ok(px) and _ok(vpa) and vpa > 0 and px > 0:
            p = px / vpa
            v = round(p, 2) if PVP_PLAUSIVEL[0] <= p <= PVP_PLAUSIVEL[1] else None
        if nova:
            s.append(v)
            mudou = True
        elif s and s[-1] != v and v is not None:
            s[-1] = v
            mudou = True
    dados["datas"] = datas
    return mudou
