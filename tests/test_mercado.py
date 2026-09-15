# -*- coding: utf-8 -*-
"""Testes da aba de indicadores de mercado. Nenhum acessa a rede.

As amostras abaixo são recortes reais: as taxas de 14/09/2026 do Tesouro
Transparente e do Treasury, conferidas na fonte no dia em que a aba foi
escrita. Servem para travar o formato — o vocabulário da coluna "Tipo Titulo"
já mudou uma vez na CVM e vai mudar de novo aqui.
"""
from __future__ import annotations

from datetime import date

import pytest

from mercado import arquivo, curvas, ibov, pvp, tesouro, treasury

CSV_TESOURO = """Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU Compra Manha;PU Venda Manha;PU Base Manha
Tesouro Prefixado;01/01/2027;14/09/2026;13,59;13,71;878,20;877,40;877,80
Tesouro Prefixado;01/01/2029;14/09/2026;13,97;14,09;683,10;682,30;682,70
Tesouro Prefixado;01/01/2032;14/09/2026;14,33;14,45;471,20;470,40;470,80
Tesouro Prefixado com Juros Semestrais;01/01/2032;14/09/2026;14,25;14,37;980,10;979,30;979,70
Tesouro Prefixado com Juros Semestrais;01/01/2037;14/09/2026;14,38;14,50;962,40;961,60;962,00
Tesouro IPCA+;15/05/2029;14/09/2026;7,55;7,67;3512,10;3511,30;3511,70
Tesouro IPCA+;15/08/2040;14/09/2026;7,34;7,46;1611,20;1610,40;1610,80
Tesouro IPCA+ com Juros Semestrais;15/05/2045;14/09/2026;7,39;7,51;3902,10;3901,30;3901,70
Tesouro Selic;01/03/2031;14/09/2026;0,07;0,19;16011,20;16010,40;16010,80
Tesouro Educa+;15/12/2040;14/09/2026;7,42;7,54;1250,10;1249,30;1249,70
Tesouro Prefixado;01/01/2027;04/09/2026;13,44;13,56;875,20;874,40;874,80
Tesouro Prefixado;01/01/2032;04/09/2026;14,10;14,22;469,20;468,40;468,80
Tesouro IPCA+;15/05/2029;04/09/2026;7,48;7,60;3502,10;3501,30;3501,70
Tesouro Prefixado;01/01/2027;13/03/2026;13,10;13,22;820,20;819,40;819,80
Tesouro Prefixado;01/01/2032;13/03/2026;13,87;13,99;455,20;454,40;454,80
Tesouro IPCA+;15/05/2029;13/03/2026;7,10;7,22;3400,10;3399,30;3399,70
"""

CSV_TREASURY = """Date,"1 Mo","2 Mo","3 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"
09/14/2026,3.94,4.06,4.11,4.18,4.37,4.65,4.73,4.80,4.88,4.97,5.37,5.34
09/04/2026,3.90,4.02,4.08,4.14,4.30,4.58,4.66,4.74,4.82,4.91,5.30,5.28
03/13/2026,3.70,3.68,3.66,3.60,3.50,3.52,3.60,3.78,3.98,4.22,4.83,4.88
"""

CSV_TIPS = """Date,"5 YR","7 YR","10 YR","20 YR","30 YR"
09/14/2026,2.40,2.49,2.60,2.89,3.05
09/04/2026,2.34,2.43,2.54,2.83,2.99
03/13/2026,1.52,1.74,1.98,2.42,2.66
"""


@pytest.fixture
def td():
    return tesouro.ler_csv(CSV_TESOURO)


@pytest.fixture
def us():
    return treasury.ler_csv(CSV_TREASURY)


@pytest.fixture
def tips():
    return treasury.ler_csv(CSV_TIPS)


# ---------------------------------------------------------------------------
# Tesouro
# ---------------------------------------------------------------------------
def test_ignora_titulos_que_nao_formam_curva(td):
    """Selic é pós-fixado e Educa+ tem outro fluxo: nenhum dos dois entra."""
    assert set(td["FAMILIA"]) == {"pre", "ipca"}
    assert len(td) == 14        # 16 linhas na amostra, menos a Selic e a Educa+


def test_taxa_e_a_media_entre_compra_e_venda(td):
    linha = td[(td["FAMILIA"] == "pre")
               & (td["DATA"] == "2026-09-14")
               & (td["VENCIMENTO"] == "2027-01-01")]
    assert linha["TAXA"].iloc[0] == pytest.approx((13.59 + 13.71) / 2)


def test_zero_cupom_vence_o_titulo_com_cupom_no_mesmo_vencimento(td):
    """01/01/2032 existe como LTN e como NTN-F. Fica a LTN, e uma só."""
    c = tesouro.curva(td, "pre", date(2026, 9, 14))
    de_2032 = [v for v in c if v.vencimento == date(2032, 1, 1)]
    assert len(de_2032) == 1
    assert de_2032[0].cupom is False
    assert de_2032[0].taxa == pytest.approx((14.33 + 14.45) / 2)


def test_titulo_com_cupom_entra_onde_nao_ha_zero_cupom(td):
    c = tesouro.curva(td, "pre", date(2026, 9, 14))
    de_2037 = [v for v in c if v.vencimento == date(2037, 1, 1)]
    assert len(de_2037) == 1 and de_2037[0].cupom is True


def test_curva_sai_ordenada_por_prazo(td):
    c = tesouro.curva(td, "ipca", date(2026, 9, 14))
    assert [v.prazo for v in c] == sorted(v.prazo for v in c)


def test_foto_antiga_nunca_olha_para_a_frente(td):
    """Se não há pregão no alvo, vale o anterior — nunca o seguinte."""
    datas = tesouro.datas_disponiveis(td)
    assert tesouro.data_mais_proxima(datas, date(2026, 9, 10)) == date(2026, 9, 4)
    assert tesouro.data_mais_proxima(datas, date(2026, 1, 1)) is None


def test_as_quatro_fotos(td):
    f = tesouro.fotos(td, date(2026, 9, 14))
    assert f["hoje"] == date(2026, 9, 14)
    assert f["semana"] == date(2026, 9, 4)       # alvo 07/09, feriado
    assert f["semestre"] == date(2026, 3, 13)


def test_vocabulario_mudado_da_erro_claro():
    ruim = CSV_TESOURO.replace("Tesouro Prefixado", "Tesouro Pre-Fixado") \
                      .replace("Tesouro IPCA+", "Tesouro IPCA")
    with pytest.raises(ValueError, match="Tipo Titulo"):
        tesouro.ler_csv(ruim)


# ---------------------------------------------------------------------------
# Treasury
# ---------------------------------------------------------------------------
def test_converte_de_semestral_para_efetiva_ao_ano():
    assert treasury.para_efetiva_ao_ano(4.97) == pytest.approx(5.0318, abs=1e-4)
    assert treasury.para_efetiva_ao_ano(0.0) == 0.0


def test_prazos_das_colunas():
    assert treasury.prazo_da_coluna('"10 Yr"') == 1000 / 100
    assert treasury.prazo_da_coluna("3 Mo") == pytest.approx(0.25)
    assert treasury.prazo_da_coluna("1.5 Month") == pytest.approx(0.125)
    assert treasury.prazo_da_coluna("Date") is None


def test_curva_americana_usa_o_ultimo_pregao_ate_a_data(us):
    """07/09 fecha o Brasil e não os EUA; 12/09 não está na amostra."""
    assert treasury.data_efetiva(us, date(2026, 9, 10)) == date(2026, 9, 4)
    c = treasury.curva(us, date(2026, 9, 14))
    assert c[-1][0] == 30.0
    assert c[-1][1] == pytest.approx(treasury.para_efetiva_ao_ano(5.34))


# ---------------------------------------------------------------------------
# Interpolação
# ---------------------------------------------------------------------------
def test_interpola_entre_vertices():
    p = [(2.0, 10.0), (4.0, 14.0)]
    assert curvas.interpolar(p, 3.0) == pytest.approx(12.0)
    assert curvas.interpolar(p, 2.0) == pytest.approx(10.0)


def test_nunca_extrapola():
    """O ponto inteiro: fora do observado é None, não a última taxa repetida."""
    p = [(2.0, 10.0), (4.0, 14.0)]
    assert curvas.interpolar(p, 1.5) is None
    assert curvas.interpolar(p, 20.0) is None


def test_curva_prefixada_termina_onde_os_dados_terminam(td):
    c = tesouro.curva(td, "pre", date(2026, 9, 14))
    g = curvas.na_grade([(v.prazo, v.taxa) for v in c])
    assert curvas.em(g, 10.0) is not None
    assert curvas.em(g, 20.0) is None, \
        "não existe prefixado brasileiro de 20 anos; a curva não pode ser esticada"


def test_spread_falta_de_um_lado_e_falta_do_spread():
    assert curvas.diferenca([10.0, None, 12.0], [4.0, 4.0, None]) == [6.0, None, None]


def test_grade_cobre_de_1_a_20():
    assert curvas.GRADE[0] == 1 and curvas.GRADE[-1] == 20
    assert 10.0 in curvas.GRADE and 2.0 in curvas.GRADE


# ---------------------------------------------------------------------------
# Montagem do arquivo
# ---------------------------------------------------------------------------
def test_montar_juros_produz_as_quatro_fotos(td, us, tips):
    j = arquivo.montar_juros(td, us, tips, date(2026, 9, 14))
    assert set(j["series"]) == {"hoje", "semana", "mes", "semestre"}
    s = j["series"]["hoje"]
    assert s["dataBR"] == "2026-09-14"
    assert len(s["pre"]["grade"]) == len(curvas.GRADE)
    # O spread real só começa onde há TIPS e NTN-B — 5 anos.
    assert curvas.em(s["spreadReal"], 1.0) is None
    assert curvas.em(s["spreadReal"], 10.0) is not None


def test_spread_nominal_bate_com_a_conta_na_mao(td, us, tips):
    j = arquivo.montar_juros(td, us, tips, date(2026, 9, 14))
    s = j["series"]["hoje"]
    br = curvas.em(s["pre"]["grade"], 5.0)
    eua = curvas.em(s["eua"]["grade"], 5.0)
    # Os três lados são gravados arredondados a 3 casas, então a conta refeita
    # a partir do arquivo pode divergir até meio milésimo de cada parcela.
    assert curvas.em(s["spreadNominal"], 5.0) == pytest.approx(br - eua, abs=2e-3)


# ---------------------------------------------------------------------------
# Ibovespa e P/VP
# ---------------------------------------------------------------------------
RESPOSTA_B3 = {
    "header": {"date": "15/09/26", "theoricalQty": "93.803.750.400"},
    "results": [
        {"cod": "PETR4", "asset": "PETROBRAS", "type": "PN  N2",
         "part": "4,120", "theoricalQty": "5.000.000.000"},
        {"cod": "PETR3", "asset": "PETROBRAS", "type": "ON  N2",
         "part": "1,880", "theoricalQty": "2.000.000.000"},
        {"cod": "VALE3", "asset": "VALE", "type": "ON  NM",
         "part": "9,000", "theoricalQty": "4.000.000.000"},
        {"cod": "XPTO3", "asset": "SEM DADO", "type": "ON",
         "part": "0,500", "theoricalQty": "1.000.000.000"},
    ],
}

FUNDAMENTOS = [
    {"cvm": 9512, "nome": "PETROLEO BRASILEIRO S.A.", "pl": 400e9, "acoes": 13e9,
     "dtBalanco": "2026-06-30"},
    {"cvm": 4170, "nome": "VALE S.A.", "pl": 200e9, "acoes": 4.5e9,
     "dtBalanco": "2026-06-30"},
]
MAPA = {"PETR": 9512, "VALE": 4170, "XPTO": 99999}


def test_le_a_carteira_da_b3():
    c = ibov.ler_resposta(RESPOSTA_B3)
    assert c["data"] == "2026-09-15"
    assert c["papeis"][0]["qtd"] == 5_000_000_000
    assert c["papeis"][0]["part"] == pytest.approx(4.12)


def test_duas_classes_da_mesma_empresa_nao_contam_o_patrimonio_duas_vezes():
    """PETR3 e PETR4 usam o mesmo VPA, cada uma com a sua quantidade."""
    papeis = ibov.ler_resposta(RESPOSTA_B3)["papeis"]
    vpas = pvp.vpa_por_prefixo(FUNDAMENTOS, MAPA)
    precos = {"PETR4": 40.0, "PETR3": 44.0, "VALE3": 60.0, "XPTO3": 10.0}
    r = pvp.calcular(papeis, precos, vpas)

    vpa_petr = 400e9 / 13e9
    vpa_vale = 200e9 / 4.5e9
    mercado = 5e9 * 40 + 2e9 * 44 + 4e9 * 60
    patrimonio = (5e9 + 2e9) * vpa_petr + 4e9 * vpa_vale
    assert r.pvp == pytest.approx(mercado / patrimonio)


def test_papel_sem_patrimonio_fica_de_fora_e_aparece_na_cobertura():
    papeis = ibov.ler_resposta(RESPOSTA_B3)["papeis"]
    vpas = pvp.vpa_por_prefixo(FUNDAMENTOS, MAPA)
    r = pvp.calcular(papeis, {"PETR4": 40.0, "PETR3": 44.0,
                              "VALE3": 60.0, "XPTO3": 10.0}, vpas)
    assert r.faltando == ["XPTO3"]
    assert r.n_com_dado == 3 and r.n_total == 4
    assert r.cobertura == pytest.approx((4.12 + 1.88 + 9.0) / 15.5)


def test_pvp_do_indice_e_media_harmonica_nao_aritmetica():
    """Uma empresa pequena e caríssima não pode dominar o índice."""
    papeis = [{"ticker": "AAAA3", "tipo": "ON", "part": 99.0, "qtd": 1e9},
              {"ticker": "BBBB3", "tipo": "ON", "part": 1.0, "qtd": 1e6}]
    vpas = {"AAAA": {"vpa": 10.0, "nome": "grande", "fonteAcoes": "cvm"},
            "BBBB": {"vpa": 2.0, "nome": "pequena", "fonteAcoes": "cvm"}}
    r = pvp.calcular(papeis, {"AAAA3": 10.0, "BBBB3": 100.0}, vpas)
    # A pequena tem P/VP 50; a média aritmética simples daria 25,5.
    assert r.pvp == pytest.approx((1e9 * 10 + 1e6 * 100) / (1e9 * 10 + 1e6 * 2.0),
                                  rel=1e-9)
    assert r.pvp < 1.02


def test_carteira_curta_demais_nao_passa(monkeypatch):
    class R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"header": {"date": "15/09/26"}, "results": []}

    class S:
        def get(self, *a, **k): return R()

    with pytest.raises(RuntimeError, match="P/VP de índice incompleto"):
        ibov.baixar(S())


def test_acoes_invalidas_nao_viram_vpa():
    ruins = [{"cvm": 1, "pl": 100.0, "acoes": 0},
             {"cvm": 2, "pl": 100.0, "acoes": None},
             {"cvm": 3, "pl": None, "acoes": 10.0}]
    assert pvp.vpa_por_prefixo(ruins, {"AAAA": 1, "BBBB": 2, "CCCC": 3}) == {}


# ---------------------------------------------------------------------------
# Histórico do P/VP
# ---------------------------------------------------------------------------
def test_historico_substitui_o_ponto_do_mesmo_dia():
    s = [["2026-09-10", 1.40], ["2026-09-14", 1.50]]
    novo = arquivo.juntar_historico(s, date(2026, 9, 14), 1.55)
    assert novo == [["2026-09-10", 1.4], ["2026-09-14", 1.55]]


def test_historico_ignora_valor_ausente():
    s = [["2026-09-10", 1.40]]
    assert arquivo.juntar_historico(s, date(2026, 9, 14), None) == s


# ---------------------------------------------------------------------------
# Patrimônio no tempo (point-in-time)
# ---------------------------------------------------------------------------
def _painel():
    import pandas as pd
    return pd.DataFrame({
        "CD_CVM": [1, 1, 1],
        "DT_REFER": pd.to_datetime(["2024-12-31", "2025-12-31", "2026-06-30"]),
        "DT_RECEB": pd.to_datetime(["2025-03-20", "2026-03-18", pd.NaT]),
        "PATRIMONIO": [100.0, 120.0, 130.0],
    })


def test_balanco_nao_entra_antes_de_ter_sido_entregue():
    """Em 02/01/2026 o balanço de 31/12/2025 ainda não existia publicamente."""
    p = _painel()
    assert pvp.patrimonio_vigente(p, 1, "2026-01-02") == 100.0
    assert pvp.patrimonio_vigente(p, 1, "2026-03-19") == 120.0


def test_sem_data_de_entrega_usa_o_prazo_regulatorio():
    """30/06/2026 sem DT_RECEB só vale a partir de 90 dias depois."""
    p = _painel()
    assert pvp.patrimonio_vigente(p, 1, "2026-08-01") == 120.0
    assert pvp.patrimonio_vigente(p, 1, "2026-10-01") == 130.0


def test_empresa_sem_historico_devolve_none():
    assert pvp.patrimonio_vigente(_painel(), 999, "2026-09-14") is None


def test_patrimonio_e_achado_pela_descricao_nao_pelo_codigo():
    """Em banco o 2.03 é 'Provisões' e o patrimônio está no 2.07.

    Ler pelo código devolveria as provisões. O painel tem que pegar o 2.07.
    """
    import pandas as pd
    bpp = pd.DataFrame({
        "CD_CVM": [1, 1, 1],
        "DT_REFER": pd.to_datetime(["2026-06-30"] * 3),
        "DT_RECEB": pd.to_datetime(["2026-08-14"] * 3),
        "CD_CONTA": ["2.03", "2.07", "2.07.01"],
        "DS_CONTA": ["Provisões", "Patrimônio Líquido Consolidado",
                     "Patrimônio Líquido Atribuído ao Controlador"],
        "VL_CONTA": [40.4e9, 190.8e9, 185.0e9],
    })
    painel = pvp.painel_patrimonio(bpp, "patrimônio líquido consolidado")
    assert len(painel) == 1
    assert painel["PATRIMONIO"].iloc[0] == 190.8e9


# ---------------------------------------------------------------------------
# Arquivo publicado
# ---------------------------------------------------------------------------
def test_modo_demonstracao_se_declara():
    import atualizar_mercado
    d = atualizar_mercado.demo()
    assert d["meta"]["demo"] is True
    assert d["juros"]["series"]["hoje"]["pre"]["grade"][-1] is None


def test_titulo_quase_vencido_nao_entra_na_curva():
    """Caso real: em 14/08/2026 a NTN-B de 15/08/2026 marcava 13,32% de juro
    REAL contra 8,04% da seguinte. Um dia de prazo transforma centavos de
    arredondamento em pontos percentuais; se entrasse, o vértice de 1 ano da
    curva real sairia perto de 12%."""
    csv = (
        "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;"
        "PU Compra Manha;PU Venda Manha;PU Base Manha\n"
        "Tesouro IPCA+;15/08/2026;14/08/2026;13,32;13,44;4739,77;4740,25;4740,25\n"
        "Tesouro IPCA+;15/05/2029;14/08/2026;8,04;8,16;3844,28;3831,93;3831,93\n"
        "Tesouro IPCA+;15/08/2040;14/08/2026;7,66;7,78;1697,78;1671,34;1671,34\n"
    )
    c = tesouro.curva(tesouro.ler_csv(csv), "ipca", date(2026, 8, 14))
    assert [v.vencimento.year for v in c] == [2029, 2040]
    g = curvas.na_grade([(v.prazo, v.taxa) for v in c])
    assert curvas.em(g, 1.0) is None       # antes do primeiro vértice: não existe
    assert curvas.em(g, 10.0) < 8.1


def test_ntnb_curta_nao_entra_por_causa_da_defasagem_do_ipca():
    """Caso real de 16/03/2026: a NTN-B de 15/08/2026, a cinco meses do
    vencimento, marcava 9,88% de juro real contra 8,21% da seguinte. A taxa
    real de uma NTN-B curta mede a defasagem do IPCA, não o juro do prazo."""
    csv = (
        "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;"
        "PU Compra Manha;PU Venda Manha;PU Base Manha\n"
        "Tesouro IPCA+;15/08/2026;16/03/2026;9,88;10,00;4455,00;4450,87;4450,87\n"
        "Tesouro IPCA+;15/05/2029;16/03/2026;8,15;8,27;3625,45;3611,40;3611,40\n"
        "Tesouro IPCA+;15/08/2040;16/03/2026;7,31;7,43;1685,47;1658,05;1658,05\n"
        "Tesouro Prefixado;01/01/2027;16/03/2026;13,91;14,03;902,26;901,04;901,04\n"
    )
    td = tesouro.ler_csv(csv)
    real = tesouro.curva(td, "ipca", date(2026, 3, 16))
    assert [v.vencimento.year for v in real] == [2029, 2040]

    # A LTN de 0,8 ano continua valendo: no prefixado não há defasagem de índice.
    nominal = tesouro.curva(td, "pre", date(2026, 3, 16))
    assert len(nominal) == 1 and nominal[0].prazo < 1.0


# ---------------------------------------------------------------------------
# Número de ações: as duas fontes e a conciliação
# ---------------------------------------------------------------------------
def test_cvm_vence_quando_as_duas_fontes_concordam():
    n, fonte = pvp.acoes_da_empresa(6_135_427_665, 7_106_000_000)
    assert n == 6_135_427_665 and fonte == "cvm"


def test_escala_mil_vezes_errada_da_cvm_e_descartada():
    """Vivara, primeira coleta real: a CVM informou 235 bilhões de ações para
    uma empresa de 235 milhões. O P/VP dela saiu 2.016."""
    n, fonte = pvp.acoes_da_empresa(235_071_814_000, 235_135_052)
    assert n == 235_135_052
    assert "divergia" in fonte


def test_sem_numero_na_cvm_vale_o_implicito():
    """Vale e Itaú vieram sem nº de ações — 19% do índice."""
    n, fonte = pvp.acoes_da_empresa(None, 4_255_762_795)
    assert n == 4_255_762_795 and fonte == "mercado"


def test_sem_nenhuma_das_duas_a_empresa_fica_de_fora():
    assert pvp.acoes_da_empresa(None, None) == (None, "sem fonte")
    assert pvp.acoes_da_empresa(0, 0)[0] is None


def test_acoes_implicitas_usam_a_mediana_entre_as_classes():
    """O Yahoo usa preços de momentos diferentes para PETR3 e PETR4."""
    from mercado import acoes
    d = {"PETR3": (699_342_585_856, 54.26), "PETR4": (668_417_720_320, 48.92),
         "VALE3": (321_224_966_144, 75.48)}
    imp = acoes.implicitas_por_prefixo(d)
    assert 12.8e9 < imp["PETR"] < 13.7e9
    assert imp["VALE"] == pytest.approx(321_224_966_144 / 75.48)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------
def _carteira_unit(tipo="UNT N2"):
    return [{"ticker": "KLBN11", "tipo": tipo, "part": 0.581, "qtd": 786_869_850}]


def test_unit_carrega_o_patrimonio_de_varias_acoes():
    """KLBN11 = 1 ON + 4 PN. Sem o fator 5 ela aparecia com P/VP 10,4."""
    vpas = {"KLBN": {"vpa": 1.8431, "fonteAcoes": "cvm", "nome": "KLABIN S.A."}}
    r = pvp.calcular(_carteira_unit(), {"KLBN11": 19.22}, vpas)
    assert r.detalhe[0]["pvp"] == pytest.approx(19.22 / (1.8431 * 5), rel=1e-6)
    assert 2.0 < r.pvp < 2.2


def test_unit_sem_fator_conhecido_fica_de_fora():
    vpas = {"XPTO": {"vpa": 10.0, "fonteAcoes": "cvm"}}
    papeis = [{"ticker": "XPTO11", "tipo": "UNT", "part": 1.0, "qtd": 1e9}]
    r = pvp.calcular(papeis, {"XPTO11": 30.0}, vpas)
    assert r.faltando == ["XPTO11"] and r.pvp is None


def test_unit_so_entra_com_o_numero_de_acoes_da_cvm():
    """Para a BPAC11 o implícito no valor de mercado dá P/VP 0,99 ou 2,96
    conforme conte units ou ações, e o número não diz qual. Fica de fora."""
    vpas = {"KLBN": {"vpa": 1.8431, "fonteAcoes": "mercado"}}
    r = pvp.calcular(_carteira_unit(), {"KLBN11": 19.22}, vpas)
    assert r.faltando == ["KLBN11"]


def test_pvp_absurdo_de_um_papel_nao_entra_na_soma():
    vpas = {"AAAA": {"vpa": 10.0, "fonteAcoes": "cvm"},
            "BBBB": {"vpa": 0.0111, "fonteAcoes": "cvm"}}   # Vivara, 235 bi de ações
    papeis = [{"ticker": "AAAA3", "tipo": "ON", "part": 90.0, "qtd": 1e9},
              {"ticker": "BBBB3", "tipo": "ON", "part": 10.0, "qtd": 1e8}]
    r = pvp.calcular(papeis, {"AAAA3": 12.0, "BBBB3": 22.40}, vpas)
    assert r.faltando == ["BBBB3"]
    assert r.pvp == pytest.approx(1.2)
