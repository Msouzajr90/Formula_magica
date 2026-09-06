"""Score multifator dos FII.

Como funciona, em uma frase: cada fator vira um **percentil dentro do universo
elegível**, e o score é a média ponderada desses percentis.

Por que percentil e não o valor bruto: os fatores estão em unidades
incomparáveis (DY em %, P/VP em múltiplo, liquidez em reais) e todos têm cauda
longa. Somar valores brutos deixaria a liquidez, que varia em três ordens de
grandeza, dominando tudo. Somar posições no ranking — o que Greenblatt faz do
lado das ações — resolve a escala mas descarta a distância: o 1º e o 2º ficam
sempre à mesma distância, mesmo quando um paga 12% e o outro 8%. O percentil
fica no meio: mantém a ordem, normaliza a escala e preserva parte da distância.

O que este score **não** é: uma medida de valor justo. Ele não olha contrato de
locação, qualidade de inquilino, risco de crédito dos CRI, alavancagem, nem
laudo de avaliação. É uma triagem — serve para reduzir 300 fundos a 20 que
merecem leitura de relatório gerencial, e nada além disso.

Esta implementação e a de `web/public/fiis.js` precisam dar o mesmo resultado.
A do navegador existe para o usuário mexer nos pesos sem esperar servidor; esta
existe para a exportação e para os testes. `tests/test_fiis.py` compara as duas
em cima do mesmo conjunto de números.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import ParamsFII

# Cada fator: coluna de origem e se maior é melhor.
FATORES = {
    "dy": ("DY_SCORE", True),
    "pvp": ("P_VP", False),
    "consistencia": ("CONSISTENCIA", True),
    "liquidez": ("LIQUIDEZ", True),
}


def percentil(serie: pd.Series, maior_melhor: bool = True) -> pd.Series:
    """Percentil em [0, 1]. Empates recebem o mesmo valor; ausentes viram 0,5.

    Ausente vira o meio da distribuição, não zero: um fundo sem o dado não deve
    ser premiado nem punido por uma falha de coleta.
    """
    s = pd.to_numeric(serie, errors="coerce")
    if s.notna().sum() <= 1:
        return pd.Series(0.5, index=serie.index)
    r = s.rank(method="average", pct=True, na_option="keep")
    if not maior_melhor:
        r = 1.0 - r
    return r.fillna(0.5)


def _dy_para_score(df: pd.DataFrame, p: ParamsFII) -> pd.Series:
    """O DY que entra no score.

    Com `usar_dy_mediano`, é o menor entre o DY de 12 meses e o DY mediano
    anualizado. O mínimo, e não a média, porque a assimetria do erro é
    assimétrica: superestimar o rendimento recorrente de um fundo faz o
    investidor comprar contando com uma renda que não existe, e subestimar
    apenas o deixa de fora de uma lista de triagem.
    """
    dy12 = pd.to_numeric(df.get("DY_12M"), errors="coerce")
    if not p.usar_dy_mediano:
        return dy12
    med = pd.to_numeric(df.get("DY_MEDIANO"), errors="coerce")
    return pd.concat([dy12, med], axis=1).min(axis=1, skipna=True)


def calcular(df: pd.DataFrame, p: ParamsFII | None = None,
             *, por_familia: bool = False) -> pd.DataFrame:
    """Acrescenta as colunas de percentil, o SCORE e a posição no ranking.

    Com `por_familia`, os percentis são calculados dentro de Papel, Tijolo e
    Híbrido separadamente. É o modo honesto de comparar: o P/VP de um fundo de
    papel e o de um fundo de laje corporativa não medem a mesma coisa, então
    ranqueá-los na mesma lista mistura duas escalas — o mesmo erro que o site
    das ações evita ao separar bancos das demais empresas.
    """
    p = p or ParamsFII()
    df = df.copy()
    if df.empty:
        return df

    df["DY_SCORE"] = _dy_para_score(df, p)
    pesos = p.pesos_fatores()

    grupos = df.groupby("FAMILIA").groups if por_familia else {None: df.index}
    for _, idx in grupos.items():
        bloco = df.loc[idx]
        soma = pd.Series(0.0, index=idx)
        for nome, (coluna, maior) in FATORES.items():
            pc = percentil(bloco[coluna], maior)
            df.loc[idx, f"PC_{nome.upper()}"] = pc
            soma += pesos[nome] * pc
        df.loc[idx, "SCORE"] = soma

    # Arredondamento meio para cima (não o `round` do numpy, que vai para o par),
    # igual ao `Math.round` do navegador. E antes disso, uma quantização a 12
    # casas.
    #
    # A quantização existe por causa de uma falha real, que só apareceu no
    # GitHub Actions: percentis são frações de inteiros, então o score cai
    # exatamente em x,x5 com frequência. Nesses pontos, uma diferença de um
    # último bit entre a soma do numpy e a do JavaScript joga um lado para
    # 352,4999999 e o outro para 352,5 — e a tela mostra 35,2 enquanto a
    # exportação mostra 35,3. Zerar o ruído antes de arredondar faz os dois
    # partirem do mesmo número.
    df["SCORE"] = np.floor(np.floor(df["SCORE"] * 1e12 + 0.5) / 1e12 * 1000 + 0.5) / 10
    ordem = ["FAMILIA"] if por_familia else []
    df["POSICAO"] = (df.groupby(ordem)["SCORE"].rank(ascending=False, method="min")
                     if ordem else df["SCORE"].rank(ascending=False, method="min"))
    df["POSICAO"] = df["POSICAO"].astype("Int64")
    return df.sort_values("SCORE", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------
# Rótulo curto (coluna da tabela) -> frase inteira (título ao passar o mouse).
# A frase completa numa célula de tabela empurra a linha para oito alturas e
# torna o ranking ilegível quando metade dos fundos tem alerta — que é o caso
# com dados reais.
CURTOS = {
    "extra": "rendimento não recorrente",
    "dy_alto": "DY muito alto",
    "desconto": "desconto forte no VP",
}


def alertas_curtos(df: pd.DataFrame) -> pd.Series:
    """Mesma lógica de `alertas`, em duas ou três palavras."""
    longos = alertas(df)
    fora = pd.Series("", index=df.index, dtype=object)
    fora[longos.str.contains("não recorrente", na=False)] = CURTOS["extra"]
    fora[longos.str.contains("amortização", na=False)] = CURTOS["dy_alto"]
    fora[longos.str.contains("valor patrimonial", na=False)] = CURTOS["desconto"]
    return fora


def alertas(df: pd.DataFrame) -> pd.Series:
    """Marca o que um DY alto costuma esconder. Uma frase por fundo, ou vazio.

    Estes são os três modos de errar que mais aparecem em tela de FII, e o
    score sozinho não os captura — por isso viram texto ao lado da linha em vez
    de virarem mais um fator diluído na média.
    """
    fora = pd.Series("", index=df.index, dtype=object)

    razao = pd.to_numeric(df.get("RAZAO_EXTRA"), errors="coerce")
    marca = razao > 1.3
    fora[marca] = ("rendimento dos 12 meses "
                   + (razao[marca] * 100 - 100).round(0).astype("Int64").astype(str)
                   + "% acima da mediana — provável evento não recorrente")

    dy = pd.to_numeric(df.get("DY_12M"), errors="coerce")
    muito_alto = (dy > 0.18) & (fora == "")
    fora[muito_alto] = "DY acima de 18% ao ano — verifique se há amortização de cota embutida"

    pvp = pd.to_numeric(df.get("P_VP"), errors="coerce")
    desconto = (pvp < 0.75) & (fora == "")
    fora[desconto] = "negociado a menos de 75% do valor patrimonial — o mercado discorda do laudo"

    return fora
