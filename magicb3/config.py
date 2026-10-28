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
# Mesma história do patrimônio líquido: o plano de contas dos bancos usa outra
# numeração. Itaú, BTG, BMG e Inter não têm 3.11 — sem estes candidatos, a
# linha do lucro é descartada JÁ NA LEITURA do arquivo da CVM e nenhuma busca
# posterior consegue encontrá-la.
CD_LUCRO_CANDIDATOS = ("3.07", "3.08", "3.09", "3.10", "3.11", "3.12", "3.13")
DS_LUCRO_LIQUIDO = "lucro/prejuízo consolidado do período"
DS_LUCRO_ALTERNATIVAS = ("lucro/prejuízo do período",
                         "resultado líquido do período",
                         "lucro ou prejuízo líquido consolidado do período")
CD_LPA_BASICO_ON = "3.99.01.01"

# BPA (Ativo)
CD_ATIVO_TOTAL = "1"
CD_ATIVO_CIRCULANTE = "1.01"
CD_CAIXA = "1.01.01"                 # Caixa e Equivalentes de Caixa
CD_APLIC_FINANCEIRAS = "1.01.02"     # Aplicações Financeiras (circulante)
CD_INVESTIMENTOS = "1.02.02"   # inclui propriedades para investimento (shoppings, imóveis)
CD_IMOBILIZADO = "1.02.03"
CD_INTANGIVEL = "1.02.04"

# BPP (Passivo)
CD_PASSIVO_CIRCULANTE = "2.01"
CD_EMPRESTIMOS_CP = "2.01.04"
CD_PASSIVO_NAO_CIRC = "2.02"
CD_EMPRESTIMOS_LP = "2.02.01"
CD_PATRIMONIO_LIQUIDO = "2.03"   # nas financeiras é "Provisões"; o PL fica em 2.07
# Bancos e seguradoras usam outro plano de contas com os MESMOS códigos. A
# descrição, porém, é idêntica nos dois — por isso o PL é localizado por ela.
DS_PATRIMONIO_LIQUIDO = "patrimônio líquido consolidado"
# Códigos onde o PL pode aparecer conforme o plano de contas. Precisam ser
# LIDOS do CSV para que a busca por descrição tenha o que encontrar — o filtro
# de contas na leitura é aplicado antes. Medido no ITR de 06/2026: 410 empresas
# em 2.03, 7 em 2.07 (Banco do Brasil, Bradesco) e 5 em 2.08 (Itaú).
CD_PL_CANDIDATOS = ("2.03", "2.04", "2.05", "2.06", "2.07", "2.08", "2.09")

# Setores que Greenblatt manda excluir: bancos, seguradoras e utilities.
# Em instituições financeiras, "dívida" é matéria-prima e não financiamento,
# então ROIC e EV perdem o sentido econômico. Em utilities, o capital é
# regulado e o ROIC é administrativamente fixado.
# Padrões em regex (case-insensitive) casados contra SETOR_ATIV da CVM
# e contra o segmento da B3.
SETORES_FINANCEIROS = (
    r"banco",
    r"seguro|seguradora|resseguro",
    r"previd[êe]ncia|capitaliza[çc][ãa]o",
    r"intermedia[çc][ãa]o financeira|financeiras?\b",
    r"arrendamento mercantil",
    r"securitiza",
    r"cr[ée]dito imobili[áa]rio",
    # "Bolsas", no plural: é como a CVM grafa o setor da B3 S.A. ("Bolsas de
    # Valores/Mercadorias e Futuros"). Com "bolsa de valores" no singular o
    # padrão nunca casou, e a B3 entrava no ranking como empresa operacional.
    r"bolsas? de valores|valores mobili[áa]rios",
)

# Concessionárias. Greenblatt as exclui junto das financeiras, mas por outro
# motivo: aqui ROIC e EV até fazem sentido contábil: o que não faz sentido é a
# leitura. O retorno sobre capital de uma concessionária é fixado pelo regulador
# sobre a base de ativos regulatória, então um ROIC alto costuma indicar uma
# revisão tarifária favorável, não vantagem competitiva durável. No Brasil o
# grupo é grande e líquido, então vale poder incluí-lo por escolha explícita.
SETORES_UTILIDADE_PUBLICA = (
    r"energia el[ée]trica",
    r"[áa]gua e saneamento|saneamento",
    r"^g[áa]s\b|distribui[çc][ãa]o de g[áa]s",
    r"utilidade p[úu]blica",
)

SETORES_EXCLUIDOS_PADRAO = SETORES_FINANCEIROS + SETORES_UTILIDADE_PUBLICA

# Concessões de infraestrutura. Pela ICPC 01, a rodovia, o aeroporto ou a rede
# de água de uma concessão não vão para o imobilizado: são registrados como
# INTANGÍVEL (direito de cobrar do usuário). A fórmula do livro, que só olha
# imobilizado, enxerga então uma concessionária sem ativo — a Ecorodovias, com
# R$ 29 bi de rodovias no intangível e R$ 0,8 bi de imobilizado, saía com ROIC
# de 529% em 06/2026; com a concessão no capital, 14%.
#
# O setor sozinho não basta: "Serviços Transporte e Logística" também abriga
# locadoras e operadores logísticos, cujo intangível é ágio de aquisição — e
# ágio continua fora, como manda Greenblatt. Por isso a regra exige também que
# o intangível seja o maior ativo de longo prazo (maior que imobilizado +
# investimentos). Medido em 06/2026: Ecorodovias 73% x 2% do ativo, Motiva
# 50% x 3%; Rumo 12% x 49%, Localiza 10% x 62%, Tegma 14% x 31% (ficam fora).
SETORES_CONCESSAO = (
    r"transporte",
    r"rodovi|ferrovi|aeroport|portu[áa]ri",
) + SETORES_UTILIDADE_PUBLICA

# Exclusões caso a caso, por prefixo de negociação. São decisões de método,
# não filtros automáticos: cada uma carrega um motivo curto (vai para a coluna
# "Motivo" das excluídas) e uma nota que o site mostra junto do ranking.
EXCLUSOES_MANUAIS: dict[str, tuple[str, str]] = {
    "B3SA": (
        "fora do ranking por decisão de método (ver nota)",
        "A B3 opera com sistemas, marca e efeito de rede, não com capital "
        "tangível: o imobilizado é uma fração mínima do que ela usa, e mais da "
        "metade do ativo é o ágio da fusão com a Cetip, que a fórmula exclui. "
        "O ROIC do livro fica na casa das centenas por cento e garante o 1º "
        "lugar sem dizer nada sobre a qualidade do negócio em relação às "
        "demais. Além disso, pela CVM ela é do setor de bolsas de valores, que "
        "o filtro de financeiras já pretendia tirar.",
    ),
}

# Quantas ações formam uma unit. O preço de uma unit é o de várias ações; com o
# nº TOTAL de ações da companhia, o valor de mercado é preço × ações ÷ fator.
# Sem isto a KLBN11 valia R$ 115 bi em vez de R$ 23 bi (cinco vezes) e a
# BPAC11 R$ 700 bi em vez de R$ 232 bi. Não há fonte pública desses fatores
# num arquivo só, e eles mudam raramente; unit fora da lista fica sem valor de
# mercado — o erro silencioso é pior que o buraco declarado.
ACOES_POR_UNIT = {
    "ALUP11": 3,    # Alupar:      1 ON + 2 PN
    "BPAC11": 3,    # BTG Pactual: 1 ON + 2 PN
    "ENGI11": 5,    # Energisa:    1 ON + 4 PN
    "IGTI11": 3,    # Iguatemi:    1 ON + 2 PN
    "KLBN11": 5,    # Klabin:      1 ON + 4 PN
    "SANB11": 2,    # Santander:   1 ON + 1 PN
    "TAEE11": 3,    # Taesa:       1 ON + 2 PN
}

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
    incluir_investimentos: bool = True   # soma 1.02.02 ao capital tangível
    incluir_intangivel_concessao: bool = True  # soma 1.02.04 nas concessionárias
    base_ey: Literal["ebit_ev", "lucro_preco", "lpa_original_tcc"] = "ebit_ev"
    usar_ltm: bool = True                         # 12 meses móveis (DFP + ITR)

    # ---- financeiras ----------------------------------------------------
    # Bancos e seguradoras não têm ROIC nem EV com sentido econômico, então são
    # ranqueados à parte por ROE e Lucro/Preço. A cota abaixo é quantas vagas da
    # carteira ficam com eles — escolha do investidor, sem base teórica.
    vagas_financeiras: int = 0
    # Idem para concessionárias: ranqueadas entre si, cota explícita.
    vagas_utilidades: int = 0

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
