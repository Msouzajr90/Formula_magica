# -*- coding: utf-8 -*-
"""Gera o `web/public/mercado.json` — a aba de indicadores de mercado.

Três blocos independentes. Se o P/VP falhar, as curvas de juros são
publicadas mesmo assim, com o aviso no arquivo; o contrário também vale. Um
indicador fora do ar não deve derrubar os outros dois — foi o que aconteceu
com os FIIs quando uma fonte mudou de contrato e a coleta inteira morreu.

Uso:
    python atualizar_mercado.py                # tudo
    python atualizar_mercado.py --sem-pvp      # só as curvas de juros
    python atualizar_mercado.py --demo         # números sorteados, para ver a tela
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).parent
SAIDA = RAIZ / "web" / "public" / "mercado.json"
CARTEIRA = RAIZ / "web" / "public" / "ibov_carteira.json"
HISTORICO_PVP = RAIZ / "web" / "public" / "pvp_historico.json"
MAPA_CVM = RAIZ / "web" / "public" / "mapa_cvm.json"
HISTORICO_SPREAD = RAIZ / "web" / "public" / "spread_historico.json"
FUNDAMENTOS = RAIZ / "web" / "public" / "fundamentos.json"

log = logging.getLogger("mercado")


# ---------------------------------------------------------------------------
# Juros
# ---------------------------------------------------------------------------
def coletar_juros(sessao, hoje: date | None = None,
                  com_historico: bool = True,
                  avisos: list[str] | None = None) -> dict:
    """As quatro fotos da curva e, de quebra, a série do spread no tempo.

    As duas coisas saem do mesmo download. O CSV do Tesouro tem 21 anos e os
    do Treasury são um por ano — baixar os 22 anos custa algumas dezenas de
    segundos a mais e dá a série histórica inteira, sem nada a acumular entre
    execuções. Ela é reescrita do zero todo dia: um erro corrigido no cálculo
    conserta o passado na execução seguinte.
    """
    from mercado import arquivo, bcb, historico, tesouro, treasury

    log.info("Baixando o CSV do Tesouro Transparente…")
    td = tesouro.ler_csv(tesouro.baixar_csv(sessao))
    log.info("Tesouro: %d linhas, de %s a %s", len(td),
             td["DATA"].min().date(), td["DATA"].max().date())

    fim = hoje or date.today()
    if com_historico:
        anos = list(range(td["DATA"].min().year, fim.year + 1))
    else:
        # Seis meses atrás pode cair no ano anterior; por isso dois anos.
        anos = sorted({fim.year, (fim - timedelta(days=200)).year})
    log.info("Baixando as curvas do Treasury (%d anos: %s a %s)…",
             len(anos), anos[0], anos[-1])
    us_nom = treasury.baixar(treasury.TIPO_NOMINAL, anos, sessao)
    us_real = treasury.baixar(treasury.TIPO_REAL, anos, sessao)
    log.info("Treasury: %d pontos nominais, %d reais", len(us_nom), len(us_real))

    if com_historico:
        # Dólar, meta Selic e Focus. Cada um numa tentativa própria: são três
        # gráficos independentes, e o Banco Central fora do ar não pode
        # derrubar a série de juros, que é a parte principal do arquivo.
        # Cada fonte numa tentativa própria, e cada falha vira AVISO no
        # arquivo — não só linha de log. A primeira coleta de verdade falhou
        # só no Focus, o log disse, e ninguém leu: o arquivo saiu com
        # `avisos: []` e a aba ficou sem o juro real ex-ante sem nada na tela
        # explicando. Log que ninguém lê não é aviso.
        inicio = td["DATA"].min().date()
        recado = avisos if avisos is not None else []
        dolar = selic = focus = None
        try:
            dolar = bcb.serie_sgs(bcb.DOLAR, inicio, fim, sessao)
            selic = bcb.serie_sgs(bcb.SELIC_META, inicio, fim, sessao)
        except Exception as exc:                               # noqa: BLE001
            log.error("SGS do Banco Central: FALHOU — %s", exc)
            recado.append("O SGS do Banco Central não respondeu; a aba "
                          f"Brasil × EUA fica sem o dólar e sem a Selic. {exc}")
        try:
            focus = bcb.focus_ipca_12m(inicio, sessao)
        except Exception as exc:                               # noqa: BLE001
            log.error("Focus (Olinda): FALHOU — %s", exc)
            recado.append("O Focus não respondeu; o gráfico do ciclo da Selic "
                          f"fica sem o juro real ex-ante. {exc}")

        s = historico.serie(td, us_nom, us_real,
                            dolar=dolar, selic=selic, focus=focus)
        HISTORICO_SPREAD.parent.mkdir(parents=True, exist_ok=True)
        HISTORICO_SPREAD.write_text(
            json.dumps(s, separators=(",", ":")), encoding="utf-8")
        tam = HISTORICO_SPREAD.stat().st_size / 1024
        log.info("spread_historico.json: %d pregões, %.0f KB", len(s["datas"]), tam)
        for k, v in historico.resumo(s).items():
            log.info("  %-12s %4d dias, %s a %s, último %s",
                     k, v["n"], v["inicio"], v["fim"], v["ultimo"])

    return arquivo.montar_juros(td, us_nom, us_real, hoje)


# ---------------------------------------------------------------------------
# P/VP do Ibovespa
# ---------------------------------------------------------------------------
def coletar_pvp(sessao) -> tuple[dict, list[str]]:
    from magicb3 import prices
    from mercado import acoes, arquivo, empresas, ibov, pvp

    avisos: list[str] = []

    carteira, origem = ibov.baixar_ou_carregar(CARTEIRA, sessao)
    papeis = carteira["papeis"]
    if origem == "arquivo":
        avisos.append("A B3 não respondeu; a carteira do Ibovespa usada é a "
                      f"guardada no repositório, de {carteira.get('data')}.")
    log.info("Carteira do Ibovespa: %d papéis (%s), de %s",
             len(papeis), origem, carteira.get("data"))

    if not FUNDAMENTOS.exists():
        raise FileNotFoundError(
            f"{FUNDAMENTOS} não existe. O patrimônio líquido vem dele; gere com "
            "`python baixar_fundamentos.py` num computador no Brasil.")
    fund = json.loads(FUNDAMENTOS.read_text(encoding="utf-8"))
    lista_empresas = fund.get("empresas") or []
    log.info("fundamentos.json: %d empresas, gerado em %s",
             len(lista_empresas), (fund.get("meta") or {}).get("geradoEm"))

    mapa, origem_mapa = empresas.baixar_ou_carregar(MAPA_CVM, sessao)
    if origem_mapa == "arquivo":
        avisos.append("A API de companhias da B3 não respondeu; o mapa de "
                      "prefixo para código CVM usado é o guardado no repositório.")

    codigos = [p["ticker"] for p in papeis]
    fim = date.today() + timedelta(days=1)
    blocos = prices.baixar_historico([c + ".SA" for c in codigos],
                                     fim - timedelta(days=15), fim)
    fech = blocos["fechamento"]
    precos, data_preco = {}, None
    for col in fech.columns:
        serie = fech[col].dropna()
        if len(serie):
            precos[str(col).replace(".SA", "")] = float(serie.iloc[-1])
            d = serie.index[-1]
            data_preco = max(data_preco, d) if data_preco else d
    quando = data_preco.date() if data_preco is not None else date.today()
    log.info("Preços de %s para %d papéis", quando, len(precos))

    # Segunda fonte do nº de ações. Sem ela, 10 papéis do índice — Vale e Itaú
    # entre eles — ficam de fora por falta de escala confirmada na CVM.
    implicitas = acoes.implicitas_por_prefixo(acoes.valor_de_mercado(codigos))
    vpas = pvp.vpa_por_prefixo(lista_empresas, mapa, implicitas)
    log.info("Patrimônio por ação disponível para %d prefixos", len(vpas))

    res = pvp.calcular(papeis, precos, vpas)
    if res.pvp is None:
        raise RuntimeError("Nenhum papel do índice tinha preço e patrimônio.")
    log.info("P/VP do Ibovespa: %.3f (cobertura %.1f%% do índice, %d de %d papéis)",
             res.pvp, res.cobertura * 100, res.n_com_dado, res.n_total)
    if res.cobertura < 0.85:
        avisos.append(f"O cálculo do P/VP cobre {res.cobertura:.0%} do peso do "
                      "índice; os papéis sem patrimônio ou sem preço ficaram de fora.")

    serie = arquivo.juntar_historico(
        arquivo.carregar_historico_pvp(HISTORICO_PVP), quando, res.pvp)
    HISTORICO_PVP.parent.mkdir(parents=True, exist_ok=True)
    HISTORICO_PVP.write_text(json.dumps(serie, separators=(",", ":")),
                             encoding="utf-8")

    return arquivo.montar_pvp(res, quando, origem, serie,
                              carteira.get("data")), avisos


# ---------------------------------------------------------------------------
# Demonstração
# ---------------------------------------------------------------------------
def demo() -> dict:
    """Números sorteados, com a mesma forma do arquivo real.

    Existe para ver a tela funcionando antes de qualquer coleta. A tela lê
    `meta.demo` e mostra um aviso vermelho — o mesmo padrão das outras abas,
    pela mesma razão: um gráfico bonito com número inventado é pior que
    gráfico nenhum.
    """
    import random

    from mercado import arquivo, curvas

    random.seed(20260915)
    g = curvas.GRADE
    hoje = date.today()
    datas = {"hoje": hoje, "semana": hoje - timedelta(days=7),
             "mes": hoje - timedelta(days=30), "semestre": hoje - timedelta(days=182)}

    def curva_falsa(nivel, inclinacao, ate):
        return [round(nivel + inclinacao * (p ** 0.5) + random.uniform(-.05, .05), 3)
                if p <= ate else None for p in g]

    series = {}
    for i, (k, d) in enumerate(datas.items()):
        desloc = i * 0.18
        pre = curva_falsa(13.4 - desloc, 0.32, 11)
        ipca = curva_falsa(7.2 - desloc * .4, 0.12, 20)
        eua = curva_falsa(4.2, 0.22, 20)
        tips = curva_falsa(1.9, 0.2, 20)
        for c in (tips,):
            for j, p in enumerate(g):
                if p < 5:
                    c[j] = None
        for j, p in enumerate(g):
            if p < 2.5:
                ipca[j] = None
        series[k] = {
            "rotulo": arquivo.NOMES[k], "dataBR": d.isoformat(), "dataEUA": d.isoformat(),
            "pre": {"pontos": [], "grade": pre, "alcance": [0.3, 11.2]},
            "ipca": {"pontos": [], "grade": ipca, "alcance": [2.6, 33.9]},
            "eua": {"pontos": [], "grade": eua, "alcance": [0.08, 30]},
            "tips": {"pontos": [], "grade": tips, "alcance": [5, 30]},
            "spreadNominal": curvas.diferenca(pre, eua),
            "spreadReal": curvas.diferenca(ipca, tips),
        }

    juros = {"grade": g, "datas": {k: v.isoformat() for k, v in datas.items()},
             "series": series, "verticesNominais": [2.0, 5.0, 10.0],
             "verticesReais": [5.0, 10.0, 20.0]}

    serie_pvp = []
    v = 1.35
    for k in range(60):
        v += random.uniform(-.03, .03)
        serie_pvp.append([(hoje - timedelta(days=30 * (60 - k))).isoformat(), round(v, 3)])
    pvp_bloco = {"atual": {"data": hoje.isoformat(), "valor": round(v, 3),
                           "valorMercado": 3.1e12, "patrimonio": 2.3e12,
                           "cobertura": 0.97, "nComDado": 74, "nTotal": 76,
                           "faltando": [], "carteiraDe": "demo",
                           "dataCarteira": hoje.isoformat()},
                 "historico": serie_pvp, "empresas": []}

    return arquivo.montar(juros, pvp_bloco, demo=True,
                          avisos=["Arquivo em modo demonstração."])


# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sem-pvp", action="store_true",
                    help="publica só as curvas de juros")
    ap.add_argument("--sem-juros", action="store_true",
                    help="publica só o P/VP (mantém as curvas do arquivo atual)")
    ap.add_argument("--demo", action="store_true",
                    help="números sorteados, para ver a tela")
    ap.add_argument("--sem-historico", action="store_true",
                    help="não refaz a série do spread desde 2004 (coleta rápida)")
    ap.add_argument("--saida", default=str(SAIDA))
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.path.insert(0, str(RAIZ))

    from mercado import arquivo

    if args.demo:
        arquivo.gravar(demo(), args.saida)
        print(f"{args.saida} gravado em modo DEMONSTRAÇÃO.")
        return 0

    from magicb3 import rede

    sessao = rede.sessao(tentativas=3, backoff=2.0)
    avisos: list[str] = []

    anterior = {}
    if Path(args.saida).exists():
        try:
            anterior = json.loads(Path(args.saida).read_text(encoding="utf-8"))
        except Exception:                                      # noqa: BLE001
            anterior = {}

    juros = anterior.get("juros") or {}
    if not args.sem_juros:
        try:
            juros = coletar_juros(sessao, com_historico=not args.sem_historico,
                                  avisos=avisos)
        except Exception as exc:                               # noqa: BLE001
            log.error("Curvas de juros: FALHOU — %s", exc)
            avisos.append(f"As curvas de juros não puderam ser atualizadas: {exc}")
            if not juros:
                print("Nenhuma curva coletada e não há arquivo anterior.", file=sys.stderr)
                return 1

    pvp_bloco = anterior.get("pvp") or {"atual": None, "historico": [], "empresas": []}
    if not args.sem_pvp:
        try:
            pvp_bloco, avisos_pvp = coletar_pvp(sessao)
            avisos += avisos_pvp
        except Exception as exc:                               # noqa: BLE001
            log.error("P/VP do Ibovespa: FALHOU — %s", exc)
            avisos.append(f"O P/VP do Ibovespa não pôde ser atualizado: {exc}")

    arquivo.gravar(arquivo.montar(juros, pvp_bloco, avisos=avisos), args.saida)
    tam = Path(args.saida).stat().st_size / 1024
    print(f"{args.saida} gravado ({tam:.0f} KB).")
    for a in avisos:
        print("  aviso:", a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
