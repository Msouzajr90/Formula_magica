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
