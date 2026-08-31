"""Arquivo de fundamentos — a ponte entre o Brasil e a nuvem.

Motivo de existir: `dados.cvm.gov.br` recusa conexões vindas de servidores no
exterior. Confirmado em produção — do GitHub Actions, o IPv4 expira por
descarte de pacotes e o IPv6 não tem rota. Yahoo Finance e a API da B3
funcionam normalmente de lá.

A solução separa o que muda devagar do que muda todo dia:

    fundamentos (CVM)  -> muda 4x por ano  -> baixado de um PC no Brasil,
                                              gravado neste arquivo e versionado
    mercado (Yahoo/B3) -> muda todo dia    -> baixado pelo robô na nuvem

O arquivo tem uns 200 KB e cabe no repositório sem incomodar.
"""
from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pandas as pd

from . import config as C

VERSAO = 1

# nome curto no arquivo -> código de conta da CVM
CONTAS = {
    "ativoTotal": C.CD_ATIVO_TOTAL,
    "ativoCirc": C.CD_ATIVO_CIRCULANTE,
    "caixa": C.CD_CAIXA,
    "aplic": C.CD_APLIC_FINANCEIRAS,
    "passivoCirc": C.CD_PASSIVO_CIRCULANTE,
    "dividaCp": C.CD_EMPRESTIMOS_CP,
    "dividaLp": C.CD_EMPRESTIMOS_LP,
    "imobilizado": C.CD_IMOBILIZADO,
    "intangivel": C.CD_INTANGIVEL,
    "patrimonio": C.CD_PATRIMONIO_LIQUIDO,
}


def _n(x):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(v) or math.isinf(v)) else round(v, 2)


def _t(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    s = str(x).strip()
    return s if s and s.lower() not in ("nan", "nat") else None


def exportar(ebit: pd.DataFrame, bp: pd.DataFrame, setores: pd.DataFrame,
             caminho: Path | str, *, anos: list[int]) -> dict:
    """Grava o arquivo a partir do que `cvm.py` produziu."""
    df = ebit.merge(bp, on="CD_CVM", how="left")
    if not setores.empty:
        df = df.merge(setores, on="CD_CVM", how="left")

    # Acesso por nome de coluna: os códigos de conta ("1.01", "2.03") não são
    # identificadores Python válidos, então itertuples os renomearia.
    def col(nome: str):
        return df[nome] if nome in df.columns else pd.Series([None] * len(df),
                                                             index=df.index)

    campos = {
        "cvm": col("CD_CVM"), "cnpj": col("CNPJ_CIA"), "nome": col("DENOM_CIA"),
        "setor": col("SETOR"), "ebitLtm": col("EBIT_LTM"),
        "dtBase": col("DT_BASE"), "dtBalanco": col("DT_BP"), "fonte": col("FONTE"),
    }
    contas = {nome: col(conta) for nome, conta in CONTAS.items()}

    empresas = []
    for i in df.index:
        if pd.isna(campos["cvm"][i]):
            continue
        item = {
            "cvm": int(campos["cvm"][i]),
            "cnpj": _t(campos["cnpj"][i]),
            "nome": _t(campos["nome"][i]),
            "setor": _t(campos["setor"][i]),
            "ebitLtm": _n(campos["ebitLtm"][i]),
            "dtBase": (_t(campos["dtBase"][i]) or "")[:10] or None,
            "dtBalanco": (_t(campos["dtBalanco"][i]) or "")[:10] or None,
            "fonte": _t(campos["fonte"][i]),
        }
        for nome, serie in contas.items():
            item[nome] = _n(serie[i])
        empresas.append(item)

    dados = {
        "meta": {
            "versao": VERSAO,
            "geradoEm": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "anos": anos,
            "nEmpresas": len(empresas),
            "origem": "dados.cvm.gov.br (DFP + ITR)",
        },
        "empresas": empresas,
    }

    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
    return dados


def importar(caminho: Path | str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Lê o arquivo e devolve (ebit, balanço, setores) no formato do pipeline."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(
            f"{caminho} não existe.\n"
            "Esse arquivo é gerado por `python baixar_fundamentos.py`, que precisa "
            "rodar num computador no Brasil — a CVM recusa conexões do exterior."
        )
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    emp = pd.DataFrame(dados.get("empresas") or [])
    if emp.empty:
        raise ValueError(f"{caminho} não tem empresas.")

    ebit = pd.DataFrame({
        "CD_CVM": emp["cvm"].astype(int),
        "CNPJ_CIA": emp.get("cnpj"),
        "DENOM_CIA": emp.get("nome"),
        "EBIT_LTM": pd.to_numeric(emp.get("ebitLtm"), errors="coerce"),
        "DT_BASE": pd.to_datetime(emp.get("dtBase"), errors="coerce"),
        "FONTE": emp.get("fonte"),
        "DT_RECEB": pd.NaT,
    })

    bp = pd.DataFrame({"CD_CVM": emp["cvm"].astype(int),
                       "DT_BP": pd.to_datetime(emp.get("dtBalanco"), errors="coerce")})
    for nome, conta in CONTAS.items():
        bp[conta] = pd.to_numeric(emp.get(nome), errors="coerce").fillna(0.0)

    setores = pd.DataFrame({"CD_CVM": emp["cvm"].astype(int),
                            "SETOR": emp.get("setor")}).dropna(subset=["SETOR"])

    return ebit, bp, setores


def idade_em_dias(caminho: Path | str) -> int | None:
    """Há quantos dias o arquivo foi gerado. Serve para avisar que envelheceu."""
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        gerado = pd.Timestamp(dados["meta"]["geradoEm"])
        return int((pd.Timestamp.now() - gerado).days)
    except Exception:                                          # noqa: BLE001
        return None
