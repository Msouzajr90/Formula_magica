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
# Papel, tijolo e fundo de fundos
# ---------------------------------------------------------------------------
# A classificação NÃO usa o rótulo da CVM, e a razão é empírica: na competência
# 07/2026 a coluna `Mandato` veio vazia nos 1.343 fundos, e o `Segmento_Atuacao`
# trocou de vocabulário — "Títulos e Val. Mob." deixou de existir e 637 fundos
# caíram em "Multicategoria". Qualquer classificador baseado nesses campos
# rotularia o mercado inteiro como tijolo, MXRF11 e KNCR11 incluídos.
#
# Em vez do rótulo, olhamos a carteira: o informe de ativo e passivo diz quanto
# de cada fundo está em imóveis, em recebíveis e em cotas de outros fundos. É um
# critério melhor mesmo que o rótulo voltasse a ser preenchido — mede onde o
# dinheiro está, e não como o fundo se declara.
#
# Grupos de contas do `inf_mensal_fii_ativo_passivo`:
CONTAS_IMOVEIS = ("Direitos_Bens_Imoveis",)
CONTAS_PAPEL = ("CRI", "CRI_CRA", "Letras_Hipotecarias", "LCI", "LCI_LCA", "LIG",
                "Debentures", "Cedulas_Debentures", "Notas_Promissorias")
CONTAS_FOF = ("FII", "Outras_Cotas_FI", "Fundo_Acoes", "FDIC")
CONTA_TOTAL_INVESTIDO = "Total_Investido"
CONTA_CAIXA = "Total_Necessidades_Liquidez"

# Acima desta fatia da carteira o fundo é considerado "puro" daquele tipo.
# 65% é uma escolha: separa bem os casos conhecidos (KNRI11 92% imóveis vira
# tijolo, XPML11 com 56% imóveis e 30% em cotas de outros FII vira híbrido) sem
# criar uma categoria "híbrido" que engula metade do mercado.
LIMITE_CONCENTRACAO = 0.65


def familia(pct_imoveis, pct_papel, pct_fof) -> str:
    """'Tijolo', 'Papel', 'Fundo de fundos', 'Híbrido' ou 'Sem dado'.

    Recebe as fatias da carteira, não rótulos. Ausência de dado devolve
    'Sem dado' em vez de chutar — 65 dos 1.343 fundos não informam a carteira,
    e colocá-los em qualquer grupo sujaria o ranking daquele grupo.
    """
    try:
        i, p, f = float(pct_imoveis), float(pct_papel), float(pct_fof)
    except (TypeError, ValueError):
        return "Sem dado"
    if not (i == i and p == p and f == f):        # NaN
        return "Sem dado"
    if i >= LIMITE_CONCENTRACAO:
        return "Tijolo"
    if p >= LIMITE_CONCENTRACAO:
        return "Papel"
    if f >= LIMITE_CONCENTRACAO:
        return "Fundo de fundos"
    return "Híbrido"


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


# ---------------------------------------------------------------------------
# Fiagro
# ---------------------------------------------------------------------------
# A CVM publica o informe de Fiagro num dataset separado, com um zip por
# COMPETÊNCIA (e não por ano, como o de FII) e uma única tabela larga em vez das
# três do FII. O conteúdo é equivalente: patrimônio, cotas, VP/cota, cotistas,
# ISIN e a carteira aberta.
INF_MENSAL_FIAGRO = ("https://dados.cvm.gov.br/dados/FIAGRO/DOC/INF_MENSAL/DADOS"
                     "/inf_mensal_fiagro_{comp}.zip")

# Contas do informe de Fiagro, agrupadas como as do FII. A carteira de um Fiagro
# é quase toda crédito do agronegócio — CRA, CPR, CDCA — que é o análogo do CRI
# num fundo de papel. Terra e participação societária fazem o papel do imóvel.
CONTAS_FIAGRO_IMOVEIS = ("Imoveis_Rurais", "Participacoes_Societarias")
CONTAS_FIAGRO_PAPEL = (
    "CRA", "CRI", "Outros_Titulos_Securitizacao",
    "CPR", "CDCA", "Outros_Titulos_Credito_Agronegocio",
    "Debentures", "Notas_Comerciais", "Outros_Titulos_Divida_Corporativa",
    "Demais_Direitos_Creditorios",
)
CONTAS_FIAGRO_FOF = ("Cotas_Fundos_Investimento",)
CONTA_FIAGRO_TOTAL = "Total_Investido"

# Como o fundo aparece na tela. É informação, não critério de ranking: os três
# entram no mesmo grupo de crédito (ver `FAMILIA_DE_CREDITO`), porque seguram
# dívida, pagam todo mês e têm o patrimônio marcado a mercado. O que muda é o
# lastro e a lei da isenção, e isso o usuário precisa enxergar.
TIPO_FII = "FII"
TIPO_FIAGRO = "Fiagro"
TIPO_FIINFRA = "FI-Infra"

# Fiagro e FI-Infra são ranqueados junto com os FII de papel.
FAMILIA_DE_CREDITO = "Papel"


def familia_do_fundo(tipo, pct_imoveis, pct_papel, pct_fof) -> str:
    """A família usada no ranking, considerando o tipo de veículo.

    Fiagro e FI-Infra vão para o grupo de papel por decisão, não por medida da
    carteira. A razão é que o ranking compara P/VP, e P/VP só é comparável entre
    fundos cujo patrimônio é apurado do mesmo jeito: os três seguram dívida
    marcada a mercado e pagam todo mês, enquanto um fundo de tijolo carrega
    laudo anual. Ranquear um Fiagro contra uma laje corporativa mistura duas
    escalas — é o mesmo motivo pelo qual o ranking pode ser rodado por família.

    A composição continua exportada (PCT_IMOVEIS/PAPEL/FOF), então um Fiagro de
    terra aparece na tela com a carteira que tem; o que ele não faz é mudar de
    lista. E `TIPO_FUNDO` fica visível na tabela, para ninguém confundir a
    isenção de IR de um FII com a de um FI-Infra, que vem de lei diferente.
    """
    t = "" if tipo is None else str(tipo).strip()
    if t in (TIPO_FIAGRO, TIPO_FIINFRA):
        return FAMILIA_DE_CREDITO
    return familia(pct_imoveis, pct_papel, pct_fof)


# ---------------------------------------------------------------------------
# FI-Infra
# ---------------------------------------------------------------------------
# O FI-Infra (fundo incentivado de investimento em infraestrutura, art. 3º da
# Lei 12.431) não tem informe mensal próprio: ele é um FI comum aos olhos da
# CVM, e o que existe dele é o INFORME DIÁRIO — cota, patrimônio e cotistas,
# um arquivo por competência.
#
# E há um problema que não se resolve com dado aberto: **nenhum arquivo da CVM
# liga o CNPJ do fundo ao código de negociação na B3**. O `cad_fi.csv` não tem
# ISIN; o `registro_fundo_classe.zip` (cadastro novo, pós-Resolução 175) traz
# `Codigo_CVM`, que é o número de registro, não o ticker. Foi verificado nos
# três CSVs do zip, 136 mil linhas: não há ISIN nem código de negociação.
#
# Por isso o FI-Infra entra por uma LISTA (`fiinfra.csv`) — e a lista é
# conferida por máquina a cada execução, ver `fiib3/fiinfra.py`.
INF_DIARIO_FI = ("https://dados.cvm.gov.br/dados/FI/DOC/INF_DIARIO/DADOS"
                 "/inf_diario_fi_{comp}.zip")
REGISTRO_FUNDO_CLASSE = ("https://dados.cvm.gov.br/dados/FI/CAD/DADOS"
                         "/registro_fundo_classe.zip")

# Situação cadastral aceitável para um fundo entrar no universo.
SITUACAO_ATIVA = "EM FUNCIONAMENTO NORMAL"

# Rótulo de segmento dos FI-Infra na tela. Eles não têm "segmento de atuação"
# no sentido do FII; o que descreve o fundo é o lastro.
SEGMENTO_FIINFRA = "Debêntures incentivadas"
