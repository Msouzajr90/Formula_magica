"""Dados sintéticos, para navegar a interface sem esperar download nenhum.

Os códigos são de fundos que existem; **todos os números são sorteados**. Isso
é uma armadilha óbvia e por isso o dicionário devolvido carrega `demo: True`,
o gerador do JSON propaga a marca e o site pinta um aviso vermelho no topo. A
mesma disciplina do lado das ações: dado inventado nunca sai daqui sem etiqueta.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicadores, score
from .config import ParamsFII, familia

# (código, nome curto, mandato, segmento)
FUNDOS = [
    ("MXRF11", "Maxi Renda", "Títulos e Valores Mobiliários", "Títulos e Val. Mob."),
    ("KNCR11", "Kinea Rendimentos", "Títulos e Valores Mobiliários", "Títulos e Val. Mob."),
    ("KNRI11", "Kinea Renda Imobiliária", "Híbrido", "Híbrido"),
    ("HGLG11", "CSHG Logística", "Renda", "Logística"),
    ("XPML11", "XP Malls", "Renda", "Shoppings"),
    ("VISC11", "Vinci Shopping Centers", "Renda", "Shoppings"),
    ("BTLG11", "BTG Logística", "Renda", "Logística"),
    ("HGRU11", "CSHG Renda Urbana", "Renda", "Outros"),
    ("KNIP11", "Kinea Índices de Preços", "Títulos e Valores Mobiliários", "Títulos e Val. Mob."),
    ("PVBI11", "VBI Prime Properties", "Renda", "Lajes Corporativas"),
    ("RECR11", "REC Recebíveis", "Títulos e Valores Mobiliários", "Títulos e Val. Mob."),
    ("HSML11", "HSI Malls", "Renda", "Shoppings"),
    ("ALZR11", "Alianza Trust Renda", "Renda", "Logística"),
    ("VGHF11", "Valora Hedge Fund", "Híbrido", "Híbrido"),
    ("TRXF11", "TRX Real Estate", "Renda", "Outros"),
    ("RZTR11", "Riza Terrax", "Renda", "Outros"),
    ("BRCO11", "Bresco Logística", "Renda", "Logística"),
    ("GGRC11", "GGR Covepi Renda", "Renda", "Logística"),
    ("IRDM11", "Iridium Recebíveis", "Títulos e Valores Mobiliários", "Títulos e Val. Mob."),
    ("XPLG11", "XP Log", "Renda", "Logística"),
]


def coletar(p: ParamsFII | None = None, *, semente: int = 7,
            por_familia: bool = False, **_) -> dict:
    p = p or ParamsFII()
    rng = np.random.default_rng(semente)
    n = len(FUNDOS)
    hoje = pd.Timestamp.today().normalize()

    preco = np.round(rng.uniform(8, 130, n), 2)
    pvp = np.round(rng.uniform(0.72, 1.14, n), 3)
    dy = rng.uniform(0.07, 0.14, n)

    linhas = []
    for i, (cod, nome, mandato, segmento) in enumerate(FUNDOS):
        mensal = preco[i] * dy[i] / 12
        linhas.append({
            "TICKER": cod, "CNPJ": f"{i:014d}", "NOME": nome,
            "MANDATO": mandato, "SEGMENTO": segmento,
            "FAMILIA": familia(mandato, segmento),
            "GESTAO": rng.choice(["Ativa", "Passiva"]),
            "ADMINISTRADOR": "Administradora Exemplo",
            "SITUACAO": "EM FUNCIONAMENTO NORMAL",
            "COMPETENCIA": (hoje - pd.DateOffset(months=1)).strftime("%Y-%m"),
            "PRECO": preco[i],
            "VP_COTA": round(preco[i] / pvp[i], 2),
            "PL": float(rng.uniform(3e8, 6e9)),
            "COTAS": float(rng.uniform(5e6, 8e7)),
            "COTISTAS": float(rng.integers(3_000, 900_000)),
            "LIQUIDEZ": float(rng.uniform(6e5, 2.5e7)),
            "VAR_12M": float(rng.uniform(-0.18, 0.25)),
            "PROV_12M": mensal * 12,
            "PROV_MEDIANA_12M": mensal * 12 * rng.uniform(0.85, 1.0),
            "MESES_PAGOS_12M": int(rng.integers(11, 13)),
            "MESES_PAGOS_36M": int(rng.integers(30, 37)),
            "CV_PROVENTOS": float(rng.uniform(0.03, 0.35)),
            "ULTIMO_PROVENTO": mensal,
            "DT_ULTIMO_PROVENTO": hoje - pd.DateOffset(days=int(rng.integers(5, 35))),
            "IDADE_MESES": float(rng.integers(30, 200)),
            "DT_FUNCIONAMENTO": hoje - pd.DateOffset(months=int(rng.integers(30, 200))),
            "ORIGEM_TICKER": "demo",
        })

    df = pd.DataFrame(linhas)
    df["RAZAO_EXTRA"] = df["PROV_12M"] / df["PROV_MEDIANA_12M"]
    df["P_VP"] = df["PRECO"] / df["VP_COTA"]
    df["DY_12M"] = df["PROV_12M"] / df["PRECO"]
    df["DY_MEDIANO"] = df["PROV_MEDIANA_12M"] / df["PRECO"]
    df["DY_SOBRE_VP"] = df["PROV_12M"] / df["VP_COTA"]
    df["RENDIMENTO_MENSAL"] = df["PROV_12M"] / 12
    df["RETORNO_12M"] = df["VAR_12M"] + df["DY_12M"]
    regular = (df["MESES_PAGOS_12M"] / 12).clip(0, 1)
    estavel = (1 - df["CV_PROVENTOS"]).clip(0, 1)
    df["CONSISTENCIA"] = 0.5 * regular + 0.5 * estavel

    elegiveis, excluidos = indicadores.filtrar(df, p)
    ranking = score.calcular(elegiveis, p, por_familia=por_familia)
    ranking["ALERTA"] = score.alertas(ranking)

    mensal_tab = _serie_mensal(ranking, rng)
    return {
        "ranking": ranking,
        "excluidos": excluidos,
        "proventos": pd.DataFrame(columns=["TICKER", "DATA", "VALOR"]),
        "mensal": mensal_tab,
        "meta": {
            "gerado_em": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "competencia_informe": (hoje - pd.DateOffset(months=1)).strftime("%Y-%m"),
            "fundos_no_informe": n, "fundos_com_ticker": n,
            "fundos_com_cotacao": n, "elegiveis": int(len(elegiveis)),
            "excluidos": int(len(excluidos)), "origem_ticker_b3": 0,
            "avisos": ["Modo demonstração: todos os números foram sorteados."],
            "demo": True,
        },
    }


def _serie_mensal(ranking: pd.DataFrame, rng) -> pd.DataFrame:
    meses = pd.period_range(end=pd.Timestamp.today().to_period("M") - 1,
                            periods=24, freq="M")
    dados = {}
    for _, linha in ranking.iterrows():
        base = linha["RENDIMENTO_MENSAL"]
        dados[linha["TICKER"] + ".SA"] = np.round(
            base * rng.uniform(0.85, 1.15, len(meses)), 4)
    return pd.DataFrame(dados, index=meses)
