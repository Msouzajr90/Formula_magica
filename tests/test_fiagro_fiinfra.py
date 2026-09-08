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

from fiib3 import arquivo_informe, b3_listados, casamento, config as C
from fiib3 import cvm_fii, fiinfra, indicadores, tickers_fii
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
# Casamento de razão social entre cadastros
# ---------------------------------------------------------------------------
# Os nomes exatos que apareceram na primeira execução real, em 07/09/2026.
B3_JURO = "SPARTA INFRA FIC FI INFRA RENDA FIXA CP"
CVM_JURO = ("SPARTA INFRA FI EM COTAS DE FUNDOS INCENTIVADOS DE INVESTIMENTO "
            "EM INFRAESTRUTURA RENDA FIXA")
CVM_MASTER_SPARTA = ("SPARTA INFRA MASTER I FUNDO INCENTIVADO DE INVESTIMENTO "
                     "EM INFRAESTRUTURA RENDA FIXA")

REGISTRO = pd.DataFrame([
    {"CNPJ": "42730834000100", "NOME": CVM_JURO,
     "SITUACAO": "Em Funcionamento Normal",
     "DT_FUNCIONAMENTO": pd.Timestamp("2021-05-02")},
    {"CNPJ": "43140450000192", "NOME": CVM_MASTER_SPARTA,
     "SITUACAO": "Em Funcionamento Normal",
     "DT_FUNCIONAMENTO": pd.Timestamp("2021-03-01")},
    {"CNPJ": "26324298000189",
     "NOME": "KINEA INFRA FIF CIC DE FUNDOS INCENTIVADOS DE INVESTIMENTO EM "
             "INFRA RF CRED PRIV RESP LIMITADA",
     "SITUACAO": "Em Funcionamento Normal",
     "DT_FUNCIONAMENTO": pd.Timestamp("2018-03-01")},
    {"CNPJ": "77777777000197", "NOME": "FUNDO ENCERRADO DE INFRAESTRUTURA XYZ",
     "SITUACAO": "Cancelado", "DT_FUNCIONAMENTO": pd.Timestamp("2017-01-01")},
])


def test_casa_a_mesma_razao_social_escrita_de_dois_jeitos():
    """A falha que derrubou a primeira execução real.

    A B3 corta a razão social em 50 caracteres e abrevia o que sobra; a CVM
    escreve por extenso. É o mesmo fundo, e a comparação caractere a caractere
    dá 77% — abaixo de qualquer corte defensável. Em conjunto de palavras, com
    as abreviações desdobradas, os dois nomes são quase idênticos.
    """
    cnpj, nota, _ = casamento.Casador(REGISTRO).casar(B3_JURO)
    assert cnpj == "42730834000100"
    assert nota >= casamento.COBERTURA_MINIMA


def test_fundo_master_nao_e_escolhido_mas_continua_competindo():
    """Quem lista em bolsa é o fundo que investe no master, nunca o master.

    A regra tem duas metades e as duas importam. Sem a primeira, o NUIF11 casava
    com um master cuja cota valia R$ 1,55 contra R$ 100 do fundo listado. Sem a
    segunda — deixar o master competir —, o segundo colocado herdaria a vaga sem
    ninguém para disputá-la, e foi assim que o BIDB11 assumiu o CNPJ de um fundo
    de outra gestora.
    """
    escolhido = casamento.Casador(REGISTRO).casar(B3_JURO)[0]
    assert escolhido != "43140450000192", "escolheu o master"

    so_o_master = REGISTRO[REGISTRO["NOME"].eq(CVM_MASTER_SPARTA)]
    assert casamento.Casador(so_o_master).casar(B3_JURO)[0] is None


def test_palavra_generica_sozinha_nao_casa():
    """Cobrir o nome inteiro é a pergunta certa; caber dentro dele não é.

    Um candidato genérico cujas palavras cabem todas no nome procurado tiraria
    nota máxima na direção contrária sem dizer nada — foi o que fez o ROOT11
    (Bulletwood) casar com um "RENDA FIXA LONGO PRAZO FUNDO DE INVESTIMENTO
    FINANCEIRO" quando a medida era simétrica.
    """
    generico = pd.DataFrame([
        {"CNPJ": "11111111000191",
         "NOME": "RENDA FIXA LONGO PRAZO FUNDO DE INVESTIMENTO FINANCEIRO",
         "SITUACAO": "Em Funcionamento Normal"},
    ])
    assert casamento.Casador(generico).casar(
        "BULLETWOOD FUN DE INVES FIN EM COTAS DE FUN INCENT")[0] is None


def test_credito_sozinho_ainda_distingue_fundos():
    """"Crédito privado" é boilerplate; "crédito" sozinho não é.

    O BTG Pactual Crédito Agrícola e o BTG Pactual Terras Agrícolas são dois
    Fiagro listados, com códigos diferentes. Jogar "crédito" fora como palavra
    solta fazia um virar o outro — por isso o ruído é removido por frase.
    """
    assert "CREDITO" in casamento.tokens("BTG PACTUAL CRÉDITO AGRÍCOLA FIAGRO")
    assert "CREDITO" not in casamento.tokens("SPARTA INFRA FIC FI INFRA RF CP")


def test_abreviacoes_da_b3_viram_as_palavras_da_cvm():
    assert casamento.tokens("FDO INV COTAS") == casamento.tokens(
        "FUNDO DE INVESTIMENTO EM COTAS")
    assert "INFRAESTRUTURA" in casamento.tokens("SUNO INFRA DEB FIC FDO INC IE RF")


def test_palavra_rara_pesa_mais_que_palavra_de_prospecto():
    """É o IDF que separa nome de gestora de vocabulário de prospecto."""
    corpus = pd.DataFrame([
        {"CNPJ": f"{i:014d}", "NOME": f"FUNDO {i} INCENTIVADO EM INFRAESTRUTURA"}
        for i in range(50)
    ] + [{"CNPJ": "99999999999999", "NOME": "SPARTA INCENTIVADO EM INFRAESTRUTURA"}])
    c = casamento.Casador(corpus)
    assert c.peso("SPARTA") > c.peso("INFRAESTRUTURA")


def test_candidatos_vem_ordenado_e_com_cnpj():
    tops = casamento.Casador(REGISTRO).candidatos(B3_JURO, n=3)
    assert list(tops.columns) == ["CNPJ", "NOME", "SITUACAO", "NOTA", "NOTA2"]
    assert (tops["NOTA"].diff().dropna() <= 1e-9).all(), "tem que vir ordenado"


# ---------------------------------------------------------------------------
# A lista de fundos listados da B3
# ---------------------------------------------------------------------------
EXPORT_B3 = ("Razão Social;Fundo;Código\n"
             "SPARTA INFRA FIC FI INFRA RENDA FIXA CP;SPARTA INFRA;JURO;\n"
             "KINEA INFRA - FDO INV COTAS FDO INC. INV INF RF CP;KINEA INFRAF;KDIF;\n")


def test_export_da_b3_e_lido_apesar_do_ponto_e_virgula_sobrando(tmp_path):
    """Três colunas no cabeçalho e quatro campos por linha.

    Lido de forma ingênua, o pandas trata a primeira coluna como índice e o
    código some. O arquivo é o que a B3 entrega; quem se adapta é o leitor.
    """
    arq = tmp_path / "fiinfra.csv"
    arq.write_text(EXPORT_B3, encoding="utf-8")
    out = b3_listados.ler_export(arq)
    assert list(out["TICKER"]) == ["JURO11", "KDIF11"]
    assert out.iloc[0]["RAZAO"].startswith("SPARTA INFRA")
    assert out.iloc[1]["PREGAO"] == "KINEA INFRAF"


def test_export_da_b3_aceita_latin1(tmp_path):
    """O arquivo sai do site em ISO-8859-1; o repositório guarda em UTF-8."""
    arq = tmp_path / "fiagro.csv"
    arq.write_bytes(("Razão Social;Fundo;Código\n"
                     "ITAÚ ASSET RURAL FIAGRO;FIAGRO RURA;RURA;\n"
                     ).encode("ISO-8859-1"))
    out = b3_listados.ler_export(arq)
    assert list(out["TICKER"]) == ["RURA11"]
    assert "ITAÚ" in out.iloc[0]["RAZAO"]


def test_codigo_do_isin_e_conferido_contra_a_lista_da_b3():
    """Primeira passada: comparação exata, sem heurística nenhuma.

    Quando o informe traz ISIN o código já está determinado, e o que falta é só
    saber se ele consta da lista de listados. Usar casamento de nome aqui seria
    trocar certeza por heurística — e no CRAA11 a heurística falhava, porque a
    CVM abrevia o nome dele para "SPARTA FIAGRO FUNDO DE I. NAS CADEIAS P. A.".
    """
    informe = pd.DataFrame({
        "CNPJ": ["48903610000121"],
        "NOME": ["SPARTA FIAGRO FUNDO DE I. NAS CADEIAS P. A. R. LIMITADA"],
        "ISIN": pd.array(["BRCRAACTF008"], dtype="string"),
        "NEGOCIA_BOLSA": pd.array(["N"], dtype="string"),
    })
    export = _export([{"CODIGO": "CRAA", "TICKER": "CRAA11", "PREGAO": "FIAGRO CRAA",
                       "RAZAO": "SPARTA FIAGRO FUNDO DE INVESTIMENTO NAS CADEIAS "
                                "PRODUTIVAS AGROINDUSTRIAIS - IMOB RESP LIMITADA"}])
    out, _ = b3_listados.aplicar_tickers(informe, export)
    assert out.iloc[0]["TICKER"] == "CRAA11"
    assert out.iloc[0]["ORIGEM_TICKER"] == "b3"


def test_estar_na_lista_da_b3_vence_o_campo_de_mercado_da_cvm():
    """O campo cadastral erra; a lista da bolsa não.

    O CRAA11 vem marcado como BALCAO no informe da CVM e está listado na B3.
    Sem esta regra ele era cortado por "não negociado em bolsa" e sumia da tela
    — que foi exatamente como ele sumiu.
    """
    informe = pd.DataFrame({
        "CNPJ": ["48903610000121", "99999999000199"],
        "NOME": ["SPARTA FIAGRO FUNDO DE I. NAS CADEIAS P. A.", "FUNDO FECHADO X"],
        "ISIN": pd.array(["BRCRAACTF008", "BRXXXXCTF001"], dtype="string"),
        "NEGOCIA_BOLSA": pd.array(["N", "N"], dtype="string"),
    })
    export = _export([{"CODIGO": "CRAA", "TICKER": "CRAA11", "PREGAO": "FIAGRO CRAA",
                       "RAZAO": "SPARTA FIAGRO FUNDO DE INVESTIMENTO NAS CADEIAS "
                                "PRODUTIVAS AGROINDUSTRIAIS"}])
    out, _ = b3_listados.aplicar_tickers(informe, export)
    bolsa = dict(zip(out["CNPJ"], out["NEGOCIA_BOLSA"]))
    assert bolsa["48903610000121"] == "S", "listado na B3 tem que negociar em bolsa"
    assert bolsa["99999999000199"] == "N", "quem não está na lista não é promovido"


def test_codigo_sai_do_nome_quando_nao_ha_isin():
    """Segunda passada: só para o que a primeira não resolveu.

    Onze dos 49 Fiagro listados não têm ISIN no informe — o RURA11 entre eles.
    """
    informe = pd.DataFrame({
        "CNPJ": ["11111111000191"],
        "NOME": ["ITAÚ ASSET RURAL FIAGRO RESPONSABILIDADE LIMITADA"],
        "ISIN": pd.array([None], dtype="string"),
        "NEGOCIA_BOLSA": pd.array(["N"], dtype="string"),
    })
    export = _export([{"CODIGO": "RURA", "TICKER": "RURA11", "PREGAO": "FIAGRO RURA",
                       "RAZAO": "ITAÚ ASSET RURAL FIAGRO RESP LIMITADA"}])
    out, _ = b3_listados.aplicar_tickers(informe, export)
    assert out.iloc[0]["TICKER"] == "RURA11"
    assert out.iloc[0]["NEGOCIA_BOLSA"] == "S"


def test_fundo_do_informe_fora_da_lista_da_b3_mantem_o_codigo_do_isin():
    """A lista da B3 é uma foto: um fundo recém-listado pode não estar nela.

    Apagar o código do ISIN nesse caso tiraria da tela um fundo que negocia. Ele
    fica, e se de fato não negociar cai no filtro de liquidez, com o motivo à
    vista na aba de excluídos.
    """
    informe = pd.DataFrame({
        "CNPJ": ["22222222000192"], "NOME": ["FUNDO NOVISSIMO FIAGRO"],
        "TICKER": pd.array(["NOVO11"], dtype="string"),
    })
    export = _export([{"CODIGO": "RURA", "TICKER": "RURA11", "PREGAO": "FIAGRO RURA",
                       "RAZAO": "ITAÚ ASSET RURAL FIAGRO"}])
    out, avisos = b3_listados.aplicar_tickers(informe, export)
    assert out.iloc[0]["TICKER"] == "NOVO11"
    assert any("não estão na lista da B3" in a for a in avisos)


# ---------------------------------------------------------------------------
# A lista de FI-Infra: sincronizar, resolver, conferir
# ---------------------------------------------------------------------------
def _lista(linhas) -> pd.DataFrame:
    return pd.DataFrame(linhas, columns=list(fiinfra.COLUNAS), dtype="string")


def _export(linhas) -> pd.DataFrame:
    return pd.DataFrame(linhas, columns=["CODIGO", "TICKER", "PREGAO", "RAZAO"],
                        dtype="string")


def test_lista_do_disco_ignora_comentario_e_normaliza_cnpj(tmp_path):
    arq = tmp_path / "fiinfra.csv"
    arq.write_text("# explicação\n# mais explicação\n"
                   "TICKER;RAZAO_B3;CNPJ;NOME_CVM;CONFERIDO_EM\n"
                   "juro11;SPARTA INFRA;42.730.834/0001-00;SPARTA;2026-09-07\n"
                   "CDII11;SPARTA INFRA CDI;;;\n"
                   "lixo;;;;\n", encoding="utf-8")
    out = fiinfra.ler_lista(arq)
    assert list(out["TICKER"]) == ["JURO11", "CDII11"]
    assert out.iloc[0]["CNPJ"] == "42730834000100"
    assert pd.isna(out.iloc[1]["CNPJ"])


def test_gravar_lista_preserva_o_cabecalho(tmp_path):
    """O arquivo explica a si mesmo; reescrevê-lo não pode apagar a explicação."""
    arq = tmp_path / "fiinfra.csv"
    arq.write_text("# por que este arquivo existe\n"
                   "TICKER;RAZAO_B3;CNPJ;NOME_CVM;CONFERIDO_EM\n"
                   "JURO11;SPARTA INFRA;;;\n", encoding="utf-8")
    df = fiinfra.ler_lista(arq)
    df.loc[0, "CNPJ"] = "42730834000100"
    fiinfra.gravar_lista(df, arq)
    texto = arq.read_text(encoding="utf-8")
    assert texto.startswith("# por que este arquivo existe")
    assert "JURO11;SPARTA INFRA;42730834000100" in texto


def test_sincronizar_mantem_o_conferido_e_acusa_o_que_mudou():
    lista = _lista([
        {"TICKER": "JURO11", "RAZAO_B3": "SPARTA INFRA FIC FI INFRA RENDA FIXA CP",
         "CNPJ": "42730834000100", "NOME_CVM": CVM_JURO, "CONFERIDO_EM": "2026-09-01"},
        {"TICKER": "VELHO11", "RAZAO_B3": "FUNDO QUE SAIU", "CNPJ": "11111111000191",
         "NOME_CVM": "X", "CONFERIDO_EM": "2026-01-01"},
        {"TICKER": "MUDOU11", "RAZAO_B3": "NOME ANTIGO DO FUNDO",
         "CNPJ": "22222222000192", "NOME_CVM": "Y", "CONFERIDO_EM": "2026-01-01"},
    ])
    export = _export([
        {"CODIGO": "JURO", "TICKER": "JURO11", "PREGAO": "SPARTA INFRA",
         "RAZAO": "SPARTA INFRA FIC FI INFRA RENDA FIXA CP"},
        {"CODIGO": "MUDO", "TICKER": "MUDOU11", "PREGAO": "X",
         "RAZAO": "NOME NOVO E DIFERENTE DO FUNDO"},
        {"CODIGO": "NOVO", "TICKER": "NOVO11", "PREGAO": "Y", "RAZAO": "FUNDO NOVO"},
    ])
    out, avisos = fiinfra.sincronizar(lista, export)
    por_ticker = out.set_index("TICKER")

    assert set(por_ticker.index) == {"JURO11", "MUDOU11", "NOVO11"}
    assert por_ticker.at["JURO11", "CNPJ"] == "42730834000100", "conferido não pode sumir"
    assert pd.isna(por_ticker.at["NOVO11", "CNPJ"])
    # Razão social diferente pode ser reescrita, mas pode ser incorporação:
    # manter o CNPJ antigo publicaria um fundo sob o código de outro.
    assert pd.isna(por_ticker.at["MUDOU11", "CNPJ"])
    texto = " | ".join(avisos)
    assert "NOVO11" in texto and "VELHO11" in texto and "MUDOU11" in texto


def test_sincronizar_com_export_vazio_nao_apaga_nada():
    lista = _lista([{"TICKER": "JURO11", "RAZAO_B3": "X", "CNPJ": "42730834000100",
                     "NOME_CVM": "Y", "CONFERIDO_EM": "2026-09-01"}])
    out, avisos = fiinfra.sincronizar(lista, _export([]))
    assert list(out["TICKER"]) == ["JURO11"]
    assert avisos


def test_resolver_grava_cnpj_e_relata_quem_ficou_em_duvida(tmp_path, monkeypatch):
    monkeypatch.setattr(fiinfra, "RELATORIO", tmp_path / "pendentes.txt")
    lista = _lista([
        {"TICKER": "JURO11", "RAZAO_B3": B3_JURO, "CNPJ": None,
         "NOME_CVM": None, "CONFERIDO_EM": None},
        {"TICKER": "XXXX11", "RAZAO_B3": "PADARIA DO ZE", "CNPJ": None,
         "NOME_CVM": None, "CONFERIDO_EM": None},
    ])
    out, avisos, relatorio = fiinfra.resolver(lista, REGISTRO)
    assert out.set_index("TICKER").at["JURO11", "CNPJ"] == "42730834000100"
    assert pd.isna(out.set_index("TICKER").at["XXXX11", "CNPJ"])
    assert any("XXXX11" in a for a in avisos)
    assert "XXXX11" in relatorio


def test_conferencia_exige_cadastro_situacao_e_razao_social():
    lista = _lista([
        {"TICKER": "JURO11", "RAZAO_B3": B3_JURO, "CNPJ": "42730834000100",
         "NOME_CVM": CVM_JURO, "CONFERIDO_EM": "2026-09-01"},
        {"TICKER": "MORT11", "RAZAO_B3": "X", "CNPJ": "77777777000197",
         "NOME_CVM": "FUNDO ENCERRADO DE INFRAESTRUTURA XYZ",
         "CONFERIDO_EM": "2025-01-01"},
        {"TICKER": "FANT11", "RAZAO_B3": "X", "CNPJ": "88888888000188",
         "NOME_CVM": "NAO EXISTE", "CONFERIDO_EM": "2025-01-01"},
        {"TICKER": "TROC11", "RAZAO_B3": "X", "CNPJ": "26324298000189",
         "NOME_CVM": "OUTRO NOME COMPLETAMENTE DIFERENTE DISSO AQUI",
         "CONFERIDO_EM": "2025-01-01"},
        {"TICKER": "VAZI11", "RAZAO_B3": "X", "CNPJ": None, "NOME_CVM": None,
         "CONFERIDO_EM": None},
    ])
    ok, avisos = fiinfra.conferir(lista, REGISTRO)

    assert list(ok["TICKER"]) == ["JURO11"]
    assert ok.iloc[0]["DT_FUNCIONAMENTO"] == pd.Timestamp("2021-05-02")
    texto = " | ".join(avisos)
    assert "MORT11" in texto and "CANCELADO" in texto
    assert "FANT11" in texto and "não está no cadastro" in texto
    assert "TROC11" in texto and "razão social" in texto
    assert "VAZI11" in texto and "sem CNPJ" in texto


def test_coletar_monta_o_informe_no_formato_do_pipeline(monkeypatch, tmp_path):
    arq = tmp_path / "fiinfra.csv"
    arq.write_text("TICKER;RAZAO_B3;CNPJ;NOME_CVM;CONFERIDO_EM\n", encoding="utf-8")
    exp = tmp_path / "b3.csv"
    exp.write_text("Razão Social;Fundo;Código\n"
                   f"{B3_JURO};SPARTA INFRA;JURO;\n", encoding="utf-8")
    monkeypatch.setattr(fiinfra, "RELATORIO", tmp_path / "pendentes.txt")
    monkeypatch.setattr(cvm_fii, "baixar_registro_classes", lambda **kw: REGISTRO)
    monkeypatch.setattr(cvm_fii, "_zip_informe_diario", lambda comp, **kw: _zip_diario(
        [_linha_diario("42730834000100", "2026-08-31", "100.28", "2062923000", "91766")]))

    out, avisos = fiinfra.coletar(usar_cache=False, caminho=arq, export=exp,
                                  competencias=1)
    assert len(out) == 1
    linha = out.iloc[0]
    assert linha["TICKER"] == "JURO11"
    assert linha["TIPO_FUNDO"] == C.TIPO_FIINFRA
    assert linha["NEGOCIA_BOLSA"] == "S"
    assert linha["VP_COTA"] == pytest.approx(100.28)
    # nº de cotas não vem no informe diário: sai de patrimônio / cota
    assert linha["COTAS"] == pytest.approx(2062923000 / 100.28)
    # o CNPJ resolvido fica gravado para as próximas execuções
    assert fiinfra.ler_lista(arq).iloc[0]["CNPJ"] == "42730834000100"


def test_coletar_avisa_e_omite_fundo_sem_informe_diario(monkeypatch, tmp_path):
    """Fundo que sumiu do informe diário não pode ficar na tela com dado velho."""
    arq = tmp_path / "fiinfra.csv"
    arq.write_text("TICKER;RAZAO_B3;CNPJ;NOME_CVM;CONFERIDO_EM\n"
                   f"JURO11;{B3_JURO};42730834000100;{CVM_JURO};2026-09-01\n",
                   encoding="utf-8")
    exp = tmp_path / "b3.csv"
    exp.write_text(f"Razão Social;Fundo;Código\n{B3_JURO};SPARTA INFRA;JURO;\n",
                   encoding="utf-8")
    monkeypatch.setattr(fiinfra, "RELATORIO", tmp_path / "pendentes.txt")
    monkeypatch.setattr(cvm_fii, "baixar_registro_classes", lambda **kw: REGISTRO)
    monkeypatch.setattr(cvm_fii, "_zip_informe_diario",
                        lambda comp, **kw: _zip_diario([]))
    out, avisos = fiinfra.coletar(usar_cache=False, caminho=arq, export=exp,
                                  competencias=1)
    assert out.empty
    assert any("JURO11" in a and "informe diário" in a for a in avisos)


def test_arquivos_versionados_passam_pelos_proprios_leitores():
    """O que vai para o Git tem que ser legível por quem vai lê-lo."""
    lista = fiinfra.ler_lista()
    assert list(lista.columns) == list(fiinfra.COLUNAS)
    for caminho in (b3_listados.EXPORT_FIAGRO, b3_listados.EXPORT_FIINFRA):
        export = b3_listados.ler_export(caminho)
        assert len(export) > 20, f"{caminho.name} veio quase vazio"
        assert export["TICKER"].str.fullmatch(r"[A-Z]{4}11").all()
        assert export["TICKER"].is_unique


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


def test_pvp_absurdo_em_fiinfra_derruba_o_fundo():
    """A conferência independente do casamento de nomes.

    O FI-Infra é o único veículo cuja identidade é inferida, e um casamento
    errado não deixa rastro no dado — publica o patrimônio de um fundo sob o
    código de outro. Como FI-Infra carrega debênture marcada a mercado, o preço
    anda colado no valor patrimonial: um P/VP de 50 não é oportunidade, é o
    VP/cota de um fundo master (R$ 1,55) sob o código de um fundo que negocia a
    R$ 100. A faixa é larga porque existe para pegar ordem de grandeza.
    """
    df = _tabela_minima([
        {"TICKER": "BOM111", "TIPO_FUNDO": C.TIPO_FIINFRA, "PRECO": 100.0,
         "VP_COTA": 99.0, "P_VP": 100.0 / 99.0},
        {"TICKER": "RUIM11", "TIPO_FUNDO": C.TIPO_FIINFRA, "PRECO": 100.0,
         "VP_COTA": 1.55, "P_VP": 100.0 / 1.55},
        # O mesmo P/VP num FII é desconto, não defeito: laudo anual contra preço.
        {"TICKER": "DESC11", "TIPO_FUNDO": C.TIPO_FII, "PRECO": 60.0,
         "VP_COTA": 100.0, "P_VP": 0.60},
    ])
    elegiveis, excluidos = indicadores.filtrar(df, ParamsFII(
        liquidez_minima_diaria=0, patrimonio_minimo=0, cotistas_minimo=0))
    assert set(elegiveis["TICKER"]) == {"BOM111", "DESC11"}
    assert list(excluidos["TICKER"]) == ["RUIM11"]
    assert "outro fundo" in excluidos.iloc[0]["MOTIVO_EXCLUSAO"]
