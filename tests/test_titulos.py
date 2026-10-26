# -*- coding: utf-8 -*-
"""Curvas brasileiras pela ANBIMA e o acervo de curvas. Nenhum teste acessa a rede.

`amostras/anbima_ms261023.txt` é o arquivo real de 23/10/2026, com as LFT
recortadas (não entram na curva). Foi baixado no dia em que o Tesouro
Transparente parou de entregar o CSV e esta fonte entrou no lugar.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from mercado import arquivo, curvas, tesouro, titulos, treasury

AMOSTRAS = Path(__file__).parent / "amostras"


def _ms() -> str:
    return (AMOSTRAS / "anbima_ms261023.txt").read_text(encoding="utf-8")


@pytest.fixture
def anbima():
    ref, t = titulos.ler_ms(_ms())
    return {ref.isoformat(): {"fonte": "anbima", "t": t}}


def _juros_antigo() -> dict:
    """Um `mercado.json` publicado pelo Tesouro, como o de 23/10/2026."""
    def foto(d, pre, ipca):
        return {"dataBR": d,
                "pre": {"pontos": [{"vencimento": v, "taxa": t, "cupom": c}
                                   for v, t, c in pre]},
                "ipca": {"pontos": [{"vencimento": v, "taxa": t, "cupom": c}
                                    for v, t, c in ipca]}}
    pre = [("2028-01-01", 12.83, False), ("2032-01-01", 13.10, False),
           ("2037-01-01", 13.20, True)]
    ipca = [("2029-05-15", 7.60, False), ("2040-08-15", 7.20, False),
            ("2045-05-15", 7.10, True)]
    return {"series": {k: foto(d, pre, ipca) for k, d in (
        ("hoje", "2026-10-15"), ("semana", "2026-10-08"),
        ("mes", "2026-09-15"), ("semestre", "2026-04-16"))}}


CSV_TREASURY = """Date,"1 Mo","2 Mo","3 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"
10/23/2026,3.94,4.06,4.11,4.18,4.37,4.65,4.73,4.80,4.88,4.97,5.37,5.34
10/15/2026,3.90,4.02,4.08,4.14,4.30,4.58,4.66,4.74,4.82,4.91,5.30,5.28
09/15/2026,3.92,4.03,4.09,4.15,4.33,4.60,4.69,4.77,4.85,4.94,5.33,5.31
04/16/2026,3.70,3.68,3.66,3.60,3.50,3.52,3.60,3.78,3.98,4.22,4.83,4.88
"""
CSV_TIPS = """Date,"5 YR","7 YR","10 YR","20 YR","30 YR"
10/23/2026,2.40,2.49,2.60,2.89,3.05
10/15/2026,2.34,2.43,2.54,2.83,2.99
09/15/2026,2.36,2.45,2.56,2.85,3.01
04/16/2026,1.52,1.74,1.98,2.42,2.66
"""


# ---------------------------------------------------------------------------
# Leitura do arquivo da ANBIMA
# ---------------------------------------------------------------------------
def test_le_a_data_e_so_os_titulos_que_formam_curva():
    ref, t = titulos.ler_ms(_ms())
    assert ref == date(2026, 10, 23)
    fam = [x[0] for x in t]
    assert fam.count("pre") == 11 + 6          # LTN + NTN-F
    assert fam.count("ipca") == 14             # NTN-B
    # LFT e NTN-C ficam de fora
    assert len(t) == 31


def test_taxa_indicativa_em_formato_brasileiro():
    _, t = titulos.ler_ms(_ms())
    assert ["pre", 0, "2027-04-01", 13.2353] in t       # LTN
    assert ["pre", 1, "2037-01-01", 12.8865] in t       # NTN-F
    assert ["ipca", 1, "2060-08-15", 6.4448] in t       # NTN-B


def test_cabecalho_ausente_falha_alto():
    with pytest.raises(ValueError, match="Cabeçalho"):
        titulos.ler_ms("<html>429 - Muitas Requisições</html>")


def test_curva_prefixada_da_anbima(anbima):
    tab = titulos.tabela(anbima)
    pre = tesouro.curva(tab, "pre", date(2026, 10, 23))
    # A NTN-F de 01/01/2027 tem 0,19 ano: fica de fora pelo prazo mínimo.
    assert pre[0].vencimento == date(2027, 4, 1)
    # Em 01/01/2029 há LTN e NTN-F: fica a LTN, que é a taxa à vista.
    em_2029 = [v for v in pre if v.vencimento == date(2029, 1, 1)]
    assert len(em_2029) == 1 and not em_2029[0].cupom and em_2029[0].taxa == 12.7548
    # Chega a 10 anos pela NTN-F 2037 e não a 20.
    g = curvas.na_grade([(v.prazo, v.taxa) for v in pre])
    assert curvas.em(g, 10.0) is not None
    assert curvas.em(g, 20.0) is None


def test_curva_real_da_anbima_sem_ntnb_curta(anbima):
    tab = titulos.tabela(anbima)
    ipca = tesouro.curva(tab, "ipca", date(2026, 10, 23))
    # A NTN-B de 15/05/2027 (0,56 ano) sai pela defasagem do IPCA.
    assert ipca[0].vencimento == date(2028, 8, 15)
    assert all(v.cupom for v in ipca)
    assert ipca[-1].vencimento == date(2060, 8, 15)


# ---------------------------------------------------------------------------
# Acervo
# ---------------------------------------------------------------------------
def test_recupera_as_fotos_do_arquivo_anterior():
    a = titulos.das_fotos(_juros_antigo())
    assert list(a) == ["2026-10-15", "2026-10-08", "2026-09-15", "2026-04-16"]
    assert a["2026-09-15"]["fonte"] == "foto"
    assert ["pre", 1, "2037-01-01", 13.2] in a["2026-09-15"]["t"]


def test_anbima_vence_tesouro_que_vence_foto_em_qualquer_ordem():
    d = "2026-10-15"
    foto = {d: {"fonte": "foto", "t": [["pre", 0, "2030-01-01", 1.0]]}}
    tes = {d: {"fonte": "tesouro", "t": [["pre", 0, "2030-01-01", 2.0]]}}
    anb = {d: {"fonte": "anbima", "t": [["pre", 0, "2030-01-01", 3.0]]}}
    assert titulos.fundir(anb, tes, foto)[d]["fonte"] == "anbima"
    assert titulos.fundir(foto, anb, tes)[d]["fonte"] == "anbima"
    assert titulos.fundir(foto, tes)[d]["fonte"] == "tesouro"


def test_mesma_fonte_fica_a_mais_nova():
    d = "2026-10-23"
    velho = {d: {"fonte": "anbima", "t": [["pre", 0, "2030-01-01", 1.0]]}}
    novo = {d: {"fonte": "anbima", "t": [["pre", 0, "2030-01-01", 2.0]]}}
    assert titulos.fundir(velho, novo)[d]["t"][0][3] == 2.0


def test_dia_vazio_nao_entra():
    assert titulos.fundir({"2026-10-23": {"fonte": "anbima", "t": []}}) == {}


def test_poda_diaria_semanal_e_fotos():
    hoje = date(2026, 10, 23)
    dia = {"fonte": "anbima", "t": [["pre", 0, "2030-01-01", 12.0]]}
    acervo = {d: dia for d in (
        "2026-10-22", "2026-09-10",                  # até 45 dias: ficam
        "2026-08-03", "2026-08-05", "2026-08-07",    # mesma semana: fica a sexta
        "2026-04-16",                                # 190 dias: um por semana
        "2025-10-01")}                               # mais de 220: só se for foto
    p = titulos.podar(acervo, hoje)
    assert list(p) == ["2026-04-16", "2026-08-07", "2026-09-10", "2026-10-22"]
    p = titulos.podar(acervo, hoje, {date(2025, 10, 1)})
    assert "2025-10-01" in p


def test_tesouro_cobre_so_os_dias_que_o_acervo_nao_tem(anbima):
    csv = ("Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha\n"
           "Tesouro Prefixado;01/01/2032;23/10/2026;99,00;99,00\n"
           "Tesouro Prefixado;01/01/2032;14/10/2026;12,90;12,90\n")
    td = tesouro.ler_csv(csv)
    tab = titulos.juntar_com_tesouro(anbima, td)
    dia23 = tab[tab["DATA"] == "2026-10-23"]
    assert 99.0 not in dia23["TAXA"].tolist()           # o dia é da ANBIMA
    assert (tab["DATA"] == "2026-10-14").sum() == 1      # o 14/10 vem do Tesouro


# ---------------------------------------------------------------------------
# Fotos
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("chave, dia, esperado", [
    ("hoje", date(2026, 10, 23), "hoje"),
    ("semana", date(2026, 10, 16), "1 semana atrás"),
    ("semana", date(2026, 10, 14), "1 semana atrás"),     # feriado no meio
    ("semana", date(2026, 10, 11), "12 dias atrás"),
    ("mes", date(2026, 9, 23), "1 mês atrás"),
    ("mes", date(2026, 9, 15), "5 semanas atrás"),
    ("semestre", date(2026, 4, 16), "6 meses atrás"),
    ("semestre", date(2025, 12, 1), "11 meses atrás"),
])
def test_rotulo_diz_a_distancia_de_verdade(chave, dia, esperado):
    assert titulos.rotulo(chave, date(2026, 10, 23), dia) == esperado


def test_fotos_com_tesouro_fora_do_ar(anbima):
    acervo = titulos.fundir(titulos.das_fotos(_juros_antigo()), anbima)
    fontes = {d: v["fonte"] for d, v in acervo.items()}
    j = arquivo.montar_juros(titulos.tabela(acervo), treasury.ler_csv(CSV_TREASURY),
                             treasury.ler_csv(CSV_TIPS), fontes=fontes)
    assert j["datas"] == {"hoje": "2026-10-23", "semana": "2026-10-15",
                          "mes": "2026-09-15", "semestre": "2026-04-16"}
    s = j["series"]
    assert s["hoje"]["fonteBR"] == "ANBIMA"
    assert s["semestre"]["fonteBR"] == "Tesouro Direto"
    assert s["semana"]["rotulo"] == "1 semana atrás"
    assert s["mes"]["rotulo"] == "5 semanas atrás"
    assert s["semestre"]["rotulo"] == "6 meses atrás"
    # As regras do validador: pré chega a 10 anos e não a 20; NTN-B a 10.
    assert curvas.em(s["hoje"]["pre"]["grade"], 10.0) is not None
    assert curvas.em(s["hoje"]["pre"]["grade"], 20.0) is None
    assert curvas.em(s["hoje"]["ipca"]["grade"], 10.0) is not None


# ---------------------------------------------------------------------------
# Coleta inteira, sem rede
# ---------------------------------------------------------------------------
def test_coleta_segue_sem_o_tesouro(monkeypatch, tmp_path, anbima):
    import atualizar_mercado as am

    def tesouro_fora(sessao=None):
        raise RuntimeError("O Tesouro devolveu uma página HTML "
                           "('429 - Muitas Requisições', status 429) no lugar do CSV.")

    monkeypatch.setattr(tesouro, "baixar_csv", tesouro_fora)
    monkeypatch.setattr(titulos, "baixar_recentes", lambda fim, sessao: anbima)
    monkeypatch.setattr(treasury, "baixar", lambda tipo, anos, sessao:
                        treasury.ler_csv(CSV_TIPS if tipo == treasury.TIPO_REAL
                                         else CSV_TREASURY))
    hist = tmp_path / "spread_historico.json"
    monkeypatch.setattr(am, "HISTORICO_SPREAD", hist)

    avisos: list[str] = []
    j = am.coletar_juros(None, hoje=date(2026, 10, 25), avisos=avisos,
                         anterior=_juros_antigo())

    assert j["datas"]["hoje"] == "2026-10-23"
    assert j["acervo"]["2026-10-23"]["fonte"] == "anbima"
    assert j["acervo"]["2026-04-16"]["fonte"] == "foto"     # foto em uso não é podada
    assert not hist.exists()           # sem o Tesouro, a série longa não é refeita
    assert any("Tesouro Transparente" in a for a in avisos)

    # No dia seguinte, o acervo guardado basta, mesmo sem a ANBIMA.
    monkeypatch.setattr(titulos, "baixar_recentes", lambda fim, sessao: {})
    avisos = []
    j2 = am.coletar_juros(None, hoje=date(2026, 10, 26), avisos=avisos, anterior=j)
    assert j2["datas"]["hoje"] == "2026-10-23"
    assert set(j2["acervo"]) == set(j["acervo"])
    assert any("ANBIMA" in a for a in avisos)


def test_sem_fonte_nenhuma_e_sem_acervo_falha(monkeypatch):
    import atualizar_mercado as am

    def fora(*a, **k):
        raise RuntimeError("fora")

    monkeypatch.setattr(tesouro, "baixar_csv", fora)
    monkeypatch.setattr(titulos, "baixar_recentes", lambda fim, sessao: {})
    with pytest.raises(RuntimeError, match="Nem o Tesouro"):
        am.coletar_juros(None, hoje=date(2026, 10, 25), avisos=[], anterior={})


def test_pagina_html_do_tesouro_vira_erro_claro():
    class Resp:
        status_code = 200
        content = ("<!DOCTYPE html><html><head><title>429 - Muitas Requisições"
                   "</title></head></html>").encode("windows-1252")

        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError

    class Sessao:
        def get(self, url, timeout=None):
            return Resp()

    with pytest.raises(RuntimeError, match="429 - Muitas Requisições"):
        tesouro.baixar_csv(Sessao())
