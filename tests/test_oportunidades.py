# -*- coding: utf-8 -*-
"""Aba Oportunidades: z do ln P/VP, cobertura, ponto de hoje, saltos, "desde",
e a paridade entre a referência em Python e o motor que roda no navegador."""
from __future__ import annotations

import json
import math
import shutil
import statistics
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from mercado import oportunidades as op

RAIZ = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


def _sextas(fim: date, n: int) -> list[str]:
    return [(fim - timedelta(weeks=n - 1 - i)).isoformat() for i in range(n)]


def _serie(n=600, fim=date(2026, 10, 30), base=1.5, amp=0.25, periodo=37):
    """P/VP determinístico em torno de `base`, oscilando no log."""
    datas = _sextas(fim, n)
    vals = [round(base * math.exp(amp * math.sin(2 * math.pi * i / periodo)), 4) for i in range(n)]
    return datas, vals


# ---------------------------------------------------------------------------
# A conta
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("anos", [1, 5, 10])
def test_z_igual_a_conta_feita_a_mao(anos):
    datas, vals = _serie()
    e = op.estatistica(datas, vals, len(vals) - 1, anos)
    corte = op.anos_antes(date.fromisoformat(datas[-1]), anos).isoformat()
    janela = [v for d, v in zip(datas, vals) if d > corte]
    lns = [math.log(v) for v in janela]
    m, s = statistics.fmean(lns), statistics.stdev(lns)
    assert e["n"] == len(janela)
    assert e["z"] == pytest.approx((math.log(vals[-1]) - m) / s, abs=1e-12)
    assert e["mediaGeo"] == pytest.approx(math.exp(m), rel=1e-12)
    assert e["percentil"] == pytest.approx(sum(v < vals[-1] for v in janela) / len(janela))


def test_gatilho_e_o_pvp_que_da_z_igual_a_menos_k():
    datas, vals = _serie()
    r = op.avaliar_papel(datas, vals, vpa=10.0, preco=None, data_preco=None, k=2)
    j = r["janelas"][5]
    assert math.log(j["gatilho"]) == pytest.approx(j["media"] - 2 * j["dp"])
    assert j["precoGatilho"] == pytest.approx(10.0 * j["gatilho"])


def test_na_escala_original_o_gatilho_seria_negativo():
    """A razão do log: série com cauda para cima, média − 2σ < 0 na escala
    normal; no log o gatilho é positivo e o papel dispara quando cai."""
    datas = _sextas(date(2026, 10, 30), 300)
    vals = [0.8] * 280 + [9.0] * 18 + [0.8, 0.25]
    assert statistics.fmean(vals) - 2 * statistics.stdev(vals) < 0
    r = op.avaliar_papel(datas, vals, None, None, None)
    j = r["janelas"][5]
    assert j["gatilho"] > 0 and j["z"] < -2


def test_cobertura_minima_tira_janelas_que_o_papel_nao_tem():
    """Abriu capital há 3 anos: tem z de 1 ano, não de 5 nem de 10."""
    datas, vals = _serie()
    vals = [None] * (len(vals) - 156) + vals[-156:]
    r = op.avaliar_papel(datas, vals, None, None, None)
    assert r["janelas"][1] is not None
    assert r["janelas"][5] is None and r["janelas"][10] is None


def test_buracos_ate_20_por_cento_sao_tolerados():
    datas, vals = _serie()
    vals = [None if i % 6 == 0 else v for i, v in enumerate(vals)]   # ~17% vazio
    vals[-1] = 1.4
    assert op.estatistica(datas, vals, len(vals) - 1, 5) is not None
    vals2 = [None if i % 4 == 0 else v for i, v in enumerate(vals)]  # 25% vazio
    vals2[-1] = 1.4
    assert op.estatistica(datas, vals2, len(vals2) - 1, 5) is None


def test_grade_curta_nao_vira_janela_de_10_anos():
    """Com 6 anos de grade, a janela de 10 não existe — a cobertura sozinha não
    pegaria, porque conta só as datas que a grade tem."""
    datas, vals = _serie(n=313)
    assert op.estatistica(datas, vals, len(vals) - 1, 10) is None
    assert op.estatistica(datas, vals, len(vals) - 1, 5) is not None


def test_anos_antes_com_29_de_fevereiro():
    assert op.anos_antes(date(2024, 2, 29), 1) == date(2023, 2, 28)
    assert op.anos_antes(date(2026, 10, 30), 10) == date(2016, 10, 30)


# ---------------------------------------------------------------------------
# Ponto de hoje
# ---------------------------------------------------------------------------
def test_ponto_de_hoje_na_mesma_semana_substitui():
    datas, vals = ["2026-10-23", "2026-10-28"], [1.0, 1.1]
    d, v = op.com_hoje(datas, vals, vpa=10, preco=9, data_preco="2026-10-30")
    assert d == ["2026-10-23", "2026-10-30"] and v == [1.0, 0.9]


def test_ponto_de_hoje_no_mesmo_dia_substitui():
    d, v = op.com_hoje(["2026-10-30"], [0.89], vpa=10, preco=8.5, data_preco="2026-10-30")
    assert d == ["2026-10-30"] and v == [0.85]


def test_ponto_de_hoje_em_semana_nova_acrescenta():
    d, v = op.com_hoje(["2026-10-30"], [1.0], vpa=10, preco=9, data_preco="2026-11-03")
    assert d == ["2026-10-30", "2026-11-03"] and v == [1.0, 0.9]


def test_preco_velho_ou_sem_vpa_nao_mexe():
    base = (["2026-10-30"], [1.0])
    assert op.com_hoje(*base, vpa=10, preco=9, data_preco="2026-10-20") == (base[0], base[1])
    assert op.com_hoje(*base, vpa=None, preco=9, data_preco="2026-11-03") == (base[0], base[1])
    assert op.com_hoje(*base, vpa=10, preco=0, data_preco="2026-11-03") == (base[0], base[1])


@pytest.mark.parametrize("gerado,esperado", [
    ("2026-10-31 02:08", "2026-10-30"),    # sábado de madrugada → sexta
    ("2026-11-02 02:10", "2026-10-30"),    # segunda de madrugada → sexta
    ("2026-11-03 21:40", "2026-11-03"),    # depois do fechamento → o próprio dia
    ("2026-11-01 15:00", "2026-10-30"),    # domingo à tarde → sexta
    ("2026-11-04", "2026-11-04"),          # sem hora: o próprio dia
    ("", None),
])
def test_data_do_preco(gerado, esperado):
    assert op.data_do_preco(gerado) == esperado


# ---------------------------------------------------------------------------
# Saltos e "desde"
# ---------------------------------------------------------------------------
def test_salto_dentro_da_janela_e_detectado_e_tira_da_lista():
    datas, vals = _serie()
    vals = [v * 6 if i < len(vals) - 60 else v for i, v in enumerate(vals)]  # PL mudou há 60 semanas
    vals[-1] = vals[-2] * 0.55                            # queda forte, sem ser salto
    r = op.avaliar_papel(datas, vals, None, None, None)
    s = r["janelas"][5]["salto"]
    assert s and s["data"] == datas[len(vals) - 60] and s["fator"] == pytest.approx(6, rel=0.2)
    assert r["janelas"][1]["salto"] is None               # o salto é anterior à janela de 1 ano
    res = {"X": r}
    assert op.classificar(res, 5)[0] == []
    assert op.classificar(res, 5, com_salto=True)[0] == ["X"]


def test_queda_de_preco_depois_do_ultimo_balanco_nao_e_salto():
    """Sem degraus do VPA: depois do prazo do último balanço o patrimônio não
    muda, então o P/VP cair à metade é o preço caindo — é o que a aba procura."""
    datas, vals = _serie()
    vals[-1] = vals[-2] * 0.4
    sem_data = op.avaliar_papel(datas, vals, None, None, None)
    assert sem_data["janelas"][5]["salto"]["tipo"] == "pvp"
    com_data = op.avaliar_papel(datas, vals, None, None, None, dt_balanco="2026-06-30")
    assert com_data["janelas"][5]["salto"] is None
    assert op.classificar({"X": com_data}, 5)[0] == ["X"]


def test_degrau_de_patrimonio_e_salto_e_queda_de_preco_nao():
    datas, vals = _serie()
    n = len(vals)
    vals[-1] = vals[-2] * 0.4                                  # queda de preço
    degraus = [[0, 8.0], [n - 300, 8.3], [n - 200, 8.6], [n - 100, 8.4]]
    r = op.avaliar_papel(datas, vals, 8.4, None, None, degraus=degraus)
    assert r["janelas"][5]["salto"] is None                     # PL andou pouco
    degraus2 = degraus[:2] + [[n - 150, 14.0]]                  # aumento de capital
    r2 = op.avaliar_papel(datas, vals, 14.0, None, None, degraus=degraus2)
    s = r2["janelas"][5]["salto"]
    assert s == {"tipo": "patrimonio", "data": datas[n - 150], "de": 8.3, "para": 14.0,
                 "fator": pytest.approx(14 / 8.3)}
    assert r2["janelas"][1]["salto"] is None                    # fora da janela de 1 ano
    # Degrau para PL negativo (None) e de volta não compara com o vazio.
    degraus3 = [[0, 8.0], [n - 150, None], [n - 140, 8.1]]
    assert op.avaliar_papel(datas, vals, 8.1, None, None, degraus=degraus3)["janelas"][5]["salto"] is None


def test_degraus_vpa_do_historico():
    import pandas as pd
    from mercado import pvp_papeis

    pl = pd.Series([float("nan"), 1000.0, 1000.0, 1200.0, -5.0, 1300.0])
    assert pvp_papeis.degraus_vpa(pl, acoes=100.0) == [[0, None], [1, 10.0], [3, 12.0], [4, None], [5, 13.0]]
    assert pvp_papeis.degraus_vpa(pl, acoes=100.0, fator=3)[1] == [1, 30.0]


def test_desde_conta_as_semanas_seguidas_sem_olhar_o_futuro():
    datas, vals = _serie()
    for i in range(1, 4):
        vals[-i] = 0.6                                        # três semanas no chão
    r = op.avaliar_papel(datas, vals, None, None, None)
    d = r["janelas"][5]["desde"]
    assert d == {"data": datas[-3], "semanas": 3}
    # O z de cada semana da sequência é o que se teria calculado naquele dia.
    for corte in (len(vals) - 3, len(vals) - 2):
        hoje = op.estatistica(datas[:corte + 1], vals[:corte + 1], corte, 5)
        assert hoje["z"] == op.estatistica(datas, vals, corte, 5)["z"]
        assert hoje["z"] < -2


def test_classificar_ordena_e_separa_quase_la():
    def r(z):
        return {"janelas": {5: {"z": z, "salto": None}, 1: None, 10: None}}
    res = {"A": r(-1.7), "B": r(-3.0), "C": r(-2.2), "D": r(-1.4), "E": r(-2.0)}
    op_, quase = op.classificar(res, 5, k=2)
    assert op_ == ["B", "C"]
    assert quase == ["E", "A"]                 # −2 entra no quase; −1,4 fica fora


# ---------------------------------------------------------------------------
# Paridade com o motor do navegador
# ---------------------------------------------------------------------------
def _js(fn, *args):
    r = subprocess.run([NODE, str(RAIZ / "tests" / "paridade_oportunidades.mjs")],
                       input=json.dumps({"fn": fn, "args": list(args)}),
                       capture_output=True, text=True, timeout=120, check=True)
    return json.loads(r.stdout)


def _compara(py: dict, js: dict):
    assert set(py) == set(js)
    for t in py:
        assert py[t]["data"] == js[t]["data"], t
        assert (py[t]["pvp"] is None) == (js[t]["pvp"] is None), t
        for a in op.JANELAS:
            p, j = py[t]["janelas"][a], js[t]["janelas"][str(a)]
            assert (p is None) == (j is None), (t, a)
            if p is None:
                continue
            for c in ("z", "percentil", "mediaGeo", "gatilho", "media", "dp", "cobertura"):
                assert j[c] == pytest.approx(p[c], rel=1e-10, abs=1e-12), (t, a, c)
            assert p["n"] == j["n"] and p["desde"] == j["desde"], (t, a)
            assert (p["salto"] is None) == (j["salto"] is None), (t, a)
            if p["salto"]:
                assert p["salto"]["data"] == j["salto"]["data"], (t, a)


@pytest.mark.skipif(not NODE, reason="node não instalado")
def test_paridade_funcoes_de_data():
    datas = [(date(2015, 12, 25) + timedelta(days=i)).isoformat() for i in range(0, 4000, 3)]
    sem = _js("semana", datas[0])
    assert sem == list(date.fromisoformat(datas[0]).isocalendar()[:2])
    for d in datas[::40] + ["2020-12-31", "2021-01-03", "2026-12-28", "2027-01-01"]:
        assert _js("semana", d) == list(date.fromisoformat(d).isocalendar()[:2]), d
    assert _js("anosAntes", "2024-02-29", 1) == "2023-02-28"
    for g in ("2026-10-31 02:08", "2026-11-02 02:10", "2026-11-03 21:40", "2026-11-04", ""):
        assert _js("dataDoPreco", g) == op.data_do_preco(g), g


@pytest.mark.skipif(not NODE, reason="node não instalado")
def test_paridade_em_arquivo_sintetico(tmp_path):
    datas, base = _serie()
    papeis = {}
    for i, t in enumerate(["AAAA3", "BBBB4", "CCCC3", "DDDD11"]):
        s = [round(v * (1 + 0.1 * i), 4) for v in base]
        if t == "BBBB4":
            s[-3:] = [0.5, 0.45, 0.4]
        if t == "CCCC3":
            s = [None] * 400 + s[400:]
        if t == "DDDD11":
            s = [v * 5 if j < 500 else v for j, v in enumerate(s)]
        papeis[t] = {"nome": t, "s": s, "vpa": 10.0 + i}
        if t == "AAAA3":
            papeis[t]["v"] = [[0, 9.0], [300, 9.5], [550, 15.0]]
        if t == "BBBB4":
            papeis[t]["dtBalanco"] = "2026-06-30"
    pp = {"datas": datas, "papeis": papeis}
    dados = {"meta": {"geradoEm": "2026-10-31 02:08"},
             "empresas": [{"ticker": "AAAA3", "preco": 12.0}, {"ticker": "BBBB4", "preco": 4.0}],
             "excluidas": [{"ticker": "DDDD11", "preco": 15.0}]}
    (tmp_path / "pp.json").write_text(json.dumps(pp))
    (tmp_path / "d.json").write_text(json.dumps(dados))
    for k in (1.5, 2, 3):
        _compara(op.avaliar(pp, dados, k), _js("arquivos", str(tmp_path / "pp.json"),
                                                 str(tmp_path / "d.json"), k))


@pytest.mark.skipif(not NODE, reason="node não instalado")
def test_paridade_nos_arquivos_publicados():
    pp_arq = RAIZ / "web" / "public" / "pvp_papeis.json"
    dados_arq = RAIZ / "web" / "public" / "dados.json"
    if not pp_arq.exists():
        pytest.skip("pvp_papeis.json ainda não gerado")
    pp = json.loads(pp_arq.read_text(encoding="utf-8"))
    dados = json.loads(dados_arq.read_text(encoding="utf-8")) if dados_arq.exists() else None
    _compara(op.avaliar(pp, dados, 2),
             _js("arquivos", str(pp_arq), str(dados_arq) if dados else None, 2))
