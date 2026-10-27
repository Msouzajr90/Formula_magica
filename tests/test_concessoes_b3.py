# -*- coding: utf-8 -*-
"""Concessionárias com o intangível no capital, e a B3 fora do ranking.

Os números são os balanços consolidados de 30/06/2026 (ITR da CVM), em R$ mi.
"""
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from magicb3 import config as C
from magicb3 import fundamentals

import atualizar_dados


def _universo():
    """ECOR3 e MOTV3 (concessão no intangível), RENT3 (locadora do mesmo setor,
    intangível = ágio), SBSP3 (saneamento), B3SA3 e uma operacional comum."""
    mi = 1e6
    return pd.DataFrame({
        "CD_CVM": [19453, 18821, 19739, 14443, 21610, 1],
        "TICKER": ["ECOR3.SA", "MOTV3.SA", "RENT3.SA", "SBSP3.SA", "B3SA3.SA", "OPA3.SA"],
        "DENOM_CIA": ["Ecorodovias", "Motiva", "Localiza", "Sabesp", "B3", "Op A"],
        "SETOR": ["Serviços Transporte e Logística", "Serviços Transporte e Logística",
                  "Serviços Transporte e Logística", "Saneamento, Serv. Água e Gás",
                  "Bolsas de Valores/Mercadorias e Futuros", "Comércio"],
        "EBIT_LTM": [4147 * mi, 7833 * mi, 9000 * mi, 9000 * mi, 7247 * mi, 1000 * mi],
        "LUCRO_LTM": [100 * mi, 2000 * mi, 3000 * mi, 5000 * mi, 4900 * mi, 600 * mi],
        "PATRIMONIO": [4399 * mi, 15000 * mi, 25000 * mi, 50000 * mi, 18729 * mi, 3000 * mi],
        "VALOR_MERCADO": [3610 * mi, 30000 * mi, 50000 * mi, 80000 * mi, 75871 * mi, 5000 * mi],
        "ACOES": [1e9] * 6,
        "LIQUIDEZ_MEDIA": [50e6] * 6,
        C.CD_ATIVO_TOTAL: [39586 * mi, 79123 * mi, 90820 * mi, 90000 * mi, 48951 * mi, 5000 * mi],
        C.CD_ATIVO_CIRCULANTE: [6272 * mi, 15000 * mi, 20000 * mi, 15000 * mi, 19048 * mi, 2000 * mi],
        C.CD_CAIXA: [3206 * mi, 8000 * mi, 8000 * mi, 5000 * mi, 1163 * mi, 300 * mi],
        C.CD_APLIC_FINANCEIRAS: [1921 * mi, 2000 * mi, 4000 * mi, 1000 * mi, 15339 * mi, 0.0],
        C.CD_PASSIVO_CIRCULANTE: [2483 * mi, 9000 * mi, 15000 * mi, 12000 * mi, 9942 * mi, 900 * mi],
        C.CD_EMPRESTIMOS_CP: [896 * mi, 3000 * mi, 5000 * mi, 3000 * mi, 2623 * mi, 200 * mi],
        C.CD_EMPRESTIMOS_LP: [27955 * mi, 30000 * mi, 30000 * mi, 25000 * mi, 12310 * mi, 800 * mi],
        C.CD_INVESTIMENTOS: [2 * mi, 500 * mi, 0.0, 100 * mi, 126 * mi, 0.0],
        C.CD_IMOBILIZADO: [783 * mi, 1900 * mi, 56000 * mi, 900 * mi, 828 * mi, 1200 * mi],
        C.CD_INTANGIVEL: [29084 * mi, 39600 * mi, 9000 * mi, 38000 * mi, 25535 * mi, 0.0],
    })


def _indicadores(uni, params):
    mercado = uni[["CD_CVM", "TICKER", "SETOR", "VALOR_MERCADO", "ACOES", "LIQUIDEZ_MEDIA"]]
    ebit = uni[["CD_CVM", "DENOM_CIA", "EBIT_LTM", "LUCRO_LTM"]]
    bp = uni.drop(columns=["DENOM_CIA", "EBIT_LTM", "LUCRO_LTM", "TICKER", "SETOR",
                           "VALOR_MERCADO", "ACOES", "LIQUIDEZ_MEDIA"])
    return fundamentals.montar_indicadores(ebit, bp, mercado, params).set_index("TICKER")


# ---------------------------------------------------------------------------
# Concessionárias
# ---------------------------------------------------------------------------
def test_ecorodovias_com_a_rodovia_no_capital():
    """Regressão: 529% de ROIC com a rodovia fora do capital; ~14% com ela."""
    ind = _indicadores(_universo(), C.Params())
    assert bool(ind.loc["ECOR3.SA", "CONCESSAO"])
    assert ind.loc["ECOR3.SA", "CAPITAL_TANGIVEL"] == pytest.approx((783 + 2 + 29084) * 1e6)
    assert ind.loc["ECOR3.SA", "ROIC"] == pytest.approx(4147 / 29869, rel=1e-6)


def test_sem_a_regra_volta_o_artefato():
    ind = _indicadores(_universo(), C.Params(incluir_intangivel_concessao=False))
    assert not ind["CONCESSAO"].any()
    assert ind.loc["ECOR3.SA", "ROIC"] > 5          # os 529% de antes


def test_motiva_tambem_e_concessao():
    ind = _indicadores(_universo(), C.Params())
    assert bool(ind.loc["MOTV3.SA", "CONCESSAO"])
    assert 0.10 < ind.loc["MOTV3.SA", "ROIC"] < 0.25


def test_locadora_do_mesmo_setor_nao_ganha_o_agio():
    """Na Localiza o intangível é ágio, e o ativo é a frota no imobilizado."""
    ind = _indicadores(_universo(), C.Params())
    assert not bool(ind.loc["RENT3.SA", "CONCESSAO"])
    giro = max((20000 - 8000 - 4000) - (15000 - 5000), 0)
    assert ind.loc["RENT3.SA", "CAPITAL_TANGIVEL"] == pytest.approx((giro + 56000) * 1e6)


def test_saneamento_tambem_recebe_a_concessao():
    """Vale para as utilidades, que têm ranking próprio quando há vagas."""
    ind = _indicadores(_universo(), C.Params())
    assert bool(ind.loc["SBSP3.SA", "CONCESSAO"])


def test_operacional_comum_nao_muda():
    ind = _indicadores(_universo(), C.Params())
    assert not bool(ind.loc["OPA3.SA", "CONCESSAO"])
    assert ind.loc["OPA3.SA", "CAPITAL_TANGIVEL"] == pytest.approx(
        ((2000 - 300) - (900 - 200) + 1200) * 1e6)


def test_sem_coluna_de_intangivel_nao_quebra():
    """O fundamentos.json antigo pode não trazer o intangível."""
    uni = _universo().drop(columns=[C.CD_INTANGIVEL])
    ind = _indicadores(uni, C.Params())
    assert not ind["CONCESSAO"].any()


# ---------------------------------------------------------------------------
# B3 fora do ranking
# ---------------------------------------------------------------------------
def test_setor_da_b3_casa_com_o_filtro_de_financeiras():
    """O padrão estava no singular ("bolsa de valores") e nunca casava."""
    df = pd.DataFrame({"SETOR": ["Bolsas de Valores/Mercadorias e Futuros"]})
    assert bool(fundamentals.eh_financeira(df).iloc[0])


def test_b3_sai_com_motivo_e_nota():
    p = C.Params(liquidez_minima_diaria=1e6, vagas_financeiras=5, vagas_utilidades=5)
    ok, fora = fundamentals.aplicar_filtros(_indicadores(_universo(), p).reset_index(), p)
    assert "B3SA3.SA" not in set(ok["TICKER"])
    linha = fora.set_index("TICKER").loc["B3SA3.SA"]
    assert "decisão de método" in linha["MOTIVO_EXCLUSAO"]
    assert "Cetip" in linha["NOTA_EXCLUSAO"]


def test_exportacao_leva_nota_e_marca_de_concessao():
    rk = pd.DataFrame({
        "TICKER": ["ECOR3.SA", "OPA3.SA"], "DENOM_CIA": ["Eco", "Op"],
        "SETOR": ["Transporte", "Comércio"], "TIPO": ["operacional"] * 2,
        "ROIC": [0.14, 0.3], "EY": [0.15, 0.1], "POS_ROIC": [2, 1], "POS_EY": [1, 2],
        "RANK_FINAL": [3, 3], "CONCESSAO": [True, False], "SELECIONADA": [True, True],
    })
    rej = pd.DataFrame({
        "TICKER": ["B3SA3.SA"], "DENOM_CIA": ["B3"], "SETOR": ["Bolsas"],
        "MOTIVO_EXCLUSAO": ["fora"], "NOTA_EXCLUSAO": ["nota da B3"],
    })
    res = SimpleNamespace(ranking=rk, rejeitadas=rej, cov=pd.DataFrame(),
                          mu=pd.Series(dtype=float), diagnostico={})
    d = atualizar_dados.montar_json(res, C.Params(), pool=2)
    por = {e["ticker"]: e for e in d["empresas"]}
    assert por["ECOR3"].get("concessao") is True
    assert "concessao" not in por["OPA3"]
    assert d["excluidas"][0]["nota"] == "nota da B3"
