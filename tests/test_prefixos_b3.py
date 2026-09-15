# -*- coding: utf-8 -*-
"""O filtro de prefixo da B3 não pode derrubar companhia de verdade.

A regra era `[A-Z]{4}` — quatro LETRAS — com um comentário dizendo cortar os
emissores sem ação negociada. Não cortava: das 3.189 companhias que a API
devolve sem BDR, 3.111 passavam. O que ela realmente fazia era derrubar a
B3 S.A., cujo prefixo é `B3SA`, e que pesa 3,3% do Ibovespa.

Estes testes existem para que ninguém reaperte a regra por engano de novo.
"""
from __future__ import annotations

import pandas as pd
import pytest

from magicb3 import tickers


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch):
    monkeypatch.setattr(tickers.time, "sleep", lambda s: None)


@pytest.fixture
def cache_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(tickers, "_cache", lambda nome: tmp_path / nome)
    return tmp_path


def _responde(monkeypatch, linhas):
    monkeypatch.setattr(tickers, "_pagina_b3",
                        lambda pagina, tamanho=120: {"results": linhas,
                                                     "page": {"totalPages": 1}})


def _empresa(prefixo, cvm, **extra):
    base = {"codeCVM": cvm, "issuingCompany": prefixo,
            "companyName": f"{prefixo} S.A.", "segment": "Novo Mercado"}
    base.update(extra)
    return base


def test_b3sa_entra_no_mapa(cache_isolado, monkeypatch):
    """O caso que motivou a correção. Se este teste cair, o ranking perde a B3."""
    _responde(monkeypatch, [_empresa("B3SA", 21610), _empresa("PETR", 9512)])
    df = tickers.baixar_empresas_b3(usar_cache=False)
    assert "B3SA" in set(df["PREFIXO"])
    assert int(df.loc[df["PREFIXO"] == "B3SA", "CD_CVM"].iloc[0]) == 21610


def test_b3sa_chega_ate_os_tickers_candidatos(cache_isolado, monkeypatch):
    """Não basta entrar no mapa: B3SA3 precisa sair do outro lado."""
    _responde(monkeypatch, [_empresa("B3SA", 21610)])
    df = tickers.baixar_empresas_b3(usar_cache=False)
    assert "B3SA3.SA" in set(tickers.candidatos_de_ticker(df)["TICKER"])


def test_quatro_letras_continuam_passando(cache_isolado, monkeypatch):
    """A regra foi ampliada, não trocada: o caso comum não pode ter mudado."""
    _responde(monkeypatch, [_empresa(p, i) for i, p in
                            enumerate(("PETR", "VALE", "ITUB", "WEGE"), start=1)])
    df = tickers.baixar_empresas_b3(usar_cache=False)
    assert set(df["PREFIXO"]) == {"PETR", "VALE", "ITUB", "WEGE"}


@pytest.mark.parametrize("prefixo", ["3BSA", "1234", "B3S", "B3SA1", "B3-A", ""])
def test_o_que_nao_e_codigo_de_negociacao_fica_fora(cache_isolado, monkeypatch,
                                                    prefixo):
    """Quatro alfanuméricos COMEÇANDO POR LETRA — não qualquer coisa."""
    _responde(monkeypatch, [_empresa(prefixo, 1), _empresa("PETR", 9512)])
    df = tickers.baixar_empresas_b3(usar_cache=False)
    assert set(df["PREFIXO"]) == {"PETR"}


def test_bdr_continua_fora_mesmo_com_digito(cache_isolado, monkeypatch):
    """BDR tem lastro estrangeiro e não entrega DFP à CVM. A regra nova não
    pode ter aberto uma porta lateral para ele."""
    _responde(monkeypatch, [_empresa("A1BC", 100, typeBDR="Patrocinado"),
                            _empresa("B3SA", 21610)])
    df = tickers.baixar_empresas_b3(usar_cache=False)
    assert set(df["PREFIXO"]) == {"B3SA"}


def test_cache_da_regra_antiga_nao_e_reaproveitado(cache_isolado, monkeypatch):
    """O parquet gravado antes da correção não tem a B3 S.A. Se ele continuasse
    sendo lido, a correção só apareceria quando alguém limpasse o cache na mão."""
    antigo = cache_isolado / "b3_empresas.parquet"
    pd.DataFrame({"CD_CVM": [9512], "PREFIXO": ["PETR"],
                  "DENOM_CIA": ["Petrobras"], "SEGMENTO": ["NM"]}
                 ).to_parquet(antigo, index=False)

    _responde(monkeypatch, [_empresa("B3SA", 21610), _empresa("PETR", 9512)])
    df = tickers.baixar_empresas_b3(usar_cache=True)

    assert "B3SA" in set(df["PREFIXO"]), "leu o cache velho em vez de rebaixar"
    assert (cache_isolado / tickers.ARQUIVO_CACHE).exists()


def test_no_recuo_o_cache_velho_ainda_serve(cache_isolado, monkeypatch, caplog):
    """Mapa incompleto é melhor que rodada perdida — desde que avise."""
    antigo = cache_isolado / "b3_empresas.parquet"
    pd.DataFrame({"CD_CVM": [9512], "PREFIXO": ["PETR"],
                  "DENOM_CIA": ["Petrobras"], "SEGMENTO": ["NM"]}
                 ).to_parquet(antigo, index=False)

    def sempre_falha(pagina, tamanho=120):
        raise TimeoutError("Read timed out")

    monkeypatch.setattr(tickers, "_pagina_b3", sempre_falha)
    with caplog.at_level("WARNING"):
        df = tickers.baixar_empresas_b3(usar_cache=False)

    assert list(df["PREFIXO"]) == ["PETR"]
    assert "B3SA" in caplog.text, "usou um mapa sem a B3 S.A. sem dizer nada"
