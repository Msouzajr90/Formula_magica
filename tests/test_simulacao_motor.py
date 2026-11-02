# -*- coding: utf-8 -*-
"""O motor da Simulação (JavaScript) conferido contra o Python.

Cada função de cálculo do `web/public/simulacao_motor.js` roda no Node pelo
`tests/paridade_simulacao.mjs` e é comparada com:

  * `magicb3` — Ledoit-Wolf, média exponencial, mínima variância (scipy),
    métricas e retorno de carteira buy-and-hold;
  * uma referência em pandas escrita aqui, para o que o magicb3 não tem
    (rebalanceamento periódico, Sortino, VaR/CVaR);
  * o próprio `app.js`, de onde o otimizador foi copiado.

Sem Node instalado, os testes são pulados (o GitHub Actions tem Node).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import minimize

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from magicb3 import backtest, optimizer  # noqa: E402

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node não instalado")


def js(fn: str, *args):
    r = subprocess.run([NODE, str(RAIZ / "tests" / "paridade_simulacao.mjs")],
                       input=json.dumps({"fn": fn, "args": list(args)}),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ---------------------------------------------------------------------------
# dados de teste
# ---------------------------------------------------------------------------
def _retornos(n=252, p=8, semente=3, deriva=None):
    rng = np.random.default_rng(semente)
    fator = rng.normal(0.0004, 0.012, n)
    betas = rng.uniform(0.4, 1.4, p)
    idio = rng.uniform(0.006, 0.02, p)
    d = np.zeros(p) if deriva is None else np.asarray(deriva)
    X = fator[:, None] * betas + rng.normal(0, 1, (n, p)) * idio + d / 252
    return pd.DataFrame(X, columns=[f"A{i}" for i in range(p)])


def _dados(n=900, ativos=("AAAA3", "BBBB4", "CCCC3", "DDDD11"), semente=11, inicio_tardio=None,
           fim_cedo=None):
    """Base pequena no formato que o motor recebe (frações, não inteiros)."""
    rng = np.random.default_rng(semente)
    pregoes = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2019-01-02", periods=n)]
    mkt = rng.normal(0.0004, 0.013, n)
    series = {}
    for k, t in enumerate(ativos):
        r = 0.7 * mkt + rng.normal(0.0002 * k, 0.015, n)
        i0 = 1
        fim = n - 1
        if inicio_tardio and t in inicio_tardio:
            i0 = inicio_tardio[t]
        if fim_cedo and t in fim_cedo:
            fim = fim_cedo[t]
        series[t] = {"i0": i0, "r": r[i0:fim + 1].round(8).tolist()}
    cdi = np.full(n, 0.0004)
    return {
        "pregoes": pregoes,
        "series": series,
        "ibov": {"i0": 1, "r": mkt[1:].round(8).tolist()},
        "cdi": {"i0": 1, "r": cdi[1:].tolist()},
    }


def _cfg(**kw):
    c = {"ativos": [{"t": "AAAA3", "peso": 0.4}, {"t": "BBBB4", "peso": 0.3},
                    {"t": "CCCC3", "peso": 0.2}, {"t": "DDDD11", "peso": 0.1}],
         "modo": "manual", "rebal": "nenhum", "custoBps": 15,
         "inicio": None, "fim": None, "teto": 0.4, "alvo": "minvar", "janela": 252}
    c.update(kw)
    return c


# ---------------------------------------------------------------------------
# otimizador e estimadores
# ---------------------------------------------------------------------------
def test_otimizar_identico_ao_do_app_js():
    X = _retornos()
    S = optimizer.cov_ledoit_wolf(X).to_numpy().tolist()
    mu = optimizer.mu_ewma(X).to_numpy().tolist()
    for lam in (0.0, 0.5, 5.0):
        a = js("otimizar", S, mu, 0.3, lam, 900)
        b = js("otimizar_appjs", S, mu, 0.3, lam, 900)
        np.testing.assert_allclose(a, b, atol=0, rtol=0)


def test_ledoit_wolf_e_media_exponencial_batem_com_o_python():
    X = _retornos(p=10)
    S = np.array(js("covLedoitWolf", X.to_numpy().tolist()))
    mu = np.array(js("muEwma", X.to_numpy().tolist()))
    np.testing.assert_allclose(S, optimizer.cov_ledoit_wolf(X).to_numpy(), rtol=1e-10)
    np.testing.assert_allclose(mu, optimizer.mu_ewma(X).to_numpy(), rtol=1e-10)


def test_minima_variancia_bate_com_o_scipy():
    X = _retornos(p=10)
    S = optimizer.cov_ledoit_wolf(X)
    mu = optimizer.mu_ewma(X)
    ref = optimizer.carteira_min_variancia(mu, S, w_max=0.2)
    r = js("pesosMarkowitz", X.to_numpy().tolist(), "minvar", {"teto": 0.2})
    w = np.array(r["w"])
    var_js = w @ S.to_numpy() @ w
    var_py = ref.to_numpy() @ S.to_numpy() @ ref.to_numpy()
    # a limpeza de posições < 0,5% pode custar um tiquinho de variância
    assert var_js <= var_py * 1.005
    assert w.max() <= 0.2 + 1e-9
    assert w.sum() == pytest.approx(1)


def _sharpe(w, mu, S, rf):
    return (w @ mu - rf) / np.sqrt(w @ S @ w)


def test_maximo_sharpe_alcanca_o_otimo_do_scipy():
    X = _retornos(p=8, deriva=np.linspace(0.05, 0.40, 8))
    S = optimizer.cov_ledoit_wolf(X).to_numpy()
    mu = optimizer.mu_ewma(X).to_numpy()
    rf, cap = 0.10, 0.35
    melhor = -np.inf
    rng = np.random.default_rng(0)
    for _ in range(12):
        x0 = rng.dirichlet(np.ones(8))
        res = minimize(lambda w: -_sharpe(w, mu, S, rf), x0, method="SLSQP",
                       bounds=[(0, cap)] * 8,
                       constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1}],
                       options={"maxiter": 500, "ftol": 1e-12})
        if res.success:
            melhor = max(melhor, _sharpe(res.x, mu, S, rf))
    r = js("pesosMarkowitz", X.to_numpy().tolist(), "maxsharpe", {"teto": cap, "rfAnual": rf})
    assert r["aviso"] is None
    assert _sharpe(np.array(r["w"]), mu, S, rf) >= melhor - 0.005


def test_maximo_sharpe_negativo_cai_na_minima_variancia():
    X = _retornos(p=6, deriva=np.full(6, -1.5))   # EWMA é ruidosa: -30% não basta
    r = js("pesosMarkowitz", X.to_numpy().tolist(), "maxsharpe", {"teto": 0.5, "rfAnual": 0.12})
    m = js("pesosMarkowitz", X.to_numpy().tolist(), "minvar", {"teto": 0.5})
    assert r["aviso"] == "sharpeNegativo"
    np.testing.assert_allclose(r["w"], m["w"], atol=1e-9)


def test_volatilidade_alvo_acerta_o_alvo_com_o_maior_retorno():
    X = _retornos(p=8, deriva=np.linspace(0.0, 0.5, 8))
    S = optimizer.cov_ledoit_wolf(X).to_numpy()
    mu = optimizer.mu_ewma(X).to_numpy()
    cap = 0.35
    m = js("pesosMarkowitz", X.to_numpy().tolist(), "minvar", {"teto": cap})
    alvo = m["info"]["volMin"] * 1.3
    r = js("pesosMarkowitz", X.to_numpy().tolist(), "volalvo", {"teto": cap, "volAlvo": alvo})
    w = np.array(r["w"])
    assert np.sqrt(w @ S @ w) == pytest.approx(alvo, abs=0.003)
    ref = minimize(lambda w: -(w @ mu), np.full(8, 1 / 8), method="SLSQP",
                   bounds=[(0, cap)] * 8,
                   constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1},
                                {"type": "ineq", "fun": lambda w: alvo ** 2 - w @ S @ w}],
                   options={"maxiter": 500, "ftol": 1e-12})
    assert w @ mu >= ref.x @ mu - 0.003


# ---------------------------------------------------------------------------
# métricas
# ---------------------------------------------------------------------------
def test_metricas_batem_com_magicb3():
    rng = np.random.default_rng(5)
    n = 700
    rb = rng.normal(0.0004, 0.014, n)
    rp = 0.8 * rb + rng.normal(0.0002, 0.009, n)
    rc = np.full(n, 0.00045)
    datas = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2020-01-02", periods=n)]
    m = js("metricas", rp.tolist(), rb.tolist(), rc.tolist(), datas)
    rf = (1 + 0.00045) ** 252 - 1
    ref = backtest.calcular_metricas(pd.Series(rp), pd.Series(rb), rf_aa=rf)
    assert m["rf"] == pytest.approx(rf, rel=1e-10)
    for chave, valor in (("total", ref.retorno_total), ("anual", ref.retorno_anualizado),
                         ("vol", ref.volatilidade), ("sharpe", ref.sharpe),
                         ("mdd", ref.drawdown_maximo), ("beta", ref.beta),
                         ("alfa", ref.alfa_anual), ("te", ref.tracking_error),
                         ("ir", ref.information_ratio)):
        assert m[chave] == pytest.approx(valor, rel=1e-9, abs=1e-12), chave

    # o que o magicb3 não tem, contra numpy
    exc = np.minimum(rp - rc, 0)
    dsv = np.sqrt((exc ** 2).mean() * 252)
    assert m["sortino"] == pytest.approx((ref.retorno_anualizado - rf) / dsv, rel=1e-9)
    q = np.quantile(rp, 0.05)
    assert m["var95"] == pytest.approx(-q, rel=1e-12)
    assert m["cvar95"] == pytest.approx(-rp[rp <= q].mean(), rel=1e-12)
    assert m["var99"] == pytest.approx(-np.quantile(rp, 0.01), rel=1e-12)
    assert m["correlacaoIbov"] == pytest.approx(np.corrcoef(rp, rb)[0, 1], rel=1e-9)
    # mensal: composição por mês do calendário
    s = pd.Series(rp, index=pd.to_datetime(datas))
    ref_m = (1 + s).groupby(s.index.to_period("M")).prod() - 1
    np.testing.assert_allclose([x["v"] for x in m["mensal"]], ref_m.to_numpy(), rtol=1e-12)
    # móveis de 252: último ponto = retorno composto e vol dos últimos 252
    assert m["moveis"]["ret12"][-1] == pytest.approx(np.prod(1 + rp[-252:]) - 1, rel=1e-9)
    assert m["moveis"]["vol12"][-1] == pytest.approx(rp[-252:].std(ddof=1) * np.sqrt(252), rel=1e-7)


def test_captura_de_alta_e_baixa():
    datas = ["2024-01-02", "2024-02-01", "2024-03-01", "2024-04-01"]
    rb = [0.10, -0.05, 0.02, -0.10]
    rp = [0.05, -0.05, 0.01, -0.02]
    m = js("metricas", rp, rb, [0.0] * 4, datas)
    sobe = (np.sqrt(1.05 * 1.01) - 1) / (np.sqrt(1.10 * 1.02) - 1)
    desce = (np.sqrt(0.95 * 0.98) - 1) / (np.sqrt(0.95 * 0.90) - 1)
    assert m["capturaAlta"] == pytest.approx(sobe, rel=1e-12)
    assert m["capturaBaixa"] == pytest.approx(desce, rel=1e-12)


def test_drawdown_pico_vale_e_recuperacao():
    datas = [f"2024-01-{d:02d}" for d in range(2, 12)]
    rp = [0.10, -0.20, -0.10, 0.05, 0.40, 0.01, -0.05, 0.0, 0.0, 0.0]
    dd = js("drawdown", rp, datas)
    curva = np.cumprod(1 + np.array(rp))
    assert dd["mdd"] == pytest.approx((curva / np.maximum.accumulate(curva)).min() - 1)
    assert dd["pico"] == "2024-01-02"
    assert dd["vale"] == "2024-01-04"
    assert dd["recuperacao"] == "2024-01-06"
    assert dd["pregoesQueda"] == 2 and dd["pregoesRecuperacao"] == 2


# ---------------------------------------------------------------------------
# simulação
# ---------------------------------------------------------------------------
def test_comprar_e_segurar_igual_ao_magicb3():
    d = _dados()
    r = js("simular", d, _cfg())
    s = 0
    idx = pd.Index(d["pregoes"][s + 1:])
    rets = pd.DataFrame({t: d["series"][t]["r"][s:] for t in d["series"]}, index=idx)
    pesos = pd.Series({"AAAA3": 0.4, "BBBB4": 0.3, "CCCC3": 0.2, "DDDD11": 0.1})
    ref = backtest.retorno_carteira(rets, pesos, custo_bps=15)
    np.testing.assert_allclose(r["carteira"], ref.to_numpy(), rtol=0, atol=1e-13)


def _referencia_rebalanceada(d, pesos, freq, custo_bps, s, e):
    """Simulação independente em pandas, com a mesma convenção de datas."""
    c = custo_bps / 1e4
    P = d["pregoes"]
    R = pd.DataFrame({t: pd.Series(d["series"][t]["r"], index=range(d["series"][t]["i0"],
                      d["series"][t]["i0"] + len(d["series"][t]["r"]))) for t in pesos.index})
    chave = {"mensal": lambda x: x[:7],
             "trimestral": lambda x: x[:4] + str((int(x[5:7]) - 1) // 3),
             "anual": lambda x: x[:4]}[freq]
    V = pesos.to_numpy() * (1 - c)          # a compra custa já no primeiro dia
    total, out = 1.0, []
    for i in range(s + 1, e + 1):
        ant = total
        V = V * (1 + R.loc[i].to_numpy())
        total = V.sum()
        if i < e and chave(P[i]) != chave(P[i - 1]):
            giro = np.abs(pesos.to_numpy() - V / total).sum()
            total *= 1 - c * giro
            V = pesos.to_numpy() * total
        if i == e:
            total *= 1 - c
        out.append(total / ant - 1)
    return np.array(out)


@pytest.mark.parametrize("freq", ["mensal", "trimestral", "anual"])
def test_rebalanceamento_periodico_bate_com_referencia(freq):
    d = _dados()
    r = js("simular", d, _cfg(rebal=freq, inicio="2019-03-15"))
    s = d["pregoes"].index(r["inicio"])
    e = d["pregoes"].index(r["fim"])
    pesos = pd.Series({"AAAA3": 0.4, "BBBB4": 0.3, "CCCC3": 0.2, "DDDD11": 0.1})
    ref = _referencia_rebalanceada(d, pesos, freq, 15, s, e)
    np.testing.assert_allclose(r["carteira"], ref, rtol=0, atol=1e-13)
    # uma troca por mês/trimestre/ano novo entre a compra e o último pregão
    per = pd.PeriodIndex(pd.to_datetime(d["pregoes"][s:e]),
                         freq={"mensal": "M", "trimestral": "Q", "anual": "Y"}[freq])
    assert r["nRebalances"] == per.nunique() - 1


def test_contribuicoes_somam_o_retorno_e_o_risco():
    d = _dados()
    r = js("simular", d, _cfg(rebal="trimestral"))
    soma = sum(a["contribRetorno"] for a in r["porAtivo"])
    assert soma - r["custos"] == pytest.approx(r["metricas"]["total"], abs=1e-10)
    assert sum(a["contribRisco"] for a in r["porAtivo"]) == pytest.approx(1, abs=1e-10)


def test_markowitz_nao_olha_para_o_futuro():
    """Mudar os retornos DEPOIS de uma data não pode mudar os pesos dela."""
    d = _dados(n=1000)
    cfg = _cfg(modo="markowitz", alvo="maxsharpe", rebal="trimestral",
               ativos=[{"t": t} for t in d["series"]])
    a = js("simular", d, cfg)
    corte = a["composicoes"][3]["data"]
    k = d["pregoes"].index(corte)
    rng = np.random.default_rng(99)
    for t, sr in d["series"].items():
        j = k + 1 - sr["i0"]
        sr["r"] = sr["r"][:j] + rng.normal(0.003, 0.03, len(sr["r"]) - j).round(8).tolist()
    b = js("simular", d, cfg)
    for ca, cb in zip(a["composicoes"][:4], b["composicoes"][:4]):
        assert ca["data"] == cb["data"]
        np.testing.assert_allclose(ca["w"], cb["w"], atol=1e-12)
    assert not np.allclose(a["composicoes"][4]["w"], b["composicoes"][4]["w"])


def test_markowitz_adia_o_inicio_ate_ter_12_meses():
    d = _dados(inicio_tardio={"CCCC3": 300})
    r = js("simular", d, _cfg(modo="markowitz", ativos=[{"t": t} for t in d["series"]],
                              inicio="2019-01-02"))
    assert r["inicio"] == d["pregoes"][300 + 252 - 1]
    assert any("CCCC3" in a and "12 meses" in a for a in r["avisos"])


def test_manual_adia_inicio_e_antecipa_fim():
    d = _dados(inicio_tardio={"BBBB4": 50}, fim_cedo={"DDDD11": 700})
    r = js("simular", d, _cfg())
    assert r["inicio"] == d["pregoes"][49]
    assert r["fim"] == d["pregoes"][700]
    assert len(r["carteira"]) == 700 - 49
    assert any("BBBB4" in a for a in r["avisos"]) and any("DDDD11" in a for a in r["avisos"])


def test_periodo_curto_e_um_ativo_no_markowitz_dao_erro():
    d = _dados()
    assert "curto" in js("simular", d, _cfg(inicio="2022-06-01", fim="2022-06-10"))["erro"]
    um = _cfg(modo="markowitz", ativos=[{"t": "AAAA3"}])
    assert "dois ativos" in js("simular", d, um)["erro"]
    assert "sem dados" in js("simular", d, _cfg(ativos=[{"t": "ZZZZ3"}]))["erro"]


def test_pesos_em_branco_dividem_o_que_sobra():
    r = js("pesosInformados", [{"t": "A", "peso": 0.5}, {"t": "B", "peso": None},
                               {"t": "C", "peso": None}])
    np.testing.assert_allclose(r["w"], [0.5, 0.25, 0.25])
    r = js("pesosInformados", [{"t": "A", "peso": 0.3}, {"t": "B", "peso": 0.3}])
    np.testing.assert_allclose(r["w"], [0.5, 0.5])
    assert r["avisos"]


def test_estado_na_url_ida_e_volta():
    cfg = {"ativos": [{"t": "PETR4", "peso": 0.3}, {"t": "VALE3", "peso": None}],
           "modo": "markowitz", "alvo": "volalvo", "volAlvo": 0.18, "teto": 0.25,
           "rebal": "trimestral", "custoBps": 20, "inicio": "2015-01-02", "fim": "2026-10-30"}
    q = js("codificar", cfg)
    assert "PETR4:30" in q and "VALE3" in q
    volta = js("decodificarEstado", q)
    assert volta["ativos"] == cfg["ativos"]
    for k in ("modo", "alvo", "rebal", "custoBps", "inicio", "fim"):
        assert volta[k] == cfg[k], k
    assert volta["volAlvo"] == pytest.approx(0.18)
    assert volta["teto"] == pytest.approx(0.25)
    lixo = js("decodificarEstado", "a=PETR4,<script>,X&r=zzz&c=-5&de=ontem")
    assert [a["t"] for a in lixo["ativos"]] == ["PETR4"]
    assert lixo["rebal"] == "nenhum" and lixo["custoBps"] == 15 and lixo["inicio"] is None
