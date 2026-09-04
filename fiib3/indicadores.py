"""Monta a tabela de indicadores e aplica os filtros de universo.

Os indicadores, e por que cada um está aqui:

  P/VP          preço da cota dividido pelo valor patrimonial por cota. É o
                indicador mais citado e o mais mal usado: ele compara o preço
                com uma *avaliação contábil*. Em fundo de tijolo, o laudo é
                anual e defasado; em fundo de papel, o VP acompanha a marcação
                dos CRI e o P/VP fica quase sempre perto de 1, o que torna a
                comparação entre as duas famílias sem sentido. Por isso o
                ranking do site pode ser rodado dentro de cada família.

  DY 12m        proventos dos últimos 12 meses sobre o preço atual. Convenção
                de mercado. Sobe com qualquer rendimento extraordinário.

  DY mediano    mediana dos rendimentos mensais anualizada, sobre o preço.
                É o DY que sobra quando se tira o evento não recorrente.

  Consistência  quantos dos últimos 12 meses tiveram pagamento e quão estáveis
                foram. Um fundo que pagou 12 vezes valores parecidos e outro
                que pagou 5 vezes com o mesmo total anual não são a mesma coisa
                para quem vive de renda.

  Liquidez      volume financeiro médio diário. Em FII isso é restrição de
                verdade: metade do mercado não negocia R$ 500 mil por dia, e
                sair de uma posição relevante nesses fundos leva semanas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from .config import ParamsFII


def montar(informe: pd.DataFrame, cadastro: pd.DataFrame,
           preco: pd.Series, liq: pd.Series, var12: pd.Series,
           resumo: pd.DataFrame) -> pd.DataFrame:
    """Junta CVM + mercado numa linha por ticker."""
    df = informe.copy()
    df = df[df["TICKER"].notna()]

    if cadastro is not None and not cadastro.empty:
        df = df.merge(cadastro, on="CNPJ", how="left")
    for col in ("NOME", "SITUACAO"):
        if col not in df.columns:
            df[col] = pd.NA

    chave = df["TICKER"].astype(str).str.upper() + ".SA"
    df["PRECO"] = chave.map(preco)
    df["LIQUIDEZ"] = chave.map(liq)
    df["VAR_12M"] = chave.map(var12)
    for col in resumo.columns:
        df[col] = chave.map(resumo[col])

    df["FAMILIA"] = [C.familia(m, s) for m, s in
                     zip(df.get("MANDATO"), df.get("SEGMENTO"))]

    # ---- indicadores -----------------------------------------------------
    vp = pd.to_numeric(df["VP_COTA"], errors="coerce")
    df["P_VP"] = np.where(vp > 0, df["PRECO"] / vp, np.nan)

    preco_ok = pd.to_numeric(df["PRECO"], errors="coerce").where(lambda s: s > 0)
    df["DY_12M"] = df["PROV_12M"] / preco_ok
    df["DY_MEDIANO"] = df["PROV_MEDIANA_12M"] / preco_ok
    df["DY_SOBRE_VP"] = df["PROV_12M"] / vp.where(vp > 0)
    df["RENDIMENTO_MENSAL"] = df["PROV_12M"] / 12.0

    # Retorno total do cotista: variação do preço + rendimentos recebidos.
    df["RETORNO_12M"] = df["VAR_12M"] + df["DY_12M"]

    # Consistência em [0, 1]: metade vem de ter pago todos os meses, metade de
    # ter pago valores estáveis. Um fundo que paga sempre R$ 0,10 tira 1,0;
    # um que paga em 6 meses com valores erráticos fica perto de 0,2.
    regular = (df["MESES_PAGOS_12M"] / 12.0).clip(0, 1)
    estavel = (1.0 - df["CV_PROVENTOS"].fillna(1.0)).clip(0, 1)
    df["CONSISTENCIA"] = 0.5 * regular + 0.5 * estavel

    df["IDADE_MESES"] = _idade_meses(df.get("DT_FUNCIONAMENTO"))
    return df.reset_index(drop=True)


def _idade_meses(dt) -> pd.Series:
    if dt is None:
        return pd.Series(dtype=float)
    d = pd.to_datetime(dt, errors="coerce")
    hoje = pd.Timestamp.today().normalize()
    return ((hoje - d).dt.days / 30.44).round(0)


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
def filtrar(df: pd.DataFrame, p: ParamsFII) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa o universo elegível dos excluídos, com o motivo de cada exclusão.

    O motivo importa tanto quanto a exclusão. No lado das ações, a lista de
    empresas cortadas é uma aba do site — a mesma ideia vale aqui, porque um
    fundo conhecido que sumiu da tela sem explicação parece um defeito.
    """
    df = df.copy()
    motivos: list[pd.Series] = []

    def regra(mascara: pd.Series, texto: str) -> None:
        # fillna(False): campo ausente não exclui ninguém — quem exclui por
        # ausência é a regra específica ("sem cotação", "sem valor patrimonial").
        m = pd.Series(mascara, index=df.index).fillna(False).astype(bool)
        motivos.append(pd.Series(np.where(m, texto, ""), index=df.index))

    situacao = df.get("SITUACAO", pd.Series("", index=df.index)).astype("string")
    regra(situacao.str.contains("cancelad|liquidad", case=False, na=False),
          "registro cancelado ou em liquidação")

    if p.excluir_fundos_exclusivos:
        exc = df.get("EXCLUSIVO", pd.Series("", index=df.index)).astype("string")
        regra(exc.str.strip().str.upper().eq("S"), "fundo exclusivo")

    negocia = df.get("NEGOCIA_BOLSA", pd.Series(pd.NA, index=df.index)).astype("string")
    regra(negocia.str.strip().str.upper().eq("N"), "não negociado em bolsa")

    regra(df["PRECO"].isna(), "sem cotação no Yahoo")
    regra(df["VP_COTA"].isna() | (df["VP_COTA"] <= 0), "sem valor patrimonial")
    regra(df["PL"].fillna(0) < p.patrimonio_minimo,
          f"patrimônio abaixo de {_brl(p.patrimonio_minimo)}")
    regra(df["COTISTAS"].fillna(0) < p.cotistas_minimo,
          f"menos de {p.cotistas_minimo} cotistas")
    regra(df["LIQUIDEZ"].fillna(0) < p.liquidez_minima_diaria,
          f"liquidez abaixo de {_brl(p.liquidez_minima_diaria)}/dia")
    regra(df["MESES_PAGOS_12M"].fillna(0) < p.meses_minimos_com_rendimento,
          f"pagou rendimento em menos de {p.meses_minimos_com_rendimento} dos últimos 12 meses")
    regra(df["IDADE_MESES"].fillna(999) < p.idade_minima_meses,
          f"menos de {p.idade_minima_meses} meses de funcionamento")

    juntos = pd.concat(motivos, axis=1)
    primeiro = juntos.apply(lambda linha: next((m for m in linha if m), ""), axis=1)
    df["MOTIVO_EXCLUSAO"] = primeiro
    elegiveis = df[primeiro == ""].drop(columns=["MOTIVO_EXCLUSAO"])
    excluidos = df[primeiro != ""]
    return elegiveis.reset_index(drop=True), excluidos.reset_index(drop=True)


def _brl(v: float) -> str:
    if v >= 1_000_000:
        return f"R$ {v / 1_000_000:.0f} mi"
    if v >= 1_000:
        return f"R$ {v / 1_000:.0f} mil"
    return f"R$ {v:.0f}"
