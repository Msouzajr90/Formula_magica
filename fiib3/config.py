"""Parâmetros e endereços da parte de fundos imobiliários.

O desenho é deliberadamente igual ao de `magicb3`: os dados estruturais vêm
da CVM (fonte oficial, auditável) e os dados de mercado vêm do Yahoo. O que
muda é que, em FII, o "balanço" útil é o **informe mensal** — publicado até o
15º dia útil do mês seguinte —, e não a demonstração anual. A defasagem
típica é de 4 a 6 semanas, contra 3 meses das companhias abertas.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Endereços das fontes
# ---------------------------------------------------------------------------
CAD_FII_URL = "https://dados.cvm.gov.br/dados/FII/CAD/DADOS/cad_fii.csv"
INF_MENSAL_BASE = "https://dados.cvm.gov.br/dados/FII/DOC/INF_MENSAL/DADOS"
INF_MENSAL_ZIP = INF_MENSAL_BASE + "/inf_mensal_fii_{ano}.zip"

# A API de fundos listados da B3 é a mesma família da usada em magicb3.tickers,
# com outro proxy. `typeFund=7` é o código de FII.
B3_FUNDS_URL = ("https://sistemaswebb3-listados.b3.com.br/fundsProxy"
                "/fundsCall/GetListedFundsSIG/{payload}")
B3_TIPO_FII = 7

CACHE_DIR = Path.home() / ".fiib3_cache"

# ---------------------------------------------------------------------------
# Segmentos
# ---------------------------------------------------------------------------
# A CVM classifica em duas dimensões que interessam:
#   Mandato          -> Híbrido / Renda / Desenvolvimento para Renda / Títulos e Valores Mobiliários
#   Segmento_Atuacao -> Lajes Corporativas / Shoppings / Logística / Híbrido / Residencial ...
#
# O mercado fala em "papel" e "tijolo". A tradução abaixo é uma conveniência de
# apresentação, não uma classificação oficial — e por isso fica explícita aqui
# em vez de escondida no meio do cálculo.
MANDATO_PAPEL = ("títulos e valores mobiliários", "titulos e valores mobiliarios")
SEGMENTO_PAPEL = ("títulos e val. mob.", "titulos e val. mob.")


def familia(mandato: str | None, segmento: str | None) -> str:
    """'Papel', 'Tijolo', 'Híbrido' ou 'Outros' — rótulo de apresentação."""
    m = (mandato or "").strip().lower()
    s = (segmento or "").strip().lower()
    if any(p in m for p in MANDATO_PAPEL) or any(p in s for p in SEGMENTO_PAPEL):
        return "Papel"
    if "híbrido" in m or "hibrido" in m or "híbrido" in s or "hibrido" in s:
        return "Híbrido"
    if m or s:
        return "Tijolo"
    return "Outros"


# ---------------------------------------------------------------------------
# Parâmetros
# ---------------------------------------------------------------------------
@dataclass
class ParamsFII:
    """Tudo o que a interface expõe, com os padrões que considero defensáveis."""

    # ---- universo -------------------------------------------------------
    liquidez_minima_diaria: float = 500_000.0   # R$/dia; FII é menos líquido que ação
    janela_liquidez_dias: int = 63              # ~3 meses de pregão
    patrimonio_minimo: float = 100_000_000.0    # R$ 100 mi: abaixo disso a taxa
                                                # de administração come o resultado
    cotistas_minimo: int = 500                  # exclui fundo de balcão/exclusivo
    excluir_fundos_exclusivos: bool = True
    meses_minimos_com_rendimento: int = 8       # nos últimos 12
    idade_minima_meses: int = 12                # sem 12 meses não há DY confiável

    # ---- indicadores ----------------------------------------------------
    # O DY dos últimos 12 meses é o número que todo mundo olha e o mais fácil de
    # distorcer: um rendimento extraordinário (venda de imóvel, ganho de capital)
    # infla o indicador por 12 meses sem nada de recorrente por trás. Por isso o
    # score usa também a MEDIANA dos 12 pagamentos, anualizada, que ignora o pico.
    janela_proventos_meses: int = 12
    janela_consistencia_meses: int = 36
    usar_dy_mediano: bool = True

    # ---- score ----------------------------------------------------------
    # Pesos dos fatores, aplicados sobre o percentil de cada um dentro do
    # universo elegível. Somam 1,0 — a interface renormaliza se o usuário mexer.
    peso_dy: float = 0.35
    peso_pvp: float = 0.30
    peso_consistencia: float = 0.20
    peso_liquidez: float = 0.15

    # ---- carteira -------------------------------------------------------
    capital: float = 100_000.0
    metodo_pesos: Literal["igual", "score", "manual"] = "igual"
    peso_maximo_ativo: float = 0.20
    max_por_segmento: float = 0.40              # concentração máxima por segmento

    def pesos_fatores(self) -> dict[str, float]:
        bruto = {"dy": self.peso_dy, "pvp": self.peso_pvp,
                 "consistencia": self.peso_consistencia,
                 "liquidez": self.peso_liquidez}
        total = sum(bruto.values()) or 1.0
        return {k: v / total for k, v in bruto.items()}

    def to_dict(self) -> dict:
        return asdict(self)
