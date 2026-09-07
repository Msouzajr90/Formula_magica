# -*- coding: utf-8 -*-
"""Fiagro e FI-Infra: os dois veículos que entraram depois do FII.

Nenhum teste aqui vai à rede. Os arquivos da CVM são reconstruídos em memória
com os nomes de coluna reais — que é o ponto: o leitor foi escrito olhando o
arquivo de verdade, e estes testes travam o formato que ele viu.
"""
from __future__ import annotations

import io
import zipfile

import pandas as pd
import pytest

from fiib3 import arquivo_informe, config as C, cvm_fii, fiinfra, indicadores
from fiib3 import tickers_fii
from fiib3.config import ParamsFII


# ---------------------------------------------------------------------------
# Família: Fiagro e FI-Infra vão para o grupo de papel
# ---------------------------------------------------------------------------
def test_fiagro_e_fiinfra_entram_no_grupo_de_papel():
    """Mesmo com a carteira dizendo outra coisa: é decisão, não medida.

    Um Fiagro de terra tem 100% em imóveis rurais. Ele continua sendo ranqueado
    com os fundos de crédito, porque o que o ranking compara é P/VP, e o P/VP só
    é comparável entre patrimônios apurados do mesmo jeito.
    """
    assert C.familia_do_fundo(C.TIPO_FIAGRO, 1.0, 0.0, 0.0) == "Papel"
    assert C.familia_do_fundo(C.TIPO_FIINFRA, float("nan"), float("nan"),
                              float("nan")) == "Papel"


def test_fii_continua_classificado_pela_carteira():
    assert C.familia_do_fundo(C.TIPO_FII, 0.92, 0.07, 0.0) == "Tijolo"
    assert C.familia_do_fundo(C.TIPO_FII, 0.04, 0.74, 0.15) == "Papel"
    assert C.familia_do_fundo(C.TIPO_FII, 0.56, 0.02, 0.30) == "Híbrido"
    assert C.familia_do_fundo(None, None, None, None) == "Sem dado"


# ---------------------------------------------------------------------------
# Leitor do informe de Fiagro
# ---------------------------------------------------------------------------
COLUNAS_FIAGRO = [
    "CNPJ_Classe", "Data_Referencia", "Versao", "Nome_Classe", "Codigo_ISIN",
    "Nome_Administrador", "Nome_Gestor", "Publico_Alvo",
    "Classificacao_Autorregulada", "Mercado_Negociacao", "Data_Entrega",
    "Data_Registro", "Patrimonio_Liquido", "Valor_Ativo", "Cotas_Emitidas",
    "Valor_Patrimonial_Cotas", "Numero_Cotistas", "Dividend_Yield_Mes",
    "Rentabilidade_Efetiva_Mes", "CRA", "CPR", "Imoveis_Rurais",
    "Total_Investido", "Total_Necessidades_Liquidez", "Total_Passivo",
]


def _linha_fiagro(cnpj, data, **campos):
    linha = dict.fromkeys(COLUNAS_FIAGRO, "0")
    linha.update({"CNPJ_Classe": cnpj, "Data_Referencia": data, "Versao": "1",
                  "Nome_Classe": f"FUNDO {cnpj[:4]}", "Codigo_ISIN": "BRRURACTF001",
                  "Mercado_Negociacao": "BOLSA", "Data_Registro": "2020-01-10",
                  "Data_Entrega": "2026-08-14",
                  "Patrimonio_Liquido": "100000000", "Cotas_Emitidas": "10000000",
                  "Valor_Patrimonial_Cotas": "10", "Numero_Cotistas": "5000",
                  "CRA": "80000000", "Total_Investido": "100000000"})
    linha.update(campos)
    return linha


def _zip_fiagro(linhas) -> zipfile.ZipFile:
    buf = io.BytesIO()
    csv = pd.DataFrame(linhas, columns=COLUNAS_FIAGRO).to_csv(
        sep=";", index=False).encode("ISO-8859-1")
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("inf_mensal_fiagro_202607.csv", csv)
        z.writestr("inf_mensal_fiagro_subclasse_202607.csv", b"nada;aqui\n")
    buf.seek(0)
    return zipfile.ZipFile(buf)


def test_fiagro_le_o_formato_real(monkeypatch):
    linhas = [_linha_fiagro("12345678000199", "2026-07-31")]
    monkeypatch.setattr(cvm_fii, "baixar_informe_fiagro",
                        lambda comp, **kw: _zip_fiagro(linhas))
    out = cvm_fii.ler_informe_fiagro(competencias=1, usar_cache=False)

    assert len(out) == 1
    linha = out.iloc[0]
    assert linha["CNPJ"] == "12345678000199"
    assert linha["COMPETENCIA"] == "2026-07"
    assert linha["PL"] == 100_000_000
    assert linha["VP_COTA"] == 10
    assert linha["COTISTAS"] == 5000
    assert linha["TIPO_FUNDO"] == C.TIPO_FIAGRO
    # A carteira do Fiagro tem contas próprias; CRA é o análogo do CRI.
    assert linha["PCT_PAPEL"] == pytest.approx(0.8)
    assert linha["PCT_IMOVEIS"] == pytest.approx(0.0)


def test_fiagro_traduz_o_mercado_de_negociacao(monkeypatch):
    """O Fiagro escreve 'BALCAO' por extenso; o FII usa S/N.

    Sem a tradução, o filtro de "não negociado em bolsa" não pegaria nenhum
    Fiagro fechado, e dezenas de fundos entrariam no universo só para cair
    depois por falta de cotação — com o motivo errado na aba de excluídos.
    """
    linhas = [
        _linha_fiagro("11111111000191", "2026-07-31", Mercado_Negociacao="BOLSA"),
        _linha_fiagro("22222222000192", "2026-07-31",
                      Mercado_Negociacao="BALCAO NAO ORGANIZADO"),
    ]
    monkeypatch.setattr(cvm_fii, "baixar_informe_fiagro",
                        lambda comp, **kw: _zip_fiagro(linhas))
    out = cvm_fii.ler_informe_fiagro(competencias=1, usar_cache=False)
    bolsa = dict(zip(out["CNPJ"], out["NEGOCIA_BOLSA"]))
    assert bolsa["11111111000191"] == "S"
    assert bolsa["22222222000192"] == "N"


def test_fiagro_fica_com_a_competencia_mais_nova_de_cada_fundo(monkeypatch):
    """A competência recém-publicada vem incompleta — daí ler várias.

    Em 06/09/2026 o arquivo de 08/2026 tinha 9 fundos e o de 07/2026 tinha mais
    de cem: os administradores ainda estavam entregando. Ler quatro competências
    e guardar a linha mais nova de cada fundo resolve sem adivinhar qual mês já
    fechou.
    """
    velho = _zip_fiagro([_linha_fiagro("33333333000193", "2026-06-30",
                                       Patrimonio_Liquido="90000000"),
                         _linha_fiagro("44444444000194", "2026-06-30")])
    novo = _zip_fiagro([_linha_fiagro("33333333000193", "2026-07-31",
                                      Patrimonio_Liquido="120000000")])
    zips = iter([novo, velho])
    monkeypatch.setattr(cvm_fii, "baixar_informe_fiagro",
                        lambda comp, **kw: next(zips))
    out = cvm_fii.ler_informe_fiagro(competencias=2, usar_cache=False).set_index("CNPJ")

    assert len(out) == 2, "o fundo que só entregou em junho não pode sumir"
    assert out.loc["33333333000193", "PL"] == 120_000_000
    assert out.loc["33333333000193", "COMPETENCIA"] == "2026-07"


def test_fiagro_indisponivel_nao_derruba_a_coleta(monkeypatch):
    def explode(comp, **kw):
        raise RuntimeError("404")
    monkeypatch.setattr(cvm_fii, "baixar_informe_fiagro", explode)
    assert cvm_fii.ler_informe_fiagro(competencias=2, usar_cache=False).empty


# ---------------------------------------------------------------------------
# Informe diário: a única fonte de patrimônio do FI-Infra
# ---------------------------------------------------------------------------
def _zip_diario(linhas, nome="inf_diario_fi_202608.csv") -> zipfile.ZipFile:
    buf = io.BytesIO()
    csv = pd.DataFrame(linhas).to_csv(sep=";", index=False).encode("ISO-8859-1")
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(nome, csv)
    buf.seek(0)
    return zipfile.ZipFile(buf)


def _linha_diario(cnpj, data, cota, pl, cotistas):
    return {"TP_FUNDO_CLASSE": "FI", "CNPJ_FUNDO_CLASSE": cnpj, "DT_COMPTC": data,
            "VL_TOTAL": pl, "VL_QUOTA": cota, "VL_PATRIM_LIQ": pl,
            "CAPTC_DIA": "0", "RESG_DIA": "0", "NR_COTST": cotistas}


def test_informe_diario_filtra_por_cnpj_e_fica_com_a_data_mais_nova(monkeypatch):
    linhas = [
        _linha_diario("55555555000195", "2026-08-28", "104.5", "300000000", "9000"),
        _linha_diario("55555555000195", "2026-08-31", "105.2", "310000000", "9100"),
        _linha_diario("99999999000199", "2026-08-31", "1.0", "1000", "3"),
    ]
    monkeypatch.setattr(cvm_fii, "_zip_informe_diario",
                        lambda comp, **kw: _zip_diario(linhas))
    out = cvm_fii.ler_informe_diario(["55555555000195"], competencias=1,
                                     usar_cache=False)
    assert len(out) == 1
    assert out.iloc[0]["VP_COTA"] == pytest.approx(105.2)
    assert out.iloc[0]["PL"] == 310_000_000
    assert out.iloc[0]["COTISTAS"] == 9100
    assert out.iloc[0]["COMPETENCIA"] == "2026-08"


def test_informe_diario_sem_cnpj_pedido_nao_baixa_nada(monkeypatch):
    def nao_deveria(*a, **k):                                  # pragma: no cover
        raise AssertionError("baixou o informe diário sem precisar")
    monkeypatch.setattr(cvm_fii, "_zip_informe_diario", nao_deveria)
    assert cvm_fii.ler_informe_diario([], usar_cache=False).empty


# ---------------------------------------------------------------------------
# A lista de FI-Infra e a conferência dela
# ---------------------------------------------------------------------------
REGISTRO = pd.DataFrame([
    {"CNPJ": "55555555000195", "NOME": "SPARTA INFRA FUNDO INCENTIVADO DE "
                                       "INVESTIMENTO EM INFRAESTRUTURA",
     "SITUACAO": "EM FUNCIONAMENTO NORMAL", "TIPO_CLASSE": "FIF",
     "CLASSIFICACAO": "Renda Fixa", "DT_FUNCIONAMENTO": pd.Timestamp("2019-05-02")},
    {"CNPJ": "66666666000196", "NOME": "KINEA INFRA FUNDO INCENTIVADO DE "
                                       "INVESTIMENTO EM INFRAESTRUTURA",
     "SITUACAO": "EM FUNCIONAMENTO NORMAL", "TIPO_CLASSE": "FIF",
     "CLASSIFICACAO": "Renda Fixa", "DT_FUNCIONAMENTO": pd.Timestamp("2018-03-01")},
    {"CNPJ": "77777777000197", "NOME": "FUNDO ENCERRADO DE INFRAESTRUTURA XYZ",
     "SITUACAO": "CANCELADA", "TIPO_CLASSE": "FIF",
     "CLASSIFICACAO": "Renda Fixa", "DT_FUNCIONAMENTO": pd.Timestamp("2017-01-01")},
])


def _lista(linhas) -> pd.DataFrame:
    return pd.DataFrame(linhas, columns=list(fiinfra.COLUNAS), dtype="string")


def test_lista_do_disco_ignora_comentario_e_normaliza_cnpj(tmp_path):
    arq = tmp_path / "fiinfra.csv"
    arq.write_text("# explicação\n# mais explicação\n"
                   "TICKER;CNPJ;NOME_CVM;CONFERIDO_EM\n"
                   "juro11;55.555.555/0001-95;SPARTA;2026-09-01\n"
                   "CDII11;;;\n"
                   "lixo;;;\n", encoding="utf-8")
    out = fiinfra.ler_lista(arq)
    assert list(out["TICKER"]) == ["JURO11", "CDII11"]
    assert out.iloc[0]["CNPJ"] == "55555555000195"
    assert pd.isna(out.iloc[1]["CNPJ"])


def test_gravar_lista_preserva_o_cabecalho(tmp_path):
    """O arquivo explica a si mesmo; reescrevê-lo não pode apagar a explicação."""
    arq = tmp_path / "fiinfra.csv"
    arq.write_text("# por que este arquivo existe\n"
                   "TICKER;CNPJ;NOME_CVM;CONFERIDO_EM\nJURO11;;;\n",
                   encoding="utf-8")
    df = fiinfra.ler_lista(arq)
    df.loc[0, "CNPJ"] = "55555555000195"
    fiinfra.gravar_lista(df, arq)
    texto = arq.read_text(encoding="utf-8")
    assert texto.startswith("# por que este arquivo existe")
    assert "JURO11;55555555000195" in texto


def test_casar_liga_o_nome_do_yahoo_ao_cnpj_da_cvm():
    cnpj, nota, nome = fiinfra.casar("Sparta Infra FIC FI Infraestrutura RL",
                                     REGISTRO)
    assert cnpj == "55555555000195"
    assert nota >= fiinfra.SEMELHANCA_MINIMA
    assert "SPARTA" in nome


def test_casar_recusa_quando_nao_ha_vencedor_claro():
    """Na dúvida, não publica.

    Dois fundos com nomes quase idênticos (um fundo e sua classe de cotas) não
    podem ser desempatados por semelhança de texto. O resultado certo é não
    escolher nenhum e pedir conferência humana.
    """
    ambiguo = pd.DataFrame([
        {"CNPJ": "11111111000191", "NOME": "ALFA INFRA RENDA FIXA I",
         "SITUACAO": "EM FUNCIONAMENTO NORMAL"},
        {"CNPJ": "22222222000192", "NOME": "ALFA INFRA RENDA FIXA II",
         "SITUACAO": "EM FUNCIONAMENTO NORMAL"},
    ])
    cnpj, _, _ = fiinfra.casar("Alfa Infra Renda Fixa", ambiguo)
    assert cnpj is None


def test_casar_recusa_nome_desconhecido():
    assert fiinfra.casar("Padaria do Zé S.A.", REGISTRO)[0] is None


def test_conferencia_exige_cadastro_situacao_e_razao_social():
    lista = _lista([
        {"TICKER": "JURO11", "CNPJ": "55555555000195",
         "NOME_CVM": "SPARTA INFRA FUNDO INCENTIVADO DE INVESTIMENTO EM INFRAESTRUTURA",
         "CONFERIDO_EM": "2026-09-01"},
        {"TICKER": "MORT11", "CNPJ": "77777777000197",
         "NOME_CVM": "FUNDO ENCERRADO DE INFRAESTRUTURA XYZ", "CONFERIDO_EM": "2025-01-01"},
        {"TICKER": "FANT11", "CNPJ": "88888888000188", "NOME_CVM": "NAO EXISTE",
         "CONFERIDO_EM": "2025-01-01"},
        {"TICKER": "TROC11", "CNPJ": "66666666000196",
         "NOME_CVM": "OUTRO NOME COMPLETAMENTE DIFERENTE DISSO AQUI",
         "CONFERIDO_EM": "2025-01-01"},
        {"TICKER": "VAZI11", "CNPJ": None, "NOME_CVM": None, "CONFERIDO_EM": None},
    ])
    ok, avisos = fiinfra.conferir(lista, REGISTRO)

    assert list(ok["TICKER"]) == ["JURO11"]
    texto = " | ".join(avisos)
    assert "MORT11" in texto and "CANCELADA" in texto
    assert "FANT11" in texto and "não está no cadastro" in texto
    assert "TROC11" in texto and "razão social" in texto
    assert "VAZI11" in texto and "sem CNPJ" in texto


def test_conferencia_devolve_o_que_o_pipeline_precisa():
    lista = _lista([{"TICKER": "JURO11", "CNPJ": "55555555000195",
                     "NOME_CVM": None, "CONFERIDO_EM": None}])
    ok, _ = fiinfra.conferir(lista, REGISTRO)
    assert set(ok.columns) >= {"TICKER", "CNPJ", "NOME", "SITUACAO",
                               "DT_FUNCIONAMENTO"}
    assert ok.iloc[0]["DT_FUNCIONAMENTO"] == pd.Timestamp("2019-05-02")


def test_coletar_monta_o_informe_no_formato_do_pipeline(monkeypatch, tmp_path):
    arq = tmp_path / "fiinfra.csv"
    arq.write_text("TICKER;CNPJ;NOME_CVM;CONFERIDO_EM\n"
                   "JURO11;55555555000195;;\n", encoding="utf-8")
    monkeypatch.setattr(cvm_fii, "baixar_registro_classes", lambda **kw: REGISTRO)
    monkeypatch.setattr(cvm_fii, "_zip_informe_diario", lambda comp, **kw: _zip_diario(
        [_linha_diario("55555555000195", "2026-08-31", "105.2", "310000000", "9100")]))

    out, avisos = fiinfra.coletar(usar_cache=False, resolver_pendentes=False,
                                  caminho=arq, competencias=1)
    assert len(out) == 1 and not avisos
    linha = out.iloc[0]
    assert linha["TICKER"] == "JURO11"
    assert linha["TIPO_FUNDO"] == C.TIPO_FIINFRA
    assert linha["NEGOCIA_BOLSA"] == "S"
    assert linha["VP_COTA"] == pytest.approx(105.2)
    # nº de cotas não vem no informe diário: sai de patrimônio / cota
    assert linha["COTAS"] == pytest.approx(310_000_000 / 105.2)


def test_coletar_avisa_e_omite_fundo_sem_informe_diario(monkeypatch, tmp_path):
    """Fundo que sumiu do informe diário não pode ficar na tela com dado velho."""
    arq = tmp_path / "fiinfra.csv"
    arq.write_text("TICKER;CNPJ;NOME_CVM;CONFERIDO_EM\n"
                   "JURO11;55555555000195;;\n", encoding="utf-8")
    monkeypatch.setattr(cvm_fii, "baixar_registro_classes", lambda **kw: REGISTRO)
    monkeypatch.setattr(cvm_fii, "_zip_informe_diario",
                        lambda comp, **kw: _zip_diario([]))
    out, avisos = fiinfra.coletar(usar_cache=False, resolver_pendentes=False,
                                  caminho=arq, competencias=1)
    assert out.empty
    assert any("JURO11" in a and "informe diário" in a for a in avisos)


def test_lista_versionada_do_repositorio_e_legivel():
    """O arquivo que vai para o Git tem que passar pelo próprio leitor."""
    lista = fiinfra.ler_lista()
    assert list(lista.columns) == list(fiinfra.COLUNAS)
    assert lista["TICKER"].str.fullmatch(r"[A-Z]{4}\d{1,2}").all()
    assert lista["TICKER"].is_unique


# ---------------------------------------------------------------------------
# O código de negociação que vem pronto
# ---------------------------------------------------------------------------
def test_ticker_da_lista_vence_o_derivado_do_isin():
    """FI-Infra chega com o código preenchido; nada pode sobrescrevê-lo."""
    informe = pd.DataFrame({
        "CNPJ": ["55555555000195", "12345678000199"],
        "ISIN": [pd.NA, "BRMXRFCTF008"],
        "TICKER": pd.array(["JURO11", None], dtype="string"),
    })
    mapa = tickers_fii.montar_mapa(informe, usar_b3=False, usar_cache=False)
    assert list(mapa["TICKER"]) == ["JURO11", "MXRF11"]
    assert list(mapa["ORIGEM_TICKER"]) == ["lista", "isin"]


# ---------------------------------------------------------------------------
# O arquivo-ponte
# ---------------------------------------------------------------------------
def test_arquivo_ponte_leva_e_traz_o_tipo_de_fundo(tmp_path):
    informe = pd.DataFrame({
        "CNPJ": ["55555555000195", "12345678000199"],
        "COMPETENCIA": ["2026-08", "2026-07"],
        "TIPO_FUNDO": [C.TIPO_FIINFRA, C.TIPO_FII],
        "TICKER": ["JURO11", None],
        "PL": [310_000_000.0, 100_000_000.0],
        "VP_COTA": [105.2, 10.0],
    })
    destino = tmp_path / "informe.json"
    arquivo_informe.exportar(informe, None, destino)
    lido, _ = arquivo_informe.importar(destino)
    por_cnpj = lido.set_index("CNPJ")
    assert por_cnpj.loc["55555555000195", "TIPO_FUNDO"] == C.TIPO_FIINFRA
    assert por_cnpj.loc["55555555000195", "TICKER"] == "JURO11"
    assert por_cnpj.loc["12345678000199", "TIPO_FUNDO"] == C.TIPO_FII


def test_arquivo_ponte_antigo_continua_sendo_lido_como_fii(tmp_path):
    """Versão 2 não tinha TIPO_FUNDO. Sem o padrão, o site inteiro viraria
    'Sem dado' na primeira coleta depois da atualização."""
    destino = tmp_path / "informe.json"
    destino.write_text(
        '{"meta":{"versao":2,"geradoEm":"2026-08-01 10:00","competencia":"2026-07"},'
        '"fundos":[{"cnpj":"12345678000199","comp":"2026-07","pl":1.0}]}',
        encoding="utf-8")
    lido, _ = arquivo_informe.importar(destino)
    assert lido.iloc[0]["TIPO_FUNDO"] == "FII"


# ---------------------------------------------------------------------------
# O filtro de informe atrasado, agora por tipo de veículo
# ---------------------------------------------------------------------------
def _tabela_minima(linhas) -> pd.DataFrame:
    base = {"PRECO": 10.0, "VP_COTA": 10.0, "PL": 500_000_000.0,
            "COTISTAS": 10_000.0, "LIQUIDEZ": 5_000_000.0,
            "MESES_PAGOS_12M": 12.0, "IDADE_MESES": 60.0,
            "SITUACAO": "", "EXCLUSIVO": "N", "NEGOCIA_BOLSA": "S"}
    return pd.DataFrame([{**base, **l} for l in linhas])


def test_informe_atrasado_e_medido_dentro_de_cada_tipo():
    """As três fontes têm calendários diferentes.

    O informe diário do FI-Infra sai no dia seguinte; o mensal de FII sai até o
    15º dia útil do mês seguinte e o arquivo-ponte costuma ser gerado uma vez por
    mês. Com uma régua só, tirada do máximo global, um FI-Infra de agosto
    derrubaria o mercado inteiro de FII sempre que a ponte atrasasse duas
    competências — 1.300 fundos sumindo da tela por causa de um.
    """
    df = _tabela_minima([
        {"TICKER": "JURO11", "TIPO_FUNDO": C.TIPO_FIINFRA, "COMPETENCIA": "2026-09"},
        {"TICKER": "MXRF11", "TIPO_FUNDO": C.TIPO_FII, "COMPETENCIA": "2026-06"},
        {"TICKER": "HGLG11", "TIPO_FUNDO": C.TIPO_FII, "COMPETENCIA": "2026-06"},
        {"TICKER": "VELH11", "TIPO_FUNDO": C.TIPO_FII, "COMPETENCIA": "2025-11"},
    ])
    elegiveis, excluidos = indicadores.filtrar(df, ParamsFII(
        liquidez_minima_diaria=0, patrimonio_minimo=0, cotistas_minimo=0))
    assert set(elegiveis["TICKER"]) == {"JURO11", "MXRF11", "HGLG11"}
    assert list(excluidos["TICKER"]) == ["VELH11"]


def test_montar_marca_fiagro_como_papel_mesmo_sem_carteira():
    informe = pd.DataFrame({
        "CNPJ": ["12345678000199"], "TICKER": ["RURA11"],
        "TIPO_FUNDO": [C.TIPO_FIAGRO], "VP_COTA": [10.0], "PL": [1e8],
        "PCT_IMOVEIS": [float("nan")], "PCT_PAPEL": [float("nan")],
        "PCT_FOF": [float("nan")], "DT_FUNCIONAMENTO": [pd.Timestamp("2021-01-01")],
    })
    vazia = pd.Series(dtype=float)
    out = indicadores.montar(informe, pd.DataFrame(), vazia, vazia, vazia,
                             pd.DataFrame())
    assert out.iloc[0]["FAMILIA"] == "Papel"
