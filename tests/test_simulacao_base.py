# -*- coding: utf-8 -*-
"""Base de preços da aba Simulação — nenhum teste acessa a rede.

O teste que mais importa é `test_incremental_igual_ao_completo`: atualizar
dia a dia tem que dar EXATAMENTE os mesmos arquivos que rebaixar tudo de uma
vez. Se as duas rotas divergirem, o backtest dependeria de quando a base foi
montada.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import validar_precos
from simulacao import arquivo, base, config as C, demo, series as S, universo

HOJE = date(2026, 10, 30)


# ---------------------------------------------------------------------------
# series
# ---------------------------------------------------------------------------
CAL = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09",
       "2026-01-12", "2026-01-13"]


def _s(d: dict) -> pd.Series:
    return pd.Series(list(d.values()), index=pd.to_datetime(list(d.keys())))


def test_retorno_basico_e_i0():
    i0, r = S.retornos_no_calendario(_s({"2026-01-05": 10, "2026-01-06": 11,
                                         "2026-01-07": 9.9}), CAL)
    assert i0 == 1
    np.testing.assert_allclose(r, [0.1, -0.1])


def test_pregao_sem_negocio_vira_zero_e_o_movimento_cai_no_seguinte():
    i0, r = S.retornos_no_calendario(_s({"2026-01-05": 10, "2026-01-08": 12}), CAL)
    assert i0 == 1
    np.testing.assert_allclose(r, [0, 0, 0.2])
    # o total composto é o mesmo de ponta a ponta
    assert np.prod(1 + r) == pytest.approx(1.2)


def test_data_fora_do_calendario_vai_para_o_pregao_seguinte():
    # 10/01 é sábado: um negócio registrado ali conta para 12/01
    i0, r = S.retornos_no_calendario(_s({"2026-01-09": 10, "2026-01-10": 11}), CAL)
    assert CAL[i0] == "2026-01-12"
    np.testing.assert_allclose(r, [0.1])


def test_papel_deslistado_termina_e_nao_e_carregado_para_frente():
    i0, r = S.retornos_no_calendario(_s({"2026-01-05": 10, "2026-01-06": 10.5,
                                         "2026-01-07": 10.2}), CAL)
    assert i0 + len(r) - 1 == 2          # termina em 07/01, não em 13/01


def test_um_preco_so_nao_e_serie():
    assert S.retornos_no_calendario(_s({"2026-01-05": 10}), CAL) is None
    assert S.retornos_no_calendario(pd.Series(dtype=float), CAL) is None


def test_preco_zero_ou_negativo_e_descartado():
    i0, r = S.retornos_no_calendario(_s({"2026-01-05": 10, "2026-01-06": 0,
                                         "2026-01-07": 11}), CAL)
    np.testing.assert_allclose(r, [0, 0.1])


def test_escala_do_cdi_guarda_o_numero_exato():
    # 0,055131% ao dia: com a escala das ações o erro é pequeno, mas sempre
    # na mesma direção; com a do CDI, nenhum
    f = 0.055131 / 100
    assert S.compactar([f], C.ESCALA_CDI) == [55131]
    anual_exato = (1 + f) ** 252 - 1
    anual_acao = (1 + S.compactar([f], C.ESCALA)[0] / C.ESCALA) ** 252 - 1
    anual_cdi = (1 + S.compactar([f], C.ESCALA_CDI)[0] / C.ESCALA_CDI) ** 252 - 1
    assert anual_exato - anual_acao > 5e-5
    assert anual_cdi == pytest.approx(anual_exato, abs=1e-12)


def test_emendar_sobreposicao_o_novo_vence():
    i0, r, div = S.emendar(1, [10, 20, 30], 3, [31, 40])
    assert (i0, r) == (1, [10, 20, 31, 40])
    assert div == 1


def test_emendar_com_buraco_recusa():
    assert S.emendar(1, [10, 20], 4, [40]) is None


def test_emendar_preserva_a_cauda_se_o_novo_termina_antes():
    i0, r, _ = S.emendar(1, [10, 20, 30, 40], 2, [21])
    assert r == [10, 21, 30, 40]


def test_emendar_contiguo_sem_sobreposicao():
    assert S.emendar(1, [10, 20], 3, [30])[:2] == (1, [10, 20, 30])


def test_liquidez_conta_dia_sem_negocio_como_zero():
    idx = pd.bdate_range("2026-01-01", periods=63)
    fech = pd.Series(10.0, index=idx)
    vol = pd.Series([300_000.0 if i % 3 == 0 else 0.0 for i in range(63)], index=idx)
    liq = S.liquidez(fech, vol)
    assert liq["atual"] == pytest.approx(1_000_000, rel=0.02)
    assert liq["neg"] == pytest.approx(1 / 3, abs=0.02)


def test_liquidez_maxima_e_a_maior_media_movel():
    idx = pd.bdate_range("2015-01-01", periods=300)
    fech = pd.Series(10.0, index=idx)
    vol = pd.Series(np.r_[np.full(100, 500_000.0), np.full(200, 1_000.0)], index=idx)
    liq = S.liquidez(fech, vol)
    assert liq["max"] == pytest.approx(5_000_000)
    assert liq["atual"] == pytest.approx(10_000)


def test_cdi_de_dia_sem_pregao_cai_no_pregao_seguinte():
    # 09/01 (sexta) tem CDI mas não está no calendário da B3 deste teste
    cal = ["2026-01-07", "2026-01-08", "2026-01-12"]
    cdi = {date(2026, 1, 8): 0.05, date(2026, 1, 9): 0.05, date(2026, 1, 12): 0.05}
    i0, r = S.cdi_no_calendario(cdi, cal)
    assert i0 == 1
    np.testing.assert_allclose(r, [0.0005, 1.0005 ** 2 - 1])


def test_calendario_so_cresce_no_fim():
    velho = ["2026-01-05", "2026-01-07"]
    novo = S.estender_calendario(velho, ["2026-01-06", "2026-01-07", "2026-01-08"])
    assert novo == ["2026-01-05", "2026-01-07", "2026-01-08"]


def test_realinhar_preserva_o_retorno_composto():
    velho = CAL
    novo = [d for d in CAL if d != "2026-01-08"]
    r = [10_000, 20_000, -5_000, 30_000, 1_000, 2_000]
    i0, r2 = base.realinhar(1, r, C.ESCALA, velho, novo)
    tot = np.prod(1 + np.array(r) / C.ESCALA)
    assert np.prod(1 + np.array(r2) / C.ESCALA) == pytest.approx(tot, rel=1e-5)
    assert len(r2) == len(r) - 1


def test_saltos_marcados():
    s = S.saltos(1, [0, 500_000, -800_000], CAL)
    assert s == [["2026-01-07", 0.5], ["2026-01-08", -0.8]]


# ---------------------------------------------------------------------------
# universo
# ---------------------------------------------------------------------------
def test_candidatos_juntam_fontes_irmaos_fii_etf_e_extras(tmp_path):
    pub = tmp_path / "public"
    pub.mkdir()
    (pub / "dados.json").write_text(json.dumps({
        "empresas": [{"ticker": "PETR4", "nome": "PETROBRAS"}],
        "excluidas": [{"ticker": "ITUB4", "nome": "ITAU"}]}), encoding="utf-8")
    (pub / "ibov_carteira.json").write_text(json.dumps({
        "papeis": [{"ticker": "VALE3", "nome": "VALE"}]}), encoding="utf-8")
    (pub / "fiis.json").write_text(json.dumps({
        "fundos": [{"ticker": "HGLG11", "nome": "CSHG LOG"}]}), encoding="utf-8")
    extras = tmp_path / "extras.txt"
    extras.write_text("# comentario\nAAPL34 bdr Apple BDR\nXYZ\nROXO34 bdr\n",
                      encoding="utf-8")
    c = universo.candidatos(pub, extras)
    assert c["PETR4"]["classe"] == "acao"
    assert "PETR3" in c and "PETR11" in c and "ITUB3" in c and "VALE4" in c
    assert c["HGLG11"]["classe"] == "fii"
    assert c["BOVA11"]["classe"] == "etf"
    assert c["AAPL34"] == {"nome": "Apple BDR", "classe": "bdr"}
    assert "XYZ" not in c
    assert "HGLG3" not in c                       # FII não gera irmão de classe


def test_padrao_de_ticker_aceita_b3sa_e_recusa_lixo():
    assert universo.valido("B3SA3")
    assert universo.valido("TAEE11")
    assert not universo.valido("PETR")
    assert not universo.valido("PETR4F")
    assert not universo.valido("^BVSP")


# ---------------------------------------------------------------------------
# base.atualizar — ponta a ponta com fontes falsas
# ---------------------------------------------------------------------------
class Contador:
    """Embrulha as fontes e anota o que foi pedido a cada uma."""

    def __init__(self, fontes):
        self.f = fontes
        self.pedidos = []

    def precos(self, tickers, inicio, fim):
        self.pedidos.append((tuple(tickers), inicio, fim))
        return self.f.precos(tickers, inicio, fim)

    def ibov(self, inicio, fim):
        return self.f.ibov(inicio, fim)

    def cdi(self, inicio, fim):
        return self.f.cdi(inicio, fim)


def _arquivos(pasta: Path) -> dict:
    return {p.name: json.loads(p.read_text(encoding="utf-8"))
            for p in sorted(pasta.glob("*.json")) if p.name != "indice.json"}


def test_incremental_igual_ao_completo(tmp_path):
    fontes = demo.fontes_falsas(HOJE)
    cands = demo.candidatos_demo()
    a, b = tmp_path / "a", tmp_path / "b"
    meio = HOJE - timedelta(days=45)

    base.atualizar(a, completo=True, hoje=meio, fontes=fontes, candidatos=cands)
    for d in (meio + timedelta(days=13), meio + timedelta(days=30), HOJE):
        rel = base.atualizar(a, hoje=d, fontes=fontes, candidatos=cands)
        assert rel.modo == "incremental"
    base.atualizar(b, completo=True, hoje=HOJE, fontes=fontes, candidatos=cands)

    fa, fb = _arquivos(a), _arquivos(b)
    assert fa.keys() == fb.keys()
    for nome in fa:
        assert fa[nome]["i0"] == fb[nome]["i0"], nome
        assert fa[nome]["r"] == fb[nome]["r"], nome
    ia, ib = arquivo.ler_indice(a), arquivo.ler_indice(b)
    assert ia["pregoes"] == ib["pregoes"]
    assert [x["t"] for x in ia["ativos"]] == [x["t"] for x in ib["ativos"]]
    for xa, xb in zip(ia["ativos"], ib["ativos"]):
        assert xa["liqMax"] == pytest.approx(xb["liqMax"], rel=1e-9), xa["t"]


def test_incremental_baixa_so_a_janela(tmp_path):
    fontes = Contador(demo.fontes_falsas(HOJE))
    cands = demo.candidatos_demo()
    base.atualizar(tmp_path, completo=True, hoje=HOJE - timedelta(days=7),
                   fontes=fontes, candidatos=cands)
    fontes.pedidos.clear()
    base.atualizar(tmp_path, hoje=HOJE, fontes=fontes, candidatos=cands)
    assert len(fontes.pedidos) == 1                     # o recusado não é repedido
    tickers, inicio, _ = fontes.pedidos[0]
    assert "MTSA4" not in tickers
    assert (HOJE - inicio).days < C.JANELA_INCREMENTAL_DIAS + 15


def test_recusado_volta_a_ser_testado_depois_do_prazo(tmp_path):
    fontes = Contador(demo.fontes_falsas(HOJE))
    cands = demo.candidatos_demo()
    ontem = HOJE - timedelta(days=C.REAVALIAR_RECUSADOS_DIAS + 1)
    base.atualizar(tmp_path, completo=True, hoje=ontem, fontes=fontes, candidatos=cands)
    fontes.pedidos.clear()
    base.atualizar(tmp_path, hoje=HOJE, fontes=fontes, candidatos=cands)
    assert any(p[0] == ("MTSA4",) for p in fontes.pedidos)


def test_papel_que_sumiu_do_yahoo_fica_na_base(tmp_path):
    f = demo.fontes_falsas(HOJE)
    cands = demo.candidatos_demo()
    base.atualizar(tmp_path, completo=True, hoje=HOJE - timedelta(days=7),
                   fontes=f, candidatos=cands)
    antes = arquivo.ler_serie(tmp_path, "PETR3")

    def sem_petr3(tickers, inicio, fim):
        return f.precos([t for t in tickers if t != "PETR3"], inicio, fim)

    rel = base.atualizar(tmp_path, hoje=HOJE, fontes=SimpleNamespace(
        precos=sem_petr3, ibov=f.ibov, cdi=f.cdi), candidatos={})
    assert "PETR3" in rel.nao_atualizados
    ind = arquivo.ler_indice(tmp_path)
    assert "PETR3" in [a["t"] for a in ind["ativos"]]
    assert arquivo.ler_serie(tmp_path, "PETR3")["r"] == antes["r"]
    # e saiu da lista de candidatos de hoje sem sair da base
    assert len(ind["ativos"]) == 30


def test_buraco_maior_que_a_janela_reconstroi_o_papel(tmp_path):
    f = demo.fontes_falsas(HOJE)
    cands = demo.candidatos_demo()
    base.atualizar(tmp_path, completo=True, hoje=HOJE - timedelta(days=7),
                   fontes=f, candidatos=cands)
    # corta os últimos 120 pregões gravados do WEGE3: a janela de 100 dias
    # corridos não alcança, e a emenda teria buraco
    s = arquivo.ler_serie(tmp_path, "WEGE3")
    s["r"] = s["r"][:-120]
    arquivo.gravar_se_mudou(arquivo.caminho_serie(tmp_path, "WEGE3"), s)
    rel = base.atualizar(tmp_path, hoje=HOJE, fontes=f, candidatos=cands)
    assert "WEGE3" in rel.reconstruidos
    b = tmp_path / "ref"
    base.atualizar(b, completo=True, hoje=HOJE, fontes=f, candidatos=cands)
    assert arquivo.ler_serie(tmp_path, "WEGE3")["r"] == arquivo.ler_serie(b, "WEGE3")["r"]


def test_cdi_fora_do_ar_mantem_o_gravado_e_avisa(tmp_path):
    f = demo.fontes_falsas(HOJE)
    cands = demo.candidatos_demo()
    base.atualizar(tmp_path, completo=True, hoje=HOJE - timedelta(days=7),
                   fontes=f, candidatos=cands)

    def cdi_fora(*_):
        raise ConnectionError("api.bcb.gov.br recusou")

    rel = base.atualizar(tmp_path, hoje=HOJE, candidatos=cands,
                         fontes=SimpleNamespace(precos=f.precos, ibov=f.ibov, cdi=cdi_fora))
    assert any("CDI" in a for a in rel.avisos)
    ind = arquivo.ler_indice(tmp_path)
    assert ind["bench"]["CDI"]["i0"] + ind["bench"]["CDI"]["n"] < len(ind["pregoes"])


def test_base_demo_e_refeita_do_zero_com_dado_real(tmp_path):
    import atualizar_precos
    atualizar_precos.main(["--demo", "--pasta", str(tmp_path), "--hoje", "2026-10-30"])
    assert arquivo.ler_indice(tmp_path)["demo"] is True
    rel = base.atualizar(tmp_path, hoje=HOJE, fontes=demo.fontes_falsas(HOJE),
                         candidatos=demo.candidatos_demo())
    assert rel.modo == "completo"
    assert arquivo.ler_indice(tmp_path)["demo"] is False


def test_cdi_da_demo_bate_com_a_selic():
    """A série guardada reproduz o CDI de entrada: 13,65% a.a. no fim."""
    f = demo.fontes_falsas(HOJE)
    cdi = f.cdi(date(2026, 1, 1), HOJE)
    cal = S.calendario_de(f.ibov(date(2026, 1, 1), HOJE))
    i0, r = S.cdi_no_calendario(cdi, cal)
    rr = np.array(S.compactar(r, C.ESCALA_CDI)) / C.ESCALA_CDI
    taxa = (1 + rr[-1]) ** 252 - 1
    assert taxa == pytest.approx(0.1365, abs=0.0005)


# ---------------------------------------------------------------------------
# validador
# ---------------------------------------------------------------------------
@pytest.fixture
def base_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "MINIMO_ATIVOS", 10)
    base.atualizar(tmp_path, completo=True, hoje=HOJE, fontes=demo.fontes_falsas(HOJE),
                   candidatos=demo.candidatos_demo())
    return tmp_path


def test_validador_aceita_base_boa(base_ok):
    erros, avisos = validar_precos.conferir(base_ok, hoje=HOJE)
    assert erros == []
    assert any("AMER3" in a for a in avisos)          # salto de −77% é avisado


def test_validador_recusa_demo(base_ok):
    ind = arquivo.ler_indice(base_ok)
    ind["demo"] = True
    arquivo.gravar_indice(base_ok, ind)
    erros, _ = validar_precos.conferir(base_ok, hoje=HOJE)
    assert any("DEMONSTRAÇÃO" in e for e in erros)


def test_validador_recusa_base_velha(base_ok):
    erros, _ = validar_precos.conferir(base_ok, hoje=HOJE + timedelta(days=12))
    assert any("dias atrás" in e for e in erros)


def test_validador_recusa_indice_que_nao_bate_com_o_arquivo(base_ok):
    ind = arquivo.ler_indice(base_ok)
    ind["ativos"][0]["n"] += 1
    arquivo.gravar_indice(base_ok, ind)
    erros, _ = validar_precos.conferir(base_ok, hoje=HOJE)
    assert any("índice diz" in e for e in erros)


def test_validador_recusa_cdi_absurdo(base_ok):
    s = arquivo.ler_serie(base_ok, C.ARQ_CDI)
    s["r"] = [v * 10 for v in s["r"]]
    arquivo.gravar_se_mudou(arquivo.caminho_serie(base_ok, C.ARQ_CDI), s)
    erros, _ = validar_precos.conferir(base_ok, hoje=HOJE)
    assert any("CDI" in e for e in erros)


# ---------------------------------------------------------------------------
# coleta — o formato que o magicb3.prices devolve
# ---------------------------------------------------------------------------
def test_coleta_tira_o_sufixo_e_o_fuso(monkeypatch):
    from magicb3 import prices
    from simulacao import coleta

    idx = pd.DatetimeIndex(["2026-01-05", "2026-01-06"]).tz_localize("America/Sao_Paulo")
    pedidos = []

    def falso(simbolos, inicio, fim):
        pedidos.append((list(simbolos), inicio, fim))
        df = pd.DataFrame({s: [10.0, 11.0] for s in simbolos}, index=idx)
        return {"preco": df, "fechamento": df, "volume": df * 1000}

    monkeypatch.setattr(prices, "baixar_historico", falso)
    d = coleta.baixar_precos(["PETR4", "VALE3"], date(2026, 1, 1), date(2026, 1, 6))
    assert list(d["preco"].columns) == ["PETR4", "VALE3"]
    assert d["preco"].index.tz is None
    assert pedidos[0][0] == ["PETR4.SA", "VALE3.SA"]
    assert pedidos[0][2] == date(2026, 1, 7)          # o fim do yfinance é exclusivo
    ib = coleta.baixar_ibov(date(2026, 1, 1), date(2026, 1, 6))
    assert S.calendario_de(ib) == ["2026-01-05", "2026-01-06"]


# ---------------------------------------------------------------------------
# Último pregão que o Yahoo ainda não fechou para as ações
# ---------------------------------------------------------------------------
def test_pregao_novo_sem_preco_da_maioria_sai_do_fim():
    idx = pd.to_datetime(CAL)
    px = pd.DataFrame({t: np.linspace(10, 11, len(CAL)) for t in "ABCDEFGHIJ"}, index=idx)
    px.iloc[-1, 1:] = np.nan                           # 13/01: só A tem preço
    cal, adiados = S.sem_pregoes_incompletos(CAL, px, 0.8)
    assert cal == CAL[:-1]
    assert adiados == [("2026-01-13", pytest.approx(0.1))]


def test_pregao_com_quase_todos_fica_e_deslistado_nao_conta():
    idx = pd.to_datetime(CAL)
    px = pd.DataFrame({t: np.linspace(10, 11, len(CAL)) for t in "ABCDEFGHIJ"}, index=idx)
    px.iloc[-1, 0] = np.nan                            # 9 de 10: passa
    px["MORTO"] = np.nan                               # sem preço há meses: fora da conta
    px.loc[idx[0], "MORTO"] = 5.0
    cal, adiados = S.sem_pregoes_incompletos(CAL, px, 0.8, janela_dias=3)
    assert cal == CAL and adiados == []


def test_pregao_ja_gravado_nunca_sai():
    idx = pd.to_datetime(CAL)
    px = pd.DataFrame({t: np.linspace(10, 11, len(CAL)) for t in "ABCDE"}, index=idx)
    px.iloc[-2:, :] = np.nan
    cal, _ = S.sem_pregoes_incompletos(CAL, px, 0.8, protegido=CAL[-1])
    assert cal == CAL
    cal, adiados = S.sem_pregoes_incompletos(CAL, px, 0.8, protegido=CAL[-3])
    assert cal == CAL[:-2] and [d for d, _ in adiados] == CAL[-2:][::-1]


def _yahoo_de_madrugada(f, dia):
    """Como o Yahoo responde entre a meia-noite de Nova York e a abertura:
    o Ibovespa traz o dia; as ações trazem só o volume, preço vazio."""
    def precos(tickers, inicio, fim):
        d = f.precos(tickers, inicio, fim)
        out = {}
        for k, df in d.items():
            df = df.copy()
            if k != "volume" and not df.empty and pd.Timestamp(dia) in df.index:
                cols = list(df.columns)[: max(1, len(df.columns) * 9 // 10)]
                df.loc[pd.Timestamp(dia), cols] = np.nan
            out[k] = df
        return out
    return SimpleNamespace(precos=precos, ibov=f.ibov, cdi=f.cdi)


def test_rodada_de_madrugada_adia_o_dia_e_a_seguinte_completa(tmp_path):
    """O caso de 04 e 05/11/2026: sem o corte, o calendário ganhava o dia do
    Ibovespa, 90% dos papéis paravam um dia antes e o validador barrava a
    publicação inteira. Com o corte, a base fica no pregão anterior, passa no
    validador, e o dia entra completo na rodada seguinte."""
    f = demo.fontes_falsas(HOJE)
    cands = demo.candidatos_demo()
    ontem = HOJE - timedelta(days=1)                   # 29/10/2026, quinta
    base.atualizar(tmp_path, completo=True, hoje=ontem - timedelta(days=1),
                   fontes=f, candidatos=cands)
    ind0 = arquivo.ler_indice(tmp_path)

    rel = base.atualizar(tmp_path, hoje=ontem, fontes=_yahoo_de_madrugada(f, ontem),
                         candidatos=cands)
    assert [d for d, _ in rel.adiados] == [ontem.isoformat()]
    assert any("adiado" in a for a in rel.avisos)
    ind1 = arquivo.ler_indice(tmp_path)
    assert ind1["pregoes"] == ind0["pregoes"]          # o dia não entrou
    erros, _ = validar_precos.conferir(tmp_path, hoje=ontem)
    # a base de demonstração tem 30 papéis, abaixo do mínimo de produção; o
    # que importa aqui é o erro que travou o robô
    assert not [e for e in erros if "último pregão" in e or "Ibovespa" in e]

    rel = base.atualizar(tmp_path, hoje=ontem, fontes=f, candidatos=cands)
    assert rel.adiados == []
    ind2 = arquivo.ler_indice(tmp_path)
    assert ind2["pregoes"][-1] == ontem.isoformat()
    ref = tmp_path / "ref"
    base.atualizar(ref, completo=True, hoje=ontem, fontes=f, candidatos=cands)
    assert _arquivos(tmp_path) == _arquivos(ref)
