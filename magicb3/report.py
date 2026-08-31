"""Exportação para Excel."""
from __future__ import annotations

import io

import pandas as pd


def exportar_excel(res, params, metricas: dict | None = None) -> bytes:
    """Gera o .xlsx em memória (compatível com pandas >= 2.0: usa close(), não save())."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
        pd.DataFrame([params.to_dict()]).T.rename(columns={0: "valor"}).to_excel(
            writer, sheet_name="Parametros")

        pesos = res.pesos[res.pesos > 0].sort_values(ascending=False)
        carteira = pesos.rename("Peso").to_frame()
        carteira["Peso %"] = (carteira["Peso"] * 100).round(2)
        carteira.to_excel(writer, sheet_name="Carteira sugerida")

        res.ranking.to_excel(writer, sheet_name="Ranking completo", index=False)
        res.selecionadas.to_excel(writer, sheet_name="Selecionadas", index=False)
        if len(res.rejeitadas):
            cols = [c for c in ["TICKER", "DENOM_CIA", "SETOR", "ROIC", "EY",
                                "LIQUIDEZ_MEDIA", "MOTIVO_EXCLUSAO"]
                    if c in res.rejeitadas.columns]
            res.rejeitadas[cols].to_excel(writer, sheet_name="Excluidas", index=False)

        fr = pd.DataFrame({
            "Retorno esperado": res.fronteira.retorno,
            "Volatilidade": res.fronteira.risco,
            "Sharpe": res.fronteira.sharpe,
        }, index=res.fronteira.pesos.columns)
        fr.to_excel(writer, sheet_name="Fronteira eficiente")
        res.fronteira.pesos.to_excel(writer, sheet_name="Pesos por carteira")

        res.cov.to_excel(writer, sheet_name="Covariancia")
        res.retornos.corr().to_excel(writer, sheet_name="Correlacao")

        if metricas:
            pd.DataFrame(metricas).to_excel(writer, sheet_name="Backtest")

        pd.DataFrame([res.diagnostico]).T.rename(columns={0: "valor"}).to_excel(
            writer, sheet_name="Diagnostico")

    return buf.getvalue()
