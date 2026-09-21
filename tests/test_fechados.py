# -*- coding: utf-8 -*-
"""Testes da aba de fundos fechados. Nenhum acessa a rede.

Os casos sintéticos reproduzem armadilhas encontradas nos arquivos reais e
estão nomeados pelo fundo que as revelou. Os que dependem das amostras em
`amostra_fontes/fundos/` são pulados quando elas não estão presentes, para a
suíte continuar verde numa máquina limpa e no robô.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fechados import arquivo, coleta, config as C, indicadores

AMOSTRAS = Path(__file__).parent.parent / "amostra_fontes" / "fundos"
HOJE = pd.Timestamp("2026-09-21")


def _amostra(nome: str) -> pd.DataFrame:
    caminho = AMOSTRAS / nome
    if not caminho.exists():
        pytest.skip(f"amostra {nome} não está presente")
    return pd.read_csv(caminho, sep=";", dtype="string")


def _longo(**campos) -> pd.DataFrame:
    """Uma tabela longa mínima, com o esquema completo."""
    n = len(next(iter(campos.values())))
    base = {c: [pd.NA] * n for c in coleta.ESQUEMA}
    base.update({"CNPJ": ["11111111111111"] * n, "NOME": ["FUNDO X"] * n,
                 "TIPO": [C.TIPO_FII] * n})
    base.update(campos)
    return pd.DataFrame(base)[list(coleta.ESQUEMA)]


# ---------------------------------------------------------------------------
# Escala
# ---------------------------------------------------------------------------
def test_fiagro_vem_em_percentual_e_fii_em_fracao():
    """Somar os dois sem converter erraria por cem vezes.

    Medido: a mediana de `Percentual_Rentabilidade_Efetiva_Mes` é 0,001 no
    informe de FII e 0,32 no de Fiagro. O segundo é percentual.
    """
    longo = _longo(DATA=[pd.Timestamp("2026-07-01")] * 2,
                   CNPJ=["11111111111111", "22222222222222"],
                   TIPO=[C.TIPO_FII, C.TIPO_FIAGRO],
                   RENT_MES=[0.012, 1.2])
    out, _ = indicadores.normalizar_escala(longo)
    assert out.loc[0, "RENT_MES"] == pytest.approx(0.012)
    assert out.loc[1, "RENT_MES"] == pytest.approx(0.012)


def test_escala_errada_gera_aviso():
    longo = _longo(DATA=[pd.Timestamp("2026-07-01")] * 2,
                   CNPJ=["11111111111111", "22222222222222"],
                   TIPO=[C.TIPO_FII] * 2, RENT_MES=[3.5, 4.0])
    _, avisos = indicadores.normalizar_escala(longo)
    assert any("escala" in a for a in avisos)


# ---------------------------------------------------------------------------
# Prazo
# ---------------------------------------------------------------------------
def test_riza_viseu_a_data_manda_e_o_conflito_e_publicado():
    """Declarado Indeterminado, com vencimento em 2032. A data vence."""
    linha = pd.Series({"ROTULO_PRAZO": "Indeterminado",
                       "DT_VENCIMENTO": pd.Timestamp("2032-05-12")})
    r = indicadores.resolver_prazo(linha, HOJE)
    assert r["PRAZO"] == C.PRAZO_DETERMINADO
    assert r["ROTULO_CONFLITA"] is True
    assert r["ANOS_RESTANTES"] == pytest.approx(5.64, abs=0.05)


def test_vencimento_em_3035_nao_vira_prazo_restante():
    linha = pd.Series({"ROTULO_PRAZO": "Determinado",
                       "DT_VENCIMENTO": pd.Timestamp("3035-07-01")})
    r = indicadores.resolver_prazo(linha, HOJE)
    assert r["PRAZO_SUSPEITO"] is True
    assert r["ANOS_RESTANTES"] is None
    assert r["DT_VENCIMENTO"] == "3035-07-01"      # a data segue visível


def test_vector_queluz_venceu_e_continua_informando():
    linha = pd.Series({"ROTULO_PRAZO": "Determinado",
                       "DT_VENCIMENTO": pd.Timestamp("2021-07-14")})
    r = indicadores.resolver_prazo(linha, HOJE)
    assert r["PRAZO_VENCIDO"] is True
    assert r["ANOS_RESTANTES"] < 0


def test_fip_sem_prazo_nenhum_nao_inventa():
    linha = pd.Series({"ROTULO_PRAZO": pd.NA, "DT_VENCIMENTO": pd.NaT})
    r = indicadores.resolver_prazo(linha, HOJE)
    assert r["PRAZO"] == C.PRAZO_SEM_DADO
    assert r["ANOS_RESTANTES"] is None


def test_rotulo_de_prazo_do_fiagro_e_descartado():
    """'1000 ANO/ANOS' e '0 DIA/DIAS' não são prazo — 210 de 289 vinham assim."""
    s = pd.Series(["1000 ANO/ANOS", "0 ANO/ANOS", "0 DIA/DIAS", "Determinado"],
                  dtype="string")
    out = coleta._rotulo_de_prazo(s)
    assert out.isna().tolist() == [True, True, True, False]
    assert out.iloc[3] == "Determinado"


# ---------------------------------------------------------------------------
# Séries
# ---------------------------------------------------------------------------
def test_rentabilidade_acumulada_compoe():
    g = _longo(DATA=pd.date_range("2026-01-01", periods=3, freq="MS"),
               RENT_MES=[0.01, 0.01, 0.01])
    m = indicadores.metricas_da_serie(g, 12)
    assert m["RENT_12M"] == pytest.approx(1.01 ** 3 - 1)


def test_dy_acumulado_soma_e_nao_compoe():
    g = _longo(DATA=pd.date_range("2026-01-01", periods=3, freq="MS"),
               DY_MES=[0.01, 0.02, 0.03])
    assert indicadores.metricas_da_serie(g, 12)["DY_12M"] == pytest.approx(0.06)


def test_variacao_de_cotistas_usa_a_janela_e_o_ultimo_informe():
    g = _longo(DATA=pd.date_range("2026-01-01", periods=3, freq="MS"),
               COTISTAS=[1000.0, 900.0, 800.0])
    m = indicadores.metricas_da_serie(g, 12)
    assert m["COTISTAS_VAR_12M"] == pytest.approx(-0.2)
    assert m["COTISTAS_VAR_ULTIMO"] == pytest.approx(-1 / 9, abs=1e-6)


def test_amortizacao_conta_meses_e_nao_so_soma():
    g = _longo(DATA=pd.date_range("2026-01-01", periods=4, freq="MS"),
               AMORT_MES=[0.0, 0.05, 0.0, 0.03])
    m = indicadores.metricas_da_serie(g, 12)
    assert m["AMORT_12M"] == pytest.approx(0.08)
    assert m["MESES_COM_AMORT"] == 2


def test_informe_republicado_nao_conta_duas_vezes():
    """A CVM reenvia informe corrigido mantendo o original no mesmo arquivo."""
    g = _longo(DATA=[pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-01"),
                     pd.Timestamp("2026-02-01")],
               RENT_MES=[0.01, 0.01, 0.01])
    cons, _ = indicadores.consolidar(g, hoje=HOJE)
    assert cons.loc[0, "N_INFORMES"] == 2
    assert cons.loc[0, "RENT_12M"] == pytest.approx(1.01 ** 2 - 1)


# ---------------------------------------------------------------------------
# Universo
# ---------------------------------------------------------------------------
def test_master_de_feeder_fica_de_fora_pelo_numero_de_cotistas():
    cons = pd.DataFrame({
        "TIPO": [C.TIPO_FII, C.TIPO_FII],
        "NOME": ["LCP PREFIXADO FEEDER", "LCP PREFIXADO MASTER"],
        "PUBLICO": ["INVESTIDORES EM GERAL", "INVESTIDOR PROFISSIONAL"],
        "EXCLUSIVO": [False, False], "COTISTAS": [12974, 22], "PL": [1, 1]})
    ok = indicadores.elegiveis(cons)
    assert ok.tolist() == [True, False]


def test_fip_entra_com_publico_profissional_e_corte_proprio():
    """Sem a exceção, o filtro zeraria o universo de FIP inteiro."""
    cons = pd.DataFrame({
        "TIPO": [C.TIPO_FIP, C.TIPO_FIP],
        "NOME": ["FIP A", "FIP B"],
        "PUBLICO": ["Investidores profissionais", "Investidores qualificados"],
        "EXCLUSIVO": [pd.NA, pd.NA], "COTISTAS": [60, 4], "PL": [1, 1]})
    ok = indicadores.elegiveis(cons)
    assert ok.tolist() == [True, False]


def test_exclusivo_nulo_nao_exclui():
    """FIP não informa o campo; tratá-lo como exclusivo apagaria a fonte."""
    cons = pd.DataFrame({
        "TIPO": [C.TIPO_FIP], "NOME": ["FIP"],
        "PUBLICO": ["Investidores qualificados"], "EXCLUSIVO": [pd.NA],
        "COTISTAS": [500], "PL": [1]})
    assert indicadores.elegiveis(cons).iloc[0]


# ---------------------------------------------------------------------------
# Arquivo
# ---------------------------------------------------------------------------
def test_exportar_e_importar_preserva_o_cnpj_com_zeros(tmp_path):
    g = _longo(DATA=[pd.Timestamp("2026-07-01")],
               CNPJ=["00123456000199"], COTISTAS=[500.0], PL=[1e8])
    cons, avisos = indicadores.consolidar(g, hoje=HOJE)
    destino = tmp_path / "fundos_fechados.json"
    dados = arquivo.exportar(cons, destino, avisos=avisos)
    assert dados["meta"]["nFundos"] == 1
    volta = arquivo.importar(destino)
    assert volta.loc[0, "CNPJ"] == "00123456000199"
    assert list(volta.columns) == list(C.COLUNAS)


def test_avisos_viajam_no_arquivo(tmp_path):
    g = _longo(DATA=[pd.Timestamp("2026-07-01")],
               DT_VENCIMENTO=[pd.Timestamp("3035-01-01")],
               ROTULO_PRAZO=["Determinado"])
    cons, avisos = indicadores.consolidar(g, hoje=HOJE)
    dados = arquivo.exportar(cons, tmp_path / "x.json", avisos=avisos)
    assert any("fora de escala" in a for a in dados["meta"]["avisos"])


# ---------------------------------------------------------------------------
# Contra os arquivos reais
# ---------------------------------------------------------------------------
def test_fii_real_pega_total_numero_cotistas_e_nao_vinculo_familiar():
    """O erro que a primeira sondagem cometeu: `Cotistas_Vinculo_Familiar`
    casava antes de `Total_Numero_Cotistas` e zerava todo filtro."""
    geral = _amostra("fii__inf_mensal_fii_geral_2026.csv")
    compl = _amostra("fii__inf_mensal_fii_complemento_2026.csv")
    longo = coleta.montar_fii(geral, compl)
    esperado = pd.to_numeric(compl["Total_Numero_Cotistas"], errors="coerce")
    assert longo["COTISTAS"].dropna().max() == esperado.max()


def test_fii_real_consolida_sem_perder_fundo():
    geral = _amostra("fii__inf_mensal_fii_geral_2026.csv")
    compl = _amostra("fii__inf_mensal_fii_complemento_2026.csv")
    longo = coleta.montar_fii(geral, compl)
    cons, _ = indicadores.consolidar(longo, hoje=HOJE)
    assert len(cons) == longo["CNPJ"].nunique()
    assert cons["COMPETENCIA"].notna().all()
    assert (cons["PERIODICIDADE"] == "mensal").all()


def test_fii_real_prazo_determinado_tem_vencimento():
    """Nos 257 determinados do informe de 2026, 257 têm data."""
    det = _amostra("fii__prazo_determinado.csv")
    longo = coleta.montar_fii(det, det)
    cons, _ = indicadores.consolidar(longo, hoje=HOJE)
    determinados = cons[cons["PRAZO"] == C.PRAZO_DETERMINADO]
    assert len(determinados) > 200
    assert determinados["DT_VENCIMENTO"].notna().all()


def test_fip_real_usa_as_colunas_que_tem_conteudo():
    """`NR_COTST` e `VL_PATRIM_COTA` existem e vêm vazias; as boas têm
    outro nome."""
    bruto = _amostra("fip2__inf_quadrimestral_fip_2026.csv")
    longo = coleta.montar_fip(bruto)
    assert longo["COTISTAS"].notna().mean() > 0.9
    assert longo["VP_COTA"].notna().mean() > 0.9
    cons, _ = indicadores.consolidar(longo, hoje=HOJE)
    assert (cons["PERIODICIDADE"] == "quadrimestral").all()
    assert (cons["PRAZO"] == C.PRAZO_SEM_DADO).all()


# ---------------------------------------------------------------------------
# O que a primeira execução real ensinou
# ---------------------------------------------------------------------------
def test_mes_absurdo_sai_do_acumulado_em_vez_de_contaminar():
    """O Packem Fiagro reportou -380% num mês; composto, come o ano inteiro."""
    g = _longo(DATA=pd.date_range("2026-01-01", periods=4, freq="MS"),
               RENT_MES=[0.01, -3.8064, 0.01, 0.01])
    m = indicadores.metricas_da_serie(g, 12)
    assert m["MESES_DESCARTADOS"] == 1
    assert m["RENT_12M"] == pytest.approx(1.01 ** 3 - 1)


def test_retorno_pela_cota_serve_de_contraprova():
    """VP/cota está em reais e não tem ambiguidade de unidade."""
    g = _longo(DATA=pd.date_range("2026-01-01", periods=3, freq="MS"),
               VP_COTA=[100.0, 105.0, 110.0])
    assert indicadores.metricas_da_serie(g, 12)["RENT_VP_12M"] == \
        pytest.approx(0.10)


def test_conferir_fala_do_conjunto_que_recebe():
    """Avisar sobre fundo que o filtro descartou treina quem lê a ignorar."""
    bruto = _longo(DATA=[pd.Timestamp("2026-07-01")] * 2,
                   CNPJ=["11111111111111", "22222222222222"],
                   NOME=["RUIM", "BOM"], RENT_MES=[5.0, 0.01],
                   COTISTAS=[10.0, 5000.0], PUBLICO=["INVESTIDORES EM GERAL"] * 2)
    cons, _ = indicadores.consolidar(bruto, hoje=HOJE)
    publicado = cons[indicadores.elegiveis(cons)]
    assert len(publicado) == 1
    assert indicadores.conferir(cons, "universo bruto")
    assert indicadores.conferir(publicado, "publicado") == []
