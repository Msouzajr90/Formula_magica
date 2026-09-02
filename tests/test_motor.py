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

    # a "Beta" é banco e agora sai como NaN (métricas próprias), então o
    # equal_nan isola o que este teste realmente mede: a reação ao preço
    assert np.allclose(ey_tcc_a, ey_tcc_b, equal_nan=True)   # bug: não reage
    assert not np.allclose(ey_ok_a, ey_ok_b, equal_nan=True)  # corrigido: reage


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


# ---------------------------------------------------------------------------
# Financeiras: métricas próprias e ranking separado
# ---------------------------------------------------------------------------
def _universo_misto():
    """Três operacionais e duas financeiras, com os campos de cada grupo."""
    return pd.DataFrame({
        "CD_CVM": [1, 2, 3, 4, 5],
        "TICKER": ["OPA3.SA", "OPB3.SA", "OPC3.SA", "BBAS3.SA", "ITUB4.SA"],
        "DENOM_CIA": ["Op A", "Op B", "Op C", "Banco A", "Banco B"],
        "SETOR": ["Comércio", "Comércio", "Comércio", "Bancos", "Bancos"],
        "EBIT_LTM": [1e9, 2e9, 0.5e9, 5e9, 8e9],
        "LUCRO_LTM": [0.6e9, 1.2e9, 0.3e9, 17e9, 40e9],
        "PATRIMONIO": [3e9, 8e9, 2e9, 190e9, 220e9],
        "VALOR_MERCADO": [5e9, 20e9, 3e9, 120e9, 380e9],
        "ACOES": [1e9] * 5,
        "LIQUIDEZ_MEDIA": [50e6] * 5,
        C.CD_ATIVO_CIRCULANTE: [2e9, 6e9, 1e9, 65e9, 90e9],
        C.CD_CAIXA: [0.3e9, 1e9, 0.1e9, 27e9, 30e9],
        C.CD_APLIC_FINANCEIRAS: [0.0] * 5,
        C.CD_PASSIVO_CIRCULANTE: [0.9e9, 3e9, 0.5e9, 5e9, 8e9],
        C.CD_EMPRESTIMOS_CP: [0.2e9, 0.5e9, 0.1e9, 0.0, 0.0],
        C.CD_EMPRESTIMOS_LP: [0.8e9, 2e9, 0.4e9, 954e9, 1200e9],
        C.CD_INVESTIMENTOS: [0.0, 0.0, 0.0, 0.0, 0.0],
        C.CD_IMOBILIZADO: [1.2e9, 4e9, 0.8e9, 710e9, 900e9],
        C.CD_ATIVO_TOTAL: [5e9, 15e9, 3e9, 2588e9, 3000e9],
    })


def _indicadores(uni, params):
    mercado = uni[["CD_CVM", "TICKER", "SETOR", "VALOR_MERCADO", "ACOES", "LIQUIDEZ_MEDIA"]]
    ebit = uni[["CD_CVM", "DENOM_CIA", "EBIT_LTM", "LUCRO_LTM"]]
    bp = uni.drop(columns=["DENOM_CIA", "EBIT_LTM", "LUCRO_LTM", "TICKER", "SETOR",
                           "VALOR_MERCADO", "ACOES", "LIQUIDEZ_MEDIA"])
    return fundamentals.montar_indicadores(ebit, bp, mercado, params)


def test_financeiras_usam_roe_e_lucro_preco():
    """Num banco, ROIC e EBIT/EV não têm sentido: 'dívida' é depósito de cliente
    e o capital tangível não é o que produz o resultado."""
    p = C.Params(vagas_financeiras=2, liquidez_minima_diaria=1e6)
    ind = _indicadores(_universo_misto(), p).set_index("TICKER")

    assert ind.loc["BBAS3.SA", "TIPO"] == "financeira"
    assert ind.loc["OPA3.SA", "TIPO"] == "operacional"
    # banco: ROIC vira ROE = 17/190 ; EY vira Lucro/Preço = 17/120
    assert ind.loc["BBAS3.SA", "ROIC"] == pytest.approx(17 / 190, rel=1e-6)
    assert ind.loc["BBAS3.SA", "EY"] == pytest.approx(17 / 120, rel=1e-6)
    # operacional: segue EBIT/capital tangível e EBIT/EV
    ct = (2 - 0.3) - (0.9 - 0.2) + 1.2          # = 2,2 bi
    assert ind.loc["OPA3.SA", "ROIC"] == pytest.approx(1 / ct, rel=1e-6)


def test_cota_reserva_vagas_e_nao_mistura_os_rankings():
    p = C.Params(vagas_financeiras=1, n_acoes_ranking=3, liquidez_minima_diaria=1e6)
    ok, _ = fundamentals.aplicar_filtros(_indicadores(_universo_misto(), p), p)
    rk = ranking.ranquear(ok, n=3, vagas_financeiras=1)
    sel = rk[rk["SELECIONADA"]]
    assert (sel["TIPO"] == "financeira").sum() == 1
    assert (sel["TIPO"] == "operacional").sum() == 2
    # cada grupo é numerado a partir de 1 — as posições não são comparáveis
    for tipo in ("operacional", "financeira"):
        g = rk[rk["TIPO"] == tipo]
        assert g["POSICAO"].min() == 1


def test_sem_cota_as_financeiras_sao_excluidas():
    p = C.Params(vagas_financeiras=0, liquidez_minima_diaria=1e6)
    ok, fora = fundamentals.aplicar_filtros(_indicadores(_universo_misto(), p), p)
    assert set(ok["TICKER"]) == {"OPA3.SA", "OPB3.SA", "OPC3.SA"}
    assert {"BBAS3.SA", "ITUB4.SA"} <= set(fora["TICKER"])


def test_investimentos_entram_no_capital_tangivel():
    """Regressão dos shoppings: Allos tinha R$ 0,11 bi de imobilizado e
    R$ 20 bi em Investimentos, o que dava ROIC de 1.358%."""
    bp = pd.DataFrame({
        C.CD_ATIVO_CIRCULANTE: [3.96e9], C.CD_CAIXA: [1.0e9],
        C.CD_APLIC_FINANCEIRAS: [0.0], C.CD_PASSIVO_CIRCULANTE: [3.0e9],
        C.CD_EMPRESTIMOS_CP: [0.0], C.CD_INVESTIMENTOS: [20.0e9],
        C.CD_IMOBILIZADO: [0.11e9],
    })
    ebit = 1.51e9
    sem = float(fundamentals.capital_tangivel(bp, incluir_investimentos=False).iloc[0])
    com = float(fundamentals.capital_tangivel(bp, incluir_investimentos=True).iloc[0])
    assert com - sem == pytest.approx(20.0e9)
    assert ebit / sem > 10          # ROIC > 1.000%, o artefato
    assert 0.02 < ebit / com < 0.15  # ROIC plausível depois da correção


# ---------------------------------------------------------------------------
# Histórico do backtest (o arquivo que o site consome)
# ---------------------------------------------------------------------------
def test_historico_demo_tem_estrutura_valida(tmp_path):
    from magicb3 import demo_historico
    import json
    destino = tmp_path / "historico.json"
    d = demo_historico.gerar(destino, anos=3)
    assert destino.exists()

    n = len(d["pregoes"])
    assert n > 500
    assert len(d["benchmark"]) == n
    for t, serie in d["retornos"].items():
        assert len(serie) == n, f"{t} com tamanho diferente"
    assert d["meta"]["pointInTime"] is True
    assert len(d["rebalances"]) >= 3
    for r in d["rebalances"]:
        assert r["acoes"], f"{r['data']} sem ranking"
        assert {"t", "yf", "f", "q", "p"} <= set(r["acoes"][0])

    # os retornos são inteiros escalados; reconstituir tem que dar valores plausíveis
    esc = d["meta"]["escalaRetornos"]
    algum = next(iter(d["retornos"].values()))
    vals = [v / esc for v in algum if v is not None]
    assert all(-0.5 < v < 0.5 for v in vals), "retorno diário fora de faixa plausível"


def test_validador_de_historico_reprova_demonstracao(tmp_path):
    """O gate tem que barrar o arquivo sintético, como faz com o dados.json."""
    import json, subprocess, sys
    from magicb3 import demo_historico
    destino = tmp_path / "historico.json"
    demo_historico.gerar(destino, anos=3)
    r = subprocess.run([sys.executable, "validar_historico.py", str(destino)],
                       capture_output=True, text=True)
    assert r.returncode == 1
    assert "demonstracao" in r.stdout.lower()


def test_validador_de_historico_aprova_arquivo_bom(tmp_path):
    import json
    from magicb3 import demo_historico
    import subprocess, sys
    destino = tmp_path / "historico.json"
    d = demo_historico.gerar(destino, anos=3)
    d["meta"].pop("modo")            # simula o arquivo real
    destino.write_text(json.dumps(d), encoding="utf-8")
    r = subprocess.run([sys.executable, "validar_historico.py", str(destino)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout


# ---------------------------------------------------------------------------
# Cotações: bloqueio do Yahoo vs. ticker que não existe
#
# Em produção a Action rodou 46 minutos levando YFRateLimitError em lotes
# inteiros. O recuo de 20s nunca era aplicado porque o yf.download não levanta
# exceção quando é barrado — ele registra "Failed downloads" no logger e
# devolve um DataFrame vazio, que o código antigo lia como "lote sem dados".
# ---------------------------------------------------------------------------
class _YFFalso:
    """Dublê do yfinance que reproduz os três desfechos reais."""

    def __init__(self, modo, falhas=0):
        self.modo, self.falhas, self.chamadas = modo, falhas, 0

    def download(self, tickers, **kw):
        import logging
        self.chamadas += 1
        lg = logging.getLogger("yfinance")
        modo = self.modo
        if modo == "bloqueio_temporario":
            modo = "bloqueio" if self.chamadas <= self.falhas else "ok"
        if modo == "bloqueio":
            lg.error("%d Failed downloads:", len(tickers))
            lg.error("%s: YFRateLimitError('Too Many Requests. Rate limited.')", tickers)
            return pd.DataFrame()
        if modo == "inexistente":
            lg.error("%d Failed downloads:", len(tickers))
            lg.error("%s: possibly delisted; no timezone found", tickers)
            return pd.DataFrame()
        idx = pd.date_range("2026-01-02", periods=8, freq="B")
        cols = pd.MultiIndex.from_product([["Adj Close", "Close", "Volume"], list(tickers)])
        return pd.DataFrame(1.0, index=idx, columns=cols)


@pytest.fixture
def sem_espera(monkeypatch):
    from magicb3 import prices
    monkeypatch.setattr(prices.time, "sleep", lambda s: None)


def _instalar(monkeypatch, fake, tmp_path):
    from magicb3 import prices
    monkeypatch.setattr(prices, "_yf", lambda: fake)
    monkeypatch.setattr(prices, "_cache",
                        lambda nome: tmp_path / nome)
    return prices


def test_bloqueio_do_yahoo_e_distinguido_de_ticker_inexistente(monkeypatch, sem_espera, tmp_path):
    fake = _YFFalso("bloqueio")
    prices = _instalar(monkeypatch, fake, tmp_path)
    dados, bloqueados, mortos = prices._baixar_lote(["AAAA3.SA"], "2026-01-01", "2026-02-01")
    assert dados is None and bloqueados == {"AAAA3.SA"} and not mortos
    assert fake.chamadas == 4, "bloqueio merece nova tentativa"

    fake2 = _YFFalso("inexistente")
    _instalar(monkeypatch, fake2, tmp_path)
    dados, bloqueados, mortos = prices._baixar_lote(["ZZZZ9.SA"], "2026-01-01", "2026-02-01")
    assert dados is None and not bloqueados and mortos == {"ZZZZ9.SA"}
    assert fake2.chamadas == 1, "ticker inexistente nao pode gastar 4 tentativas"


def test_lote_barrado_uma_vez_ainda_e_recuperado(monkeypatch, sem_espera, tmp_path):
    fake = _YFFalso("bloqueio_temporario", falhas=2)
    prices = _instalar(monkeypatch, fake, tmp_path)
    dados, bloqueados, _ = prices._baixar_lote(["AAAA3.SA"], "2026-01-01", "2026-02-01")
    assert not bloqueados and dados is not None and not dados.empty


def test_bloqueio_persistente_interrompe_em_vez_de_gastar_horas(monkeypatch, sem_espera, tmp_path):
    """Sem isso a rodada gasta os 180 minutos do workflow e nao entrega nada."""
    from magicb3 import prices as _p
    fake = _YFFalso("bloqueio")
    prices = _instalar(monkeypatch, fake, tmp_path)
    universo = [f"A{i:03d}3.SA" for i in range(500)]      # 10 lotes
    with pytest.raises(_p.BloqueioYahoo):
        prices.baixar_historico(universo, "2026-01-01", "2026-02-01")
    # 1 tentativa por lote, 10 lotes, 4 rodadas: varredura + 3 repescagens.
    assert fake.chamadas == 40


def test_nao_espera_dentro_do_lote_na_varredura(monkeypatch, sem_espera, tmp_path):
    """O bloqueio e intermitente: adiar custa menos que esperar parado."""
    from magicb3 import prices as _p
    fake = _YFFalso("bloqueio")
    prices = _instalar(monkeypatch, fake, tmp_path)
    original, usados = prices._baixar_lote, []

    def espiao(lote, ini, fim, tentativas=4):
        usados.append(tentativas)
        return original(lote, ini, fim, tentativas=tentativas)

    monkeypatch.setattr(prices, "_baixar_lote", espiao)
    esperas = []
    monkeypatch.setattr(prices.time, "sleep", lambda s: esperas.append(s))
    with pytest.raises(_p.BloqueioYahoo):
        prices.baixar_historico([f"A{i:03d}3.SA" for i in range(50)],
                                "2026-01-01", "2026-02-01")
    assert usados and set(usados) == {1}, \
        "cada lote leva uma tentativa so; a espera fica entre as rodadas"
    assert sum(esperas) <= _p.ORCAMENTO_ESPERA_S, "orcamento de espera estourado"


def test_perda_pequena_por_bloqueio_nao_derruba_a_rodada(monkeypatch, sem_espera, tmp_path):
    """Perder 2 de 100 papeis e aceitavel; perder 40 nao e."""
    entregues = [f"A{i:03d}3.SA" for i in range(98)]
    teimosos = ["X0013.SA", "X0023.SA"]
    fake = _YFMisto(set(entregues), set(teimosos), set())
    fake.entregues = set(entregues)

    class Teimoso(_YFMisto):
        def download(self, tickers, **kw):
            import logging
            self.chamadas += 1
            lg = logging.getLogger("yfinance")
            vivos = [t for t in tickers if t in self.entregues]
            barrados = [t for t in tickers if t in self.bloqueados]
            if barrados:
                lg.error("%s: YFRateLimitError('Too Many Requests.')", barrados)
            if not vivos:
                return pd.DataFrame()
            idx = pd.date_range("2026-01-02", periods=8, freq="B")
            cols = pd.MultiIndex.from_product([["Adj Close", "Close", "Volume"], vivos])
            return pd.DataFrame(1.0, index=idx, columns=cols)

    fake = Teimoso(set(entregues), set(teimosos), set())
    prices = _instalar(monkeypatch, fake, tmp_path)
    out = prices.baixar_historico(entregues + teimosos, "2026-01-01", "2026-02-01")
    assert len(out["preco"].columns) == 98


def test_inexistentes_ficam_anotados_e_nao_sao_reconsultados(monkeypatch, sem_espera, tmp_path):
    fake = _YFFalso("inexistente")
    prices = _instalar(monkeypatch, fake, tmp_path)
    universo = [f"Z{i:03d}9.SA" for i in range(100)]      # 2 lotes
    prices.baixar_historico(universo, "2026-01-01", "2026-02-01")
    assert fake.chamadas == 2
    assert len(prices._carregar_inexistentes()) == 100

    fake2 = _YFFalso("inexistente")
    _instalar(monkeypatch, fake2, tmp_path)
    prices.baixar_historico(universo, "2026-01-01", "2026-02-01")
    assert fake2.chamadas == 0, "a segunda rodada nao pode repetir o desperdicio"


def test_cache_por_lote_sobrevive_a_rodada_interrompida(monkeypatch, sem_espera, tmp_path):
    """O que ja baixou tem que valer na proxima tentativa."""
    fake = _YFFalso("ok")
    prices = _instalar(monkeypatch, fake, tmp_path)
    universo = [f"A{i:03d}3.SA" for i in range(100)]
    prices.baixar_historico(universo, "2026-01-01", "2026-02-01")
    assert fake.chamadas == 2

    fake2 = _YFFalso("bloqueio")            # rede pessima na segunda rodada
    _instalar(monkeypatch, fake2, tmp_path)
    out = prices.baixar_historico(universo, "2026-01-01", "2026-02-01")
    assert fake2.chamadas == 0
    assert not out["preco"].empty


def test_chave_de_cache_e_estavel_entre_processos():
    """hash() do Python muda a cada processo; o cache antigo nunca era reusado."""
    import subprocess, sys
    codigo = ("from magicb3.prices import _chave;"
              "print(_chave(('PETR4.SA','VALE3.SA'), '2020-01-01', '2026-01-01'))")
    a = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True)
    b = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True)
    assert a.stdout.strip() and a.stdout == b.stdout


class _YFMisto:
    """Reproduz o lote misto que apareceu na producao.

    49 dos 50 falharam: 25 por nao existirem e 16 por bloqueio. O unico que
    respondeu fazia o lote parecer bem-sucedido, e os 16 bloqueados sumiam
    calados — que e exatamente o tipo de perda silenciosa que o projeto inteiro
    tenta evitar.
    """

    def __init__(self, entregues, bloqueados, mortos):
        self.entregues, self.bloqueados, self.mortos = entregues, bloqueados, mortos
        self.chamadas, self.vistos = 0, []

    def download(self, tickers, **kw):
        import logging
        self.chamadas += 1
        self.vistos.append(list(tickers))
        lg = logging.getLogger("yfinance")
        pedidos = list(tickers)
        # na repescagem os bloqueados passam a responder
        vivos = [t for t in pedidos if t in self.entregues or
                 (self.chamadas > 1 and t in self.bloqueados)]
        barrados = [t for t in pedidos if t in self.bloqueados and self.chamadas == 1]
        mortos = [t for t in pedidos if t in self.mortos]
        if barrados:
            lg.error("%s: YFRateLimitError('Too Many Requests. Rate limited.')", barrados)
        if mortos:
            lg.error("%s: possibly delisted; no timezone found", mortos)
        if not vivos:
            return pd.DataFrame()
        idx = pd.date_range("2026-01-02", periods=8, freq="B")
        cols = pd.MultiIndex.from_product([["Adj Close", "Close", "Volume"], vivos])
        return pd.DataFrame(1.0, index=idx, columns=cols)


def test_lote_parcialmente_bloqueado_nao_perde_os_papeis_calado(monkeypatch, sem_espera, tmp_path):
    entregues = ["AAAA3.SA"]
    bloqueados = [f"B{i:03d}3.SA" for i in range(16)]
    mortos = [f"M{i:03d}9.SA" for i in range(25)]
    fake = _YFMisto(set(entregues), set(bloqueados), set(mortos))
    prices = _instalar(monkeypatch, fake, tmp_path)

    out = prices.baixar_historico(entregues + bloqueados + mortos,
                                  "2026-01-01", "2026-02-01")
    colunas = set(out["preco"].columns)
    faltando = set(bloqueados) - colunas
    assert not faltando, f"a repescagem deixou {len(faltando)} papeis para tras"
    assert fake.chamadas == 2, "deveria haver exatamente uma repescagem"
    assert set(fake.vistos[1]) == set(bloqueados), \
        "a repescagem so pode reconsultar quem caiu por bloqueio"


def test_lote_mutilado_por_bloqueio_nao_vira_cache(monkeypatch, sem_espera, tmp_path):
    """Cachear um lote incompleto congelaria a perda para sempre."""
    entregues, bloqueados = ["AAAA3.SA"], ["BBBB3.SA"]
    fake = _YFMisto(set(entregues), set(bloqueados), set())
    prices = _instalar(monkeypatch, fake, tmp_path)
    prices.baixar_historico(entregues + bloqueados, "2026-01-01", "2026-02-01")
    lotes_em_cache = list(tmp_path.glob("lt*_*.parquet"))
    nomes = [p.name for p in lotes_em_cache]
    assert len(lotes_em_cache) == 1, f"so a repescagem completa podia virar cache: {nomes}"


def test_pausa_entre_lotes_cresce_quando_o_yahoo_barra(monkeypatch, sem_espera, tmp_path):
    from magicb3 import prices as _p
    fake = _YFFalso("bloqueio")
    prices = _instalar(monkeypatch, fake, tmp_path)
    esperas = []
    monkeypatch.setattr(prices.time, "sleep", lambda s: esperas.append(s))
    universo = [f"A{i:03d}3.SA" for i in range(150)]
    with pytest.raises(_p.BloqueioYahoo):
        prices.baixar_historico(universo, "2026-01-01", "2026-02-01")
    longas = set(_p.ESPERA_BLOQUEIO) | set(_p.ESPERA_ENTRE_RODADAS)
    entre_lotes = [e for e in esperas if e not in longas]
    assert entre_lotes and entre_lotes[-1] > entre_lotes[0], \
        "a pausa entre lotes tinha que subir depois de um bloqueio"
    assert max(entre_lotes) <= _p.PAUSA_MAXIMA


def test_cache_antigo_de_lote_e_aposentado(tmp_path, monkeypatch):
    """O prefixo tem que mudar: a versao anterior cacheava lote mutilado."""
    from magicb3 import prices
    monkeypatch.setattr(prices, "_cache", lambda nome: tmp_path / nome)
    fake = _YFFalso("ok")
    monkeypatch.setattr(prices, "_yf", lambda: fake)
    (tmp_path / "lt_deadbeefdeadbeef.parquet").write_bytes(b"lixo antigo")
    prices.baixar_historico(["AAAA3.SA"], "2026-01-01", "2026-02-01")
    assert fake.chamadas == 1, "nao pode reaproveitar o cache da versao anterior"


def test_fracao_perdida_e_medida_sobre_os_papeis_que_existem(monkeypatch, sem_espera, tmp_path):
    """Perder 60 papeis reais nao pode passar por '3% de 2.000 chutes'."""
    from magicb3 import prices as _p
    reais = [f"R{i:03d}3.SA" for i in range(100)]
    chutes = [f"C{i:04d}9.SA" for i in range(1900)]

    class Cenario:
        def __init__(self):
            self.chamadas = 0

        def download(self, tickers, **kw):
            import logging
            self.chamadas += 1
            lg = logging.getLogger("yfinance")
            pedidos = list(tickers)
            mortos = [t for t in pedidos if t.startswith("C")]
            barrados = [t for t in pedidos if t.startswith("R")]
            if mortos:
                lg.error("%s: possibly delisted; no timezone found", mortos)
            if barrados:
                lg.error("%s: YFRateLimitError('Too Many Requests.')", barrados)
            return pd.DataFrame()

    fake = Cenario()
    prices = _instalar(monkeypatch, fake, tmp_path)
    with pytest.raises(_p.BloqueioYahoo) as erro:
        prices.baixar_historico(reais + chutes, "2026-01-01", "2026-02-01")
    assert "de 100 papéis" in str(erro.value), str(erro.value)


# ---------------------------------------------------------------------------
# Concessionarias: terceiro grupo, com cota propria
# ---------------------------------------------------------------------------
def _universo_tres_grupos():
    linhas = []
    for i in range(6):
        linhas.append({"TICKER": f"OPE{i}3.SA", "SETOR": "Comércio",
                       "TIPO": "operacional", "ROIC": 0.30 + i / 100,
                       "EY": 0.20 + i / 100})
    for i in range(4):
        linhas.append({"TICKER": f"BAN{i}4.SA", "SETOR": "Bancos",
                       "TIPO": "financeira", "ROIC": 0.18 + i / 100,
                       "EY": 0.15 + i / 100})
    for i in range(4):
        linhas.append({"TICKER": f"UTI{i}3.SA", "SETOR": "Energia Elétrica",
                       "TIPO": "utilidade", "ROIC": 0.12 + i / 100,
                       "EY": 0.13 + i / 100})
    return pd.DataFrame(linhas)


def test_utilidades_so_entram_com_vaga_reservada():
    df = _universo_tres_grupos()
    sem = ranking.ranquear(df, n=6)
    assert not (sem[sem["SELECIONADA"]]["TIPO"] == "utilidade").any()

    com = ranking.ranquear(df, n=6, vagas_utilidades=2)
    sel = com[com["SELECIONADA"]]
    assert (sel["TIPO"] == "utilidade").sum() == 2
    assert len(sel) == 6, "a cota sai das vagas das operacionais, nao soma"


def test_as_tres_cotas_convivem_sem_estourar_a_carteira():
    df = _universo_tres_grupos()
    rk = ranking.ranquear(df, n=8, vagas_financeiras=2, vagas_utilidades=3)
    sel = rk[rk["SELECIONADA"]]
    contagem = sel["TIPO"].value_counts().to_dict()
    assert contagem.get("financeira") == 2
    assert contagem.get("utilidade") == 3
    assert contagem.get("operacional") == 3
    assert len(sel) == 8


def test_utilidade_e_ranqueada_entre_as_suas_nao_contra_a_industria():
    """O ROIC regulado e menor por construcao; num ranking unico elas sumiriam."""
    df = _universo_tres_grupos()
    rk = ranking.ranquear(df, n=6, vagas_utilidades=2)
    uti = rk[rk["TIPO"] == "utilidade"].sort_values("POSICAO")
    assert list(uti["POSICAO"]) == [1, 2, 3, 4], "posicoes tem que ser do grupo"
    assert uti.iloc[0]["ROIC"] == pytest.approx(0.15), "a melhor do grupo e a 1a"


def test_cota_de_bancos_nao_liberta_as_concessionarias():
    """As duas exclusoes eram um `if` so; pedir banco trazia utility junto."""
    base = _universo_tres_grupos()
    universo = base.assign(
        CD_CVM=range(1, len(base) + 1), DENOM_CIA=base["TICKER"],
        EBIT_LTM=1e8, EV=5e8, VALOR_MERCADO=4e8, LIQUIDEZ_MEDIA=1e7,
        SEGMENTO="Novo Mercado")
    p = C.Params(vagas_financeiras=2, vagas_utilidades=0)
    aprov, _ = fundamentals.aplicar_filtros(universo, p)
    assert (aprov["TIPO"] == "financeira").any(), "bancos deviam ficar"
    assert not (aprov["TIPO"] == "utilidade").any(), "concessionarias nao foram pedidas"

    p2 = C.Params(vagas_financeiras=0, vagas_utilidades=2)
    aprov2, _ = fundamentals.aplicar_filtros(universo, p2)
    assert (aprov2["TIPO"] == "utilidade").any()
    assert not (aprov2["TIPO"] == "financeira").any(), "bancos nao foram pedidos"
