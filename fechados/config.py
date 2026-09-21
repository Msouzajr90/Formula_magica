"""Parâmetros da aba de fundos fechados.

O universo é outro e o score também
-----------------------------------
Fundo fechado de oferta pública não tem preço de tela: o valor da cota é o
patrimonial, apurado pelo administrador. Isso significa que **P/VP é 1 por
construção** e que não existe volume negociado. Dois dos quatro fatores do
score de FII (`fiib3/score.py`) simplesmente não se aplicam aqui, e copiá-los
produziria um ranking que parece funcionar e não mede nada.

O que sobra, e que este módulo parametriza: rentabilidade, prazo restante,
amortização, evolução do número de cotistas, taxa e patrimônio.

Os números abaixo foram medidos contra o informe de 2026, não escolhidos no
chute — ver `claude/ABA_fundos.md` no projeto e a saída de `sondar_fundos2.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import pandas as pd

# ---------------------------------------------------------------------------
# Endereços
# ---------------------------------------------------------------------------
BASE = "https://dados.cvm.gov.br/dados"

# FII e Fiagro reaproveitam o que `fiib3.config` já define — mesmo zip, mesma
# competência, mesmo cache. O que muda é quais colunas são lidas.
INF_QUADRIMESTRAL_FIP = (f"{BASE}/FIP/DOC/INF_QUADRIMESTRAL/DADOS"
                         "/inf_quadrimestral_fip_{ano}.csv")
# O trimestral existe de 2010 a 2023 e parou: a partir de 2024 o informe de FIP
# virou quadrimestral, em dataset separado. Fica registrado porque uma série
# histórica longa precisa dos dois.
INF_TRIMESTRAL_FIP = (f"{BASE}/FIP/DOC/INF_TRIMESTRAL/DADOS"
                      "/inf_trimestral_fip_{ano}.csv")
ANO_ULTIMO_TRIMESTRAL_FIP = 2023

TIPO_FII = "FII"
TIPO_FIAGRO = "Fiagro"
TIPO_FIP = "FIP"

# FII e Fiagro entregam informe mensal; FIP, quadrimestral. A diferença precisa
# viajar com a linha até a tela — uma variação de cotistas "no último informe"
# quer dizer um mês num caso e quatro meses no outro.
PERIODICIDADE = {TIPO_FII: "mensal", TIPO_FIAGRO: "mensal",
                 TIPO_FIP: "quadrimestral"}

# ---------------------------------------------------------------------------
# Sanidade das datas de vencimento
# ---------------------------------------------------------------------------
# Entre os 257 FII de prazo determinado do informe de 2026 há vencimento em
# 2099 e em 3035, além de 2063 e 2064. Os dois primeiros são digitação; os
# outros dois podem ser reais (fundo de 40 anos existe) mas não dá para
# distinguir. A regra: acima do teto a data é marcada como suspeita e não vira
# "anos restantes" na tela — some o número, fica o aviso.
ANOS_MAXIMOS_DE_PRAZO = 60
ANO_MINIMO_DE_VENCIMENTO = 1995


def vencimento_plausivel(data, referencia=None) -> bool:
    """A data de vencimento cabe num fundo de verdade?"""
    if data is None or pd.isna(data):
        return False
    d = pd.Timestamp(data)
    ref = pd.Timestamp(referencia or pd.Timestamp.today())
    if d.year < ANO_MINIMO_DE_VENCIMENTO:
        return False
    return d <= ref + pd.DateOffset(years=ANOS_MAXIMOS_DE_PRAZO)


# ---------------------------------------------------------------------------
# Vocabulário
# ---------------------------------------------------------------------------
PRAZO_DETERMINADO = "Determinado"
PRAZO_INDETERMINADO = "Indeterminado"
PRAZO_SEM_DADO = "Sem dado"

# O `Prazo_Duracao` do Fiagro não serve: na competência 07/2026, dos 289
# fundos, 119 vieram "0 ANO/ANOS", 51 "0 DIA/DIAS" e 40 "1000 ANO/ANOS". São
# 210 de 289 preenchidos com valor que não é prazo nenhum. No FII o mesmo campo
# é limpo — "Determinado" ou "Indeterminado", sem vazios. Por isso o rótulo do
# Fiagro é descartado na entrada, em vez de virar "Determinado" por engano.
ROTULOS_DE_PRAZO_INVALIDOS = ("0 ANO/ANOS", "0 DIA/DIAS", "1000 ANO/ANOS",
                              "0", "0 ANO", "NAO SE APLICA", "")

# ---------------------------------------------------------------------------
# Universo
# ---------------------------------------------------------------------------
@dataclass
class ParamsFechados:
    """O filtro, e por que cada corte existe.

    Três tentativas foram descartadas antes desta, todas por derrubarem fundos
    que o Marco tem ou olha:

    - "não negocia em bolsa" derrubava o XP Agro Renda Feeder, que tem registro
      em bolsa e nenhuma liquidez;
    - "investidores em geral" derrubava o Riza Viseu, que é qualificado — e boa
      parte do secundário de balcão é;
    - "prazo determinado" como corte duro derrubaria o próprio Riza Viseu, que
      vem declarado indeterminado apesar de ter data de vencimento.

    O que sobrou corta o que ninguém compra: fundo exclusivo e veículo de
    estrutura. O master de um feeder tem 1, 2 ou 22 cotistas — e sempre número
    melhor que o feeder, porque não carrega a taxa da distribuição.
    """

    cotistas_minimo: int = 100
    # FIP conta "cotistas subscritores", que é outra coisa: são veículos com
    # poucos titulares por natureza — mediana de 4 e p90 de 28 no informe de
    # 2026. O corte de 100 deixaria de fora quase tudo, inclusive feeders de
    # varejo qualificado em captação. 50 separa o veículo institucional
    # fechado do produto distribuído em plataforma, sem inventar precisão.
    cotistas_minimo_fip: int = 50
    excluir_exclusivos: bool = True
    # Radicais, e não palavras inteiras, porque as fontes divergem no número:
    # o FII escreve "INVESTIDOR PROFISSIONAL" e o FIP "Investidores
    # profissionais". Casar "PROFISSIONAL" contra "PROFISSIONAIS" falha, e o
    # filtro zerava o universo de FIP sem dar erro nenhum.
    publicos_aceitos: tuple = ("GERAL", "QUALIFICAD")
    # FIP não tem público "em geral" — só qualificado e profissional.
    publicos_aceitos_fip: tuple = ("QUALIFICAD", "PROFISSION")
    patrimonio_minimo: float = 0.0

    # ---- séries ----------------------------------------------------------
    janela_meses: int = 12
    minimo_informes_para_serie: int = 3

    def to_dict(self) -> dict:
        return asdict(self)


# Colunas do arquivo consolidado, na ordem em que a tela as usa.
COLUNAS = (
    "CNPJ", "NOME", "TIPO", "COMPETENCIA", "DT_INFORME", "PERIODICIDADE",
    "PRAZO", "DT_VENCIMENTO", "ANOS_RESTANTES", "PRAZO_SUSPEITO",
    "PRAZO_VENCIDO", "ROTULO_CONFLITA", "DT_INICIO", "IDADE_ANOS",
    "COTISTAS", "COTISTAS_PF", "COTISTAS_VAR_12M", "COTISTAS_VAR_ULTIMO",
    "PL", "VP_COTA", "COTAS",
    "RENT_MES", "RENT_12M", "RENT_VP_12M", "MESES_DESCARTADOS",
    "DY_MES", "DY_12M",
    "AMORT_MES", "AMORT_12M", "MESES_COM_AMORT",
    "TAXA_ADM", "PUBLICO", "EXCLUSIVO", "BOLSA", "CETIP", "MBO",
    "ADMINISTRADOR", "SEGMENTO", "N_INFORMES",
)
