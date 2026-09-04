"""Orquestração: da CVM e do Yahoo até a tabela pronta."""
from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from . import arquivo_informe as arquivo_informe_mod
from . import cvm_fii, indicadores, mercado, score, tickers_fii
from .config import ParamsFII

log = logging.getLogger(__name__)


def _nada(frac: float, texto: str) -> None:      # progresso silencioso
    pass


def coletar(p: ParamsFII | None = None, *, ano: int | None = None,
            usar_cache: bool = True, usar_b3: bool = False,
            por_familia: bool = False, arquivo_informe: str | None = None,
            progresso=None) -> dict:
    """Roda tudo e devolve as tabelas e os metadados da coleta.

    Com `arquivo_informe`, a CVM não é acessada: o informe e o cadastro são
    lidos do JSON gerado por `baixar_informe_fii.py` num computador no Brasil.
    É obrigatório no GitHub Actions, onde a CVM não responde — a mesma
    restrição, e a mesma solução, do lado das ações.
    """
    p = p or ParamsFII()
    prog = progresso or _nada
    ano = ano or date.today().year
    avisos: list[str] = []

    if arquivo_informe:
        prog(0.05, f"Informe do arquivo {arquivo_informe}")
        informe, cadastro = arquivo_informe_mod.importar(arquivo_informe)
        idade = arquivo_informe_mod.idade_em_dias(arquivo_informe)
        comp = arquivo_informe_mod.competencia(arquivo_informe)
        log.info("Informe lido do arquivo: %d fundos, competência %s.",
                 len(informe), comp)
        if idade is not None and idade > 45:
            avisos.append(
                f"O arquivo de informe tem {idade} dias (competência {comp}). "
                "Rode baixar_informe_fii.py de novo — patrimônio e VP/cota estão "
                "atrasados, e é o VP/cota que sustenta o P/VP.")
    else:
        prog(0.05, "Informe mensal da CVM")
        try:
            informe = cvm_fii.ler_informe(ano, usar_cache=usar_cache)
        except Exception as exc:                               # noqa: BLE001
            # Em janeiro o zip do ano corrente pode ainda não existir, e o
            # informe de dezembro está no zip do ano anterior de qualquer forma.
            log.warning("Informe de %d falhou (%s); tentando %d.", ano, exc, ano - 1)
            avisos.append(f"O informe de {ano} não estava disponível; usei o de {ano - 1}.")
            ano -= 1
            informe = cvm_fii.ler_informe(ano, usar_cache=usar_cache)

        prog(0.15, "Cadastro de fundos")
        try:
            cadastro = cvm_fii.baixar_cadastro(usar_cache=usar_cache)
        except Exception as exc:                               # noqa: BLE001
            # O `cad_fii.csv` saiu do ar (404) e só acrescentava situação
            # cadastral: a razão social vem no próprio informe. Não é motivo
            # para assustar quem está lendo o log.
            log.info("Cadastro indisponível (%s); seguindo com o informe.",
                     str(exc)[:80])
            cadastro = pd.DataFrame(columns=["CNPJ", "SITUACAO", "TIPO"])

    prog(0.25, "Códigos de negociação")
    mapa = tickers_fii.montar_mapa(informe, usar_b3=usar_b3, usar_cache=usar_cache)
    com_ticker = mapa["TICKER"].notna().sum()
    if com_ticker == 0:
        raise RuntimeError("Nenhum fundo ficou com código de negociação — "
                           "a B3 não respondeu e o ISIN não veio no informe.")
    # Só avisa se a B3 foi pedida e não entregou. O teste anterior era
    # `(ORIGEM_TICKER == "isin").all()`, que nunca dava verdadeiro: os fundos sem
    # ticker têm origem nula, e nulo não é igual a "isin" — o aviso ficou morto
    # no código enquanto a B3 devolvia lista vazia em silêncio.
    origens = mapa["ORIGEM_TICKER"].dropna()
    if usar_b3 and len(origens) and (origens == "isin").all():
        avisos.append("A API da B3 não respondeu; os códigos vieram do ISIN da CVM.")

    simbolos = tickers_fii.para_yahoo(mapa["TICKER"].dropna().unique())
    log.info("%d fundos no informe, %d com código de negociação.", len(mapa), com_ticker)

    prog(0.35, f"Cotações de {len(simbolos)} fundos")
    px = mercado.baixar_cotacoes(simbolos, usar_cache=usar_cache,
                                 progresso=lambda f, t: prog(0.35 + 0.30 * f, t))
    preco = mercado.preco_atual(px["preco"])
    liq = mercado.liquidez(px["fechamento"], px["volume"], p.janela_liquidez_dias)
    var12 = mercado.variacao(px["preco"], 12)

    negociados = [s for s in simbolos if s in px["preco"].columns]
    # Os proventos custam UMA requisição por fundo — mil fundos são mil idas ao
    # Yahoo, que demora e convida a um bloqueio por excesso de chamadas. Como
    # patrimônio, liquidez e número de cotistas já bastam para saber quem nunca
    # entraria no ranking, o corte vem antes da coleta: sobram algumas centenas
    # em vez de mais de mil. Quem é cortado aqui aparece na aba "Excluídos" com
    # o motivo certo, porque esses filtros são avaliados antes do de rendimento.
    negociados = _com_chance(mapa, negociados, preco, liq, p)
    prog(0.70, f"Rendimentos de {len(negociados)} fundos")
    prov = mercado.baixar_proventos(negociados, meses=p.janela_consistencia_meses,
                                    usar_cache=usar_cache,
                                    progresso=lambda f, t: prog(0.70 + 0.20 * f, t))
    resumo = mercado.resumo_proventos(prov, janela=p.janela_proventos_meses,
                                      janela_longa=p.janela_consistencia_meses)

    prog(0.92, "Indicadores")
    tabela = indicadores.montar(mapa, cadastro, preco, liq, var12, resumo)
    elegiveis, excluidos = indicadores.filtrar(tabela, p)
    ranking = score.calcular(elegiveis, p, por_familia=por_familia)
    ranking["ALERTA"] = score.alertas(ranking)

    prog(1.0, "Pronto")
    return {
        "ranking": ranking,
        "excluidos": excluidos,
        "proventos": prov,
        "mensal": mercado.mensalizar(prov),
        "meta": {
            "gerado_em": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "competencia_informe": _competencia(informe),
            "ano_informe": ano,
            "fundos_no_informe": int(len(mapa)),
            "fundos_com_ticker": int(com_ticker),
            "fundos_com_cotacao": int(preco.notna().sum()),
            "elegiveis": int(len(elegiveis)),
            "excluidos": int(len(excluidos)),
            "origem_ticker_b3": int((mapa["ORIGEM_TICKER"] == "b3").sum()),
            "origem_informe": ("arquivo" if arquivo_informe else "cvm"),
            "idade_informe_dias": (arquivo_informe_mod.idade_em_dias(arquivo_informe)
                                   if arquivo_informe else 0),
            "avisos": avisos,
            "demo": False,
        },
    }


def _com_chance(mapa: pd.DataFrame, negociados: list[str], preco: pd.Series,
                liq: pd.Series, p: ParamsFII) -> list[str]:
    """Fundos que ainda podem entrar no ranking depois dos filtros de tamanho.

    Só olha o que já está em mãos — patrimônio e cotistas vêm do informe, preço
    e liquidez do lote de cotações. Nada aqui depende de provento, que é
    justamente o que se quer evitar baixar à toa.
    """
    if not negociados:
        return []
    chave = mapa["TICKER"].astype("string").str.upper() + ".SA"
    pl = pd.to_numeric(mapa.get("PL"), errors="coerce").fillna(0.0)
    cotistas = pd.to_numeric(mapa.get("COTISTAS"), errors="coerce").fillna(0.0)
    liquidez = chave.map(liq).fillna(0.0)
    preco_ok = chave.map(preco).fillna(0.0)

    passa = ((pl >= p.patrimonio_minimo) & (cotistas >= p.cotistas_minimo)
             & (liquidez >= p.liquidez_minima_diaria) & (preco_ok > 0))
    escolhidos = set(chave[passa].dropna())
    restantes = [t for t in negociados if t in escolhidos]
    log.info("Proventos: %d de %d fundos passam nos filtros de tamanho.",
             len(restantes), len(negociados))
    return restantes


def _competencia(informe: pd.DataFrame) -> str:
    if "COMPETENCIA" not in informe.columns or informe.empty:
        return ""
    return str(informe["COMPETENCIA"].dropna().max() or "")
