"""Testes da camada de ingestão da CVM (sem rede — DataFrames sintéticos)."""
from __future__ import annotations

import pandas as pd
import pytest

from magicb3 import config as C
from magicb3.cvm import _normalizar, balanco_mais_recente, ebit_ltm


def _linha(cd_cvm, dt_refer, cd_conta, valor, *, escala="MIL", ordem="ÚLTIMO",
           versao=1, dt_ini=None, dt_fim=None):
    return {
        "CNPJ_CIA": "00.000.000/0001-00", "DT_REFER": dt_refer, "VERSAO": versao,
        "DENOM_CIA": f"CIA {cd_cvm}", "CD_CVM": cd_cvm, "ESCALA_MOEDA": escala,
        "ORDEM_EXERC": ordem, "DT_INI_EXERC": dt_ini, "DT_FIM_EXERC": dt_fim,
        "CD_CONTA": cd_conta, "DS_CONTA": "x", "VL_CONTA": valor,
    }


def test_normaliza_escala_monetaria():
    """O bug mais silencioso do script original: DRE em MIL e BP em UNIDADE
    davam um ROIC mil vezes maior ou menor do que o real."""
    df = pd.DataFrame([
        _linha(1, "2024-12-31", "3.05", 1_000, escala="MIL"),
        _linha(2, "2024-12-31", "3.05", 1_000_000, escala="UNIDADE"),
    ])
    out = _normalizar(df)
    assert out.set_index("CD_CVM").loc[1, "VL_CONTA"] == 1_000_000
    assert out.set_index("CD_CVM").loc[2, "VL_CONTA"] == 1_000_000


def test_descarta_penultimo_exercicio():
    df = pd.DataFrame([
        _linha(1, "2024-12-31", "3.05", 100, ordem="ÚLTIMO"),
        _linha(1, "2024-12-31", "3.05", 999, ordem="PENÚLTIMO"),
    ])
    out = _normalizar(df)
    assert len(out) == 1 and out.iloc[0]["VL_CONTA"] == 100_000


def test_mantem_apenas_versao_mais_recente():
    """Refazimentos (versão 2, 3...) conviviam com a versão 1 no script antigo
    e duplicavam a empresa no ranking."""
    df = pd.DataFrame([
        _linha(1, "2024-12-31", "3.05", 100, versao=1),
        _linha(1, "2024-12-31", "3.05", 150, versao=3),
    ])
    out = _normalizar(df)
    assert len(out) == 1 and out.iloc[0]["VL_CONTA"] == 150_000


def test_ebit_ltm_sem_itr_usa_o_anual():
    dfp = _normalizar(pd.DataFrame([
        _linha(1, "2023-12-31", "3.05", 800),
        _linha(1, "2024-12-31", "3.05", 1_000),
    ]))
    out = ebit_ltm(dfp, pd.DataFrame(), "3.05").set_index("CD_CVM")
    assert out.loc[1, "EBIT_LTM"] == 1_000_000
    assert out.loc[1, "FONTE"] == "DFP"


def test_ebit_ltm_combina_dfp_e_itr():
    """LTM = ano fechado - acumulado do mesmo período do ano anterior
             + acumulado do período corrente."""
    dfp = _normalizar(pd.DataFrame([_linha(1, "2024-12-31", "3.05", 1_000)]))
    itr = _normalizar(pd.DataFrame([
        _linha(1, "2024-06-30", "3.05", 400, dt_ini="2024-01-01", dt_fim="2024-06-30"),
        _linha(1, "2025-06-30", "3.05", 500, dt_ini="2025-01-01", dt_fim="2025-06-30"),
        # linha trimestral isolada, que deve ser ignorada
        _linha(1, "2025-06-30", "3.05", 260, dt_ini="2025-04-01", dt_fim="2025-06-30"),
    ]))
    out = ebit_ltm(dfp, itr, "3.05").set_index("CD_CVM")
    assert out.loc[1, "EBIT_LTM"] == pytest.approx((1_000 - 400 + 500) * 1_000)
    assert out.loc[1, "FONTE"] == "DFP+ITR (LTM)"
    assert out.loc[1, "DT_BASE"] == pd.Timestamp("2025-06-30")


def test_balanco_pega_a_data_mais_recente_por_empresa():
    bpa = _normalizar(pd.DataFrame([
        _linha(1, "2024-12-31", C.CD_ATIVO_CIRCULANTE, 100),
        _linha(1, "2025-06-30", C.CD_ATIVO_CIRCULANTE, 130),
        _linha(2, "2024-12-31", C.CD_ATIVO_CIRCULANTE, 50),
    ]))
    bpp = _normalizar(pd.DataFrame([
        _linha(1, "2025-06-30", C.CD_PASSIVO_CIRCULANTE, 60),
        _linha(2, "2024-12-31", C.CD_PASSIVO_CIRCULANTE, 20),
    ]))
    out = balanco_mais_recente(bpa, bpp, [C.CD_ATIVO_CIRCULANTE, C.CD_PASSIVO_CIRCULANTE])
    out = out.set_index("CD_CVM")
    assert out.loc[1, C.CD_ATIVO_CIRCULANTE] == 130_000
    assert out.loc[1, "DT_BP"] == pd.Timestamp("2025-06-30")
    assert out.loc[2, C.CD_ATIVO_CIRCULANTE] == 50_000


# ---------------------------------------------------------------------------
# Leitura em blocos com filtro de contas (caminho de baixo consumo de memória)
# ---------------------------------------------------------------------------
def _zip_sintetico(linhas: list[str], nome: str) -> "zipfile.ZipFile":
    import io, zipfile
    cab = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;"
           "ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(nome, ("\n".join([cab] + linhas)).encode("ISO-8859-1"))
    buf.seek(0)
    return zipfile.ZipFile(buf)


def _csv(cd_cvm, conta, valor, ordem="ÚLTIMO"):
    return (f"00.000.000/0001-00;2024-12-31;1;CIA;{cd_cvm};DF Consolidado;REAL;MIL;"
            f"{ordem};2024-01-01;2024-12-31;{conta};desc;{valor};S")


def test_leitura_em_blocos_filtra_contas_e_exercicio():
    from magicb3.cvm import _ler_membro
    linhas = [_csv(1, "3.05", 100), _csv(1, "3.01", 999),
              _csv(1, "3.05", 555, ordem="PENÚLTIMO"), _csv(2, "3.05", 200)]
    zf = _zip_sintetico(linhas, "dfp_cia_aberta_DRE_con_2024.csv")
    out = _ler_membro(zf, "dfp_cia_aberta_DRE_con_2024.csv",
                      contas={"3.05"}, chunk=2)     # chunk pequeno força vários blocos
    assert set(out["CD_CONTA"]) == {"3.05"}          # 3.01 descartado na leitura
    assert len(out) == 2                             # PENÚLTIMO descartado
    assert sorted(out["VL_CONTA"]) == [100, 200]


def test_leitura_em_blocos_sem_filtro_traz_tudo():
    from magicb3.cvm import _ler_membro
    zf = _zip_sintetico([_csv(1, "3.05", 100), _csv(1, "3.01", 999)],
                        "dfp_cia_aberta_DRE_con_2024.csv")
    out = _ler_membro(zf, "dfp_cia_aberta_DRE_con_2024.csv", None, chunk=1)
    assert len(out) == 2


def test_acha_membro_com_nome_alternativo():
    from magicb3.cvm import _achar_membro
    zf = _zip_sintetico([_csv(1, "3.05", 1)], "DFP_CIA_ABERTA_DRE_CON_2024.CSV")
    assert _achar_membro(zf, "dfp", "DRE", "con", 2024) == "DFP_CIA_ABERTA_DRE_CON_2024.CSV"
    assert _achar_membro(zf, "dfp", "BPA", "con", 2024) is None


# ---------------------------------------------------------------------------
# Arquivo de fundamentos (ponte Brasil -> nuvem)
# ---------------------------------------------------------------------------
def test_fundamentos_ida_e_volta(tmp_path):
    """Exportar e reimportar tem que devolver exatamente os mesmos números."""
    from magicb3 import arquivo_fundamentos as arqf
    from magicb3.cvm import balanco_mais_recente, ebit_ltm

    dfp = _normalizar(pd.DataFrame([
        _linha(1, "2024-12-31", "3.05", 1_000),
        _linha(2, "2024-12-31", "3.05", 250),
    ]))
    itr = _normalizar(pd.DataFrame([
        _linha(1, "2024-06-30", "3.05", 400, dt_ini="2024-01-01", dt_fim="2024-06-30"),
        _linha(1, "2025-06-30", "3.05", 500, dt_ini="2025-01-01", dt_fim="2025-06-30"),
    ]))
    bpa = _normalizar(pd.DataFrame([
        _linha(1, "2025-06-30", C.CD_ATIVO_CIRCULANTE, 2_000),
        _linha(1, "2025-06-30", C.CD_CAIXA, 300),
        _linha(1, "2025-06-30", C.CD_IMOBILIZADO, 1_200),
        _linha(2, "2024-12-31", C.CD_ATIVO_CIRCULANTE, 900),
    ]))
    bpp = _normalizar(pd.DataFrame([
        _linha(1, "2025-06-30", C.CD_PASSIVO_CIRCULANTE, 900),
        _linha(1, "2025-06-30", C.CD_EMPRESTIMOS_CP, 200),
        _linha(1, "2025-06-30", C.CD_EMPRESTIMOS_LP, 800),
        _linha(2, "2024-12-31", C.CD_PASSIVO_CIRCULANTE, 400),
    ]))

    contas = list(arqf.CONTAS.values())
    ebit = ebit_ltm(dfp, itr, "3.05")
    bp = balanco_mais_recente(bpa, bpp, contas)
    setores = pd.DataFrame({"CD_CVM": [1, 2], "SETOR": ["Comércio", "Bancos"]})

    destino = tmp_path / "fundamentos.json"
    saida = arqf.exportar(ebit, bp, setores, destino, anos=[2024, 2025])
    assert destino.exists() and len(saida["empresas"]) == 2

    ebit2, bp2, setores2 = arqf.importar(destino)

    # EBIT LTM = 1000 - 400 + 500 = 1100 (mil) -> 1.100.000
    e1 = ebit2.set_index("CD_CVM")
    assert e1.loc[1, "EBIT_LTM"] == pytest.approx(1_100_000)
    assert e1.loc[1, "FONTE"] == "DFP+ITR (LTM)"
    assert e1.loc[2, "EBIT_LTM"] == pytest.approx(250_000)

    b1 = bp2.set_index("CD_CVM")
    assert b1.loc[1, C.CD_ATIVO_CIRCULANTE] == pytest.approx(2_000_000)
    assert b1.loc[1, C.CD_EMPRESTIMOS_LP] == pytest.approx(800_000)
    assert set(setores2["SETOR"]) == {"Comércio", "Bancos"}

    # e os indicadores calculados em cima disso batem com o caminho direto
    from magicb3 import fundamentals
    ct = fundamentals.capital_tangivel(b1.loc[[1]])
    # giro = (2000 - 300 - 0) - (900 - 200) = 1000 ; + imob 1200 = 2200 (mil)
    assert float(ct.iloc[0]) == pytest.approx(2_200_000)


def test_fundamentos_arquivo_ausente_da_mensagem_util(tmp_path):
    from magicb3 import arquivo_fundamentos as arqf
    with pytest.raises(FileNotFoundError, match="baixar_fundamentos"):
        arqf.importar(tmp_path / "nao_existe.json")


def test_leitura_em_blocos_seguida_de_normalizacao():
    """Regressão: ESCALA_MOEDA vinha como 'category' da leitura em blocos e
    quebrava a multiplicação pelo fator de escala. Só apareceu com dado real,
    porque os testes exercitavam os dois passos separadamente."""
    from magicb3.cvm import _ler_membro, _normalizar
    linhas = [_csv(1, "3.05", 100), _csv(2, "3.05", 200)]
    linhas.append("00.000.000/0001-00;2024-12-31;1;CIA;3;DF Consolidado;REAL;"
                  "UNIDADE;ÚLTIMO;2024-01-01;2024-12-31;3.05;desc;300000;S")
    zf = _zip_sintetico(linhas, "dfp_cia_aberta_DRE_con_2024.csv")
    bruto = _ler_membro(zf, "dfp_cia_aberta_DRE_con_2024.csv", contas={"3.05"}, chunk=2)
    out = _normalizar(bruto).set_index("CD_CVM")
    assert out.loc[1, "VL_CONTA"] == 100_000        # MIL -> reais
    assert out.loc[3, "VL_CONTA"] == 300_000        # UNIDADE -> inalterado
    assert out["VL_CONTA"].dtype.kind == "f"


# ---------------------------------------------------------------------------
# Composição do capital — detecção da escala do nº de ações
# ---------------------------------------------------------------------------
def _zip_com_capital(tmp_path, linhas_cap, linhas_dre):
    """Monta um zip DFP com composicao_capital e DRE, como o da CVM."""
    import zipfile
    cab_cap = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;QT_ACAO_ORDIN_CAP_INTEGR;"
               "QT_ACAO_PREF_CAP_INTEGR;QT_ACAO_TOTAL_CAP_INTEGR;"
               "QT_ACAO_ORDIN_TESOURO;QT_ACAO_PREF_TESOURO;QT_ACAO_TOTAL_TESOURO")
    cab_dre = ("CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;"
               "ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA")
    destino = tmp_path / "dfp_cia_aberta_2025.zip"
    with zipfile.ZipFile(destino, "w") as z:
        z.writestr("dfp_cia_aberta_composicao_capital_2025.csv",
                   ("\n".join([cab_cap] + linhas_cap)).encode("ISO-8859-1"))
        z.writestr("dfp_cia_aberta_DRE_con_2025.csv",
                   ("\n".join([cab_dre] + linhas_dre)).encode("ISO-8859-1"))
    return tmp_path


def test_composicao_capital_corrige_escala_em_milhares(tmp_path):
    """A CVM publica o nº de ações sem coluna de escala: umas empresas informam
    em unidades e outras em milhares. Confirmado no DFP 2025 — Petrobras em
    unidades, Ambev em milhares. Sem corrigir, o valor de mercado sai 1.000
    vezes menor e o ranking de Earnings Yield vira outra coisa."""
    from magicb3 import cvm

    def cap(cnpj, nome, on, pn):
        return f"{cnpj};2025-12-31;1;{nome};{on};{pn};{on + pn};0;0;0"

    def dre(cnpj, cd_cvm, conta, valor):
        return (f"{cnpj};2025-12-31;1;CIA;{cd_cvm};DF Consolidado;REAL;MIL;"
                f"ÚLTIMO;2025-01-01;2025-12-31;{conta};d;{valor};S")

    # UNIDADES: 2 bi de ações, lucro 4 bi (em mil), LPA R$ 2,00 -> 2 bi implícito
    # MILHARES: 16 mil (= 16 mi), lucro 32.000 mil, LPA R$ 2,00 -> 16 mi implícito
    pasta = _zip_com_capital(
        tmp_path,
        [cap("11.111.111/0001-11", "EM UNIDADES", 2_000_000_000, 0),
         cap("22.222.222/0001-22", "EM MILHARES", 16_000, 0)],
        [dre("11.111.111/0001-11", 1, "3.11", 4_000_000),      # R$ 4 bi
         dre("11.111.111/0001-11", 1, "3.99.01.01", 2.0),      # LPA R$ 2,00
         dre("22.222.222/0001-22", 2, "3.11", 32_000),         # R$ 32 mi
         dre("22.222.222/0001-22", 2, "3.99.01.01", 2.0)],     # LPA R$ 2,00
    )

    out = cvm.composicao_capital([2025], pasta_zips=pasta).set_index("CNPJ_CIA")
    unid = out.loc["11.111.111/0001-11"]
    milh = out.loc["22.222.222/0001-22"]

    assert bool(unid["ESCALA_CONFIRMADA"]) and bool(milh["ESCALA_CONFIRMADA"])
    assert unid["ACOES"] == pytest.approx(2e9)          # mantida
    assert milh["ACOES"] == pytest.approx(16e6)         # 16.000 x 1.000
    assert milh["ACOES_BRUTO"] == pytest.approx(16e3)   # o cru continua registrado


def test_composicao_capital_sem_lpa_nao_chuta(tmp_path):
    """Sem como confirmar a escala, é melhor devolver nulo do que um número
    que pode estar mil vezes errado."""
    from magicb3 import cvm
    pasta = _zip_com_capital(
        tmp_path,
        ["33.333.333/0001-33;2025-12-31;1;SEM LPA;5000;0;5000;0;0;0"],
        ["33.333.333/0001-33;2025-12-31;1;CIA;3;DF Consolidado;REAL;MIL;"
         "ÚLTIMO;2025-01-01;2025-12-31;3.11;d;1000;S"],
    )
    out = cvm.composicao_capital([2025], pasta_zips=pasta).set_index("CNPJ_CIA")
    linha = out.loc["33.333.333/0001-33"]
    assert not bool(linha["ESCALA_CONFIRMADA"])
    assert pd.isna(linha["ACOES"])
    assert linha["ACOES_BRUTO"] == pytest.approx(5000)
