"""Ranking combinado de Greenblatt.

Diferenças em relação ao script do TCC:
  * empates recebem a mesma posição (`method='min'`), em vez de posição
    arbitrária vinda da ordem do DataFrame;
  * o desempate do ranking final usa o ROIC (critério de qualidade), não o índice;
  * o número de ações selecionadas é um parâmetro explícito;
  * operacionais e financeiras são ranqueadas SEPARADAMENTE.

Sobre a separação: numa empresa operacional a qualidade é medida por
ROIC (EBIT sobre capital tangível) e o preço por EBIT/EV. Num banco, esses
dois números não existem — "dívida" é depósito de cliente e o capital
tangível não é o que produz o resultado. As financeiras usam ROE e
Lucro/Preço. Como ROE é inflado por alavancagem, que é exatamente o que
Greenblatt evitou ao escolher EBIT sobre capital, misturar as duas escalas
num único ranking ordinal favoreceria sistematicamente um dos lados.
Por isso cada grupo é ordenado entre os seus, e a divisão de vagas é uma
escolha explícita do investidor.
"""
from __future__ import annotations

import pandas as pd


def _ranquear_grupo(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["POS_ROIC"] = out["ROIC"].rank(ascending=False, method="min").astype(int)
    out["POS_EY"] = out["EY"].rank(ascending=False, method="min").astype(int)
    out["RANK_FINAL"] = out["POS_ROIC"] + out["POS_EY"]
    out = out.sort_values(["RANK_FINAL", "ROIC"], ascending=[True, False])
    return out.reset_index(drop=True)


def ranquear(df: pd.DataFrame, n: int = 30, vagas_financeiras: int = 0,
             vagas_utilidades: int = 0) -> pd.DataFrame:
    """Ranqueia e marca as selecionadas.

    `vagas_financeiras` e `vagas_utilidades` são quantas das `n` vagas ficam com
    bancos/seguradoras e com concessionárias. Com 0 nas duas (padrão), só entram
    operacionais — a regra de Greenblatt. O resto das vagas é das operacionais.
    """
    if df.empty:
        vazio = df.copy()
        for c in ("POS_ROIC", "POS_EY", "RANK_FINAL", "POSICAO", "SELECIONADA"):
            vazio[c] = pd.Series(dtype="int64" if c != "SELECIONADA" else "bool")
        return vazio

    if "TIPO" not in df.columns:
        df = df.assign(TIPO="operacional")

    vagas_fin = max(0, min(int(vagas_financeiras), n))
    vagas_uti = max(0, min(int(vagas_utilidades), n - vagas_fin))
    vagas_op = max(0, n - vagas_fin - vagas_uti)

    partes = []
    for tipo, vagas in (("operacional", vagas_op), ("financeira", vagas_fin),
                        ("utilidade", vagas_uti)):
        grupo = df[df["TIPO"] == tipo]
        if grupo.empty:
            continue
        g = _ranquear_grupo(grupo)
        g["POSICAO"] = g.index + 1
        g["SELECIONADA"] = g["POSICAO"] <= vagas
        partes.append(g)

    if not partes:
        return _ranquear_grupo(df).assign(POSICAO=0, SELECIONADA=False)

    # Operacionais primeiro; dentro de cada grupo, a ordem do próprio ranking.
    ordem = {"operacional": 0, "financeira": 1, "utilidade": 2}
    out = pd.concat(partes, ignore_index=True)
    out = out.sort_values(["TIPO", "POSICAO"],
                          key=lambda c: c.map(ordem) if c.name == "TIPO" else c)
    return out.reset_index(drop=True)


def resumo(df: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    """Versão enxuta para exibir na tela."""
    cols = ["POSICAO", "TIPO", "TICKER", "DENOM_CIA", "SETOR", "ROIC", "EY",
            "POS_ROIC", "POS_EY", "RANK_FINAL", "PRECO", "VALOR_MERCADO",
            "EV", "EBIT_LTM", "LIQUIDEZ_MEDIA", "DT_BASE", "FONTE"]
    cols = [c for c in cols if c in df.columns]
    return df.head(n)[cols].copy()


def rotulo_metricas(tipo: str) -> tuple[str, str]:
    """Nome das duas métricas conforme o tipo de empresa — a interface precisa
    deixar explícito que as colunas não significam a mesma coisa nos dois grupos."""
    if tipo == "financeira":
        return "ROE", "Lucro / Preço"
    # A concessionária usa as mesmas duas métricas da operacional; o que muda é
    # com quem ela é comparada, não como é medida.
    return "ROIC", "EBIT / EV"
