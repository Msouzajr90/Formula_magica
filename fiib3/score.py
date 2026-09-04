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


def _arredondar_score(v):
    """Score em 0..1 -> nota em 0..100 com uma casa, meio para cima.

    O `+ 0.5` seguido de `floor` reproduz o `Math.round` do navegador, que
    arredonda meio para cima — o `round` do numpy arredondaria meio para o par.

    O passo do meio existe por um motivo menos óbvio. Como os percentis são
    frações de inteiros, a soma ponderada cai EXATAMENTE em x,x5 com alguma
    frequência: no caso que quebrou em produção, o valor exato era 352,5. Em
    ponto flutuante ninguém acerta 352,5 na mosca — dá 352,5000000000001 numa
    máquina e 352,4999999999999 noutra, conforme a versão do numpy/pandas
    mudar a ordem das somas. Um lado arredonda para 35,3, o outro para 35,2, e
    o teste de paridade acusa uma divergência que não existe: a diferença é de
    1e-13, e nenhuma decisão de investimento depende dela.

    Encaixar o valor no milionésimo antes de arredondar mata esse ruído sem
    tocar em nada que seja informação. O navegador faz o mesmo, na mesma ordem.
    """
    milesimos = v * 1000
    milesimos = np.floor(milesimos * 1e6 + 0.5) / 1e6
    return np.floor(milesimos + 0.5) / 10


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

    df["SCORE"] = _arredondar_score(df["SCORE"])
    ordem = ["FAMILIA"] if por_familia else []
    df["POSICAO"] = (df.groupby(ordem)["SCORE"].rank(ascending=False, method="min")
                     if ordem else df["SCORE"].rank(ascending=False, method="min"))
    df["POSICAO"] = df["POSICAO"].astype("Int64")
    return df.sort_values("SCORE", ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------
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
