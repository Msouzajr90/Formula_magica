"""Informe mensal e cadastro de FII, dos dados abertos da CVM.

O informe mensal (`FII/DOC/INF_MENSAL`) é a fonte oficial de tudo o que não é
preço: patrimônio líquido, número de cotas, valor patrimonial por cota, número
de cotistas, mandato e segmento de atuação. Um zip por ano, com três CSVs por
mês dentro:

    inf_mensal_fii_geral_AAAAMM.csv           cadastro do mês, ISIN, segmento
    inf_mensal_fii_ativo_passivo_AAAAMM.csv   PL, total do ativo e do passivo
    inf_mensal_fii_complemento_AAAAMM.csv     VP/cota, cotistas, rentabilidade

Uma decisão de projeto que vale explicar: **nenhum nome de coluna é fixado no
código**. A CVM renomeia colunas entre safras (e a documentação vem num zip
separado que ninguém lê), então cada campo é localizado por uma lista de
padrões e, se nenhum casar, o erro diz quais colunas existiam de fato. É a
diferença entre "KeyError: 'Valor_Patrimonial_Cotas'" e uma mensagem que
permite consertar em trinta segundos.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from pathlib import Path

import pandas as pd

from . import config as C
from .config import CACHE_DIR

log = logging.getLogger(__name__)

# `magicb3.rede` já resolve o problema de IPv6 do servidor da CVM e traz uma
# sessão com repetição. Reaproveitar evita manter duas cópias da mesma correção.
try:
    from magicb3 import rede
except ImportError:                                            # pragma: no cover
    rede = None


def _sessao():
    if rede is not None:
        return rede.sessao()
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})
    return s


def _cache(nome: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / nome


# ---------------------------------------------------------------------------
# Localização tolerante de colunas
# ---------------------------------------------------------------------------
def _chave(nome: str) -> str:
    """Normaliza para comparar: minúsculas, sem acento e sem separador."""
    n = str(nome).strip().lower()
    for de, para in (("ãâáàä", "a"), ("éêèë", "e"), ("íîì", "i"),
                     ("óôõòö", "o"), ("úûùü", "u"), ("ç", "c")):
        for ch in de:
            n = n.replace(ch, para)
    return re.sub(r"[^a-z0-9]", "", n)


def coluna(df: pd.DataFrame, *padroes: str, obrigatoria: bool = True) -> str | None:
    """Primeira coluna cujo nome normalizado contém um dos padrões.

    Os padrões são testados na ordem dada, então o mais específico vem primeiro.
    """
    mapa = {_chave(c): c for c in df.columns}
    for p in padroes:
        alvo = _chave(p)
        if alvo in mapa:
            return mapa[alvo]
        for k, original in mapa.items():
            if alvo in k:
                return original
    if obrigatoria:
        raise KeyError(
            f"Nenhuma coluna casa com {padroes!r}.\n"
            f"Colunas disponíveis: {list(df.columns)}"
        )
    return None


def _numero(serie: pd.Series) -> pd.Series:
    """Converte para float aceitando tanto '1234.56' quanto '1.234,56'."""
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce")
    s = serie.astype("string").str.strip()
    # se houver vírgula decimal, o ponto é separador de milhar
    tem_virgula = s.str.contains(",", na=False)
    s = s.mask(tem_virgula, s.str.replace(".", "", regex=False)
                            .str.replace(",", ".", regex=False))
    return pd.to_numeric(s, errors="coerce")


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def _baixar(url: str, *, timeout: int = 300) -> bytes:
    log.info("Baixando %s", url)
    r = _sessao().get(url, timeout=timeout)
    r.raise_for_status()
    return r.content


def baixar_informe_mensal(ano: int, *, usar_cache: bool = True) -> zipfile.ZipFile:
    """Zip do informe mensal de um ano, com cache em disco."""
    arq = _cache(f"inf_mensal_fii_{ano}.zip")
    if usar_cache and arq.exists() and arq.stat().st_size > 1024:
        return zipfile.ZipFile(arq)
    conteudo = _baixar(C.INF_MENSAL_ZIP.format(ano=ano))
    if usar_cache:
        arq.write_bytes(conteudo)
        return zipfile.ZipFile(arq)
    return zipfile.ZipFile(io.BytesIO(conteudo))


def _ler_csv(zf: zipfile.ZipFile, nome: str) -> pd.DataFrame:
    with zf.open(nome) as fh:
        return pd.read_csv(fh, sep=";", encoding="ISO-8859-1",
                           dtype="string", low_memory=False)


def _membros(zf: zipfile.ZipFile, familia: str) -> list[str]:
    """Nomes dos CSVs de uma família ('geral', 'complemento', ...), em ordem."""
    alvo = _chave(familia)
    return sorted(n for n in zf.namelist()
                  if n.lower().endswith(".csv") and alvo in _chave(n))


def _competencia(nome: str) -> str:
    """'..._geral_202608.csv' -> '2026-08'."""
    m = re.search(r"(\d{4})(\d{2})", Path(nome).stem)
    return f"{m.group(1)}-{m.group(2)}" if m else ""


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def _ultimo_por_fundo(df: pd.DataFrame, col_cnpj: str,
                      col_data: str, col_versao: str | None) -> pd.DataFrame:
    """Uma linha por fundo: competência mais recente, maior versão.

    A CVM republica informes corrigidos mantendo o original no mesmo arquivo —
    a mesma armadilha que, no lado das ações, duplicava empresas no ranking.
    """
    df = df.copy()
    df["_data"] = pd.to_datetime(df[col_data], errors="coerce")
    df["_versao"] = (_numero(df[col_versao]) if col_versao else 1.0)
    df = df.dropna(subset=[col_cnpj, "_data"])
    df = df.sort_values([col_cnpj, "_data", "_versao"])
    return df.drop_duplicates(subset=[col_cnpj], keep="last")


def ler_informe(ano: int, *, meses: int = 3,
                usar_cache: bool = True) -> pd.DataFrame:
    """Informe mensal consolidado: uma linha por fundo, a mais recente.

    `meses` limita quantas competências finais do zip são lidas — 3 bastam para
    ter o último informe de todo fundo ativo e evitam abrir 12 arquivos à toa.
    """
    zf = baixar_informe_mensal(ano, usar_cache=usar_cache)

    geral = _concatenar(zf, "geral", meses)
    compl = _concatenar(zf, "complemento", meses)
    ativo = _concatenar(zf, "ativo_passivo", meses)
    if geral.empty:
        raise RuntimeError(
            f"O zip de {ano} não trouxe nenhum arquivo 'geral'. "
            f"Conteúdo: {zf.namelist()[:10]}"
        )

    c_cnpj = coluna(geral, "cnpj_fundo", "cnpj")
    c_data = coluna(geral, "data_referencia", "data_competencia", "dt_refer")
    c_versao = coluna(geral, "versao", obrigatoria=False)
    g = _ultimo_por_fundo(geral, c_cnpj, c_data, c_versao)

    out = pd.DataFrame({
        "CNPJ": _cnpj_limpo(g[c_cnpj]),
        "COMPETENCIA": g["_data"].dt.strftime("%Y-%m"),
        "DT_INFORME": g["_data"],
    })
    out["ISIN"] = _texto(g, coluna(g, "codigo_isin", "isin", obrigatoria=False))
    # A razão social vem no próprio informe (`Nome_Fundo_Classe`). Antes ela era
    # buscada no `cad_fii.csv`, que a CVM tirou do ar — a dependência sumiu junto.
    out["NOME"] = _texto(g, coluna(g, "nome_fundo_classe", "denominacao_social",
                                   "nome_fundo", obrigatoria=False))
    out["TIPO_CLASSE"] = _texto(g, coluna(g, "tipo_fundo_classe", obrigatoria=False))
    out["DT_ENTREGA"] = pd.to_datetime(
        _texto(g, coluna(g, "data_entrega", obrigatoria=False)), errors="coerce")
    out["MANDATO"] = _texto(g, coluna(g, "mandato", obrigatoria=False))
    out["SEGMENTO"] = _texto(g, coluna(g, "segmento_atuacao", "segmento",
                                       obrigatoria=False))
    out["GESTAO"] = _texto(g, coluna(g, "tipo_gestao", obrigatoria=False))
    out["ADMINISTRADOR"] = _texto(g, coluna(g, "nome_administrador",
                                            "administrador", obrigatoria=False))
    out["PUBLICO_ALVO"] = _texto(g, coluna(g, "publico_alvo", obrigatoria=False))
    out["EXCLUSIVO"] = _texto(g, coluna(g, "fundo_exclusivo", obrigatoria=False))
    out["NEGOCIA_BOLSA"] = _texto(g, coluna(g, "mercado_negociacao_bolsa",
                                            obrigatoria=False))
    out["DT_FUNCIONAMENTO"] = pd.to_datetime(
        _texto(g, coluna(g, "data_funcionamento", obrigatoria=False)),
        errors="coerce")
    out["COTAS"] = _valor(g, coluna(g, "quantidade_cotas_emitidas",
                                    "total_numero_cotas", "cotas_emitidas",
                                    obrigatoria=False))

    out = out.merge(_do_complemento(compl), on="CNPJ", how="left")
    out = out.merge(_do_ativo_passivo(ativo), on="CNPJ", how="left")

    # O nº de cotas aparece nos dois arquivos conforme a safra; fica o que veio.
    if "COTAS_COMPL" in out.columns:
        out["COTAS"] = out["COTAS"].fillna(out.pop("COTAS_COMPL"))

    # VP/cota: preferir o declarado; senão, PL / nº de cotas.
    calculado = out["PL"] / out["COTAS"].where(out["COTAS"] > 0)
    out["VP_COTA"] = out["VP_COTA"].fillna(calculado)
    return out.reset_index(drop=True)


def _concatenar(zf: zipfile.ZipFile, familia: str, meses: int) -> pd.DataFrame:
    nomes = _membros(zf, familia)[-max(1, meses):]
    partes = [_ler_csv(zf, n) for n in nomes]
    partes = [p for p in partes if not p.empty]
    return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()


def _texto(df: pd.DataFrame, col: str | None) -> pd.Series:
    if col is None:
        return pd.Series(pd.NA, index=df.index, dtype="string")
    return df[col].astype("string").str.strip()


def _valor(df: pd.DataFrame, col: str | None) -> pd.Series:
    if col is None:
        return pd.Series(float("nan"), index=df.index, dtype="float64")
    return _numero(df[col])


def _cnpj_limpo(serie: pd.Series) -> pd.Series:
    return (serie.astype("string").str.replace(r"\D", "", regex=True)
            .str.zfill(14))


def _do_complemento(compl: pd.DataFrame) -> pd.DataFrame:
    """Patrimônio, cotas, VP/cota e cotistas.

    O patrimônio líquido mora AQUI, e não no arquivo de ativo e passivo — que é
    o que o nome sugeriria e o que a primeira versão deste módulo supôs. O
    resultado foi a coluna sair vazia nos 1.375 fundos sem erro nenhum, que é
    exatamente o modo de falha silencioso contra o qual o `validar_fiis.py`
    existe.
    """
    if compl.empty:
        return pd.DataFrame(columns=["CNPJ", "VP_COTA", "COTISTAS", "PL",
                                     "ATIVO_TOTAL", "RENT_EFETIVA_MES", "DY_MES_CVM"])
    c_cnpj = coluna(compl, "cnpj_fundo", "cnpj")
    c_data = coluna(compl, "data_referencia", "data_competencia")
    d = _ultimo_por_fundo(compl, c_cnpj, c_data,
                          coluna(compl, "versao", obrigatoria=False))
    out = pd.DataFrame({"CNPJ": _cnpj_limpo(d[c_cnpj])})
    out["VP_COTA"] = _valor(d, coluna(d, "valor_patrimonial_cotas",
                                      "valor_patrimonial_cota",
                                      "valor_patrimonial", obrigatoria=False))
    out["COTISTAS"] = _valor(d, coluna(d, "total_numero_cotistas",
                                       "numero_cotistas", "cotistas",
                                       obrigatoria=False))
    out["COTAS_COMPL"] = _valor(d, coluna(d, "cotas_emitidas",
                                          "total_numero_cotas_emitidas",
                                          "numero_cotas", obrigatoria=False))
    out["PL"] = _valor(d, coluna(d, "patrimonio_liquido", obrigatoria=False))
    out["ATIVO_TOTAL"] = _valor(d, coluna(d, "valor_ativo", "total_ativo",
                                          "ativo_total", obrigatoria=False))
    out["RENT_EFETIVA_MES"] = _valor(d, coluna(d, "percentual_rentabilidade_efetiva_mes",
                                               obrigatoria=False))
    out["DY_MES_CVM"] = _valor(d, coluna(d, "percentual_dividend_yield_mes",
                                         obrigatoria=False))
    return out.drop_duplicates(subset=["CNPJ"])


def _soma_contas(d: pd.DataFrame, contas) -> pd.Series:
    """Soma as contas que existirem, tratando ausente como zero.

    Zero, e não NaN: uma conta que não aparece no arquivo é uma conta em que o
    fundo não tem nada. Propagar NaN aqui apagaria a carteira inteira de
    qualquer fundo com uma única conta faltando.
    """
    total = pd.Series(0.0, index=d.index)
    for nome in contas:
        col = coluna(d, nome, obrigatoria=False)
        if col is not None:
            total = total + _numero(d[col]).fillna(0.0)
    return total


def _do_ativo_passivo(ativo: pd.DataFrame) -> pd.DataFrame:
    """Composição da carteira: quanto está em imóvel, em recebível e em cota.

    Este arquivo não traz patrimônio líquido — traz a carteira aberta em ~50
    contas. É dela que sai a classificação papel/tijolo, agora que o `Mandato`
    da CVM vem vazio (ver `config.familia`).
    """
    vazio = ["CNPJ", "PCT_IMOVEIS", "PCT_PAPEL", "PCT_FOF",
             "TOTAL_INVESTIDO", "CAIXA", "PASSIVO"]
    if ativo.empty:
        return pd.DataFrame(columns=vazio)
    c_cnpj = coluna(ativo, "cnpj_fundo", "cnpj")
    c_data = coluna(ativo, "data_referencia", "data_competencia")
    d = _ultimo_por_fundo(ativo, c_cnpj, c_data,
                          coluna(ativo, "versao", obrigatoria=False))

    imoveis = _soma_contas(d, C.CONTAS_IMOVEIS)
    papel = _soma_contas(d, C.CONTAS_PAPEL)
    fof = _soma_contas(d, C.CONTAS_FOF)
    total = _soma_contas(d, (C.CONTA_TOTAL_INVESTIDO,))
    # Sem total investido não há fração possível; o fundo fica "Sem dado" em vez
    # de ser jogado num grupo por omissão.
    base = total.where(total > 0)

    out = pd.DataFrame({"CNPJ": _cnpj_limpo(d[c_cnpj])})
    out["PCT_IMOVEIS"] = (imoveis / base).to_numpy()
    out["PCT_PAPEL"] = (papel / base).to_numpy()
    out["PCT_FOF"] = (fof / base).to_numpy()
    out["TOTAL_INVESTIDO"] = total.to_numpy()
    out["CAIXA"] = _soma_contas(d, (C.CONTA_CAIXA,)).to_numpy()
    out["PASSIVO"] = _soma_contas(d, ("Total_Passivo",)).to_numpy()
    return out.drop_duplicates(subset=["CNPJ"])


# ---------------------------------------------------------------------------
# Cadastro
# ---------------------------------------------------------------------------
def baixar_cadastro(*, usar_cache: bool = True) -> pd.DataFrame:
    """`cad_fii.csv`: razão social, situação e classe de cada fundo."""
    arq = _cache("cad_fii.csv")
    if usar_cache and arq.exists() and arq.stat().st_size > 1024:
        bruto = arq.read_bytes()
    else:
        bruto = _baixar(C.CAD_FII_URL, timeout=120)
        if usar_cache:
            arq.write_bytes(bruto)
    df = pd.read_csv(io.BytesIO(bruto), sep=";", encoding="ISO-8859-1",
                     dtype="string", low_memory=False)
    c_cnpj = coluna(df, "cnpj_fundo", "cnpj")
    out = pd.DataFrame({"CNPJ": _cnpj_limpo(df[c_cnpj])})
    out["NOME"] = _texto(df, coluna(df, "denominacao_social", "denom_social",
                                    "nome", obrigatoria=False))
    out["SITUACAO"] = _texto(df, coluna(df, "situacao", obrigatoria=False))
    out["TIPO"] = _texto(df, coluna(df, "tipo_fii", "classe", obrigatoria=False))
    # Um CNPJ pode aparecer em várias classes de cota; fica a primeira.
    return out.drop_duplicates(subset=["CNPJ"], keep="first")


def ticker_do_isin(isin: str | None) -> str | None:
    """ISIN brasileiro -> prefixo do ticker. 'BRMXRFCTF004' -> 'MXRF'.

    Exige **quatro letras**, e não quatro caracteres alfanuméricos. Medido na
    competência 07/2026: dos 674 fundos marcados como negociados em bolsa, 653
    tinham ISIN aceito pelo padrão frouxo, mas 225 deles produziam códigos como
    `003H11` e `01M911` — que o Yahoo responde "Not Found", porque código de
    negociação da B3 é sempre quatro letras seguidas de dígitos. Aceitar dígitos
    no prefixo gerava 225 símbolos inexistentes, 225 consultas jogadas fora e
    225 linhas de "sem cotação no Yahoo" na aba de excluídos, escondendo os
    casos em que a ausência de cotação significa alguma coisa.

    O padrão restrito deixa 428 códigos, que é a ordem de grandeza do universo
    de FII efetivamente listados.
    """
    # `pd.isna` primeiro: com dtype "string" do pandas, um valor ausente é o
    # pd.NA, e testar a verdade dele levanta TypeError em vez de devolver False.
    if isin is None or pd.isna(isin):
        return None
    s = str(isin).strip().upper()
    m = re.fullmatch(r"BR([A-Z]{4})[A-Z]{3}\d{3}", s)
    return m.group(1) if m else None
