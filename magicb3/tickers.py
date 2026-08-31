"""Mapeamento CD_CVM / CNPJ <-> ticker da B3.

O TCC dependia de uma planilha manual no Google Drive. Isso trouxe dois
problemas: (a) a planilha refletia o universo de 2023, então empresas
deslistadas entre 2018 e 2022 sumiam do backtest (viés de sobrevivência);
(b) a coluna LIQUIDEZ era estática, aplicada a todos os anos.

Aqui o mapa é reconstruído a partir da API pública de companhias listadas
da B3, que devolve `codeCVM` — a mesma chave dos arquivos da CVM.
Há três fontes, em ordem de preferência:
  1. cache local (parquet)
  2. API da B3
  3. CSV informado pelo usuário (mesmo formato da planilha antiga)
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import pandas as pd
import requests

from .config import CACHE_DIR

log = logging.getLogger(__name__)

B3_URL = ("https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy"
          "/CompanyCall/GetInitialCompanies/{payload}")
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

SUFIXOS_CANDIDATOS = ("3", "4", "11", "5", "6")


def _cache(nome: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / nome


def _pagina_b3(pagina: int, tamanho: int = 120) -> dict:
    payload = base64.b64encode(json.dumps(
        {"language": "pt-br", "pageNumber": pagina, "pageSize": tamanho}
    ).encode()).decode()
    r = requests.get(B3_URL.format(payload=payload), headers=HEADERS, timeout=60)
    r.raise_for_status()
    return r.json()


def baixar_empresas_b3(usar_cache: bool = True) -> pd.DataFrame:
    """Companhias listadas: codeCVM, prefixo do ticker, razão social, segmento."""
    arq = _cache("b3_empresas.parquet")
    if usar_cache and arq.exists():
        return pd.read_parquet(arq)

    linhas, pagina = [], 1
    while True:
        js = _pagina_b3(pagina)
        linhas.extend(js.get("results", []))
        total = js.get("page", {}).get("totalPages", 1)
        if pagina >= total:
            break
        pagina += 1

    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    df = df.rename(columns={
        "codeCVM": "CD_CVM", "issuingCompany": "PREFIXO",
        "companyName": "DENOM_CIA", "tradingName": "NOME_PREGAO",
        "cnpj": "CNPJ", "segment": "SEGMENTO",
    })
    df["CD_CVM"] = pd.to_numeric(df["CD_CVM"], errors="coerce")
    df = df.dropna(subset=["CD_CVM", "PREFIXO"])
    df["CD_CVM"] = df["CD_CVM"].astype(int)
    cols = [c for c in ["CD_CVM", "PREFIXO", "DENOM_CIA", "NOME_PREGAO", "CNPJ", "SEGMENTO"]
            if c in df.columns]
    df = df[cols].drop_duplicates()
    if usar_cache:
        df.to_parquet(arq, index=False)
    return df


def candidatos_de_ticker(empresas: pd.DataFrame,
                         sufixos: tuple[str, ...] = SUFIXOS_CANDIDATOS) -> pd.DataFrame:
    """Expande cada prefixo nos códigos possíveis (PETR -> PETR3, PETR4, ...)."""
    linhas = []
    for _, row in empresas.iterrows():
        for s in sufixos:
            linhas.append({"CD_CVM": row["CD_CVM"],
                           "TICKER": f"{row['PREFIXO']}{s}.SA",
                           "DENOM_CIA": row.get("DENOM_CIA"),
                           "SEGMENTO": row.get("SEGMENTO")})
    return pd.DataFrame(linhas)


def carregar_csv_usuario(caminho: str | Path) -> pd.DataFrame:
    """Aceita a planilha antiga (CNPJ_CIA;EMPRESA;TICKER;ACOES_CIRC;LIQUIDEZ)."""
    df = pd.read_csv(caminho, sep=None, engine="python", encoding="latin-1")
    df.columns = [c.strip().upper() for c in df.columns]
    ren = {"CNPJ_CIA": "CNPJ", "EMPRESA": "DENOM_CIA", "ACOES_CIRC": "ACOES"}
    df = df.rename(columns={k: v for k, v in ren.items() if k in df.columns})
    if "TICKER" in df.columns:
        df["TICKER"] = (df["TICKER"].astype(str).str.strip().str.upper()
                        .where(lambda s: s.str.endswith(".SA"),
                               lambda s: s + ".SA"))
    return df


def mapa_setorial(empresas: pd.DataFrame, cadastro_cvm: pd.DataFrame) -> pd.DataFrame:
    """Une o segmento da B3 com o setor de atividade do cadastro da CVM.

    O setor é o que permite excluir bancos, seguradoras e utilities,
    exclusão que o TCC não fez (e que Greenblatt considera obrigatória,
    porque ROIC e EV não fazem sentido para instituições financeiras).
    """
    cad = cadastro_cvm.copy()
    cad.columns = [c.strip().upper() for c in cad.columns]
    col_setor = next((c for c in ("SETOR_ATIV", "SETOR_ATIVIDADE", "SETOR")
                      if c in cad.columns), None)
    if col_setor is None:
        empresas = empresas.copy()
        empresas["SETOR"] = pd.NA
        return empresas
    cad = cad.rename(columns={col_setor: "SETOR"})
    if "CD_CVM" in cad.columns:
        cad["CD_CVM"] = pd.to_numeric(cad["CD_CVM"], errors="coerce")
    sit = cad["SIT"].astype(str).str.upper() if "SIT" in cad.columns else None
    if sit is not None:
        cad = cad[sit.str.contains("ATIVO", na=False)]
    cad = cad[["CD_CVM", "SETOR"]].dropna().drop_duplicates(subset=["CD_CVM"])
    return empresas.merge(cad, on="CD_CVM", how="left")
