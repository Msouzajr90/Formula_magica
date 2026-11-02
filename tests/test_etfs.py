# -*- coding: utf-8 -*-
"""Aba ETFs: catálogo, lacunas do Yahoo, saltos, janelas, as contas, e a
paridade entre a referência em Python e o motor que roda no navegador."""
from __future__ import annotations

import json
import math
import re
import shutil
import statistics
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from simulacao import config as C, etfs as E, universo as U

RAIZ = Path(__file__).resolve().parents[1]
PUBLICO = RAIZ / "web" / "public"
NODE = shutil.which("node")
CATALOGO = json.loads((PUBLICO / "etfs_catalogo.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
def test_catalogo_consistente():
    cats, grupos = CATALOGO["categorias"], CATALOGO["grupos"]
    assert len(CATALOGO["etfs"]) >= 100
    for t, e in CATALOGO["etfs"].items():
        assert re.fullmatch(r"[A-Z0-9]{4}11", t), t
        assert U.valido(t), t
        assert e["cat"] in cats, t
        assert e.get("grupo") is None or e["grupo"] in grupos, t
        assert e["nome"] and e["indice"], t
    for g, gi in grupos.items():
        assert gi.get("ref") in (None, "IBOV", "CDI"), g
        membros = [t for t, e in CATALOGO["etfs"].items() if e.get("grupo") == g]
        assert len(membros) >= (1 if gi.get("ref") else 2), g
    assert set(CATALOGO["limiteSalto"]) <= set(cats) | {"padrao"}


def test_robo_tenta_baixar_todo_o_catalogo():
    """Uma fonte só: o que a aba lista é o que o robô procura."""
    assert C.ETFS == {t: e["nome"] for t, e in CATALOGO["etfs"].items()}
    cand = U.candidatos()
    for t in CATALOGO["etfs"]:
        assert cand[t]["classe"] == "etf", t


def test_ticker_com_digito_na_frente_so_com_11():
    assert U.valido("5GTK11") and U.valido("5PRE11") and U.valido("B5P211")
    assert not U.valido("5GTK3") and not U.valido("5GTK34")


def test_todas_as_abas_tem_o_link():
    for p in PUBLICO.glob("*.html"):
        s = p.read_text(encoding="utf-8")
        if '<nav class="nav">' in s:
            assert 'href="etfs.html"' in s, p.name


# ---------------------------------------------------------------------------
# Lacunas e saltos
# ---------------------------------------------------------------------------
def _serie(r, i0=1):
    return E.Serie(i0, np.asarray(r, float))


def test_lacuna_fila_de_zeros_e_o_salto():
    r = [0.01] * 20 + [0.0] * 30 + [0.40] + [0.01] * 20
    lac = E.lacunas(_serie(r, i0=5))
    assert lac == [[25, 55, False]]                  # 1º zero no pregão 25, salto no 55


def test_nove_zeros_nao_e_lacuna():
    assert E.lacunas(_serie([0.01] * 5 + [0.0] * 9 + [0.01] * 5)) == []


def test_lacunas_vizinhas_viram_uma():
    """Padrão real do IMAB11: parado, um preço novo, volta ao velho, parado,
    salto. O pregão da volta (−25%) é o começo da segunda lacuna."""
    r = [0.01] * 5 + [0.0] * 15 + [0.333] + [-0.25] + [0.0] * 12 + [0.362] + [0.01] * 5
    assert E.lacunas(_serie(r, i0=1)) == [[6, 35, False]]


def test_lacuna_ate_o_fim_e_aberta():
    lac = E.lacunas(_serie([0.01] * 5 + [0.0] * 12))
    assert lac == [[6, 17, True]]


def test_preparar_zera_salto_fora_e_preserva_dentro_da_lacuna():
    P = [f"d{i:04d}" for i in range(200)]
    r = [0.01] * 20 + [0.0] * 15 + [0.45] + [0.01] * 20 + [-0.875] + [0.01] * 20
    p = E.preparar(_serie(r, i0=1), 0.15, P, 77)
    s = p["serie"]
    assert p["artefatos"] == [[P[57], -0.875]]
    assert s.r[56] == 0.0                            # o desdobramento virou zero
    assert s.r[35] == pytest.approx(0.45)            # o salto da lacuna fica: é retorno de verdade
    assert s.lac == [(21, 36)] and s.s0 == 36


def test_preparar_parado():
    P = [f"d{i:04d}" for i in range(200)]
    assert E.preparar(_serie([0.01] * 50), 0.4, P, 50 + 11)["parado"] == P[50]
    assert E.preparar(_serie([0.01] * 30 + [0.0] * 20), 0.4, P, 50)["parado"] == P[30]
    pronta = E.preparar(_serie([0.01] * 50), 0.4, P, 55)["serie"]
    assert len(pronta.r) == 55 and pronta.r[-5:].tolist() == [0.0] * 5


def test_preco_real_e_limpo():
    s = E.Serie(1, np.ones(100) * 0.001, [(30, 50)], 50)
    assert E.preco_real(s, 29) and not E.preco_real(s, 30) and not E.preco_real(s, 49) and E.preco_real(s, 50)
    assert E.limpo(s, 50, 100) and not E.limpo(s, 49, 100) and E.limpo(s, 0, 29) and not E.limpo(s, 0, 30)


# ---------------------------------------------------------------------------
# Janelas e contas
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("d,m,esperado", [
    ("2026-03-31", 1, "2026-02-28"), ("2024-03-31", 1, "2024-02-29"), ("2026-10-30", 12, "2025-10-30"),
    ("2026-01-15", 13, "2024-12-15"), ("2024-02-29", 12, "2023-02-28"), ("2026-10-30", 60, "2021-10-30"),
])
def test_meses_antes(d, m, esperado):
    assert E.meses_antes(d, m) == esperado


def test_partida_do_ano_e_ultimo_pregao_do_ano_anterior():
    P = ["2025-12-29", "2025-12-30", "2026-01-02", "2026-01-05"]
    assert E.partida(P, 3, "ano") == 1
    assert E.partida(P, 3, "12m") is None


def test_risco_contra_conta_feita_a_mao():
    rng = np.random.default_rng(3)
    r = rng.normal(0.0005, 0.012, 300)
    cdi = E.Serie(1, np.full(400, 0.0005))
    s = E.Serie(1, r)
    k = E.risco(s, cdi, 50, 300)
    trecho = r[50:300]
    vol = statistics.stdev(trecho) * math.sqrt(252)
    total = math.prod(1 + x for x in trecho) - 1
    anual = (1 + total) ** (252 / 250) - 1
    rf = 1.0005 ** 252 - 1
    curva = np.cumprod(1 + trecho)
    mdd = min(0, min(curva[i] / max(1, curva[:i + 1].max()) - 1 for i in range(len(curva))))
    assert k["vol"] == pytest.approx(vol, rel=1e-12)
    assert k["anual"] == pytest.approx(anual, rel=1e-12)
    assert k["sharpe"] == pytest.approx((anual - rf) / vol, rel=1e-10)
    assert k["mdd"] == pytest.approx(mdd, rel=1e-12)


def test_semanais_blocos_de_tras_para_a_frente():
    r = np.arange(1, 23) / 1000.0
    w = E.semanais(_serie(r), 0, 22)                 # 22 retornos: 4 blocos, sobram 2 no começo
    assert len(w) == 4
    assert w[-1] == pytest.approx(np.prod(1 + r[17:22]) - 1)
    assert w[0] == pytest.approx(np.prod(1 + r[2:7]) - 1)


def test_aderencia_de_copia_e_perfeita_e_de_taxa_e_a_taxa():
    rng = np.random.default_rng(5)
    r = rng.normal(0.0004, 0.01, 800)
    ref = _serie(r)
    ad = E.aderencia(_serie(r), ref, None, 800, "max")
    assert ad["difAnual"] == pytest.approx(0, abs=1e-14) and ad["te"] == pytest.approx(0, abs=1e-14)
    assert ad["corr"] == pytest.approx(1)
    taxa = (1 - 0.005) ** (1 / 252) - 1              # 0,5% ao ano tirado todo dia
    ad = E.aderencia(_serie((1 + r) * (1 + taxa) - 1), ref, None, 800, "max")
    # a diferença de retornos anualizados não é exatamente −0,5%: é −0,5% × (1 + retorno do índice)
    tot = np.prod(1 + r) ** (252 / 800)
    assert ad["difAnual"] == pytest.approx(tot * (1 - 0.005) - tot, rel=1e-9)


def test_aderencia_pula_a_lacuna():
    rng = np.random.default_rng(7)
    r = rng.normal(0.0004, 0.01, 900)
    x = r.copy()
    x[100:130] = 0.0
    x[130] = np.prod(1 + r[100:131]) - 1
    P = [str(i) for i in range(1000)]
    px = E.preparar(_serie(x), 0.4, P, 900)["serie"]
    ad = E.aderencia(px, _serie(r), 50, 900, "3a")
    assert ad["desde"] == 131 and not ad["inteira"]
    assert ad["te"] == pytest.approx(0, abs=1e-12)


# ---------------------------------------------------------------------------
# Paridade com o navegador
# ---------------------------------------------------------------------------
def _js(fn, *args):
    r = subprocess.run([NODE, str(RAIZ / "tests" / "paridade_etfs.mjs")],
                       input=json.dumps({"fn": fn, "args": list(args)}),
                       capture_output=True, text=True, timeout=300, check=True)
    return json.loads(r.stdout)


def _igual(py, js, caminho=""):
    if isinstance(py, dict):
        assert set(py) == set(js), (caminho, set(py) ^ set(js))
        for k in py:
            _igual(py[k], js[k], f"{caminho}.{k}")
    elif isinstance(py, (list, tuple)):
        assert len(py) == len(js), caminho
        for i, (a, b) in enumerate(zip(py, js)):
            _igual(a, b, f"{caminho}[{i}]")
    elif isinstance(py, float) and (py is None or not math.isnan(py)):
        assert js is not None, caminho
        assert js == pytest.approx(py, rel=1e-9, abs=1e-12), caminho
    elif isinstance(py, float):
        assert js is None, caminho
    else:
        assert py == js, caminho


def _sintetico():
    """Calendário de 1.700 pregões e ETFs com todos os casos que a tela trata."""
    P = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2019-01-02", periods=1700)]
    fim = len(P) - 1
    rng = np.random.default_rng(11)
    ibov = rng.normal(0.0004, 0.015, fim)
    cdi = np.full(fim - 1, 0.00045)                  # CDI sem o último pregão, como no SGS

    def arq(i0, r, esc=1_000_000):
        return {"i0": i0, "esc": esc, "r": [int(round(x * esc)) for x in r]}

    s = {}
    s["AAAA11"] = arq(1, ibov + rng.normal(-0.00001, 0.001, fim))
    s["BBBB11"] = arq(800, ibov[799:] + rng.normal(0, 0.002, fim - 799))
    rf = rng.normal(0.0004, 0.002, fim)
    c = rf.copy()
    c[300:600] = 0.0
    c[600] = np.prod(1 + rf[300:601]) - 1
    c[1200:1215] = 0.0                               # padrão IMAB11: salto, volta, parado, salto
    c[1215] = 0.33
    c[1216] = 1 / 1.33 - 1
    c[1217:1230] = 0.0
    c[1230] = np.prod(1 + rf[1200:1231]) - 1
    s["CCCC11"] = arq(1, c)
    d = rng.normal(0.0005, 0.012, fim - 99)
    d[700] = -0.875
    s["DDDD11"] = arq(100, d)
    e = rng.normal(0.0003, 0.004, fim - 399)
    s["EEEE11"] = arq(400, e)
    s["FFFF11"] = arq(200, rng.normal(0.0003, 0.004, fim - 199))
    s["GGGG11"] = arq(1, rng.normal(0.0003, 0.01, fim - 30))
    i = rng.normal(0.0003, 0.01, fim)
    i[-12:] = 0.0
    s["IIII11"] = arq(1, i)
    s["JJJJ11"] = arq(50, rng.normal(0.0003, 0.01, fim - 49 - 5))
    s["KKKK11"] = arq(fim - 60, rng.normal(0.0003, 0.01, 61))   # novo: sem 26 semanas

    etfs = {
        "AAAA11": {"cat": "acoes_br", "grupo": "IBOV"}, "BBBB11": {"cat": "acoes_br", "grupo": "IBOV"},
        "CCCC11": {"cat": "renda_fixa", "grupo": "SELIC"}, "DDDD11": {"cat": "exterior"},
        "EEEE11": {"cat": "renda_fixa", "grupo": "G2"}, "FFFF11": {"cat": "renda_fixa", "grupo": "G2"},
        "GGGG11": {"cat": "cripto"}, "HHHH11": {"cat": "outros"}, "IIII11": {"cat": "outros"},
        "JJJJ11": {"cat": "acoes_br", "grupo": "G2"}, "KKKK11": {"cat": "acoes_br", "grupo": "IBOV"},
    }
    for t, e_ in etfs.items():
        e_.update(nome=f"ETF {t}", indice="índice")
    catalogo = {"categorias": CATALOGO["categorias"], "limiteSalto": CATALOGO["limiteSalto"],
                "grupos": {"IBOV": {"nome": "Ibovespa", "ref": "IBOV"},
                           "SELIC": {"nome": "Selic", "ref": "CDI", "refNota": "aprox."},
                           "G2": {"nome": "Pares"}},
                "etfs": etfs}
    ativos = [{"t": t, "classe": "etf", "i0": a["i0"], "n": len(a["r"]), "liq": 1e6 * (k + 1)}
              for k, (t, a) in enumerate(s.items())]
    indice = {"pregoes": P, "ativos": ativos, "recusados": {},
              "bench": {"IBOV": {"arquivo": "_IBOV.json"}, "CDI": {"arquivo": "_CDI.json"}}}
    return {"catalogo": catalogo, "indice": indice, "series": s,
            "ibov": arq(1, ibov), "cdi": arq(1, cdi, 100_000_000)}


def _py(d, janela):
    series = {t: E.ler_serie(a) for t, a in d["series"].items()}
    return E.avaliar(d["catalogo"], d["indice"], series, E.ler_serie(d["ibov"]),
                     E.ler_serie(d["cdi"]), janela)


def test_sintetico_cobre_os_casos():
    r = _py(_sintetico(), "3a")
    assert {p["t"] for p in r["parados"]} == {"GGGG11", "IIII11"}
    assert r["fora"] == ["HHHH11"]
    ln = {l["t"]: l for l in r["linhas"]}
    assert ln["DDDD11"]["artefatos"] and not ln["CCCC11"]["artefatos"]
    assert len(ln["CCCC11"]["lacunas"]) == 2         # a dupla do fim virou uma
    assert ln["KKKK11"]["ret"]["12m"] is None
    g = {x["g"]: x for x in r["grupos"]}
    assert g["G2"]["refT"] == "JJJJ11"               # o de história mais longa
    assert any(i.get("vazio") for i in g["IBOV"]["itens"])


@pytest.mark.skipif(not NODE, reason="node não instalado")
@pytest.mark.parametrize("janela", ["12m", "3a", "5a", "max"])
def test_paridade_sintetico(tmp_path, janela):
    d = _sintetico()
    arq = tmp_path / "d.json"
    arq.write_text(json.dumps(d))
    _igual(_py(d, janela), _js("dados", str(arq), janela))


@pytest.mark.skipif(not NODE, reason="node não instalado")
@pytest.mark.parametrize("janela", ["12m", "3a", "max"])
def test_paridade_matriz_e_curvas(tmp_path, janela):
    d = _sintetico()
    arq = tmp_path / "d.json"
    arq.write_text(json.dumps(d))
    ts = ["AAAA11", "CCCC11", "DDDD11", "EEEE11", "KKKK11"]
    js = _js("extras", str(arq), janela, ts)
    P = d["indice"]["pregoes"]
    fim = len(P) - 1
    prep = E.preparar_todas(d["catalogo"], d["indice"], {t: E.ler_serie(a) for t, a in d["series"].items()})
    ibov, _ = E.preparar_bench(E.ler_serie(d["ibov"]), E.ler_serie(d["cdi"]), fim)
    s = E.partida(P, fim, janela)
    series = [prep["prontas"][t] for t in ts] + [ibov]
    _igual(E.matriz_correlacao(series, s, fim, janela), js["matriz"])
    for t in ts:
        sr = prep["prontas"][t]
        s0 = sr.i0 - 1 if janela == "max" else s
        if js["curvas"][t] is None:
            assert s0 < sr.i0 - 1
        else:
            _igual(E.curva(sr, s0, fim), js["curvas"][t])


@pytest.mark.skipif(not NODE, reason="node não instalado")
@pytest.mark.parametrize("janela", ["12m", "3a", "10a", "max"])
def test_paridade_nos_arquivos_publicados(janela):
    if not (C.PASTA_PRECOS / C.ARQ_INDICE).exists():
        pytest.skip("base de preços ainda não gerada")
    py = E.avaliar(*E.carregar(), janela=janela)
    js = _js("pasta", str(C.PASTA_PRECOS), str(C.ARQ_CATALOGO_ETFS), janela)
    _igual(py, js)


@pytest.mark.skipif(not NODE, reason="node não instalado")
def test_estado_no_endereco():
    e = _js("decodificar", "s=bova11,5GTK11,xx,BOVA11&j=5a&g=max&c=cripto")
    assert e == {"sel": ["BOVA11", "5GTK11"], "janela": "5a", "grafico": "max", "cat": "cripto"}
    assert _js("decodificar", "j=7a")["janela"] == "3a"
    assert _js("codificar", {"sel": ["BOVA11", "IVVB11"], "janela": "3a", "grafico": "5a", "cat": "todas"}) \
        == "s=BOVA11,IVVB11"
