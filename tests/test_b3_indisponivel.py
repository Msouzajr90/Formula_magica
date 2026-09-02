# -*- coding: utf-8 -*-
"""A B3 fora do ar nao pode derrubar a coleta do dia.

Em producao a API de companhias listadas deu "Read timed out" com 90s de
espera. Como ela e a unica fonte do mapa prefixo -> CD_CVM, sem tratamento a
rodada inteira se perde por causa da indisponibilidade de um terceiro.
"""
from __future__ import annotations

import pandas as pd
import pytest

from magicb3 import tickers


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch):
    monkeypatch.setattr(tickers.time, "sleep", lambda s: None)


def _cache_falso(tmp_path, monkeypatch):
    monkeypatch.setattr(tickers, "_cache", lambda nome: tmp_path / nome)
    return tmp_path / "b3_empresas.parquet"


class _Resposta:
    def __init__(self, dados):
        self._dados = dados

    def raise_for_status(self):
        pass

    def json(self):
        return self._dados


class _SessaoFalsa:
    """Falha nas primeiras chamadas e depois responde, como a B3 instavel."""

    def __init__(self, falhas):
        self.falhas, self.chamadas = falhas, 0

    def get(self, url, **kw):
        self.chamadas += 1
        if self.chamadas <= self.falhas:
            raise TimeoutError("Read timed out")
        return _Resposta({"results": [{"codeCVM": 1, "issuingCompany": "TSTE",
                                       "companyName": "Teste S.A.",
                                       "segment": "Novo Mercado"}],
                          "page": {"totalPages": 1}})


def test_insiste_antes_de_desistir(tmp_path, monkeypatch):
    _cache_falso(tmp_path, monkeypatch)
    sessao = _SessaoFalsa(falhas=2)
    monkeypatch.setattr(tickers.rede, "sessao", lambda *a, **k: sessao)
    df = tickers.baixar_empresas_b3(usar_cache=False)
    assert sessao.chamadas == 3, "devia ter insistido duas vezes antes de acertar"
    assert list(df["PREFIXO"]) == ["TSTE"]


def test_desiste_depois_do_limite(tmp_path, monkeypatch):
    _cache_falso(tmp_path, monkeypatch)
    sessao = _SessaoFalsa(falhas=99)
    monkeypatch.setattr(tickers.rede, "sessao", lambda *a, **k: sessao)
    with pytest.raises(RuntimeError):
        tickers.baixar_empresas_b3(usar_cache=False)
    assert sessao.chamadas == 4, "quatro tentativas, nao um laco infinito"


def test_cai_para_o_cache_antigo_quando_a_b3_nao_responde(tmp_path, monkeypatch):
    arq = _cache_falso(tmp_path, monkeypatch)
    antigo = pd.DataFrame({"CD_CVM": [1, 2], "PREFIXO": ["ABCD", "EFGH"],
                           "DENOM_CIA": ["A", "B"], "SEGMENTO": ["NM", "NM"]})
    antigo.to_parquet(arq, index=False)

    def sempre_falha(pagina, tamanho=120):
        raise TimeoutError("Read timed out")

    monkeypatch.setattr(tickers, "_pagina_b3", sempre_falha)
    df = tickers.baixar_empresas_b3(usar_cache=False)
    assert list(df["PREFIXO"]) == ["ABCD", "EFGH"], "devia usar o mapa de ontem"


def test_sem_cache_o_erro_diz_o_que_fazer(tmp_path, monkeypatch):
    _cache_falso(tmp_path, monkeypatch)

    def sempre_falha(pagina, tamanho=120):
        raise TimeoutError("Read timed out")

    monkeypatch.setattr(tickers, "_pagina_b3", sempre_falha)
    with pytest.raises(RuntimeError) as erro:
        tickers.baixar_empresas_b3(usar_cache=False)
    texto = str(erro.value)
    assert "cache anterior" in texto and "rode de novo" in texto
