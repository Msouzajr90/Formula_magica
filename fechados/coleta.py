"""Lê FII, Fiagro e FIP e devolve uma tabela só, no formato longo.

Formato longo quer dizer uma linha por fundo **e por competência** — e não uma
linha por fundo. É o que permite calcular rentabilidade acumulada, amortização
do período e variação do número de cotistas sem baixar nada duas vezes.
`indicadores.consolidar` reduz isso a uma linha por fundo no fim.

As três fontes não são simétricas, e a tabela registra a assimetria em vez de
escondê-la:

| | FII | Fiagro | FIP |
|---|---|---|---|
| periodicidade | mensal | mensal | quadrimestral |
| prazo de duração | `Prazo_Duracao`, limpo | rótulo inútil | **não publica** |
| data de vencimento | `Data_Prazo_Duracao` | não tem | não tem |
| nº de cotistas | `Total_Numero_Cotistas` | `Numero_Cotistas` | `NR_TOTAL_COTST_SUBSCR` |
| valor da cota | `Valor_Patrimonial_Cotas` | `Valor_Patrimonial_Cotas` | `VL_QUOTA_CLASSE` |
| rentabilidade | `Percentual_Rentabilidade_Efetiva_Mes` | idem | **não publica** |

No FIP, `NR_COTST`, `QT_COTA` e `VL_PATRIM_COTA` existem e vêm **vazias** —
as três colunas de nome mais óbvio são justamente as que não servem. Medido no
`inf_quadrimestral_fip_2026.csv`: 0,0% preenchidas, contra 95,4% de
`NR_TOTAL_COTST_SUBSCR` e 94,5% de `VL_QUOTA_CLASSE`.
"""
from __future__ import annotations

import io
import logging
import zipfile

import pandas as pd

from fiib3 import cvm_fii
from . import config as C

log = logging.getLogger(__name__)

# Esquema comum. Coluna que a fonte não tem entra vazia, e não some — o resto
# do pipeline conta com ela existindo.
ESQUEMA = ("CNPJ", "NOME", "TIPO", "DATA", "PL", "VP_COTA", "COTAS",
           "COTISTAS", "COTISTAS_PF", "RENT_MES", "DY_MES", "AMORT_MES",
           "TAXA_ADM", "PUBLICO", "EXCLUSIVO", "BOLSA", "CETIP", "MBO",
           "ROTULO_PRAZO", "DT_VENCIMENTO", "DT_INICIO", "ADMINISTRADOR",
           "SEGMENTO")


def _vazio() -> pd.DataFrame:
    return pd.DataFrame(columns=list(ESQUEMA))


def _pegar(df: pd.DataFrame, *padroes, numero=False, data=False):
    """Coluna localizada com tolerância; ausente vira série vazia, não erro."""
    c = cvm_fii.coluna(df, *padroes, obrigatoria=False)
    if c is None:
        return pd.Series([pd.NA] * len(df), index=df.index)
    if numero:
        return cvm_fii._numero(df[c])
    if data:
        return pd.to_datetime(df[c], errors="coerce")
    return df[c].astype("string").str.strip()


def _sn(serie: pd.Series) -> pd.Series:
    """Normaliza S/N para booleano, deixando o desconhecido como nulo."""
    s = serie.astype("string").str.strip().str.upper()
    return s.map({"S": True, "N": False, "SIM": True, "NAO": False})


def _rotulo_de_prazo(serie: pd.Series) -> pd.Series:
    """Só deixa passar 'Determinado'/'Indeterminado'; o resto vira nulo.

    É aqui que o `"1000 ANO/ANOS"` do Fiagro morre. Sem este filtro ele viraria
    um rótulo qualquer e, pior, poderia ser lido como prazo determinado por
    alguma heurística adiante.
    """
    s = serie.astype("string").str.strip()
    invalidos = {v.upper() for v in C.ROTULOS_DE_PRAZO_INVALIDOS}
    limpo = s.where(~s.str.upper().isin(invalidos), pd.NA)
    return limpo.where(limpo.str.lower().isin(["determinado", "indeterminado"]),
                       pd.NA).str.capitalize()


# ---------------------------------------------------------------------------
# FII
# ---------------------------------------------------------------------------
def ler_fii(ano: int, *, usar_cache: bool = True,
            meses: int = 12) -> pd.DataFrame:
    """Informe mensal de FII: `geral` e `complemento` na mesma linha.

    As duas tabelas precisam ser juntadas por CNPJ **e competência**: prazo,
    público e datas estão no `geral`; cotistas, patrimônio, rentabilidade e
    amortização estão no `complemento`. Juntar só por CNPJ misturaria a
    competência de uma com a da outra.
    """
    zf = cvm_fii.baixar_informe_mensal(ano, usar_cache=usar_cache)
    geral = cvm_fii._concatenar(zf, "geral", meses)
    compl = cvm_fii._concatenar(zf, "complemento", meses)
    if geral.empty:
        raise RuntimeError(
            f"O zip de FII de {ano} não trouxe tabela 'geral'. "
            f"Conteúdo: {zf.namelist()[:8]}")
    return montar_fii(geral, compl)


def montar_fii(geral: pd.DataFrame, compl: pd.DataFrame) -> pd.DataFrame:
    """A parte de `ler_fii` que não toca a rede — é o que os testes exercitam."""
    g = pd.DataFrame({
        "CNPJ": cvm_fii._cnpj_limpo(_pegar(geral, "cnpj_fundo_classe", "cnpj")),
        "DATA": _pegar(geral, "data_referencia", data=True),
        "NOME": _pegar(geral, "nome_fundo_classe", "denominacao_social"),
        "DT_INICIO": _pegar(geral, "data_funcionamento", data=True),
        "PUBLICO": _pegar(geral, "publico_alvo"),
        "EXCLUSIVO": _sn(_pegar(geral, "fundo_exclusivo")),
        "BOLSA": _sn(_pegar(geral, "mercado_negociacao_bolsa")),
        "MBO": _sn(_pegar(geral, "mercado_negociacao_mbo")),
        "CETIP": _sn(_pegar(geral, "entidade_administradora_cetip")),
        "ROTULO_PRAZO": _rotulo_de_prazo(_pegar(geral, "prazo_duracao")),
        "DT_VENCIMENTO": _pegar(geral, "data_prazo_duracao", data=True),
        "ADMINISTRADOR": _pegar(geral, "nome_administrador"),
        "SEGMENTO": _pegar(geral, "segmento_atuacao"),
        "COTAS": _pegar(geral, "quantidade_cotas_emitidas", numero=True),
    })

    c = pd.DataFrame({
        "CNPJ": cvm_fii._cnpj_limpo(_pegar(compl, "cnpj_fundo_classe", "cnpj")),
        "DATA": _pegar(compl, "data_referencia", data=True),
        "COTISTAS": _pegar(compl, "total_numero_cotistas", numero=True),
        "COTISTAS_PF": _pegar(compl, "numero_cotistas_pessoa_fisica", numero=True),
        "PL": _pegar(compl, "patrimonio_liquido", numero=True),
        "VP_COTA": _pegar(compl, "valor_patrimonial_cotas", numero=True),
        "RENT_MES": _pegar(compl, "percentual_rentabilidade_efetiva_mes",
                           numero=True),
        "DY_MES": _pegar(compl, "percentual_dividend_yield_mes", numero=True),
        "AMORT_MES": _pegar(compl, "percentual_amortizacao_cotas_mes",
                            numero=True),
        "TAXA_ADM": _pegar(compl, "percentual_despesas_taxa_administracao",
                           numero=True),
    }) if not compl.empty else pd.DataFrame(columns=["CNPJ", "DATA"])

    out = g.merge(c, on=["CNPJ", "DATA"], how="left")
    out["TIPO"] = C.TIPO_FII
    log.info("FII: %d linhas, %d fundos, competências %s a %s.", len(out),
             out["CNPJ"].nunique(), out["DATA"].min(), out["DATA"].max())
    return _normalizar(out)


# ---------------------------------------------------------------------------
# Fiagro
# ---------------------------------------------------------------------------
def ler_fiagro(*, competencias: int = 6,
               usar_cache: bool = True) -> pd.DataFrame:
    """Informe mensal de Fiagro, empilhando várias competências.

    Ler uma competência só é arriscado: a de 08/2026 saiu com **9 fundos**,
    contra 289 na de 07/2026. Competência publicada pela metade é acidente
    recorrente da CVM, e empilhar é o que protege — `_ultimo_por_fundo` depois
    fica com a linha mais recente de cada um.
    """
    partes = []
    hoje = pd.Timestamp.today()
    for i in range(1, competencias + 1):
        comp = (hoje - pd.DateOffset(months=i)).strftime("%Y%m")
        try:
            zf = cvm_fii.baixar_informe_fiagro(comp, usar_cache=usar_cache)
        except Exception as exc:                                   # noqa: BLE001
            log.info("Fiagro %s indisponível (%s).", comp, str(exc)[:70])
            continue
        nomes = [n for n in zf.namelist()
                 if n.lower().endswith(".csv") and "subclasse" not in n.lower()]
        for nome in nomes:
            df = cvm_fii._ler_csv(zf, nome)
            if not df.empty:
                partes.append(df)
    if not partes:
        log.warning("Nenhuma competência de Fiagro pôde ser lida.")
        return _vazio()
    return montar_fiagro(pd.concat(partes, ignore_index=True))


def montar_fiagro(bruto: pd.DataFrame) -> pd.DataFrame:
    """A parte de `ler_fiagro` que não toca a rede."""
    if bruto.empty:
        return _vazio()
    out = pd.DataFrame({
        "CNPJ": cvm_fii._cnpj_limpo(_pegar(bruto, "cnpj_classe", "cnpj")),
        "DATA": _pegar(bruto, "data_referencia", data=True),
        "NOME": _pegar(bruto, "nome_classe", "denominacao_social"),
        "DT_INICIO": _pegar(bruto, "data_registro", data=True),
        "PUBLICO": _pegar(bruto, "publico_alvo"),
        "COTISTAS": _pegar(bruto, "numero_cotistas", numero=True),
        "COTISTAS_PF": _pegar(bruto, "numero_cotistas_pessoa_natural",
                              numero=True),
        "PL": _pegar(bruto, "patrimonio_liquido", numero=True),
        "VP_COTA": _pegar(bruto, "valor_patrimonial_cotas", numero=True),
        "COTAS": _pegar(bruto, "cotas_emitidas", numero=True),
        "RENT_MES": _pegar(bruto, "rentabilidade_efetiva_mes", numero=True),
        "DY_MES": _pegar(bruto, "dividend_yield_mes", numero=True),
        "AMORT_MES": _pegar(bruto, "percentual_amortizacao_cotas_mes",
                            numero=True),
        "TAXA_ADM": _pegar(bruto, "percentual_despesas_taxa_administracao",
                           numero=True),
        "ADMINISTRADOR": _pegar(bruto, "nome_administrador"),
        # O rótulo do Fiagro é descartado aqui dentro (ver `_rotulo_de_prazo`):
        # "1000 ANO/ANOS" não é prazo.
        "ROTULO_PRAZO": _rotulo_de_prazo(_pegar(bruto, "prazo_duracao")),
    })
    mercado = _pegar(bruto, "mercado_negociacao").str.upper()
    out["BOLSA"] = mercado.str.contains("BOLSA", na=False)
    out["MBO"] = mercado.eq("BALCAO")
    out["CETIP"] = mercado.str.contains("BALCAO", na=False)
    out["TIPO"] = C.TIPO_FIAGRO
    log.info("Fiagro: %d linhas, %d fundos.", len(out), out["CNPJ"].nunique())
    return _normalizar(out)


# ---------------------------------------------------------------------------
# FIP
# ---------------------------------------------------------------------------
def ler_fip(ano: int, *, usar_cache: bool = True) -> pd.DataFrame:
    """Informe quadrimestral de FIP.

    O informe trimestral existe de 2010 a 2023 e parou ali; de 2024 em diante o
    arquivo é quadrimestral, em dataset separado. Não há coluna de prazo,
    vencimento, rentabilidade ou amortização — das 55 colunas, a única data é a
    da competência. O que sobra é patrimônio, capital comprometido e
    integralizado, cotistas subscritores e valor da cota por classe.

    Uma nota sobre as classes: o arquivo traz uma linha por classe de cota, e
    fundo com classes A e B aparece duas vezes na mesma competência. Fica a
    classe de maior número de cotistas — que é a que o varejo compra.
    """
    url = (C.INF_QUADRIMESTRAL_FIP if ano > C.ANO_ULTIMO_TRIMESTRAL_FIP
           else C.INF_TRIMESTRAL_FIP).format(ano=ano)
    nome = url.rsplit("/", 1)[-1]
    arq = cvm_fii._cache(nome)
    if usar_cache and arq.exists() and arq.stat().st_size > 1024:
        conteudo = arq.read_bytes()
    else:
        conteudo = cvm_fii._baixar(url, timeout=900)
        if usar_cache:
            arq.write_bytes(conteudo)
    if conteudo[:2] == b"PK":
        zf = zipfile.ZipFile(io.BytesIO(conteudo))
        csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        bruto = pd.concat([cvm_fii._ler_csv(zf, n) for n in csvs],
                          ignore_index=True)
    else:
        bruto = pd.read_csv(io.BytesIO(conteudo), sep=";",
                            encoding="ISO-8859-1", dtype="string",
                            low_memory=False)
    return montar_fip(bruto)


def montar_fip(bruto: pd.DataFrame) -> pd.DataFrame:
    """A parte do `ler_fip` que não toca a rede — é o que os testes exercitam."""
    if bruto.empty:
        return _vazio()
    out = pd.DataFrame({
        "CNPJ": cvm_fii._cnpj_limpo(_pegar(bruto, "cnpj_fundo_classe",
                                           "cnpj_fundo", "cnpj")),
        "DATA": _pegar(bruto, "dt_comptc", "data_referencia", data=True),
        "NOME": _pegar(bruto, "denom_social", "nome"),
        "PUBLICO": _pegar(bruto, "publico_alvo"),
        "PL": _pegar(bruto, "vl_patrim_liq", numero=True),
        # As três armadilhas do FIP, documentadas na tabela do topo: aqui vão
        # de propósito as colunas "erradas", que são as que têm conteúdo.
        "COTISTAS": _pegar(bruto, "nr_total_cotst_subscr", numero=True),
        "COTISTAS_PF": _pegar(bruto, "nr_cotst_subscr_pf", numero=True),
        "VP_COTA": _pegar(bruto, "vl_quota_classe", numero=True),
        "COTAS": _pegar(bruto, "qt_cota_integr_classe", "qt_cota_integr",
                        numero=True),
    })
    out["TIPO"] = C.TIPO_FIP
    # FIP não negocia em bolsa nem tem registro de mercado no informe.
    for coluna in ("BOLSA", "MBO", "CETIP", "EXCLUSIVO"):
        out[coluna] = pd.NA
    for coluna in ("ROTULO_PRAZO", "DT_VENCIMENTO", "DT_INICIO", "RENT_MES",
                   "DY_MES", "AMORT_MES", "TAXA_ADM", "ADMINISTRADOR",
                   "SEGMENTO"):
        out[coluna] = pd.NA

    # Uma linha por fundo e competência: fica a classe com mais cotistas.
    out = (out.sort_values(["CNPJ", "DATA", "COTISTAS"])
              .drop_duplicates(subset=["CNPJ", "DATA"], keep="last"))
    log.info("FIP: %d linhas, %d fundos.", len(out), out["CNPJ"].nunique())
    return _normalizar(out)


# ---------------------------------------------------------------------------
def _normalizar(df: pd.DataFrame) -> pd.DataFrame:
    """Garante o esquema inteiro, descarta linha sem CNPJ ou sem data."""
    for coluna in ESQUEMA:
        if coluna not in df.columns:
            df[coluna] = pd.NA
    df = df[list(ESQUEMA)]
    df = df[df["CNPJ"].astype("string").str.fullmatch(r"\d{14}", na=False)]
    return df.dropna(subset=["DATA"]).reset_index(drop=True)


def coletar(ano: int, *, usar_cache: bool = True, com_fip: bool = True,
            competencias_fiagro: int = 6) -> tuple[pd.DataFrame, list[str]]:
    """As três fontes numa tabela. Fonte que falha vira aviso, não exceção.

    O projeto inteiro segue esta regra: uma fonte fora do ar não pode derrubar
    a publicação das outras duas. O que ela não pode é sumir em silêncio, e por
    isso os avisos sobem junto com os dados.
    """
    avisos: list[str] = []
    partes: list[pd.DataFrame] = []

    for rotulo, funcao in (
        ("FII", lambda: ler_fii(ano, usar_cache=usar_cache)),
        ("Fiagro", lambda: ler_fiagro(competencias=competencias_fiagro,
                                      usar_cache=usar_cache)),
    ):
        try:
            parte = funcao()
            partes.append(parte)
            if parte.empty:
                avisos.append(f"{rotulo}: nenhuma linha lida.")
        except Exception as exc:                                   # noqa: BLE001
            avisos.append(f"{rotulo} falhou: {str(exc)[:120]}")
            log.warning("%s falhou: %s", rotulo, exc)

    if com_fip:
        try:
            parte = ler_fip(ano, usar_cache=usar_cache)
            if parte.empty and ano > C.ANO_ULTIMO_TRIMESTRAL_FIP:
                # Em janeiro o arquivo do ano corrente ainda não existe.
                parte = ler_fip(ano - 1, usar_cache=usar_cache)
                avisos.append(f"FIP: usei o arquivo de {ano - 1}.")
            partes.append(parte)
        except Exception as exc:                                   # noqa: BLE001
            avisos.append(f"FIP falhou: {str(exc)[:120]}")
            log.warning("FIP falhou: %s", exc)

    if not partes:
        return _vazio(), avisos or ["Nenhuma fonte respondeu."]
    return pd.concat(partes, ignore_index=True), avisos
