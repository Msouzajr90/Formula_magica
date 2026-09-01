"""Ingestão dos dados abertos da CVM (DFP anual + ITR trimestral).

Corrige três problemas do script original:
  1. Normaliza ESCALA_MOEDA (MIL vs UNIDADE) -> tudo em reais.
  2. Mantém apenas a maior VERSAO de cada arquivo (evita duplicatas/refazimentos).
  3. Registra DT_RECEB (data de entrega na CVM) para permitir corte point-in-time.
"""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from . import config as C
from . import rede
from .config import CACHE_DIR

log = logging.getLogger(__name__)

BASE_DFP = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/DFP/DADOS"
BASE_ITR = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/ITR/DADOS"
CAD_URL = "https://dados.cvm.gov.br/dados/CIA_ABERTA/CAD/DADOS/cad_cia_aberta.csv"

# Colunas que interessam nos arquivos de demonstração
_COLS = [
    "CNPJ_CIA", "DT_REFER", "VERSAO", "DENOM_CIA", "CD_CVM", "ESCALA_MOEDA",
    "ORDEM_EXERC", "DT_INI_EXERC", "DT_FIM_EXERC", "CD_CONTA", "DS_CONTA", "VL_CONTA",
]

_ESCALA = {"MIL": 1_000.0, "MILHAO": 1_000_000.0, "UNIDADE": 1.0}


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / name


def _erro_de_rede(url: str, exc: Exception) -> RuntimeError:
    """Erro de rede com o diagnóstico já embutido, em vez de um traceback cru."""
    try:
        diag = rede.relatorio("dados.cvm.gov.br")
    except Exception:                                          # noqa: BLE001
        diag = "(diagnóstico indisponível)"
    return RuntimeError(
        f"Não consegui acessar {url}\n"
        f"{type(exc).__name__}: {exc}\n\n"
        f"Diagnóstico da conexão:\n{diag}\n\n"
        "Se IPv4 e IPv6 falharem os dois, o servidor da CVM não aceita conexões "
        "desta máquina. Isso acontece em servidores fora do Brasil (incluindo os "
        "do GitHub Actions). Nesse caso, gere o arquivo de dados a partir de um "
        "computador no Brasil."
    )


def _baixar_zip(url: str, *, timeout: int = 300) -> zipfile.ZipFile:
    log.info("Baixando %s", url)
    try:
        r = rede.sessao().get(url, timeout=timeout)
        r.raise_for_status()
    except Exception as exc:                                   # noqa: BLE001
        raise _erro_de_rede(url, exc) from exc
    return zipfile.ZipFile(io.BytesIO(r.content))


def _ler_membro(zf: zipfile.ZipFile, nome: str,
                contas: set[str] | None = None,
                *, chunk: int = 200_000) -> pd.DataFrame:
    """Lê um CSV do zip em blocos, descartando contas irrelevantes na leitura.

    Um DRE_con anual tem ~1,5 milhão de linhas e ~250 MB em memória se lido
    inteiro. Como só precisamos de ~10 códigos de conta, filtrar durante a
    leitura derruba isso para poucos MB — o que faz diferença no plano
    gratuito do Streamlit Cloud, limitado a ~1 GB de RAM.
    """
    pedacos: list[pd.DataFrame] = []
    with zf.open(nome) as fh:
        leitor = pd.read_csv(
            fh, sep=";", encoding="ISO-8859-1", decimal=".",
            dtype={"CD_CONTA": "string", "CNPJ_CIA": "string",
                   "ESCALA_MOEDA": "category", "ORDEM_EXERC": "category"},
            chunksize=chunk, low_memory=True,
        )
        for bloco in leitor:
            for c in _COLS:
                if c not in bloco.columns:      # ITR antigo não traz DT_INI_EXERC no BP
                    bloco[c] = pd.NA
            bloco = bloco[_COLS]
            if contas:
                bloco = bloco[bloco["CD_CONTA"].isin(contas)]
            ordem = bloco["ORDEM_EXERC"].astype("string").str.strip().str.upper()
            bloco = bloco[ordem == "ÚLTIMO"]
            if len(bloco):
                pedacos.append(bloco)

    if not pedacos:
        return pd.DataFrame(columns=_COLS)
    return pd.concat(pedacos, ignore_index=True)


def _normalizar(df: pd.DataFrame, dt_receb: pd.DataFrame | None = None) -> pd.DataFrame:
    """Aplica escala, filtra ÚLTIMO exercício e mantém a versão mais recente."""
    df = df.copy()
    df["DT_REFER"] = pd.to_datetime(df["DT_REFER"], errors="coerce")
    for c in ("DT_INI_EXERC", "DT_FIM_EXERC"):
        df[c] = pd.to_datetime(df[c], errors="coerce")

    # 1) escala monetária -> reais
    # ESCALA_MOEDA vem como dtype 'category' na leitura em blocos; sem o
    # astype("string") o .map devolve outra categoria e a multiplicação falha.
    fator = (df["ESCALA_MOEDA"].astype("string").str.strip().str.upper()
             .map(_ESCALA).astype("float64").fillna(1.0))
    df["VL_CONTA"] = pd.to_numeric(df["VL_CONTA"], errors="coerce") * fator

    # 2) apenas o exercício corrente do arquivo
    df = df[df["ORDEM_EXERC"].astype("string").str.strip().str.upper() == "ÚLTIMO"]

    # 3) só a maior VERSAO por (empresa, data de referência)
    df["VERSAO"] = pd.to_numeric(df["VERSAO"], errors="coerce")
    idx = df.groupby(["CD_CVM", "DT_REFER"])["VERSAO"].transform("max")
    df = df[df["VERSAO"] == idx]

    df = df.dropna(subset=["VL_CONTA", "CD_CVM", "DT_REFER"])
    df = df.drop_duplicates(subset=["CD_CVM", "DT_REFER", "CD_CONTA", "DT_INI_EXERC"], keep="last")

    if dt_receb is not None and not dt_receb.empty:
        df = df.merge(dt_receb, on=["CD_CVM", "DT_REFER", "VERSAO"], how="left")
    else:
        df["DT_RECEB"] = pd.NaT
    return df


def _ler_datas_recebimento(zf: zipfile.ZipFile, prefixo: str, ano: int) -> pd.DataFrame:
    """O arquivo raiz `<prefixo>_cia_aberta_<ano>.csv` traz DT_RECEB por filing."""
    nome = f"{prefixo}_cia_aberta_{ano}.csv"
    if nome not in zf.namelist():
        return pd.DataFrame()
    with zf.open(nome) as fh:
        df = pd.read_csv(fh, sep=";", encoding="ISO-8859-1", low_memory=False)
    if "DT_RECEB" not in df.columns:
        return pd.DataFrame()
    df = df[["CD_CVM", "DT_REFER", "VERSAO", "DT_RECEB"]].copy()
    df["DT_REFER"] = pd.to_datetime(df["DT_REFER"], errors="coerce")
    df["DT_RECEB"] = pd.to_datetime(df["DT_RECEB"], errors="coerce")
    df["VERSAO"] = pd.to_numeric(df["VERSAO"], errors="coerce")
    return df.drop_duplicates()


def _achar_membro(zf: zipfile.ZipFile, tipo: str, grupo: str, suf: str,
                  ano: int) -> str | None:
    """Localiza o CSV do grupo no zip sem depender do nome exato.

    A CVM já mudou o padrão de nome mais de uma vez; casar por partes evita
    que uma renomeação quebre tudo em silêncio.
    """
    exato = f"{tipo}_cia_aberta_{grupo}_{suf}_{ano}.csv"
    nomes = zf.namelist()
    if exato in nomes:
        return exato
    alvo = [f"_{grupo}_", f"_{suf}_", str(ano)]
    for n in nomes:
        base = n.rsplit("/", 1)[-1].lower()
        if base.endswith(".csv") and all(a.lower() in base for a in alvo):
            return n
    return None


def _zip_local(pasta: Path, tipo: str, ano: int) -> Path | None:
    """Procura o zip já baixado na pasta, tolerando maiúsculas e sufixos."""
    alvo = f"{tipo}_cia_aberta_{ano}.zip".lower()
    for arq in pasta.glob("*.zip"):
        nome = arq.name.lower()
        if nome == alvo or (nome.startswith(f"{tipo}_cia_aberta_{ano}") and
                            nome.endswith(".zip")):
            return arq
    return None


def carregar_demonstracoes(
    anos: list[int],
    *,
    tipo: str = "dfp",
    consolidado: bool = True,
    usar_cache: bool = True,
    contas: set[str] | None = None,
    pasta_zips: str | Path | None = None,
) -> dict[str, pd.DataFrame]:
    """Retorna {'DRE': df, 'BPA': df, 'BPP': df} já normalizados.

    `tipo` = 'dfp' (anual) ou 'itr' (trimestral).
    `contas` restringe a leitura aos códigos de conta usados (economia de RAM).
    `pasta_zips` lê arquivos já baixados em vez de acessar a rede — necessário
    quando a máquina não alcança a CVM (ver `rede.py`).
    """
    tipo = tipo.lower()
    base = BASE_DFP if tipo == "dfp" else BASE_ITR
    suf = "con" if consolidado else "ind"
    saida: dict[str, list[pd.DataFrame]] = {"DRE": [], "BPA": [], "BPP": []}

    for ano in anos:
        cache = _cache_path(f"{tipo}_{suf}_{ano}.parquet")
        if usar_cache and cache.exists():
            df = pd.read_parquet(cache)
            for grp in saida:
                saida[grp].append(df[df["_GRUPO"] == grp])
            continue

        if pasta_zips:
            local = _zip_local(Path(pasta_zips), tipo, ano)
            if local is None:
                log.warning("Zip de %s %s não encontrado em %s", tipo, ano, pasta_zips)
                continue
            log.info("Lendo %s (%.1f MB)", local.name, local.stat().st_size / 1e6)
            zf = zipfile.ZipFile(local)
        else:
            try:
                zf = _baixar_zip(f"{base}/{tipo}_cia_aberta_{ano}.zip")
            except Exception as exc:                  # noqa: BLE001
                log.warning("Falha ao baixar %s %s: %s", tipo, ano, exc)
                continue

        dt_receb = _ler_datas_recebimento(zf, tipo, ano)
        pedacos = []
        for grp in ("DRE", "BPA", "BPP"):
            nome = _achar_membro(zf, tipo, grp, suf, ano)
            if nome is None:
                log.warning("Arquivo %s não encontrado no zip de %s %s", grp, tipo, ano)
                continue
            df = _normalizar(_ler_membro(zf, nome, contas), dt_receb)
            df["_GRUPO"] = grp
            saida[grp].append(df)
            pedacos.append(df)

        if usar_cache and pedacos:
            pd.concat(pedacos, ignore_index=True).to_parquet(cache, index=False)

    return {k: (pd.concat(v, ignore_index=True) if v else pd.DataFrame(columns=_COLS))
            for k, v in saida.items()}


def carregar_cadastro(usar_cache: bool = True,
                      arquivo_local: str | Path | None = None) -> pd.DataFrame:
    """Cadastro de companhias abertas: CNPJ, CD_CVM, razão social, setor, situação."""
    if arquivo_local:
        df = pd.read_csv(arquivo_local, sep=";", encoding="ISO-8859-1", low_memory=False)
        df["CNPJ_CIA"] = df["CNPJ_CIA"].astype("string")
        return df
    cache = _cache_path("cad_cia_aberta.parquet")
    if usar_cache and cache.exists():
        return pd.read_parquet(cache)
    try:
        r = rede.sessao().get(CAD_URL, timeout=180)
        r.raise_for_status()
    except Exception as exc:                                   # noqa: BLE001
        raise _erro_de_rede(CAD_URL, exc) from exc
    df = pd.read_csv(io.BytesIO(r.content), sep=";", encoding="ISO-8859-1", low_memory=False)
    df["CNPJ_CIA"] = df["CNPJ_CIA"].astype("string")
    if usar_cache:
        df.to_parquet(cache, index=False)
    return df


# ---------------------------------------------------------------------------
# LTM (últimos 12 meses)
# ---------------------------------------------------------------------------
def ebit_ltm(dre_dfp: pd.DataFrame, dre_itr: pd.DataFrame, cd_conta: str) -> pd.DataFrame:
    """EBIT dos últimos 12 meses por empresa.

    LTM = DFP(último exercício fechado)
          - ITR acumulado até o trimestre T do ano anterior
          + ITR acumulado até o trimestre T do ano corrente

    Quando não há ITR posterior ao último DFP, devolve o próprio DFP anual.
    """
    anual = dre_dfp[dre_dfp["CD_CONTA"] == cd_conta].copy()
    anual = anual.sort_values("DT_REFER").groupby("CD_CVM", as_index=False).last()
    anual = anual.rename(columns={"VL_CONTA": "EBIT_FY", "DT_REFER": "DT_FY"})
    anual = anual[["CD_CVM", "CNPJ_CIA", "DENOM_CIA", "DT_FY", "EBIT_FY", "DT_RECEB"]]

    if dre_itr is None or dre_itr.empty:
        out = anual.rename(columns={"EBIT_FY": "EBIT_LTM", "DT_FY": "DT_BASE"})
        out["FONTE"] = "DFP"
        return out

    itr = dre_itr[dre_itr["CD_CONTA"] == cd_conta].copy()
    # No ITR, o valor acumulado do ano vai de 01/01 até a data de referência.
    dur = (itr["DT_FIM_EXERC"] - itr["DT_INI_EXERC"]).dt.days
    itr = itr[dur > 100]                       # descarta a linha "3 meses"
    itr["TRI"] = itr["DT_REFER"].dt.quarter
    itr["ANO"] = itr["DT_REFER"].dt.year
    itr = itr.sort_values("DT_REFER")

    ult = itr.groupby("CD_CVM", as_index=False).last()[
        ["CD_CVM", "DT_REFER", "VL_CONTA", "TRI", "ANO", "DT_RECEB"]
    ].rename(columns={"DT_REFER": "DT_ITR", "VL_CONTA": "YTD_ATUAL", "DT_RECEB": "DT_RECEB_ITR"})

    ant = itr[["CD_CVM", "TRI", "ANO", "VL_CONTA"]].rename(columns={"VL_CONTA": "YTD_ANTERIOR"})
    ant["ANO"] = ant["ANO"] + 1
    ult = ult.merge(ant, on=["CD_CVM", "TRI", "ANO"], how="left")

    m = anual.merge(ult, on="CD_CVM", how="left")
    tem_itr = m["DT_ITR"].notna() & (m["DT_ITR"] > m["DT_FY"]) & m["YTD_ANTERIOR"].notna()

    m["EBIT_LTM"] = m["EBIT_FY"]
    m.loc[tem_itr, "EBIT_LTM"] = (
        m.loc[tem_itr, "EBIT_FY"] - m.loc[tem_itr, "YTD_ANTERIOR"] + m.loc[tem_itr, "YTD_ATUAL"]
    )
    m["DT_BASE"] = m["DT_FY"].where(~tem_itr, m["DT_ITR"])
    m["DT_RECEB"] = m["DT_RECEB"].where(~tem_itr, m["DT_RECEB_ITR"])
    m["FONTE"] = "DFP"
    m.loc[tem_itr, "FONTE"] = "DFP+ITR (LTM)"
    return m[["CD_CVM", "CNPJ_CIA", "DENOM_CIA", "DT_BASE", "EBIT_LTM", "DT_RECEB", "FONTE"]]


def balanco_mais_recente(bpa: pd.DataFrame, bpp: pd.DataFrame,
                         contas: list[str]) -> pd.DataFrame:
    """Pivota o balanço mais recente de cada empresa nas contas pedidas."""
    bp = pd.concat([bpa, bpp], ignore_index=True)
    bp = bp[bp["CD_CONTA"].isin(contas)]
    if bp.empty:
        return pd.DataFrame(columns=["CD_CVM", "DT_BP"] + contas)
    ultimo = bp.groupby("CD_CVM")["DT_REFER"].transform("max")
    bp = bp[bp["DT_REFER"] == ultimo]
    piv = bp.pivot_table(index=["CD_CVM", "DT_REFER"], columns="CD_CONTA",
                         values="VL_CONTA", aggfunc="last").reset_index()
    piv = piv.rename(columns={"DT_REFER": "DT_BP"})
    for c in contas:
        if c not in piv.columns:
            piv[c] = 0.0
    piv.columns.name = None
    return piv


# ---------------------------------------------------------------------------
# Composição do capital — número de ações
# ---------------------------------------------------------------------------
CD_LUCRO_LIQUIDO = "3.11"      # Lucro/Prejuízo Consolidado do Período
CD_LPA_ON = "3.99.01.01"       # Lucro por Ação Básico ON, em R$/ação

def composicao_capital(anos: list[int], *, consolidado: bool = True,
                       pasta_zips: str | Path | None = None,
                       usar_cache: bool = True) -> pd.DataFrame:
    """Número de ações em circulação por empresa, com a escala corrigida.

    A CVM publica `composicao_capital`, mas — diferente das demonstrações — esse
    arquivo NÃO tem coluna de escala, e as empresas divergem: uma parte informa
    em unidades e outra em milhares. Verificado no DFP de 2025: Petrobras, WEG,
    Suzano e Gerdau vêm em unidades; Ambev, Vale, Itaú e Embraer vêm em milhares.
    Usar o número cru daria um valor de mercado 1.000 vezes menor para essas, o
    que embaralharia por completo o ranking de Earnings Yield.

    A escala é inferida comparando com o número de ações implícito no lucro por
    ação: `ações ≈ lucro líquido / LPA`. A razão entre o implícito e o informado
    cai claramente perto de 1 ou perto de 1.000.

    Devolve CNPJ_CIA, ACOES, ACOES_BRUTO e ESCALA_CONFIRMADA. Quando a escala não
    pôde ser confirmada, ACOES vem nulo — melhor não ter o dado do que ter um
    dado mil vezes errado.
    """
    base_dfp = BASE_DFP
    linhas: list[pd.DataFrame] = []
    suf = "con" if consolidado else "ind"

    for ano in anos:
        zf = None
        if pasta_zips:
            local = _zip_local(Path(pasta_zips), "dfp", ano)
            if local is not None:
                zf = zipfile.ZipFile(local)
        else:
            try:
                zf = _baixar_zip(f"{base_dfp}/dfp_cia_aberta_{ano}.zip")
            except Exception as exc:                           # noqa: BLE001
                log.warning("composicao_capital: %s", exc)
        if zf is None:
            continue

        nome = next((n for n in zf.namelist() if "composicao_capital" in n.lower()), None)
        if nome is None:
            continue
        with zf.open(nome) as fh:
            cap = pd.read_csv(fh, sep=";", encoding="ISO-8859-1", low_memory=False)
        if "QT_ACAO_TOTAL_CAP_INTEGR" not in cap.columns:
            log.warning("composicao_capital de %s sem as colunas esperadas", ano)
            continue

        cap["DT_REFER"] = pd.to_datetime(cap["DT_REFER"], errors="coerce")
        cap["ACOES_BRUTO"] = (pd.to_numeric(cap["QT_ACAO_TOTAL_CAP_INTEGR"], errors="coerce")
                              - pd.to_numeric(cap.get("QT_ACAO_TOTAL_TESOURO"),
                                              errors="coerce").fillna(0))

        # referência para a escala: ações implícitas no lucro por ação
        alvo = _achar_membro(zf, "dfp", "DRE", suf, ano)
        if alvo:
            dre = _normalizar(_ler_membro(zf, alvo, {CD_LUCRO_LIQUIDO, CD_LPA_ON}))
            piv = dre.pivot_table(index="CNPJ_CIA", columns="CD_CONTA",
                                  values="VL_CONTA", aggfunc="last")
            piv.columns.name = None
            piv = piv.reset_index()
            cap = cap.merge(piv, on="CNPJ_CIA", how="left")
            # A coluna pode nem existir se nenhuma empresa do arquivo reportou
            # a conta — daí a série de NaN em vez de None.
            def _serie(coluna: str) -> pd.Series:
                if coluna not in cap.columns:
                    return pd.Series(np.nan, index=cap.index, dtype="float64")
                return pd.to_numeric(cap[coluna], errors="coerce")

            # o LPA já vem em R$/ação; a normalização de escala não se aplica a ele
            lpa = _serie(CD_LPA_ON) / 1000.0
            lucro = _serie(CD_LUCRO_LIQUIDO)
            cap["ACOES_IMPLICITO"] = lucro / lpa.replace(0, np.nan)
        else:
            cap["ACOES_IMPLICITO"] = np.nan

        linhas.append(cap[["CNPJ_CIA", "DT_REFER", "ACOES_BRUTO", "ACOES_IMPLICITO"]])

    if not linhas:
        return pd.DataFrame(columns=["CNPJ_CIA", "ACOES", "ACOES_BRUTO",
                                     "ESCALA_CONFIRMADA"])

    df = pd.concat(linhas, ignore_index=True).sort_values("DT_REFER")
    df = df.groupby("CNPJ_CIA", as_index=False).last()

    razao = (df["ACOES_IMPLICITO"] / df["ACOES_BRUTO"].replace(0, np.nan)).abs()
    unidades = razao.between(0.3, 3.0)
    milhares = razao.between(300.0, 3000.0)

    df["ACOES"] = np.where(unidades, df["ACOES_BRUTO"],
                    np.where(milhares, df["ACOES_BRUTO"] * 1000.0, np.nan))
    df["ESCALA_CONFIRMADA"] = unidades | milhares
    df.loc[df["ACOES"] <= 0, "ACOES"] = np.nan

    log.info("composição do capital: %d empresas, %d com escala confirmada "
             "(%d em unidades, %d em milhares)",
             len(df), int(df["ESCALA_CONFIRMADA"].sum()),
             int(unidades.sum()), int(milhares.sum()))
    return df[["CNPJ_CIA", "ACOES", "ACOES_BRUTO", "ESCALA_CONFIRMADA"]]


def patrimonio_liquido(bpp: pd.DataFrame) -> pd.DataFrame:
    """Patrimônio líquido localizado pela DESCRIÇÃO da conta, não pelo código.

    Necessário porque bancos e seguradoras usam outro plano de contas com os
    mesmos códigos. Verificado no ITR de 30/06/2026:

        conta   WEG S.A.                   Banco do Brasil
        2.01    Passivo Circulante         Passivos Financeiros ao Valor Justo
        2.03    Patrimônio Líquido         Provisões
        2.07    (não existe)               Patrimônio Líquido Consolidado

    Ler `2.03` num banco devolve as provisões — R$ 40,4 bi no BB, contra os
    R$ 190,8 bi de patrimônio real. A descrição, porém, é idêntica nos dois
    planos, então é por ela que se procura.
    """
    if bpp.empty:
        return pd.DataFrame(columns=["CD_CVM", "PATRIMONIO", "CD_CONTA_PL"])
    ds = bpp["DS_CONTA"].astype("string").str.strip().str.lower()
    pl = bpp[ds.str.startswith(C.DS_PATRIMONIO_LIQUIDO, na=False)].copy()
    if pl.empty:
        return pd.DataFrame(columns=["CD_CVM", "PATRIMONIO", "CD_CONTA_PL"])
    # entre "Consolidado" e "Atribuído ao Controlador", fica o de código mais curto
    pl["_prof"] = pl["CD_CONTA"].astype(str).str.count(r"\.")
    pl = pl.sort_values(["DT_REFER", "_prof"])
    pl = pl.groupby("CD_CVM", as_index=False).first()
    return pl.rename(columns={"VL_CONTA": "PATRIMONIO",
                              "CD_CONTA": "CD_CONTA_PL"})[
        ["CD_CVM", "PATRIMONIO", "CD_CONTA_PL"]]
