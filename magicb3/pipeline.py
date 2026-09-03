"""Orquestração: do dado bruto até a carteira sugerida."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import config as C
from . import arquivo_fundamentos as arqf
from . import cvm, fundamentals, optimizer, prices, ranking, tickers

log = logging.getLogger(__name__)

CONTAS_BP = [
    C.CD_ATIVO_TOTAL, C.CD_ATIVO_CIRCULANTE, C.CD_CAIXA, C.CD_APLIC_FINANCEIRAS,
    C.CD_PASSIVO_CIRCULANTE, C.CD_EMPRESTIMOS_CP, C.CD_EMPRESTIMOS_LP,
    C.CD_INVESTIMENTOS, C.CD_IMOBILIZADO, C.CD_INTANGIVEL, C.CD_PATRIMONIO_LIQUIDO,
]

# Únicos códigos que precisam sair dos CSVs da CVM — tudo o mais é descartado
# durante a leitura, para o processo caber na memória do Streamlit Cloud.
CONTAS_USADAS = (set(CONTAS_BP) | set(C.CD_PL_CANDIDATOS)
                 | set(C.CD_LUCRO_CANDIDATOS)
                 | {C.CD_EBIT, C.CD_LUCRO_LIQUIDO, C.CD_LPA_BASICO_ON})


@dataclass
class Resultado:
    ranking: pd.DataFrame
    selecionadas: pd.DataFrame
    rejeitadas: pd.DataFrame
    pesos: pd.Series
    fronteira: optimizer.Fronteira
    retornos: pd.DataFrame
    mu: pd.Series
    cov: pd.DataFrame
    diagnostico: dict = field(default_factory=dict)


def _nada(msg: str, pct: float | None = None) -> None:  # callback padrão
    log.info(msg)


def montar_universo(params: C.Params, *, anos: list[int] | None = None,
                    progresso=_nada, usar_cache: bool = True,
                    arquivo_fundamentos: str | None = None) -> pd.DataFrame:
    """Universo investível com ROIC e EY calculados.

    `arquivo_fundamentos` aponta para um fundamentos.json já baixado. Com ele,
    a CVM não é acessada — o que é obrigatório em servidores fora do Brasil,
    onde `dados.cvm.gov.br` recusa conexões. Ver `baixar_fundamentos.py`.
    """
    hoje = date.today()
    anos = anos or [hoje.year, hoje.year - 1, hoje.year - 2]
    setores_arquivo = pd.DataFrame()

    if arquivo_fundamentos:
        progresso("Lendo fundamentos do arquivo (sem acessar a CVM)...", 0.10)
        ebit, bp, setores_arquivo = arqf.importar(arquivo_fundamentos)
        acoes_cvm = (ebit[["CD_CVM", "ACOES_CVM"]].dropna()
                     if "ACOES_CVM" in ebit.columns else pd.DataFrame())
        idade = arqf.idade_em_dias(arquivo_fundamentos)
        if idade is not None and idade > 120:
            log.warning("fundamentos.json tem %d dias — rode baixar_fundamentos.py "
                        "de novo num computador no Brasil.", idade)
        progresso("Baixando lista de companhias listadas (B3)...", 0.20)
        empresas = tickers.baixar_empresas_b3(usar_cache=usar_cache)
        if not setores_arquivo.empty:
            empresas = empresas.merge(setores_arquivo, on="CD_CVM", how="left")
        elif "SETOR" not in empresas.columns:
            empresas["SETOR"] = pd.NA
    else:
        progresso("Baixando cadastro de companhias abertas (CVM)...", 0.05)
        cadastro = cvm.carregar_cadastro(usar_cache=usar_cache)

        progresso("Baixando lista de companhias listadas (B3)...", 0.12)
        empresas = tickers.baixar_empresas_b3(usar_cache=usar_cache)
        empresas = tickers.mapa_setorial(empresas, cadastro)

        progresso("Baixando demonstrações anuais (DFP)...", 0.25)
        dfp = cvm.carregar_demonstracoes(anos, tipo="dfp", usar_cache=usar_cache,
                                         contas=CONTAS_USADAS)

        progresso("Baixando demonstrações trimestrais (ITR)...", 0.40)
        itr = (cvm.carregar_demonstracoes(anos, tipo="itr", usar_cache=usar_cache,
                                          contas=CONTAS_USADAS)
               if params.usar_ltm else {"DRE": pd.DataFrame(), "BPA": pd.DataFrame(),
                                        "BPP": pd.DataFrame()})

        progresso("Calculando EBIT dos últimos 12 meses...", 0.50)
        ebit = cvm.ebit_ltm(dfp["DRE"], itr.get("DRE", pd.DataFrame()), C.CD_EBIT)

        progresso("Lendo composição do capital (nº de ações)...", 0.52)
        try:
            cap = cvm.composicao_capital(anos, usar_cache=usar_cache)
            acoes_cvm = (cap.merge(ebit[["CNPJ_CIA", "CD_CVM"]].drop_duplicates(),
                                   on="CNPJ_CIA", how="inner")[["CD_CVM", "ACOES"]]
                         .rename(columns={"ACOES": "ACOES_CVM"}).dropna())
        except Exception as exc:                                # noqa: BLE001
            log.warning("composição do capital indisponível: %s", exc)
            acoes_cvm = pd.DataFrame()

        progresso("Consolidando balanços...", 0.55)
        bpa = pd.concat([dfp["BPA"], itr.get("BPA", pd.DataFrame())], ignore_index=True)
        bpp = pd.concat([dfp["BPP"], itr.get("BPP", pd.DataFrame())], ignore_index=True)
        bp = cvm.balanco_mais_recente(bpa, bpp, CONTAS_BP)

        # Métricas das financeiras: lucro líquido de 12 meses e patrimônio
        # líquido localizado pela descrição (o código muda entre planos).
        lucro = cvm.ebit_ltm(cvm.marcar_lucro_liquido(dfp["DRE"]),
                             cvm.marcar_lucro_liquido(itr.get("DRE", pd.DataFrame())),
                             "LL")[["CD_CVM", "EBIT_LTM"]]
        lucro = lucro.rename(columns={"EBIT_LTM": "LUCRO_LTM"})
        log.info("lucro líquido localizado em %d companhias", len(lucro))
        ebit = ebit.merge(lucro, on="CD_CVM", how="left")
        bp = bp.merge(cvm.patrimonio_liquido(bpp), on="CD_CVM", how="left")

    progresso("Baixando cotações da B3...", 0.65)
    cand = tickers.candidatos_de_ticker(empresas[empresas["CD_CVM"].isin(ebit["CD_CVM"])])
    hist = prices.baixar_historico(
        cand["TICKER"].tolist(),
        hoje - timedelta(days=int(params.janela_retornos_dias * 1.6)),
        hoje, usar_cache=usar_cache)

    px = hist["preco"].dropna(axis=1, how="all")
    validos = prices.tickers_validos(px, min_pregoes=max(60, params.janela_liquidez_dias))
    px = px[validos]
    liq = prices.liquidez_media_diaria(hist["fechamento"][validos],
                                       hist["volume"][validos],
                                       janela=params.janela_liquidez_dias)

    # Aplica o corte de liquidez ANTES de buscar o nº de ações: essa consulta é
    # uma chamada HTTP por ticker, então rodá-la sobre 1.500 candidatos levaria
    # dezenas de minutos. Depois do filtro sobram algumas centenas.
    liquidos = [t for t in validos
                if float(liq.get(t, 0) or 0) >= params.liquidez_minima_diaria]
    if not liquidos:                       # filtro zerou tudo: segue sem cortar
        log.warning("Nenhum ticker passou no filtro de liquidez; usando todos.")
        liquidos = validos
    ultimo_preco = px.ffill().iloc[-1]
    mercado = pd.DataFrame({
        "TICKER": liquidos,
        "PRECO": ultimo_preco.reindex(liquidos).values,
        "LIQUIDEZ_MEDIA": liq.reindex(liquidos).values,
    })
    mercado = mercado.merge(cand[["TICKER", "CD_CVM"]].drop_duplicates(),
                            on="TICKER", how="left")

    # Nº de ações: a CVM é a fonte preferida porque vem junto com os dados já
    # baixados. O Yahoo cobra uma requisição por empresa e foi ele que estourou
    # o limite em produção, zerando o valor de mercado de todo mundo.
    if len(acoes_cvm):
        mercado = mercado.merge(acoes_cvm.drop_duplicates("CD_CVM"),
                                on="CD_CVM", how="left")
    else:
        mercado["ACOES_CVM"] = np.nan

    faltando = mercado.loc[mercado["ACOES_CVM"].isna(), "TICKER"].tolist()
    n_yahoo = pd.Series(dtype=float)
    if faltando:
        progresso(f"Nº de ações: {len(mercado)-len(faltando)} da CVM, "
                  f"{len(faltando)} a buscar no Yahoo...", 0.82)
        n_yahoo = prices.acoes_em_circulacao(faltando, usar_cache=usar_cache)

    mercado["ACOES"] = mercado["ACOES_CVM"].fillna(
        mercado["TICKER"].map(n_yahoo) if len(n_yahoo) else np.nan)
    mercado["VALOR_MERCADO"] = mercado["PRECO"] * mercado["ACOES"]

    n_cvm = int(mercado["ACOES_CVM"].notna().sum())
    n_tot = int(mercado["ACOES"].notna().sum())
    log.info("nº de ações: %d da CVM + %d do Yahoo = %d de %d empresas",
             n_cvm, n_tot - n_cvm, n_tot, len(mercado))
    if n_tot == 0:
        raise ValueError(
            f"Nenhuma das {len(mercado)} empresas líquidas ficou com número de "
            "ações, então o valor de mercado não pôde ser calculado. A CVM não "
            "trouxe a composição do capital e o Yahoo não respondeu — este "
            "último costuma ser limite de requisições. Tente de novo mais tarde.")
    mercado = mercado.merge(empresas[["CD_CVM", "SETOR", "SEGMENTO"]].drop_duplicates("CD_CVM"),
                            on="CD_CVM", how="left")
    mercado = mercado.dropna(subset=["CD_CVM", "VALOR_MERCADO"])

    progresso("Calculando ROIC e Earnings Yield...", 0.88)
    return fundamentals.montar_indicadores(ebit, bp, mercado, params)


def montar_carteira(params: C.Params, *, progresso=_nada, usar_cache: bool = True,
                    arquivo_fundamentos: str | None = None) -> Resultado:
    universo = montar_universo(params, progresso=progresso, usar_cache=usar_cache,
                               arquivo_fundamentos=arquivo_fundamentos)
    aprovados, rejeitados = fundamentals.aplicar_filtros(universo, params)

    rk = ranking.ranquear(aprovados, n=params.n_acoes_ranking,
                          vagas_financeiras=params.vagas_financeiras,
                          vagas_utilidades=params.vagas_utilidades)
    selec = rk[rk["SELECIONADA"]].copy()

    progresso("Otimizando a carteira (Markowitz)...", 0.93)
    lista = selec["TICKER"].tolist()
    hoje = date.today()
    hist = prices.baixar_historico(
        lista, hoje - timedelta(days=int(params.janela_retornos_dias * 1.6)), hoje,
        usar_cache=usar_cache)
    px = hist["preco"][[t for t in lista if t in hist["preco"].columns]]
    px = px[prices.tickers_validos(px)]
    rets = prices.retornos(px).tail(params.janela_retornos_dias)

    mu, cov = optimizer.estimar(rets, params.metodo_retorno, params.metodo_covariancia)
    fr = optimizer.fronteira_eficiente(
        mu, cov, pontos=params.n_carteiras_fronteira,
        w_max=params.peso_maximo_ativo, w_min=params.peso_minimo_ativo,
        rf=params.taxa_livre_risco_aa)
    pesos = optimizer.limpar_pesos(fr.pesos.iloc[:, 0])

    progresso("Pronto.", 1.0)
    return Resultado(
        ranking=rk, selecionadas=selec, rejeitadas=rejeitados,
        pesos=pesos, fronteira=fr, retornos=rets, mu=mu, cov=cov,
        diagnostico={
            "universo_bruto": len(universo),
            "aprovados_nos_filtros": len(aprovados),
            "rejeitados": len(rejeitados),
            "com_serie_de_precos": int(px.shape[1]),
            "data_base_mediana": (str(pd.to_datetime(selec["DT_BASE"]).median().date())
                                  if "DT_BASE" in selec and len(selec) else None),
            "financeiras_na_carteira": int((selec.get("TIPO") == "financeira").sum())
                                      if "TIPO" in selec.columns else 0,
            "gerado_em": str(pd.Timestamp.now()),
        },
    )
