"""Testes do motor de cálculo — rodam sem rede, com dados sintéticos."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from magicb3 import config as C
from magicb3 import backtest, fundamentals, optimizer, ranking


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def retornos():
    rng = np.random.default_rng(42)
    n, p = 400, 8
    cols = [f"A{i}{'.SA'}" for i in range(p)]
    fator = rng.normal(0.0004, 0.012, n)
    betas = rng.uniform(0.4, 1.6, p)
    idio = rng.normal(0, 0.010, (n, p))
    X = fator[:, None] * betas[None, :] + idio
    idx = pd.bdate_range("2023-01-02", periods=n)
    return pd.DataFrame(X, index=idx, columns=cols)


@pytest.fixture
def universo():
    return pd.DataFrame({
        "CD_CVM": [1, 2, 3, 4, 5],
        "TICKER": ["AAA3.SA", "BBB4.SA", "CCC3.SA", "DDD3.SA", "EEE3.SA"],
        "DENOM_CIA": ["Alfa", "Beta", "Gama", "Delta", "Epsilon"],
        "SETOR": ["Comércio", "Bancos", "Energia Elétrica", "Comércio", "Comércio"],
        "EBIT_LTM": [1_000e6, 5_000e6, 800e6, -200e6, 400e6],
        "VALOR_MERCADO": [4_000e6, 30_000e6, 6_000e6, 1_000e6, 2_000e6],
        "ACOES": [1e9, 5e9, 1e9, 1e9, 1e9],
        "LIQUIDEZ_MEDIA": [50e6, 200e6, 30e6, 10e6, 100],   # último é ilíquido
        C.CD_ATIVO_CIRCULANTE: [2_000e6, 10_000e6, 1_500e6, 500e6, 900e6],
        C.CD_CAIXA: [300e6, 4_000e6, 200e6, 50e6, 100e6],
        C.CD_APLIC_FINANCEIRAS: [100e6, 1_000e6, 50e6, 0.0, 0.0],
        C.CD_PASSIVO_CIRCULANTE: [900e6, 6_000e6, 700e6, 300e6, 400e6],
        C.CD_EMPRESTIMOS_CP: [200e6, 1_500e6, 150e6, 100e6, 50e6],
        C.CD_EMPRESTIMOS_LP: [800e6, 9_000e6, 2_000e6, 400e6, 300e6],
        C.CD_IMOBILIZADO: [1_200e6, 3_000e6, 5_000e6, 400e6, 600e6],
        C.CD_ATIVO_TOTAL: [5_000e6, 40_000e6, 9_000e6, 1_500e6, 2_000e6],
        C.CD_PATRIMONIO_LIQUIDO: [2_000e6, 12_000e6, 3_000e6, 400e6, 800e6],
    })


# ---------------------------------------------------------------------------
# Fundamentos
# ---------------------------------------------------------------------------
def test_capital_tangivel_formula_do_livro(universo):
    ct = fundamentals.capital_tangivel(universo)
    # Alfa: giro = (2000 - 300 - 100) - (900 - 200) = 900 ; + imob 1200 = 2100
    assert ct.iloc[0] == pytest.approx(2_100e6)


def test_capital_de_giro_negativo_e_zerado():
    bp = pd.DataFrame({
        C.CD_ATIVO_CIRCULANTE: [100.0], C.CD_CAIXA: [90.0],
        C.CD_APLIC_FINANCEIRAS: [0.0], C.CD_PASSIVO_CIRCULANTE: [500.0],
        C.CD_EMPRESTIMOS_CP: [0.0], C.CD_IMOBILIZADO: [700.0],
    })
    assert fundamentals.capital_tangivel(bp).iloc[0] == 700.0


def test_ev_e_earnings_yield(universo):
    p = C.Params()
    ind = fundamentals.montar_indicadores(
        universo[["CD_CVM", "DENOM_CIA", "EBIT_LTM"]],
        universo.drop(columns=["DENOM_CIA", "EBIT_LTM", "TICKER", "SETOR",
                               "VALOR_MERCADO", "ACOES", "LIQUIDEZ_MEDIA"]),
        universo[["CD_CVM", "TICKER", "SETOR", "VALOR_MERCADO", "ACOES", "LIQUIDEZ_MEDIA"]],
        p)
    # Alfa: EV = 4000 + (200+800) - (300+100) = 4600 ; EY = 1000/4600
    alfa = ind[ind["CD_CVM"] == 1].iloc[0]
    assert alfa["EV"] == pytest.approx(4_600e6)
    assert alfa["EY"] == pytest.approx(1_000 / 4_600, rel=1e-6)


def test_ey_do_tcc_e_insensivel_ao_preco(universo):
    """Demonstra o erro original: dobrar o preço da ação não muda o 'EY' do TCC."""
    p_tcc = C.Params(base_ey="lpa_original_tcc")
    p_ok = C.Params(base_ey="ebit_ev")
    mercado = universo[["CD_CVM", "TICKER", "SETOR", "VALOR_MERCADO",
                        "ACOES", "LIQUIDEZ_MEDIA"]]
    bp = universo.drop(columns=["DENOM_CIA", "EBIT_LTM", "TICKER", "SETOR",
                                "VALOR_MERCADO", "ACOES", "LIQUIDEZ_MEDIA"])
    ebit = universo[["CD_CVM", "DENOM_CIA", "EBIT_LTM"]]

    caro = mercado.copy()
    caro["VALOR_MERCADO"] = caro["VALOR_MERCADO"] * 2

    ey_tcc_a = fundamentals.montar_indicadores(ebit, bp, mercado, p_tcc)["EY"]
    ey_tcc_b = fundamentals.montar_indicadores(ebit, bp, caro, p_tcc)["EY"]
    ey_ok_a = fundamentals.montar_indicadores(ebit, bp, mercado, p_ok)["EY"]
    ey_ok_b = fundamentals.montar_indicadores(ebit, bp, caro, p_ok)["EY"]

    assert np.allclose(ey_tcc_a, ey_tcc_b)          # bug: não reage ao preço
    assert not np.allclose(ey_ok_a, ey_ok_b)        # corrigido: reage


def test_filtros_excluem_setor_liquidez_e_ebit_negativo(universo):
    p = C.Params(liquidez_minima_diaria=1e6)
    ind = fundamentals.montar_indicadores(
        universo[["CD_CVM", "DENOM_CIA", "EBIT_LTM"]],
        universo.drop(columns=["DENOM_CIA", "EBIT_LTM", "TICKER", "SETOR",
                               "VALOR_MERCADO", "ACOES", "LIQUIDEZ_MEDIA"]),
        universo[["CD_CVM", "TICKER", "SETOR", "VALOR_MERCADO", "ACOES", "LIQUIDEZ_MEDIA"]],
        p)
    ok, fora = fundamentals.aplicar_filtros(ind, p)
    motivos = set(fora["MOTIVO_EXCLUSAO"])
    assert "AAA3.SA" in set(ok["TICKER"])
    assert "BBB4.SA" not in set(ok["TICKER"])   # banco
    assert "CCC3.SA" not in set(ok["TICKER"])   # utility
    assert "DDD3.SA" not in set(ok["TICKER"])   # EBIT negativo
    assert "EEE3.SA" not in set(ok["TICKER"])   # ilíquida
    assert any("EBIT" in m for m in motivos)


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------
def test_ranking_soma_posicoes_e_trata_empates():
    df = pd.DataFrame({
        "TICKER": list("ABCD"),
        "ROIC": [0.30, 0.30, 0.20, 0.10],
        "EY": [0.05, 0.15, 0.25, 0.35],
    })
    rk = ranking.ranquear(df, n=2)
    r = rk.set_index("TICKER")
    assert r.loc["A", "POS_ROIC"] == 1 and r.loc["B", "POS_ROIC"] == 1   # empate
    assert r.loc["C", "POS_ROIC"] == 3                                    # method='min'
    # EY: D=1, C=2, B=3, A=4  ->  B soma 1 (ROIC) + 3 (EY)
    assert r.loc["B", "RANK_FINAL"] == 1 + 3
    assert r.loc["A", "RANK_FINAL"] == 1 + 4
    assert rk["SELECIONADA"].sum() == 2
    assert rk["RANK_FINAL"].is_monotonic_increasing


# ---------------------------------------------------------------------------
# Otimizador
# ---------------------------------------------------------------------------
def test_ledoit_wolf_e_positiva_definida_e_encolhe(retornos):
    S = optimizer.cov_ledoit_wolf(retornos)
    assert np.all(np.linalg.eigvalsh(S.to_numpy()) > 0)
    amostral = optimizer.cov_hist(retornos)
    # o encolhimento reduz a dispersão das correlações fora da diagonal
    off = lambda M: M.to_numpy()[~np.eye(len(M), dtype=bool)]
    assert off(S).std() <= off(amostral).std() + 1e-12


def test_min_variancia_respeita_restricoes(retornos):
    mu, cov = optimizer.estimar(retornos, "ewma", "ledoit_wolf")
    w = optimizer.carteira_min_variancia(mu, cov, w_max=0.20)
    assert w.sum() == pytest.approx(1.0, abs=1e-6)
    assert (w >= -1e-9).all()
    assert w.max() <= 0.20 + 1e-6


def test_min_variancia_tem_variancia_menor_que_equal_weight(retornos):
    mu, cov = optimizer.estimar(retornos, "ewma", "ledoit_wolf")
    w = optimizer.carteira_min_variancia(mu, cov, w_max=1.0)
    ew = pd.Series(1 / len(mu), index=mu.index)
    assert float(w @ cov @ w) <= float(ew @ cov @ ew) + 1e-12


def test_fronteira_e_monotona_e_convexa(retornos):
    mu, cov = optimizer.estimar(retornos, "hist", "ledoit_wolf")
    fr = optimizer.fronteira_eficiente(mu, cov, pontos=10, w_max=0.30)
    assert fr.pesos.shape[1] >= 5
    assert np.all(np.diff(fr.retorno) >= -1e-8)     # retorno cresce
    assert np.all(np.diff(fr.risco) >= -1e-6)       # risco também
    assert np.allclose(fr.pesos.sum(axis=0), 1.0, atol=1e-6)
    assert fr.pesos.to_numpy().max() <= 0.30 + 1e-6


def test_limpar_pesos_renormaliza():
    w = pd.Series({"A": 0.60, "B": 0.395, "C": 0.004, "D": 0.001})
    lim = optimizer.limpar_pesos(w, minimo=0.005)
    assert lim["C"] == 0 and lim["D"] == 0
    assert lim.sum() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def test_retorno_da_carteira_bate_com_calculo_manual():
    idx = pd.bdate_range("2024-01-01", periods=3)
    r = pd.DataFrame({"X": [0.10, 0.00, -0.05], "Y": [-0.02, 0.03, 0.01]}, index=idx)
    w = pd.Series({"X": 0.6, "Y": 0.4})
    rp = backtest.retorno_carteira(r, w, custo_bps=0)
    valor_final = 0.6 * np.prod(1 + r["X"]) + 0.4 * np.prod(1 + r["Y"])
    assert float((1 + rp).prod()) == pytest.approx(valor_final)


def test_soma_de_acumulados_e_o_bug_do_tcc():
    """Somar retornos acumulados individuais só coincide com o retorno da
    carteira em buy-and-hold; com rebalanceamento diário, não."""
    idx = pd.bdate_range("2024-01-01", periods=60)
    rng = np.random.default_rng(7)
    r = pd.DataFrame(rng.normal(0.001, 0.02, (60, 3)), index=idx, columns=list("XYZ"))
    w = pd.Series({"X": 0.5, "Y": 0.3, "Z": 0.2})

    bh = float((1 + backtest.retorno_carteira(r, w, custo_bps=0)).prod() - 1)
    soma_acumulados = float((w * ((1 + r).prod() - 1)).sum())
    assert bh == pytest.approx(soma_acumulados, abs=1e-10)

    reb = float((1 + backtest.retorno_carteira(r, w, rebalancear=True, custo_bps=0)).prod() - 1)
    assert abs(reb - soma_acumulados) > 1e-6


def test_custo_de_transacao_reduz_retorno():
    idx = pd.bdate_range("2024-01-01", periods=10)
    r = pd.DataFrame({"X": [0.0] * 10}, index=idx)
    w = pd.Series({"X": 1.0})
    liquido = float((1 + backtest.retorno_carteira(r, w, custo_bps=15)).prod() - 1)
    assert liquido == pytest.approx((1 - 0.0015) ** 2 - 1, rel=1e-9)


def test_beta_alinha_por_nome_nao_por_posicao(retornos):
    bench = retornos.mean(axis=1).rename("bench")
    b = backtest.betas_individuais(retornos, bench)
    embaralhado = retornos[list(reversed(retornos.columns))]
    b2 = backtest.betas_individuais(embaralhado, bench)
    pd.testing.assert_series_equal(b.sort_index(), b2.sort_index())


def test_correlacao_usa_retornos_nao_precos():
    idx = pd.bdate_range("2024-01-01", periods=250)
    rng = np.random.default_rng(3)
    ra = pd.Series(rng.normal(0.001, 0.02, 250), index=idx)
    rb = pd.Series(rng.normal(0.001, 0.02, 250), index=idx)
    pa, pb = (1 + ra).cumprod(), (1 + rb).cumprod()
    corr_precos = pa.corr(pb)
    corr_retornos = ra.corr(rb)
    assert abs(corr_retornos) < 0.2          # de fato independentes
    assert abs(corr_precos) > abs(corr_retornos)   # preço infla a correlação


def test_metricas_basicas():
    idx = pd.bdate_range("2024-01-01", periods=252)
    r = pd.Series([0.0] * 251 + [0.10], index=idx)
    m = backtest.calcular_metricas(r, r, rf_aa=0.0)
    assert m.retorno_total == pytest.approx(0.10)
    assert m.beta == pytest.approx(1.0, abs=1e-6)
    assert m.drawdown_maximo == pytest.approx(0.0)


def test_drawdown_maximo():
    r = pd.Series([0.5, -0.5, 0.1])
    # 1 -> 1.5 -> 0.75 : queda de 50% a partir do pico
    assert backtest.drawdown_maximo(r) == pytest.approx(-0.5)


def test_backtest_com_rebalanceamento(retornos):
    bench = retornos.mean(axis=1)
    datas = [retornos.index[0], retornos.index[200]]
    w = pd.Series(1 / retornos.shape[1], index=retornos.columns)
    res = backtest.rodar_backtest(lambda d: w, datas, retornos, bench,
                                  custo_bps=10, rf_aa=0.10)
    assert len(res.retornos_diarios) > 300
    assert res.retornos_diarios.index.is_monotonic_increasing
    assert not res.retornos_diarios.index.has_duplicates
    assert len(res.composicoes) == 2
    assert np.isfinite(res.metricas.sharpe)


# ---------------------------------------------------------------------------
# Regressões vindas da execução real no GitHub Actions
# ---------------------------------------------------------------------------
def test_filtros_com_universo_vazio_nao_quebram():
    """Regressão: `df[campos].agg(" | ".join, axis=1)` devolve um DataFrame
    quando o DataFrame está vazio, e o `.str` seguinte estourava com
    AttributeError. Derrubou a execução #5 no GitHub Actions."""
    cols = ["CD_CVM", "TICKER", "SETOR", "SEGMENTO", "LIQUIDEZ_MEDIA",
            "EBIT_LTM", "EV", "ROIC", "EY"]
    vazio = pd.DataFrame(columns=cols)
    ok, fora = fundamentals.aplicar_filtros(vazio, C.Params())
    assert ok.empty and fora.empty


def test_filtros_usam_setor_e_segmento_juntos():
    df = pd.DataFrame({
        "CD_CVM": [1, 2, 3],
        "TICKER": ["AAA3.SA", "BBB3.SA", "CCC3.SA"],
        "SETOR": ["Comércio", "Comércio", "Comércio"],
        "SEGMENTO": ["Novo Mercado", "Bancos", "Energia Elétrica"],
        "LIQUIDEZ_MEDIA": [50e6] * 3,
        "EBIT_LTM": [1e9] * 3, "EV": [5e9] * 3,
        "ROIC": [0.2] * 3, "EY": [0.2] * 3,
    })
    ok, fora = fundamentals.aplicar_filtros(df, C.Params(liquidez_minima_diaria=1e6))
    assert set(ok["TICKER"]) == {"AAA3.SA"}          # os outros caem pelo SEGMENTO
    assert len(fora) == 2


def test_cruzamento_vazio_da_erro_explicativo():
    """Antes o universo saía vazio em silêncio e só estourava lá adiante."""
    ebit = pd.DataFrame({"CD_CVM": [1, 2], "EBIT_LTM": [1e9, 2e9]})
    bp = pd.DataFrame({"CD_CVM": [1, 2], C.CD_ATIVO_CIRCULANTE: [1e9, 1e9]})
    mercado = pd.DataFrame({"CD_CVM": [99], "TICKER": ["ZZZ3.SA"],
                            "VALOR_MERCADO": [1e9], "ACOES": [1e8],
                            "LIQUIDEZ_MEDIA": [1e6]})
    with pytest.raises(ValueError, match="não devolveu"):
        fundamentals.montar_indicadores(ebit, bp, mercado, C.Params())


def test_cd_cvm_como_texto_ou_float_ainda_cruza():
    """CD_CVM vem de três fontes; tipos diferentes não podem zerar o cruzamento."""
    ebit = pd.DataFrame({"CD_CVM": [906, 4170], "EBIT_LTM": [1e9, 2e9]})
    bp = pd.DataFrame({"CD_CVM": [906.0, 4170.0],       # float
                       C.CD_ATIVO_CIRCULANTE: [2e9, 2e9], C.CD_CAIXA: [1e8, 1e8],
                       C.CD_PASSIVO_CIRCULANTE: [5e8, 5e8], C.CD_IMOBILIZADO: [1e9, 1e9]})
    mercado = pd.DataFrame({"CD_CVM": ["906", "4170"],   # texto
                            "TICKER": ["AAA3.SA", "BBB3.SA"],
                            "VALOR_MERCADO": [5e9, 6e9], "ACOES": [1e9, 1e9],
                            "LIQUIDEZ_MEDIA": [1e7, 1e7], "SETOR": ["Comércio"] * 2})
    out = fundamentals.montar_indicadores(ebit, bp, mercado, C.Params())
    assert len(out) == 2
    assert set(out["TICKER"]) == {"AAA3.SA", "BBB3.SA"}
    assert (out["EY"] > 0).all()
