# -*- coding: utf-8 -*-
"""Aba Análise técnica — velas, indicadores, painel, backtest e o motor JS.

Nenhum teste acessa a rede. Os mais importantes:

* `test_velas_incremental_igual_ao_completo`: atualizar dia a dia tem que dar
  as MESMAS velas que rebaixar tudo (a mesma garantia da base de retornos).
* `test_indicadores_convergem_para_as_definicoes_do_pandas` e
  `test_mais_di_sem_velas_e_o_ifr`: os indicadores conferidos por fórmulas
  independentes, não só contra eles mesmos.
* `test_paridade_*`: o motor do navegador dá os mesmos números que o Python,
  em séries reais da base (PETR4, LREN3, TEND3 com lacuna de sete anos…).
* `test_backtest_nao_olha_o_futuro` e `test_custo_e_exatamente_o_das_pontas`.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import validar_precos  # noqa: E402
from simulacao import arquivo, base, demo, series as S  # noqa: E402
from simulacao import etfs as E  # noqa: E402
from tecnica import backtest as B, config as C, indicadores as I, sinais as SN, velas as V  # noqa: E402

HOJE = date(2026, 10, 30)
NODE = shutil.which("node")
PRECOS_REAIS = RAIZ / "web" / "public" / "precos"
REAIS = [t for t in ("PETR4", "LREN3", "TEND3", "VALE3", "WEGE3")
         if (PRECOS_REAIS / f"{t}.json").exists()]


def js(fn: str, *args):
    r = subprocess.run([NODE, str(RAIZ / "tests" / "paridade_tecnica.mjs")],
                       input=json.dumps({"fn": fn, "args": list(args)}, allow_nan=False),
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


CAL = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09",
       "2026-01-12", "2026-01-13"]


def _s(d: dict) -> pd.Series:
    return pd.Series(list(d.values()), index=pd.to_datetime(list(d.keys())), dtype=float)


# ---------------------------------------------------------------------------
# Velas: cálculo puro
# ---------------------------------------------------------------------------
def test_vela_basica_razoes_e_volume_financeiro():
    i0, v, ult = V.velas_no_calendario(
        _s({"2026-01-05": 10.0, "2026-01-06": 10.5}),          # abertura
        _s({"2026-01-05": 10.4, "2026-01-06": 11.2}),          # máxima
        _s({"2026-01-05": 9.8, "2026-01-06": 10.3}),           # mínima
        _s({"2026-01-05": 10.2, "2026-01-06": 11.0}),          # fechamento
        _s({"2026-01-05": 1000, "2026-01-06": 2000}), CAL)
    assert i0 == 0
    assert v["a"] == [round((10 / 10.2 - 1) * 1e4), round((10.5 / 11 - 1) * 1e4)]
    assert v["x"] == [round((10.4 / 10.2 - 1) * 1e4), round((11.2 / 11 - 1) * 1e4)]
    assert v["m"] == [round((9.8 / 10.2 - 1) * 1e4), round((10.3 / 11 - 1) * 1e4)]
    assert v["f"] == [10, 22]                                  # R$ mil
    assert ult == ["2026-01-06", 11.0]


def test_pregao_sem_negocio_vira_vela_parada():
    i0, v, _ = V.velas_no_calendario(
        _s({"2026-01-05": 10, "2026-01-08": 12}), _s({"2026-01-05": 11, "2026-01-08": 13}),
        _s({"2026-01-05": 9, "2026-01-08": 11}), _s({"2026-01-05": 10, "2026-01-08": 12}),
        _s({"2026-01-05": 100, "2026-01-08": 100}), CAL)
    assert i0 == 0 and len(v["a"]) == 4
    for k in "axmf":
        assert v[k][1] == v[k][2] == 0


def test_volume_zero_nao_tem_pavio():
    _, v, _ = V.velas_no_calendario(_s({"2026-01-05": 9}), _s({"2026-01-05": 12}),
                                    _s({"2026-01-05": 8}), _s({"2026-01-05": 10}),
                                    _s({"2026-01-05": 0}), CAL)
    assert v == {"a": [0], "x": [0], "m": [0], "f": [0]}


def test_data_fora_do_calendario_junta_no_pregao_seguinte():
    # sábado 10/01 cai no pregão de 12/01 junto com o próprio 12/01
    _, v, ult = V.velas_no_calendario(
        _s({"2026-01-10": 10.0, "2026-01-12": 10.6}), _s({"2026-01-10": 10.8, "2026-01-12": 10.7}),
        _s({"2026-01-10": 9.5, "2026-01-12": 10.1}), _s({"2026-01-10": 10.4, "2026-01-12": 10.5}),
        _s({"2026-01-10": 100, "2026-01-12": 300}), CAL)
    assert v["a"] == [round((10.0 / 10.5 - 1) * 1e4)]           # abertura do primeiro
    assert v["x"] == [round((10.8 / 10.5 - 1) * 1e4)]           # máxima do conjunto
    assert v["m"] == [round((9.5 / 10.5 - 1) * 1e4)]
    assert v["f"] == [round(10.5 * 400 / 1000)]
    assert ult == ["2026-01-12", 10.5]


def test_pontas_invertidas_e_pavio_absurdo():
    _, v, _ = V.velas_no_calendario(
        _s({"2026-01-05": 10, "2026-01-06": 10}), _s({"2026-01-05": 9.9, "2026-01-06": 30}),
        _s({"2026-01-05": 10.1, "2026-01-06": 9}), _s({"2026-01-05": 10, "2026-01-06": 10}),
        _s({"2026-01-05": 100, "2026-01-06": 100}), CAL)
    assert v["x"][0] == 0 and v["m"][0] == 0                    # corrigida: máx/mín = fechamento
    assert v["a"][1] == v["x"][1] == v["m"][1] == 0             # máxima +200%: descartada
    assert v["f"][1] == 1                                       # o volume do dia fica


def test_desdobramento_nao_muda_as_velas():
    """O Yahoo ajusta preço e quantidade pelo desdobramento: razão e volume
    financeiro não mudam — o arquivo só cresce no fim."""
    rng = np.random.default_rng(1)
    datas = pd.to_datetime(CAL)
    c = pd.Series(10 * np.cumprod(1 + rng.normal(0, 0.02, 7)), index=datas)
    o, h, l = c * 1.003, c * 1.02, c * 0.985
    vol = pd.Series(rng.integers(100, 1000, 7).astype(float), index=datas)
    antes = V.velas_no_calendario(o, h, l, c, vol, CAL)
    depois = V.velas_no_calendario(o / 2, h / 2, l / 2, c / 2, vol * 2, CAL)
    assert antes[0] == depois[0] and antes[1] == depois[1]


def test_emenda_e_buraco():
    velho = {"i0": 0, "a": [1, 2, 3], "x": [5, 5, 5], "m": [-1, -1, -1], "f": [7, 7, 7]}
    i0, v = V.emendar(velho, 2, {"a": [9, 4], "x": [6, 6], "m": [-2, -2], "f": [8, 8]})
    assert i0 == 0 and v["a"] == [1, 2, 9, 4] and v["f"] == [7, 7, 8, 8]
    assert V.emendar(velho, 5, {"a": [1], "x": [1], "m": [0], "f": [1]}) is None


def test_realinhar_pela_data():
    velhos = ["2026-01-05", "2026-01-06", "2026-01-08"]
    novos = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"]
    arq = {"t": "X", "v": 1, "i0": 0, "a": [1, 2, 3], "x": [4, 5, 6], "m": [0, 0, 0], "f": [1, 1, 1],
           "ult": ["2026-01-08", 10]}
    out = V.realinhar(arq, velhos, novos)
    assert out["i0"] == 0 and out["a"] == [1, 2, 0, 3]


# ---------------------------------------------------------------------------
# Velas: o robô inteiro
# ---------------------------------------------------------------------------
def _velas(pasta: Path) -> dict:
    return {p.name: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted((pasta / "ohlc").glob("*.json")) if not p.name.startswith("_")}


def test_so_acoes_tem_velas(tmp_path):
    base.atualizar(tmp_path, completo=True, hoje=HOJE, fontes=demo.fontes_falsas(HOJE),
                   candidatos=demo.candidatos_demo())
    ind = arquivo.ler_indice(tmp_path)
    acoes = {e["t"] for e in ind["ativos"] if e["classe"] == "acao"}
    assert {n[:-5] for n in _velas(tmp_path)} == acoes
    assert "HGLG11" not in acoes and "BOVA11" not in acoes


def test_velas_incremental_igual_ao_completo(tmp_path):
    fontes = demo.fontes_falsas(HOJE)
    cands = demo.candidatos_demo()
    a, b = tmp_path / "a", tmp_path / "b"
    meio = HOJE - timedelta(days=45)
    base.atualizar(a, completo=True, hoje=meio, fontes=fontes, candidatos=cands)
    for d in (meio + timedelta(days=13), meio + timedelta(days=30), HOJE):
        base.atualizar(a, hoje=d, fontes=fontes, candidatos=cands)
    base.atualizar(b, completo=True, hoje=HOJE, fontes=fontes, candidatos=cands)
    va, vb = _velas(a), _velas(b)
    assert va.keys() == vb.keys() and va
    for nome in va:
        assert va[nome] == vb[nome], nome


def test_primeira_execucao_depois_da_aba_baixa_o_historico_das_velas(tmp_path):
    """A base já existia sem velas: o incremental baixa o histórico inteiro só
    das ações, uma vez, e chega ao mesmo resultado do completo."""
    fontes = demo.fontes_falsas(HOJE)
    cands = demo.candidatos_demo()
    a, b = tmp_path / "a", tmp_path / "b"
    base.atualizar(a, completo=True, hoje=HOJE - timedelta(days=7), fontes=fontes, candidatos=cands)
    shutil.rmtree(a / "ohlc")
    pedidos = []

    def contando(ts, ini, fim):
        pedidos.append((tuple(ts), ini))
        return fontes.precos(ts, ini, fim)

    f2 = type(fontes)(**{**vars(fontes), "precos": contando})
    rel = base.atualizar(a, hoje=HOJE, fontes=f2, candidatos=cands)
    assert len(pedidos) == 2                       # a janela de sempre + o histórico das velas
    assert pedidos[1][1] == date(2010, 1, 1)
    assert all(t in rel.texto() for t in ("velas (técnica)",))
    base.atualizar(b, completo=True, hoje=HOJE, fontes=fontes, candidatos=cands)
    assert _velas(a) == _velas(b)
    # e na execução seguinte não baixa de novo
    pedidos.clear()
    base.atualizar(a, hoje=HOJE, fontes=f2, candidatos=cands)
    assert len(pedidos) == 1


def test_abertura_ajustada_reconstruida_bate_com_a_fonte(tmp_path):
    fontes = demo.fontes_falsas(HOJE)
    base.atualizar(tmp_path, completo=True, hoje=HOJE, fontes=fontes, candidatos=demo.candidatos_demo())
    ind = arquivo.ler_indice(tmp_path)
    ret = arquivo.ler_serie(tmp_path, "PETR4")
    vel = V.ler(tmp_path / "ohlc", "PETR4")
    prep = SN.preparar(ret, vel, ind["pregoes"])
    d = fontes.precos(["PETR4"], date(2010, 1, 1), HOJE)
    fator = d["preco"]["PETR4"] / d["fechamento"]["PETR4"]          # ajustado ÷ bruto
    k = slice(-300, None)
    # o gráfico está em reais de hoje: ajustado × (último bruto ÷ último ajustado)
    esc = d["fechamento"]["PETR4"].iloc[-1] / d["preco"]["PETR4"].iloc[-1]
    # o retorno gravado com 6 casas acumula erro de arredondamento ao longo de
    # 16 anos (~1e-5 relativo): é o que a Simulação também tem
    np.testing.assert_allclose(prep["c"][k], (d["preco"]["PETR4"] * esc).to_numpy()[k], rtol=1e-4)
    np.testing.assert_allclose(prep["o"][k], (d["abertura"]["PETR4"] * fator * esc).to_numpy()[k], rtol=2e-4)
    np.testing.assert_allclose(prep["h"][k], (d["maxima"]["PETR4"] * fator * esc).to_numpy()[k], rtol=2e-4)
    # a razão do dia é exata até o ponto-base
    raz = (d["abertura"]["PETR4"] / d["fechamento"]["PETR4"]).to_numpy()
    np.testing.assert_allclose(prep["o"] / prep["c"], raz, atol=0.51e-4)
    assert prep["c"][-1] == pytest.approx(d["fechamento"]["PETR4"].iloc[-1], abs=0.5e-4)   # 4 casas
    assert prep["emReais"]


def test_validador_aceita_a_demo_e_acusa_vela_estragada(tmp_path):
    base.atualizar(tmp_path, completo=True, hoje=HOJE, fontes=demo.fontes_falsas(HOJE),
                   candidatos=demo.candidatos_demo())
    SN.gravar(tmp_path)
    erros, avisos = validar_precos.conferir_velas(tmp_path, arquivo.ler_indice(tmp_path))
    assert erros == [] and avisos == []
    arq = tmp_path / "ohlc" / "PETR4.json"
    d = json.loads(arq.read_text())
    d["x"][10] = -5
    arq.write_text(json.dumps(d))
    erros, _ = validar_precos.conferir_velas(tmp_path, arquivo.ler_indice(tmp_path))
    assert any("PETR4" in e for e in erros)


def test_validador_sem_velas_so_avisa(tmp_path):
    base.atualizar(tmp_path, completo=True, hoje=HOJE, fontes=demo.fontes_falsas(HOJE),
                   candidatos=demo.candidatos_demo())
    shutil.rmtree(tmp_path / "ohlc")
    erros, avisos = validar_precos.conferir_velas(tmp_path, arquivo.ler_indice(tmp_path))
    assert erros == [] and any("sem velas" in a for a in avisos)


# ---------------------------------------------------------------------------
# Indicadores contra definições independentes
# ---------------------------------------------------------------------------
def _passeio(n=900, semente=5):
    rng = np.random.default_rng(semente)
    c = 30 * np.cumprod(1 + rng.normal(0.0003, 0.02, n))
    o = c * (1 + rng.normal(0, 0.004, n))
    h = np.maximum(o, c) * (1 + np.abs(rng.normal(0, 0.008, n)))
    l = np.minimum(o, c) * (1 - np.abs(rng.normal(0, 0.008, n)))
    v = rng.lognormal(15, 0.4, n)
    return o, h, l, c, v


def test_media_simples_e_bollinger_contra_numpy():
    _, _, _, c, _ = _passeio()
    mm = I.sma(c, 20)
    assert np.isnan(mm[18]) and not np.isnan(mm[19])
    np.testing.assert_allclose(mm[19:], np.convolve(c, np.ones(20) / 20, "valid"), rtol=1e-12)
    meio, sup, inf, pb = I.bollinger(c)
    i = 500
    janela = c[i - 19:i + 1]
    assert sup[i] == pytest.approx(janela.mean() + 2 * janela.std(ddof=0), rel=1e-12)
    assert pb[i] == pytest.approx((c[i] - inf[i]) / (sup[i] - inf[i]))


def test_indicadores_convergem_para_as_definicoes_do_pandas():
    """A semente (média simples) é a única diferença para o `ewm(adjust=False)`
    do pandas; depois de centenas de pregões ela some. Confere a recursão."""
    _, _, _, c, _ = _passeio()
    s = pd.Series(c)
    np.testing.assert_allclose(I.ema(c, 12)[-100:], s.ewm(span=12, adjust=False).mean().to_numpy()[-100:], rtol=1e-9)
    d = s.diff()
    g = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    p = (-d).clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    np.testing.assert_allclose(I.ifr(c)[-100:], (100 - 100 / (1 + g / p)).to_numpy()[-100:], rtol=1e-6)
    linha, sinal, hist = I.macd(c)
    ref = s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean()
    np.testing.assert_allclose(linha[-100:], ref.to_numpy()[-100:], rtol=1e-6, atol=1e-9)
    np.testing.assert_allclose(hist, linha - sinal)


def test_semente_das_medias_exponenciais_e_a_media_simples():
    x = np.arange(1.0, 31.0)
    e = I.ema(x, 10)
    assert np.isnan(e[8]) and e[9] == pytest.approx(5.5)
    assert e[10] == pytest.approx(5.5 + 2 / 11 * (11 - 5.5))
    w = I.wilder(x, 10)
    assert w[10] == pytest.approx(5.5 + (11 - 5.5) / 10)


def test_ifr_nos_extremos():
    sobe = np.arange(1.0, 40.0)
    assert np.nanmax(I.ifr(sobe)) == 100 and np.nanmin(I.ifr(sobe)) == 100
    assert np.all(I.ifr(np.full(40, 7.0))[14:] == 50)
    assert np.all(np.isnan(I.ifr(sobe)[:14])) and not np.isnan(I.ifr(sobe)[14])


def test_mais_di_sem_velas_e_o_ifr():
    """Com máxima = mínima = fechamento, o +DI de Wilder vira ganho médio ÷
    variação média — exatamente o IFR. Uma identidade que amarra ADX e IFR."""
    _, _, _, c, _ = _passeio()
    _, pdi, ndi = I.adx(c, c, c)
    np.testing.assert_allclose(pdi[14:], I.ifr(c)[14:], rtol=1e-10)
    np.testing.assert_allclose(pdi[14:] + ndi[14:], 100, rtol=1e-10)


def test_atr_e_true_range_a_mao():
    o, h, l, c, _ = _passeio(60)
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, 60)]
    np.testing.assert_allclose(I.true_range(h, l, c)[1:], tr)
    a = I.atr(h, l, c)
    assert a[14] == pytest.approx(np.mean(tr[:14]))
    assert a[15] == pytest.approx((a[14] * 13 + tr[14]) / 14)


def test_adx_e_estocastico_ficam_na_faixa():
    o, h, l, c, v = _passeio()
    ax, pdi, ndi = I.adx(h, l, c)
    assert np.isnan(ax[26]) and not np.isnan(ax[27])          # 2n − 1
    assert np.nanmin(ax) >= 0 and np.nanmax(ax) <= 100
    k, d = I.estocastico(h, l, c)
    assert np.nanmin(k) >= 0 and np.nanmax(k) <= 100
    assert np.isnan(k[14]) and not np.isnan(k[15])            # 14 + 3 − 2


def test_obv_soma_volume_com_o_sinal_do_dia():
    c = np.array([10, 11, 11, 9, 12.0])
    v = np.array([5, 1, 2, 3, 4.0])
    np.testing.assert_allclose(I.obv(c, v), [0, 1, 1, -2, 2])


def test_donchian_nao_inclui_o_proprio_dia():
    h = np.arange(1.0, 80.0)
    sup = I.anterior(I.maxima_movel(h, 55))
    assert sup[55] == h[54] and h[55] > sup[55]


# ---------------------------------------------------------------------------
# Trechos, lacunas e painel
# ---------------------------------------------------------------------------
def _ret(i0, r):
    return {"t": "X", "i0": i0, "esc": 1_000_000, "r": [int(round(x * 1e6)) for x in r]}


def _cal(n):
    return [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2015-01-02", periods=n)]


def test_lacuna_divide_em_trechos_e_os_indicadores_recomecam():
    rng = np.random.default_rng(2)
    r = rng.normal(0, 0.02, 700)
    r[300:330] = 0.0                    # 30 pregões parados…
    r[330] = 0.15                       # …e o salto de volta
    pregoes = _cal(702)
    prep = SN.preparar(_ret(1, r), None, pregoes)
    assert prep["trechos"] == [[0, 300], [331, 700]]
    ind = SN.indicadores(prep)
    assert np.all(np.isnan(ind["mm200"][301:331 + 199]))     # não atravessa a lacuna
    assert not np.isnan(ind["mm200"][331 + 199])
    assert not np.isnan(ind["mm200"][299])


def test_papel_parado_no_fim_sai_como_parado():
    r = np.concatenate([np.random.default_rng(3).normal(0, 0.02, 400), np.zeros(15)])
    pregoes = _cal(416)
    prep = SN.preparar(_ret(1, r), None, pregoes)
    lin = SN.resumo(prep, SN.indicadores(prep), None, pregoes)
    assert lin["parado"] == pregoes[400]


@pytest.mark.skipif("TEND3" not in REAIS, reason="sem a base real")
def test_tend3_real_recomeca_depois_da_lacuna():
    """TEND3 tinha preço parado no Yahoo de 2010 a 2017 (base de 02/11/2026).
    O teste não fixa a data: se o Yahoo um dia preencher a lacuna, ele não
    pode barrar o robô de preços, que roda a suíte antes de atualizar."""
    ind_ = json.loads((PRECOS_REAIS / "indice.json").read_text())
    prep = SN.preparar(arquivo.ler_serie(PRECOS_REAIS, "TEND3"), None, ind_["pregoes"])
    if not prep["lacunas"]:
        pytest.skip("TEND3 sem lacuna na base de hoje")
    assert prep["trechos"][-1][0] == prep["lacunas"][-1][1]
    lin = SN.resumo(prep, SN.indicadores(prep), None, ind_["pregoes"])
    assert lin["desde"] == ind_["pregoes"][prep["lacunas"][-1][1]]


def test_painel_da_demo(tmp_path):
    base.atualizar(tmp_path, completo=True, hoje=HOJE, fontes=demo.fontes_falsas(HOJE),
                   candidatos=demo.candidatos_demo())
    painel = SN.gravar(tmp_path)
    assert painel["pregao"] == arquivo.ler_indice(tmp_path)["pregoes"][-1]
    por = {x["t"]: x for x in painel["papeis"]}
    assert "BOVA11" not in por and "PETR4" in por
    p = por["PETR4"]
    assert p["velas"] and p["emReais"] and p["preco"] > 0
    assert 0 <= p["ifr"] <= 100 and p["tend"] in ("alta", "baixa")
    assert por["BRML3"]["atraso"] > 0                     # deslistado em 2023
    # sem mudança nas linhas, não regrava
    mt = (tmp_path / "ohlc" / "_sinais.json").stat().st_mtime_ns
    SN.gravar(tmp_path)
    assert (tmp_path / "ohlc" / "_sinais.json").stat().st_mtime_ns == mt


def test_sem_velas_o_painel_nao_inventa_estocastico_nem_adx():
    pregoes = _cal(402)
    prep = SN.preparar(_ret(1, np.random.default_rng(4).normal(0, 0.02, 400)), None, pregoes)
    lin = SN.resumo(prep, SN.indicadores(prep), None, pregoes)
    assert lin["ifr"] is not None and lin["adx"] is None and lin["estK"] is None
    assert lin["preco"] is None and not lin["emReais"]


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def _cdi(n, taxa=0.0005):
    return {"i0": 1, "r": np.full(n, taxa)}


def _prep_sintetico(n=800, semente=9, velas=True):
    o, h, l, c, v = _passeio(n + 1, semente)
    r = c[1:] / c[:-1] - 1
    pregoes = _cal(n + 1)
    vel = None
    if velas:
        vel = {"t": "X", "v": 1, "i0": 0, "esc": 10000, "vesc": 1000,
               "a": [int(round((o[k] / c[k] - 1) * 1e4)) for k in range(n + 1)],
               "x": [int(round((h[k] / c[k] - 1) * 1e4)) for k in range(n + 1)],
               "m": [int(round((l[k] / c[k] - 1) * 1e4)) for k in range(n + 1)],
               "f": [int(round(v[k] * c[k] / 1000)) for k in range(n + 1)],
               "ult": [pregoes[-1], float(round(c[-1], 4))]}
    ret = _ret(1, r)
    return ret, vel, pregoes


def test_sempre_fora_rende_o_cdi():
    ret, vel, pregoes = _prep_sintetico()
    prep = SN.preparar(ret, vel, pregoes)
    cdi = _cdi(len(pregoes))
    res = B.simular(prep, "rompimento", {"entrada": 10_000, "saida": 20}, cdi)
    assert res is None                             # nunca fica pronto: nada a testar
    res = B.simular(prep, "ifr", {"n": 14, "baixo": -1, "alto": 101}, cdi)
    assert res["ops"] == [] and res["exposto"] == 0
    np.testing.assert_allclose(res["rp"], 0.0005)


def test_custo_e_exatamente_o_das_pontas():
    ret, vel, pregoes = _prep_sintetico()
    prep = SN.preparar(ret, vel, pregoes)
    cdi = _cdi(len(pregoes))
    com = B.simular(prep, "macd", B.REGRAS["macd"], cdi)
    sem = B.simular(prep, "macd", B.REGRAS["macd"], cdi, custo_bps=0)
    n = len(com["ops"])
    assert n > 5
    razao = np.prod(1 + com["rp"]) / np.prod(1 + sem["rp"])
    assert razao == pytest.approx((1 - 0.0015) ** (2 * n), rel=1e-12)


def test_backtest_nao_olha_o_futuro():
    ret, vel, pregoes = _prep_sintetico()
    cdi = _cdi(len(pregoes))
    a = B.simular(SN.preparar(ret, vel, pregoes), "mm", {"rapida": 10, "lenta": 40, "tipo": "e"}, cdi)
    ret2 = dict(ret, r=list(ret["r"]))
    corte = 600
    for k in range(corte, len(ret2["r"])):
        ret2["r"][k] = -ret2["r"][k]               # o futuro vira o avesso
    b = B.simular(SN.preparar(ret2, vel, pregoes), "mm", {"rapida": 10, "lenta": 40, "tipo": "e"}, cdi)
    # até o pregão do corte (índice corte+1 no calendário) nada muda
    ate = corte + 1 - (a["s"] + 1)
    np.testing.assert_array_equal(a["rp"][:ate], b["rp"][:ate])


def test_ordem_na_abertura_do_dia_seguinte():
    """Sempre comprado a partir do primeiro sinal: o primeiro pregão rende só
    da abertura ao fechamento (menos o custo); os seguintes, o dia inteiro."""
    n = 300
    pregoes = _cal(n + 1)
    r = np.full(n, 0.01)                           # sobe 1% todo dia
    vel = {"t": "X", "v": 1, "i0": 0, "esc": 10000, "vesc": 1000, "a": [-50] * (n + 1),
           "x": [10] * (n + 1), "m": [-80] * (n + 1), "f": [1] * (n + 1), "ult": [pregoes[-1], 10.0]}
    prep = SN.preparar(_ret(1, r), vel, pregoes)
    res = B.simular(prep, "mm", {"rapida": 2, "lenta": 5, "tipo": "s"}, _cdi(n + 1, 0.0))
    s = res["s"]
    assert s == 4                                  # primeira média de 5
    a = -50 / 1e4
    assert res["rp"][0] == pytest.approx((1 / (1 + a)) * (1 - 0.0015) - 1)   # comprou na abertura
    assert res["rp"][1] == pytest.approx(0.01)
    assert res["rp"][-1] == pytest.approx(1.01 * (1 - 0.0015) - 1)          # venda final
    assert len(res["ops"]) == 1 and res["ops"][0]["aberta"]


@pytest.mark.skipif("TEND3" not in REAIS, reason="sem a base real")
def test_backtest_real_comeca_depois_da_lacuna():
    ind_ = json.loads((PRECOS_REAIS / "indice.json").read_text())
    pregoes = ind_["pregoes"]
    prep = SN.preparar(arquivo.ler_serie(PRECOS_REAIS, "TEND3"), None, pregoes)
    if not prep["lacunas"]:
        pytest.skip("TEND3 sem lacuna na base de hoje")
    cdi = arquivo.ler_serie(PRECOS_REAIS, "_CDI.json")
    cdi = {"i0": cdi["i0"], "r": np.asarray(cdi["r"]) / cdi["esc"]}
    res = B.simular(prep, "mm", B.REGRAS["mm"], cdi, ini=0)
    assert res["ini"] == prep["lacunas"][-1][1]
    assert res["s"] - res["ini"] == 199                # aquecimento da MM200


# ---------------------------------------------------------------------------
# Paridade com o motor do navegador
# ---------------------------------------------------------------------------
def _comparar(py, js_, nome, rtol=1e-9, atol=1e-9):
    a = np.asarray(py, dtype=float)
    b = np.array([np.nan if v is None else v for v in js_], dtype=float)
    assert a.shape == b.shape, nome
    assert np.array_equal(np.isnan(a), np.isnan(b)), f"{nome}: NaN em lugares diferentes"
    ok = ~np.isnan(a)
    np.testing.assert_allclose(b[ok], a[ok], rtol=rtol, atol=atol, err_msg=nome)


def _casos():
    out = []
    ret, vel, pregoes = _prep_sintetico()
    out.append(("sintetico", ret, vel, pregoes))
    rng = np.random.default_rng(12)
    r = rng.normal(0, 0.02, 900)
    r[200:240] = 0
    r[240] = 0.2
    out.append(("lacuna", _ret(1, r), None, _cal(902)))
    if REAIS:
        pregoes_r = json.loads((PRECOS_REAIS / "indice.json").read_text())["pregoes"]
        for t in REAIS:
            out.append((t, arquivo.ler_serie(PRECOS_REAIS, t), None, pregoes_r))
    return out


def _listas(d):
    return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in d.items()}


def _json_ret(ret):
    return {"t": ret.get("t", "X"), "i0": ret["i0"], "esc": ret.get("esc", 1_000_000), "r": list(ret["r"])}


@pytest.mark.skipif(NODE is None, reason="Node não instalado")
@pytest.mark.parametrize("caso", _casos(), ids=lambda c: c[0])
def test_paridade_indicadores(caso):
    nome, ret, vel, pregoes = caso
    prep = SN.preparar(ret, vel, pregoes)
    ind = SN.indicadores(prep)
    out = js("serie", _json_ret(ret), vel, pregoes)
    assert out["prep"]["trechos"] == prep["trechos"]
    assert [list(x) for x in out["prep"]["lacunas"]] == [list(x) for x in prep["lacunas"]]
    for k in ("c", "o", "h", "l"):
        _comparar(prep[k], out["prep"][k], f"{nome}.{k}", rtol=1e-12)
    assert set(out["ind"]) == set(ind)
    for k in ind:
        # OBV acumula volumes de bilhões: tolerância relativa ao tamanho da soma
        atol = 1e-9 * max(1.0, float(np.nanmax(np.abs(ind[k])))) if k == "obv" else 1e-9
        _comparar(ind[k], out["ind"][k], f"{nome}.{k}", rtol=1e-8, atol=atol)


@pytest.mark.skipif(NODE is None, reason="Node não instalado")
@pytest.mark.parametrize("caso", _casos(), ids=lambda c: c[0])
def test_paridade_painel(caso):
    nome, ret, vel, pregoes = caso
    ibov = None
    if (PRECOS_REAIS / "_IBOV.json").exists() and len(pregoes) > 3000:
        s = arquivo.ler_serie(PRECOS_REAIS, "_IBOV.json")
        ibov = {"i0": s["i0"], "r": (np.asarray(s["r"]) / s["esc"]).tolist()}
    prep = SN.preparar(ret, vel, pregoes)
    py = SN.resumo(prep, SN.indicadores(prep), ibov, pregoes)
    j = js("resumo", _json_ret(ret), vel, pregoes, ibov)
    assert py.keys() == j.keys()
    for k, v in py.items():
        if isinstance(v, float):
            assert j[k] == pytest.approx(v, rel=1e-8, abs=1e-10), f"{nome}.{k}"
        else:
            assert j[k] == v, f"{nome}.{k}"


@pytest.mark.skipif(NODE is None, reason="Node não instalado")
@pytest.mark.parametrize("regra", list(B.REGRAS))
@pytest.mark.parametrize("caso", _casos()[:3], ids=lambda c: c[0])
def test_paridade_backtest(caso, regra):
    nome, ret, vel, pregoes = caso
    cdi = {"i0": 1, "r": [0.0004 + 0.0001 * math.sin(i / 50) for i in range(len(pregoes))]}
    prep = SN.preparar(ret, vel, pregoes)
    py = B.simular(prep, regra, B.REGRAS[regra], {"i0": 1, "r": np.asarray(cdi["r"])}, ini=None)
    j = js("simular", _json_ret(ret), vel, pregoes, regra, B.REGRAS[regra], cdi, {})
    if py is None:
        assert j is None
        return
    for k in ("s", "e", "ini"):
        assert j[k] == py[k], k
    _comparar(py["rp"], j["rp"], f"{nome}.{regra}.rp", rtol=1e-11, atol=1e-13)
    _comparar(py["bh"], j["bh"], f"{nome}.{regra}.bh", rtol=1e-11, atol=1e-13)
    assert j["exposto"] == pytest.approx(py["exposto"])
    assert len(j["ops"]) == len(py["ops"])
    for a, b in zip(py["ops"], j["ops"]):
        assert (a["entrada"], a["saida"], a["aberta"], a["pregoes"]) == \
               (b["entrada"], b["saida"], b["aberta"], b["pregoes"])
        assert b["ret"] == pytest.approx(a["ret"], rel=1e-10, abs=1e-12)
    ro = B.resumo_operacoes(py["ops"])
    for k, v in ro.items():
        assert j["resumoOps"][k] == (pytest.approx(v) if v is not None else None), k
    # o retorno da estratégia é a composição das operações e do CDI fora
    if regra == "mm" and py["ops"]:
        assert any(o["ret"] != 0 for o in py["ops"])


@pytest.mark.skipif(NODE is None, reason="Node não instalado")
def test_estado_da_url_vai_e_volta():
    est = {"t": "PETR4", "periodo": "1a", "osc": "macd", "sobre": ["mm50", "bb"],
           "regra": "mm", "params": {"rapida": 20, "lenta": 200, "tipo": "e"}, "de": "2018-01-02",
           "filtro": "alta"}
    out = js("url", est)
    assert "rp=rapida:20,tipo:e" in out["qs"]
    assert out["volta"] == est
