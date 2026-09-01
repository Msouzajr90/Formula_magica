# -*- coding: utf-8 -*-
"""Roda o gerar_historico.gerar() inteiro com dados falsos.

Existe porque o ciclo de feedback real e de duas horas: a rodada baixa CVM e
cotacoes por 140 minutos e so entao descobre um KeyError no ultimo passo. Foi
o que aconteceu com ['SETOR']. Este teste percorre o mesmo caminho em
segundos, sem tocar na rede.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gerar_historico as gh
from magicb3 import config as C, cvm, prices, tickers

N = 30
HOJE = date(2026, 9, 1)
CONTAS_BP_FALSAS = {
    "1.01": 8e8, "1.01.01": 1e8, "1.01.02": 5e7, "1.02.02": 2e8,
    "2.01": 3e8, "2.01.04": 1e8, "1.02.03": 6e8, "2.01.03": 0.0,
}


def _empresas() -> pd.DataFrame:
    return pd.DataFrame({
        "CD_CVM": np.arange(1, N + 1),
        "PREFIXO": [f"EM{chr(65 + i // 26)}{chr(65 + i % 26)}" for i in range(N)],
        "DENOM_CIA": [f"Empresa {i}" for i in range(N)],
        "NOME_PREGAO": [f"EMP {i}" for i in range(N)],
        "SEGMENTO": "Novo Mercado",
    })


def _dre(anual: bool, ano: int) -> pd.DataFrame:
    ref = pd.Timestamp(ano, 12, 31) if anual else pd.Timestamp(ano, 6, 30)
    ini = pd.Timestamp(ano, 1, 1)
    linhas = []
    for cd in range(1, N + 1):
        for conta, base in ((C.CD_EBIT, 3e8), (C.CD_LUCRO_LIQUIDO, 2e8)):
            linhas.append({
                "CD_CVM": cd, "CNPJ_CIA": f"{cd:014d}", "DENOM_CIA": f"Empresa {cd}",
                "CD_CONTA": conta, "DS_CONTA": "conta", "VL_CONTA": base * (1 + cd / 50),
                "DT_REFER": ref, "DT_INI_EXERC": ini, "DT_FIM_EXERC": ref,
                "DT_RECEB": ref + pd.Timedelta(days=60),
            })
    return pd.DataFrame(linhas)


def _balanco(ano: int) -> pd.DataFrame:
    ref = pd.Timestamp(ano, 12, 31)
    linhas = []
    for cd in range(1, N + 1):
        for conta, valor in CONTAS_BP_FALSAS.items():
            linhas.append({
                "CD_CVM": cd, "CNPJ_CIA": f"{cd:014d}", "DENOM_CIA": f"Empresa {cd}",
                "CD_CONTA": conta, "DS_CONTA": "conta", "VL_CONTA": valor,
                "DT_REFER": ref, "DT_INI_EXERC": pd.Timestamp(ano, 1, 1),
                "DT_FIM_EXERC": ref, "DT_RECEB": ref + pd.Timedelta(days=60),
            })
        linhas.append({
            "CD_CVM": cd, "CNPJ_CIA": f"{cd:014d}", "DENOM_CIA": f"Empresa {cd}",
            "CD_CONTA": "2.03", "DS_CONTA": "Patrimônio Líquido Consolidado",
            "VL_CONTA": 9e8, "DT_REFER": ref, "DT_INI_EXERC": pd.Timestamp(ano, 1, 1),
            "DT_FIM_EXERC": ref, "DT_RECEB": ref + pd.Timedelta(days=60),
        })
    return pd.DataFrame(linhas)


def _demonstracoes(anos, tipo, **kw):
    anual = tipo == "dfp"
    dre = pd.concat([_dre(anual, a) for a in anos], ignore_index=True)
    bp = pd.concat([_balanco(a) for a in anos], ignore_index=True)
    return {"DRE": dre, "BPA": bp, "BPP": bp}


def _tickers_falsos(emp: pd.DataFrame) -> list[str]:
    return [f"{p}3.SA" for p in emp["PREFIXO"]]


@pytest.fixture
def sem_rede(monkeypatch):
    emp = _empresas()
    simbolos = _tickers_falsos(emp)
    pregoes = pd.bdate_range("2021-01-01", "2026-08-31")
    rng = np.random.default_rng(5)
    px = pd.DataFrame(
        20 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, (len(pregoes), len(simbolos))), 0)),
        index=pregoes, columns=simbolos)
    vol = pd.DataFrame(5e5, index=pregoes, columns=simbolos)

    def _hist(tickers_, inicio, fim, **kw):
        pedidos = [t for t in tickers_ if t in px.columns]
        if not pedidos:                      # o benchmark
            b = pd.DataFrame(
                100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, len(pregoes)))),
                index=pregoes, columns=list(tickers_)[:1])
            return {"preco": b, "fechamento": b, "volume": b * 0 + 1e6}
        return {"preco": px[pedidos], "fechamento": px[pedidos], "volume": vol[pedidos]}

    monkeypatch.setattr(cvm, "carregar_demonstracoes", _demonstracoes)
    monkeypatch.setattr(cvm, "carregar_cadastro", lambda **kw: pd.DataFrame(
        {"CD_CVM": emp["CD_CVM"], "SETOR_ATIV": "Comércio", "SIT": "ATIVO"}))
    monkeypatch.setattr(tickers, "baixar_empresas_b3", lambda **kw: emp)
    monkeypatch.setattr(prices, "baixar_historico", _hist)
    monkeypatch.setattr(prices, "acoes_em_circulacao",
                        lambda t, **kw: pd.Series(1e8, index=list(t)))
    class _Hoje(date):
        @classmethod
        def today(cls):
            return HOJE

    monkeypatch.setattr(gh, "date", _Hoje)
    return emp


def test_gerar_historico_de_ponta_a_ponta(sem_rede, tmp_path):
    saida = tmp_path / "historico.json"
    dados = gh.gerar(anos=5, freq="anual", pool=20, liquidez=1e5,
                     saida=saida, usar_cache=False)

    assert dados["meta"]["pointInTime"] is True
    assert dados["meta"]["nRebalances"] >= 3, "poucas datas de rebalanceamento"
    assert dados["meta"]["nTickers"] >= 15
    assert len(dados["benchmark"]) == len(dados["pregoes"])
    for nome, serie in dados["retornos"].items():
        assert len(serie) == len(dados["pregoes"]), f"serie de {nome} desalinhada"
    for reb in dados["rebalances"]:
        assert reb["acoes"], f"{reb['data']} sem ranking"
        for a in reb["acoes"]:
            assert set(a) >= {"t", "yf", "f"}
    assert saida.exists()


def test_o_validador_aprova_o_que_o_gerador_produz(sem_rede, tmp_path):
    """Os dois lados do portao tem que concordar."""
    import subprocess
    saida = tmp_path / "historico.json"
    gh.gerar(anos=5, freq="anual", pool=20, liquidez=1e5, saida=saida, usar_cache=False)
    r = subprocess.run([sys.executable, "validar_historico.py", str(saida)],
                       capture_output=True, text=True, cwd=str(Path(__file__).parents[1]))
    assert r.returncode == 0, r.stdout + r.stderr


def test_setor_entra_pelo_cadastro_e_nao_pelo_mapa_de_tickers(sem_rede):
    """Regressao do KeyError ['SETOR'] que matou a rodada de 2h."""
    emp = sem_rede
    mapa = tickers.candidatos_de_ticker(emp)
    assert "SETOR" not in mapa.columns, "o mapa nunca teve setor; nao invente"
    empresas = tickers.mapa_setorial(emp, pd.DataFrame(
        {"CD_CVM": emp["CD_CVM"], "SETOR_ATIV": "Comércio", "SIT": "ATIVO"}))
    preco = pd.Series(10.0, index=_tickers_falsos(emp))
    liq = pd.Series(1e7, index=preco.index)
    acoes = pd.Series(1e8, index=preco.index)
    mercado = gh.montar_mercado(preco, liq, mapa.drop_duplicates("TICKER"),
                                empresas, acoes)
    assert {"SETOR", "SEGMENTO", "VALOR_MERCADO"} <= set(mercado.columns)
    assert mercado["SETOR"].notna().all()
