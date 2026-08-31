"""Dados sintéticos para conhecer a interface sem depender de rede.

Nada aqui é usado no modo de dados reais.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from . import config as C
from . import backtest, fundamentals, optimizer, ranking
from .pipeline import Resultado

_NOMES = [
    ("PETR4", "Petróleo Brasileiro S.A."), ("VALE3", "Vale S.A."),
    ("ITSA4", "Itaúsa S.A."), ("WEGE3", "WEG S.A."), ("SUZB3", "Suzano S.A."),
    ("GGBR4", "Gerdau S.A."), ("PRIO3", "PetroRio S.A."), ("RADL3", "Raia Drogasil"),
    ("LREN3", "Lojas Renner S.A."), ("EMBR3", "Embraer S.A."),
    ("KLBN11", "Klabin S.A."), ("CSNA3", "Cia Siderúrgica Nacional"),
    ("SLCE3", "SLC Agrícola S.A."), ("UNIP6", "Unipar Carbocloro"),
    ("FESA4", "Ferbasa S.A."), ("TASA4", "Taurus Armas S.A."),
    ("VULC3", "Vulcabras S.A."), ("CMIN3", "CSN Mineração"),
    ("RANI3", "Irani Papel e Embalagem"), ("LEVE3", "Mahle Metal Leve"),
    ("SMTO3", "São Martinho S.A."), ("PSSA3", "Porto Seguro S.A."),
    ("ODPV3", "Odontoprev S.A."), ("GRND3", "Grendene S.A."),
    ("MYPK3", "Iochpe-Maxion S.A."), ("POMO4", "Marcopolo S.A."),
    ("TUPY3", "Tupy S.A."), ("SHUL4", "Schulz S.A."),
    ("EZTC3", "EZTEC Empreendimentos"), ("DIRR3", "Direcional Engenharia"),
    ("CURY3", "Cury Construtora"), ("PLPL3", "Plano & Plano"),
    ("BRAP4", "Bradespar S.A."), ("AGRO3", "BrasilAgro"), ("JHSF3", "JHSF Part."),
]
_SETORES = ["Petróleo e Gás", "Mineração", "Siderurgia", "Máquinas e Equip.",
            "Papel e Celulose", "Comércio", "Construção Civil", "Agropecuária",
            "Material de Transporte", "Alimentos"]


def _universo_sintetico(seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = len(_NOMES)
    ebit = rng.lognormal(20.5, 1.1, n)
    ev = ebit * rng.lognormal(2.0, 0.55, n)
    divida = ev * rng.uniform(0.0, 0.45, n)
    df = pd.DataFrame({
        "CD_CVM": np.arange(1, n + 1),
        "TICKER": [f"{t}.SA" for t, _ in _NOMES],
        "DENOM_CIA": [d for _, d in _NOMES],
        "SETOR": rng.choice(_SETORES, n),
        "EBIT_LTM": ebit,
        "EV": ev,
        "VALOR_MERCADO": ev - divida,
        "DIVIDA_LIQUIDA": divida,
        "CAPITAL_TANGIVEL": ebit / rng.uniform(0.10, 0.70, n),
        "PRECO": rng.uniform(6, 90, n).round(2),
        "LIQUIDEZ_MEDIA": rng.lognormal(16.5, 1.2, n),
        "DT_BASE": pd.Timestamp(date.today()) - pd.Timedelta(days=75),
        "FONTE": "DEMONSTRAÇÃO (dados sintéticos)",
    })
    df["ACOES"] = df["VALOR_MERCADO"] / df["PRECO"]
    df["ROIC"] = df["EBIT_LTM"] / df["CAPITAL_TANGIVEL"]
    df["EY"] = df["EBIT_LTM"] / df["EV"]
    return df


def _retornos_sinteticos(tickers: list[str], dias: int, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    p = len(tickers)
    mercado = rng.normal(0.0005, 0.011, dias)
    betas = rng.uniform(0.35, 1.75, p)
    vol_idio = rng.uniform(0.008, 0.024, p)
    alfas = rng.normal(0.0002, 0.0004, p)
    X = (alfas[None, :] + mercado[:, None] * betas[None, :]
         + rng.normal(0, 1, (dias, p)) * vol_idio[None, :])
    idx = pd.bdate_range(end=pd.Timestamp(date.today()), periods=dias)
    return pd.DataFrame(X, index=idx, columns=tickers)


def resultado_demo(params: C.Params) -> Resultado:
    uni = _universo_sintetico()
    aprov, rejeit = fundamentals.aplicar_filtros(uni, params)
    rk = ranking.ranquear(aprov, n=params.n_acoes_ranking)
    sel = rk[rk["SELECIONADA"]].copy()

    rets = _retornos_sinteticos(sel["TICKER"].tolist(), params.janela_retornos_dias)
    mu, cov = optimizer.estimar(rets, params.metodo_retorno, params.metodo_covariancia)
    fr = optimizer.fronteira_eficiente(
        mu, cov, pontos=params.n_carteiras_fronteira,
        w_max=params.peso_maximo_ativo, w_min=params.peso_minimo_ativo,
        rf=params.taxa_livre_risco_aa)

    return Resultado(
        ranking=rk, selecionadas=sel, rejeitadas=rejeit,
        pesos=optimizer.limpar_pesos(fr.pesos.iloc[:, 0]),
        fronteira=fr, retornos=rets, mu=mu, cov=cov,
        diagnostico={"modo": "DEMONSTRAÇÃO — dados sintéticos, não use para investir",
                     "universo_bruto": len(uni),
                     "aprovados_nos_filtros": len(aprov),
                     "rejeitados": len(rejeit),
                     "gerado_em": str(pd.Timestamp.now())},
    )


def backtest_demo(pesos: pd.Series, ini, fim, params: C.Params):
    dias = max(30, len(pd.bdate_range(ini, fim)))
    rets = _retornos_sinteticos(list(pesos.index), dias, seed=99)
    bench = rets.mean(axis=1) * 0.92
    rp = backtest.retorno_carteira(rets, pesos, custo_bps=params.custo_transacao_bps)
    return rp, bench
