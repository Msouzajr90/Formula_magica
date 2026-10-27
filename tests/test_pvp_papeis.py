# -*- coding: utf-8 -*-
"""Histórico de P/VP por papel: patrimônio dos controladores, point-in-time,
units, semana, e o ponto que o robô grava."""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from magicb3 import config as C
from mercado import pvp_papeis as pp

RAIZ = Path(__file__).resolve().parents[1]


def _linha(cvm, ref, receb, cd, ds, v):
    return {"CD_CVM": cvm, "DT_REFER": pd.Timestamp(ref),
            "DT_RECEB": pd.Timestamp(receb) if receb else pd.NaT,
            "CD_CONTA": cd, "DS_CONTA": ds, "VL_CONTA": v}


def _bpp():
    """Empresa 1 (tipo Cury): PL 2.049 com 394 de minoritários em 06/2026.
    Banco 2: PL no 2.07, minoritários no 2.07.09. Empresa 3: sem minoritários."""
    return pd.DataFrame([
        _linha(1, "2025-12-31", "2026-03-10", "2.03", "Patrimônio Líquido Consolidado", 1800.0),
        _linha(1, "2025-12-31", "2026-03-10", "2.03.09", "Participação dos Acionistas Não Controladores", 300.0),
        _linha(1, "2026-06-30", "2026-08-05", "2.03", "Patrimônio Líquido Consolidado", 2049.0),
        _linha(1, "2026-06-30", "2026-08-05", "2.03.09", "Participação dos Acionistas Não Controladores", 394.0),
        _linha(2, "2026-06-30", "2026-08-01", "2.03", "Provisões", 40000.0),
        _linha(2, "2026-06-30", "2026-08-01", "2.07", "Patrimônio Líquido Consolidado", 190000.0),
        _linha(2, "2026-06-30", "2026-08-01", "2.07.09", "Participação de Não Controladores", 5000.0),
        _linha(3, "2026-06-30", None, "2.03", "Patrimônio Líquido Consolidado", 500.0),
    ])


def test_patrimonio_dos_controladores():
    p = pp.painel_controladores(_bpp(), C.DS_PATRIMONIO_LIQUIDO).set_index(["CD_CVM", "DT_REFER"])
    assert p.loc[(1, pd.Timestamp("2026-06-30")), "PATRIMONIO"] == pytest.approx(1655.0)
    assert p.loc[(2, pd.Timestamp("2026-06-30")), "PATRIMONIO"] == pytest.approx(185000.0)
    assert p.loc[(3, pd.Timestamp("2026-06-30")), "PATRIMONIO"] == pytest.approx(500.0)


def test_minoritarios_fora_do_pl_nao_sao_descontados():
    """Uma conta de "não controladores" em outro grupo (resultado, por exemplo)
    não pode ser subtraída do patrimônio."""
    bpp = pd.concat([_bpp(), pd.DataFrame([
        _linha(3, "2026-06-30", None, "2.02.05", "Obrigações com não controladores", 80.0)])])
    p = pp.painel_controladores(bpp, C.DS_PATRIMONIO_LIQUIDO).set_index(["CD_CVM", "DT_REFER"])
    assert p.loc[(3, pd.Timestamp("2026-06-30")), "PATRIMONIO"] == pytest.approx(500.0)


def _fech(datas, **cols):
    return pd.DataFrame(cols, index=pd.to_datetime(datas))


def test_balanco_so_entra_depois_de_entregue():
    painel = pp.painel_controladores(_bpp(), C.DS_PATRIMONIO_LIQUIDO)
    datas = pd.to_datetime(["2026-07-31", "2026-08-07"])
    r = pp.construir(painel, {"CURY3": {"cvm": 1, "acoes": 100.0, "fonte": "cvm"}},
                     _fech(datas, CURY3=[30.0, 30.0]), datas)
    s = r["papeis"]["CURY3"]["s"]
    assert s[0] == pytest.approx(30 / (1500 / 100), abs=0.01)   # ainda o de 12/2025
    assert s[1] == pytest.approx(30 / (1655 / 100), abs=0.01)   # o de 06/2026, entregue 05/08
    assert r["papeis"]["CURY3"]["dtBalanco"] == "2026-06-30"
    assert r["papeis"]["CURY3"]["vpa"] == pytest.approx(16.55)


def test_reapresentacao_de_balanco_velho_nao_volta_no_tempo():
    bpp = pd.concat([_bpp(), pd.DataFrame([
        _linha(1, "2025-12-31", "2026-09-01", "2.03", "Patrimônio Líquido Consolidado", 1000.0)])])
    painel = pp.painel_controladores(bpp, C.DS_PATRIMONIO_LIQUIDO)
    painel = painel.drop_duplicates(subset=["CD_CVM", "DT_REFER"], keep="last")
    datas = pd.to_datetime(["2026-09-04"])
    r = pp.construir(painel, {"CURY3": {"cvm": 1, "acoes": 100.0, "fonte": "cvm"}},
                     _fech(datas, CURY3=[30.0]), datas)
    assert r["papeis"]["CURY3"]["dtBalanco"] == "2026-06-30"


def test_unit_usa_o_fator_e_exige_acoes_da_cvm():
    painel = pp.painel_controladores(_bpp(), C.DS_PATRIMONIO_LIQUIDO)
    # A empresa 3 não tem data de entrega: vale 30/06 + 90 dias = 28/09.
    datas = pd.to_datetime(["2026-10-02"])
    papeis = {"TAEE11": {"cvm": 3, "acoes": 100.0, "fonte": "cvm"},
              "XPTO11": {"cvm": 3, "acoes": 100.0, "fonte": "cvm"},
              "KLBN11": {"cvm": 3, "acoes": 100.0, "fonte": "mercado"}}
    r = pp.construir(painel, papeis, _fech(datas, TAEE11=[30.0], XPTO11=[30.0], KLBN11=[9.0]), datas)
    assert r["papeis"]["TAEE11"]["s"][0] == pytest.approx(30 / (5 * 3), abs=0.01)
    assert "XPTO11" in r["fora"] and "KLBN11" in r["fora"]


def test_pl_negativo_e_pvp_implausivel_viram_null():
    bpp = pd.DataFrame([
        _linha(5, "2026-06-30", "2026-08-01", "2.03", "Patrimônio Líquido Consolidado", -50.0),
        _linha(6, "2026-06-30", "2026-08-01", "2.03", "Patrimônio Líquido Consolidado", 1.0)])
    painel = pp.painel_controladores(bpp, C.DS_PATRIMONIO_LIQUIDO)
    datas = pd.to_datetime(["2026-09-04"])
    r = pp.construir(painel, {"NEGA3": {"cvm": 5, "acoes": 10.0, "fonte": "cvm"},
                              "CARO3": {"cvm": 6, "acoes": 1e6, "fonte": "cvm"}},
                     _fech(datas, NEGA3=[10.0], CARO3=[50.0]), datas)
    assert r["papeis"] == {}
    assert set(r["fora"]) == {"NEGA3", "CARO3"}


def test_ultimo_pregao_de_cada_semana():
    idx = pd.to_datetime(["2026-10-19", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"])
    assert [d.date().isoformat() for d in pp.datas_semanais(idx)] == ["2026-10-23", "2026-10-27"]


def _arquivo():
    return {"meta": {}, "datas": ["2026-10-16", "2026-10-23"],
            "papeis": {"CURY3": {"s": [5.0, 5.1], "vpa": 5.0},
                       "B3SA3": {"s": [3.0, 3.1], "vpa": 5.0}}}


def test_robo_acrescenta_a_semana_nova_e_marca_papel_sem_preco():
    d = _arquivo()
    assert pp.atualizar_semana(d, {"CURY3": 27.5}, date(2026, 10, 30))
    assert d["datas"][-1] == "2026-10-30"
    assert d["papeis"]["CURY3"]["s"][-1] == pytest.approx(5.5)
    assert d["papeis"]["B3SA3"]["s"][-1] is None
    assert len(d["papeis"]["B3SA3"]["s"]) == len(d["datas"])


def test_robo_substitui_na_mesma_semana_e_nao_reescreve_o_passado():
    d = _arquivo()
    assert pp.atualizar_semana(d, {"CURY3": 26.0, "B3SA3": 15.0}, date(2026, 10, 24))
    assert d["datas"] == ["2026-10-16", "2026-10-24"]
    assert d["papeis"]["CURY3"]["s"] == [5.0, 5.2]
    assert not pp.atualizar_semana(d, {"CURY3": 1.0}, date(2026, 10, 9))
    assert d["papeis"]["CURY3"]["s"] == [5.0, 5.2]


def test_script_do_robo_so_grava_na_sexta(tmp_path):
    arq, dados = tmp_path / "pvp_papeis.json", tmp_path / "dados.json"
    arq.write_text(json.dumps(_arquivo()), encoding="utf-8")
    dados.write_text(json.dumps({"empresas": [{"ticker": "CURY3", "preco": 27.5}],
                                 "excluidas": [{"ticker": "B3SA3", "preco": 15.0}]}),
                     encoding="utf-8")
    base = [sys.executable, "atualizar_pvp_papeis.py", "--arquivo", str(arq), "--dados", str(dados)]
    r = subprocess.run(base + ["--hoje", "2026-10-29"], capture_output=True, text=True, cwd=RAIZ)
    assert r.returncode == 0 and "sexta" in r.stdout
    assert json.loads(arq.read_text())["datas"][-1] == "2026-10-23"
    r = subprocess.run(base + ["--hoje", "2026-10-30"], capture_output=True, text=True, cwd=RAIZ)
    assert r.returncode == 0, r.stderr
    d = json.loads(arq.read_text())
    assert d["datas"][-1] == "2026-10-30"
    assert d["papeis"]["B3SA3"]["s"][-1] == pytest.approx(3.0)


def test_gerar_de_ponta_a_ponta_sem_rede(tmp_path, monkeypatch):
    """A cola do script local: universo do site + Ibovespa, mapa CVM, nº de
    ações, painel e preços — com a rede substituída."""
    import gerar_pvp_papeis as g
    from magicb3 import cvm, prices
    from mercado import acoes, empresas

    pub = tmp_path
    (pub / "dados.json").write_text(json.dumps({
        "empresas": [{"ticker": "CURY3", "nome": "Cury", "cvm": 1}],
        "excluidas": [{"ticker": "B3SA3", "nome": "B3", "cvm": 3, "preco": 15.0}]}),
        encoding="utf-8")
    (pub / "ibov_carteira.json").write_text(json.dumps({"papeis": [
        {"ticker": "B3SA3", "nome": "B3"}, {"ticker": "ITUB4", "nome": "Itaú"}]}),
        encoding="utf-8")
    (pub / "fundamentos.json").write_text(json.dumps({"empresas": [
        {"cvm": 1, "pl": 1655.0, "acoes": 100.0, "nome": "Cury"},
        {"cvm": 3, "pl": 500.0, "acoes": 100.0, "nome": "B3"}]}), encoding="utf-8")
    for nome in ("DADOS", "CARTEIRA", "FUNDAMENTOS"):
        monkeypatch.setattr(g, nome, pub / getattr(g, nome).name)
    monkeypatch.setattr(g, "MAPA_CVM", pub / "nao_existe.json")

    def sem_b3(_):
        raise RuntimeError("fora do ar")
    monkeypatch.setattr(empresas, "baixar_mapa", sem_b3)
    monkeypatch.setattr(acoes, "valor_de_mercado", lambda ts, **k: {})
    monkeypatch.setattr(cvm, "carregar_demonstracoes",
                        lambda anos, **k: {"BPP": _bpp() if anos[0] == 2026 else pd.DataFrame()})
    dias = pd.bdate_range("2026-09-01", "2026-10-23")
    monkeypatch.setattr(prices, "baixar_historico", lambda ts, i, f, **k: {
        "fechamento": pd.DataFrame({"CURY3.SA": 30.0, "B3SA3.SA": 15.0}, index=dias)})

    d = g.gerar(2026)
    assert set(d["papeis"]) == {"CURY3", "B3SA3"}
    assert "ITUB4" in d["meta"]["fora"]                 # sem código CVM
    assert d["datas"][-1] == "2026-10-23"
    assert d["papeis"]["CURY3"]["s"][-1] == pytest.approx(30 / 16.55, abs=0.01)
    assert d["papeis"]["B3SA3"]["s"][-1] == pytest.approx(3.0)
