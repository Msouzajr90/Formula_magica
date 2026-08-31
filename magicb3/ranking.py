"""Ranking combinado de Greenblatt.

Diferenças em relação ao script do TCC:
  * empates recebem a mesma posição (`method='min'`), em vez de posição
    arbitrária vinda da ordem do DataFrame;
  * o desempate do ranking final usa o ROIC (critério de qualidade), não o índice;
  * o número de ações selecionadas é um parâmetro explícito.
"""
from __future__ import annotations

import pandas as pd


def ranquear(df: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    """Recebe um DataFrame com colunas ROIC e EY. Devolve tudo ranqueado."""
    if df.empty:
        return df.assign(POS_ROIC=[], POS_EY=[], RANK_FINAL=[], SELECIONADA=[])

    out = df.copy()
    out["POS_ROIC"] = out["ROIC"].rank(ascending=False, method="min").astype(int)
    out["POS_EY"] = out["EY"].rank(ascending=False, method="min").astype(int)
    out["RANK_FINAL"] = out["POS_ROIC"] + out["POS_EY"]

    out = out.sort_values(["RANK_FINAL", "ROIC"], ascending=[True, False])
    out = out.reset_index(drop=True)
    out["POSICAO"] = out.index + 1
    out["SELECIONADA"] = out["POSICAO"] <= n
    return out


def resumo(df: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    """Versão enxuta para exibir na tela."""
    cols = ["POSICAO", "TICKER", "DENOM_CIA", "SETOR", "ROIC", "EY",
            "POS_ROIC", "POS_EY", "RANK_FINAL", "PRECO", "VALOR_MERCADO",
            "EV", "EBIT_LTM", "LIQUIDEZ_MEDIA", "DT_BASE", "FONTE"]
    cols = [c for c in cols if c in df.columns]
    return df.head(n)[cols].copy()
