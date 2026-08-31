"""Cálculo dos indicadores da fórmula mágica.

ROIC  = EBIT / Capital Tangível Empregado
        Capital Tangível = Capital de Giro Líquido + Ativo Imobilizado Líquido
        Capital de Giro Líquido = (Ativo Circulante - Caixa - Aplicações Financeiras)
                                - (Passivo Circulante - Empréstimos de curto prazo)

EY    = EBIT / EV
        EV = Valor de Mercado + Dívida Bruta - Caixa e Aplicações Financeiras

Este é o cálculo do livro (Greenblatt, 2010, Apêndice). O TCC usou
ROA (EBIT/Ativo Total) e LPA em reais — ambos corrigidos aqui, mas as
variantes originais continuam disponíveis para comparação.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import config as C

log = logging.getLogger(__name__)


def capital_tangivel(bp: pd.DataFrame) -> pd.Series:
    """Capital de giro líquido + imobilizado, com piso em zero no giro."""
    ac = bp.get(C.CD_ATIVO_CIRCULANTE, 0.0)
    caixa = bp.get(C.CD_CAIXA, 0.0)
    aplic = bp.get(C.CD_APLIC_FINANCEIRAS, 0.0)
    pc = bp.get(C.CD_PASSIVO_CIRCULANTE, 0.0)
    div_cp = bp.get(C.CD_EMPRESTIMOS_CP, 0.0)
    imob = bp.get(C.CD_IMOBILIZADO, 0.0)

    giro = (ac - caixa - aplic) - (pc - div_cp)
    giro = giro.clip(lower=0) if isinstance(giro, pd.Series) else max(giro, 0.0)
    return giro + imob


def divida_bruta(bp: pd.DataFrame) -> pd.Series:
    return bp.get(C.CD_EMPRESTIMOS_CP, 0.0) + bp.get(C.CD_EMPRESTIMOS_LP, 0.0)


def caixa_total(bp: pd.DataFrame) -> pd.Series:
    return bp.get(C.CD_CAIXA, 0.0) + bp.get(C.CD_APLIC_FINANCEIRAS, 0.0)


def montar_indicadores(
    ebit: pd.DataFrame,
    bp: pd.DataFrame,
    mercado: pd.DataFrame,
    params: C.Params,
) -> pd.DataFrame:
    """Junta EBIT (LTM), balanço e dados de mercado e devolve ROIC e EY.

    `mercado` precisa de: CD_CVM, TICKER, PRECO, VALOR_MERCADO, LIQUIDEZ_MEDIA, SETOR
    """
    # CD_CVM percorre três fontes (CVM, B3, Yahoo) e basta uma delas trazer o
    # código como texto ou float para o merge não casar nada — e o universo sair
    # vazio, sem erro nenhum. Padronizar o tipo antes elimina essa classe inteira
    # de falha silenciosa.
    def _chave(d: pd.DataFrame, nome: str) -> pd.DataFrame:
        d = d.copy()
        d["CD_CVM"] = pd.to_numeric(d["CD_CVM"], errors="coerce").astype("Int64")
        antes = len(d)
        d = d.dropna(subset=["CD_CVM"])
        if len(d) < antes:
            log.warning("%s: %d linhas sem CD_CVM válido", nome, antes - len(d))
        return d

    ebit, bp, mercado = (_chave(ebit, "ebit"), _chave(bp, "balanço"),
                         _chave(mercado, "mercado"))

    df = ebit.merge(bp, on="CD_CVM", how="inner").merge(mercado, on="CD_CVM", how="inner")
    log.info("cruzamento: ebit=%d balanço=%d mercado=%d -> universo=%d",
             len(ebit), len(bp), len(mercado), len(df))
    if df.empty:
        comuns = set(ebit["CD_CVM"]) & set(bp["CD_CVM"]) & set(mercado["CD_CVM"])
        raise ValueError(
            "O cruzamento entre demonstrações, balanço e mercado não devolveu "
            f"nenhuma empresa (ebit={len(ebit)}, balanço={len(bp)}, "
            f"mercado={len(mercado)}, CD_CVM em comum={len(comuns)}). "
            "Verifique se o mapeamento CD_CVM <-> ticker da B3 está atualizado.")

    df["CAPITAL_TANGIVEL"] = capital_tangivel(df)
    df["DIVIDA_BRUTA"] = divida_bruta(df)
    df["CAIXA"] = caixa_total(df)
    df["DIVIDA_LIQUIDA"] = df["DIVIDA_BRUTA"] - df["CAIXA"]
    df["EV"] = df["VALOR_MERCADO"] + df["DIVIDA_LIQUIDA"]

    # ---- ROIC -----------------------------------------------------------
    if params.base_roic == "capital_tangivel":
        base = df["CAPITAL_TANGIVEL"]
    elif params.base_roic == "ativo_total":
        base = df.get(C.CD_ATIVO_TOTAL, np.nan)
    else:
        base = df.get(C.CD_PATRIMONIO_LIQUIDO, np.nan)
    df["ROIC"] = np.where(base > 0, df["EBIT_LTM"] / base, np.nan)

    # ---- Earnings Yield -------------------------------------------------
    if params.base_ey == "ebit_ev":
        df["EY"] = np.where(df["EV"] > 0, df["EBIT_LTM"] / df["EV"], np.nan)
    elif params.base_ey == "lucro_preco":
        df["EY"] = np.where(df["VALOR_MERCADO"] > 0,
                            df["EBIT_LTM"] / df["VALOR_MERCADO"], np.nan)
    else:  # replica o bug do TCC: "LPA" = EBIT / nº de ações, em R$ por ação
        df["EY"] = df["EBIT_LTM"] / df["ACOES"].replace(0, np.nan)

    return df


def aplicar_filtros(df: pd.DataFrame, params: C.Params) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Remove o que Greenblatt manda remover. Devolve (aprovados, rejeitados+motivo)."""
    df = df.copy()
    motivos: list[pd.DataFrame] = []

    def corta(mask: pd.Series, motivo: str) -> pd.DataFrame:
        nonlocal df
        fora = df[mask].copy()
        if not fora.empty:
            fora["MOTIVO_EXCLUSAO"] = motivo
            motivos.append(fora)
        return df[~mask]

    if params.excluir_setores and not df.empty:
        campos = [c for c in ("SETOR", "SEGMENTO") if c in df.columns]
        if campos:
            # Concatenação explícita: `df[campos].agg(" | ".join, axis=1)` devolve
            # um DataFrame (não uma Series) quando o DataFrame está vazio, e aí
            # o .str seguinte quebra. Aconteceu em produção.
            texto = df[campos[0]].fillna("").astype(str)
            for c in campos[1:]:
                texto = texto + " | " + df[c].fillna("").astype(str)
            padrao = "|".join(f"(?:{p})" for p in params.excluir_setores)
            mask = texto.str.contains(padrao, case=False, na=False, regex=True)
            df = corta(mask, "setor excluído (financeiro/seguros/utilidade pública)")

    df = corta(df["LIQUIDEZ_MEDIA"].fillna(0) < params.liquidez_minima_diaria,
               f"liquidez < R$ {params.liquidez_minima_diaria:,.0f}/dia")

    if params.exigir_ebit_positivo:
        df = corta(df["EBIT_LTM"] <= 0, "EBIT negativo ou nulo")
    if params.exigir_ev_positivo:
        df = corta(df["EV"] <= 0, "EV negativo ou nulo")

    df = corta(df["ROIC"].isna() | df["EY"].isna(), "indicador não calculável")

    if params.apenas_um_ticker_por_empresa and not df.empty:
        # entre PETR3/PETR4 do mesmo CNPJ, fica o de maior liquidez
        df = df.sort_values("LIQUIDEZ_MEDIA", ascending=False)
        dup = df.duplicated(subset=["CD_CVM"], keep="first")
        df = corta(dup, "classe de ação menos líquida da mesma empresa")

    rejeitados = (pd.concat(motivos, ignore_index=True) if motivos
                  else pd.DataFrame(columns=list(df.columns) + ["MOTIVO_EXCLUSAO"]))
    return df.reset_index(drop=True), rejeitados
