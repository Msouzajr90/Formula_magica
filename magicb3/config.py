"""Parâmetros centrais da plataforma."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Códigos de conta do plano padronizado da CVM
# ---------------------------------------------------------------------------
# DRE
CD_RECEITA_LIQUIDA = "3.01"
CD_EBIT = "3.05"           # Resultado Antes do Resultado Financeiro e dos Tributos
CD_LUCRO_LIQUIDO = "3.11"  # Lucro/Prejuízo Consolidado do Período
CD_LPA_BASICO_ON = "3.99.01.01"

# BPA (Ativo)
CD_ATIVO_TOTAL = "1"
CD_ATIVO_CIRCULANTE = "1.01"
CD_CAIXA = "1.01.01"                 # Caixa e Equivalentes de Caixa
CD_APLIC_FINANCEIRAS = "1.01.02"     # Aplicações Financeiras (circulante)
CD_IMOBILIZADO = "1.02.03"
CD_INTANGIVEL = "1.02.04"

# BPP (Passivo)
CD_PASSIVO_CIRCULANTE = "2.01"
CD_EMPRESTIMOS_CP = "2.01.04"
CD_PASSIVO_NAO_CIRC = "2.02"
CD_EMPRESTIMOS_LP = "2.02.01"
CD_PATRIMONIO_LIQUIDO = "2.03"

# Setores que Greenblatt manda excluir: bancos, seguradoras e utilities.
# Em instituições financeiras, "dívida" é matéria-prima e não financiamento,
# então ROIC e EV perdem o sentido econômico. Em utilities, o capital é
# regulado e o ROIC é administrativamente fixado.
# Padrões em regex (case-insensitive) casados contra SETOR_ATIV da CVM
# e contra o segmento da B3.
SETORES_EXCLUIDOS_PADRAO = (
    r"banco",
    r"seguro|seguradora|resseguro",
    r"previd[êe]ncia|capitaliza[çc][ãa]o",
    r"intermedia[çc][ãa]o financeira|financeiras?\b",
    r"arrendamento mercantil",
    r"securitiza",
    r"cr[ée]dito imobili[áa]rio",
    r"bolsa de valores|valores mobili[áa]rios",
    r"energia el[ée]trica",
    r"[áa]gua e saneamento|saneamento",
    r"^g[áa]s\b|distribui[çc][ãa]o de g[áa]s",
    r"utilidade p[úu]blica",
)

CACHE_DIR = Path.home() / ".magicb3_cache"


@dataclass
class Params:
    """Todos os parâmetros que a interface expõe."""

    # ---- universo -------------------------------------------------------
    liquidez_minima_diaria: float = 1_000_000.0   # R$/dia, média dos últimos 3 meses
    janela_liquidez_dias: int = 63                # ~3 meses de pregão
    excluir_setores: tuple[str, ...] = SETORES_EXCLUIDOS_PADRAO
    apenas_um_ticker_por_empresa: bool = True     # evita PETR3+PETR4 na mesma carteira
    exigir_ebit_positivo: bool = True
    exigir_ev_positivo: bool = True

    # ---- fórmula mágica -------------------------------------------------
    n_acoes_ranking: int = 30                     # Greenblatt sugere 20-30
    base_roic: Literal["capital_tangivel", "ativo_total", "patrimonio_liquido"] = "capital_tangivel"
    base_ey: Literal["ebit_ev", "lucro_preco", "lpa_original_tcc"] = "ebit_ev"
    usar_ltm: bool = True                         # 12 meses móveis (DFP + ITR)

    # ---- Markowitz ------------------------------------------------------
    janela_retornos_dias: int = 252               # 1 ano de pregão
    metodo_covariancia: Literal["ledoit_wolf", "hist", "ewma"] = "ledoit_wolf"
    metodo_retorno: Literal["hist", "ewma", "media_ponderada"] = "ewma"
    peso_maximo_ativo: float = 0.15
    peso_minimo_ativo: float = 0.0
    permitir_venda_descoberta: bool = False
    n_carteiras_fronteira: int = 20
    taxa_livre_risco_aa: float = 0.105            # ~Selic; usada só para Sharpe

    # ---- backtest -------------------------------------------------------
    custo_transacao_bps: float = 15.0             # 0,15% por ponta (corretagem+emolumentos+slippage)
    defasagem_publicacao_dias: int = 0            # 0 = usa a última demonstração divulgada
    rebalance: Literal["anual", "semestral", "trimestral"] = "anual"
    benchmark: str = "^BVSP"

    def to_dict(self) -> dict:
        return asdict(self)
