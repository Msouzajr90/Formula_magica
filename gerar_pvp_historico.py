# -*- coding: utf-8 -*-
# A docstring é raw (r""") por causa dos caminhos do Windows: `\Scripts\` tem
# `\S`, que o Python 3.12 avisa ser sequência de escape inválida a cada
# execução. Não muda o comportamento, mas um aviso que aparece sempre é um
# aviso que todo mundo aprende a ignorar — inclusive os que importam.
r"""Reconstrói a série diária do P/VP do Ibovespa. RODA NO SEU COMPUTADOR.

Por que aqui e não no robô
--------------------------
A CVM recusa conexões de servidores no exterior, e o GitHub Actions roda nos
Estados Unidos. Os balanços antigos têm que ser baixados de uma máquina no
Brasil — o mesmo motivo do `baixar_informe_fii.py`. Depois de gerado, o
arquivo fica no repositório e o robô só acrescenta o ponto de cada dia.

No Windows, duplo clique em `pvp_historico.bat` — ele faz os dois passos na
ordem e pergunta antes de calcular. Pela linha de comando, use o Python do
ambiente virtual do projeto:

    .venv\Scripts\python.exe gerar_pvp_historico.py --diagnostico --desde 2015
    .venv\Scripts\python.exe gerar_pvp_historico.py --desde 2015

**Não** `python` solto: as dependências (pandas, yfinance) estão no `.venv`, e
no Windows o `python` sem caminho costuma cair no atalho da Microsoft Store,
que responde "Python was not found" e não é Python nenhum.

É uma execução longa: são centenas de MB de DFP e ITR, um ano por vez. O
diagnóstico baixa o mesmo e não calcula nada — ele diz, ano a ano, quantas
empresas do Ibovespa têm patrimônio e nº de ações. Se a cobertura estiver baixa
em algum ano, é melhor saber antes de esperar o cálculo inteiro.

Disciplina point-in-time
------------------------
Em 02/01/2022 o balanço de 31/12/2021 ainda não havia sido entregue à CVM e
não pode entrar no cálculo daquele dia. O painel guarda a data de entrega de
cada demonstração e `pvp.patrimonio_vigente` só usa o que já era público. Sem
isso a série ficaria com o patrimônio chegando antes da hora — o mesmo erro
que inflaria um backtest.

O que esta série NÃO é
----------------------
Ela usa a carteira do Ibovespa de HOJE aplicada ao passado. As empresas que
saíram do índice não aparecem, e as que entraram aparecem antes de terem
entrado. É viés de sobrevivência, empurra a série para cima, e a tela declara.
Reconstruir a carteira de cada data exigiria o histórico de carteiras teóricas
da B3, que não é publicado em série.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ))

CARTEIRA = RAIZ / "web" / "public" / "ibov_carteira.json"
MAPA_CVM = RAIZ / "web" / "public" / "mapa_cvm.json"
SAIDA = RAIZ / "web" / "public" / "pvp_historico.json"
FUNDAMENTOS = RAIZ / "web" / "public" / "fundamentos.json"

log = logging.getLogger("pvp-historico")

# Só as contas do balanço patrimonial passivo; o resto é RAM à toa.
CONTAS_BP = None          # a descrição do PL varia de código entre planos


def carregar_referencias() -> tuple[list[dict], dict[str, int]]:
    if not CARTEIRA.exists() or not MAPA_CVM.exists():
        raise FileNotFoundError(
            f"Faltam {CARTEIRA.name} ou {MAPA_CVM.name}. Rode "
            "`python atualizar_mercado.py` uma vez para gerá-los.")
    carteira = json.loads(CARTEIRA.read_text(encoding="utf-8"))
    mapa = {k.upper(): int(v) for k, v in
            json.loads(MAPA_CVM.read_text(encoding="utf-8")).items()}
    # Só interessam os prefixos que estão no índice.
    do_indice = {p["ticker"][:4].upper() for p in carteira["papeis"]}
    return carteira["papeis"], {k: v for k, v in mapa.items() if k in do_indice}


def baixar_patrimonio(anos: list[int], pasta_zips=None):
    """Painel de patrimônio líquido por empresa e data, de DFP e ITR."""
    import pandas as pd

    from magicb3 import config as C, cvm
    from mercado import pvp

    partes = []
    for tipo in ("dfp", "itr"):
        bruto = cvm.carregar_demonstracoes(anos, tipo=tipo, pasta_zips=pasta_zips)
        bpp = bruto.get("BPP")
        if bpp is None or bpp.empty:
            log.warning("%s: nenhum BPP nos anos %s", tipo.upper(), anos)
            continue
        painel = pvp.painel_patrimonio(bpp, C.DS_PATRIMONIO_LIQUIDO)
        log.info("%s: %d linhas de patrimônio, %d empresas",
                 tipo.upper(), len(painel), painel["CD_CVM"].nunique())
        partes.append(painel)

    if not partes:
        raise RuntimeError(
            "Nenhum patrimônio líquido foi lido. Se o download falhou, veja o "
            "diagnóstico de rede: `python -c \"from magicb3 import rede; "
            "print(rede.relatorio())\"`")
    todo = pd.concat(partes, ignore_index=True)
    # O ITR e a DFP se sobrepõem no 4º trimestre; fica a DFP, que é auditada.
    todo = todo.sort_values(["CD_CVM", "DT_REFER"])
    return todo.drop_duplicates(subset=["CD_CVM", "DT_REFER"], keep="first")


def acoes_de_hoje(mapa: dict[str, int], sessao=None) -> dict[int, dict]:
    """{código CVM -> {acoes, fonte, nome}} pela MESMA conta do cálculo diário.

    A primeira versão disto lia `cvm.composicao_capital` ano a ano. Não
    funcionava, e a execução real mostrou do jeito mais claro possível: zero de
    74 empresas do índice, em todos os anos. O arquivo da CVM é indexado por
    **CNPJ**, não por código CVM, e o código procurava uma coluna que nunca
    existiu — descartando cada ano em silêncio.

    A ponte CNPJ→CVM resolveria, mas resolveria pouco: o `composicao_capital`
    é exatamente a fonte cuja escala não dá para confirmar em boa parte das
    empresas — na coleta de hoje ela vem nula em 10 dos 76 papéis, Vale e Itaú
    entre eles. O caminho diário já resolve isso conciliando com o valor de
    mercado dividido pelo preço, e é esse número que vale aqui.

    Com o nº de ações constante no tempo — que é a aproximação declarada desta
    série de qualquer jeito — usar a conciliação de hoje é mais robusto que
    usar a CVM de cada ano, e é o mesmo código que roda em produção.
    """
    from mercado import acoes as mod_acoes, pvp

    if not FUNDAMENTOS.exists():
        raise FileNotFoundError(
            f"{FUNDAMENTOS} não existe. O patrimônio de hoje e o nº de ações "
            "saem dele; gere com `baixar_fundamentos.py`.")
    empresas = json.loads(FUNDAMENTOS.read_text(encoding="utf-8")).get("empresas") or []

    log.info("Consultando valor de mercado de %d papéis no Yahoo "
             "(segunda fonte do nº de ações)…", len(mapa))
    tickers = [p for p in _tickers_do_indice() if p[:4].upper() in mapa]
    implicitas = mod_acoes.implicitas_por_prefixo(mod_acoes.valor_de_mercado(tickers))

    vpas = pvp.vpa_por_prefixo(empresas, mapa, implicitas)
    por_cvm: dict[int, dict] = {}
    contagem = {}
    for pref, info in vpas.items():
        cvm = mapa.get(pref)
        if cvm is None:
            continue
        fonte = info.get("fonteAcoes") or "cvm"
        por_cvm[cvm] = {"acoes": info["acoes"], "fonte": fonte,
                        "nome": info.get("nome")}
        chave = "cvm" if fonte == "cvm" else "mercado"
        contagem[chave] = contagem.get(chave, 0) + 1

    log.info("Nº de ações resolvido para %d das %d empresas do índice "
             "(%d pela CVM, %d pelo valor de mercado)",
             len(por_cvm), len(set(mapa.values())),
             contagem.get("cvm", 0), contagem.get("mercado", 0))
    if not por_cvm:
        raise RuntimeError(
            "Nenhuma empresa do índice ficou com nº de ações. Confira se o "
            "fundamentos.json é recente e se o Yahoo respondeu.")
    return por_cvm


def _tickers_do_indice() -> list[str]:
    carteira = json.loads(CARTEIRA.read_text(encoding="utf-8"))
    return [p["ticker"] for p in carteira["papeis"]]


def precos_diarios(papeis: list[dict], inicio: date, fim: date):
    from magicb3 import prices

    yf = [p["ticker"] + ".SA" for p in papeis]
    blocos = prices.baixar_historico(yf, inicio, fim)
    # Fechamento BRUTO, não ajustado: o valor de mercado é preço vezes ações,
    # e o preço ajustado por proventos não multiplica o nº de ações de hoje.
    fech = blocos["fechamento"]
    fech.columns = [str(c).replace(".SA", "") for c in fech.columns]
    return fech


def gerar(desde: int, ate: date | None = None, pasta_zips=None,
          diagnostico: bool = False) -> dict:
    from mercado import pvp

    papeis, mapa = carregar_referencias()
    fim = ate or date.today()
    # Um ano antes do início: o balanço vigente em janeiro de `desde` foi
    # entregue no ano anterior.
    anos = list(range(desde - 1, fim.year + 1))
    log.info("Carteira: %d papéis, %d prefixos com código CVM. Anos: %s",
             len(papeis), len(mapa), anos)

    painel = baixar_patrimonio(anos, pasta_zips)
    acoes = acoes_de_hoje(mapa)

    if diagnostico:
        linhas = []
        for ano in range(desde, fim.year + 1):
            quando = min(date(ano, 12, 31), fim)
            v = pvp.vpa_na_data(painel, acoes, mapa, quando)
            peso = sum(p.get("part") or 0 for p in papeis
                       if p["ticker"][:4].upper() in v)
            linhas.append((ano, len(v), len(mapa), peso))
        print("\n ano   empresas com dado   peso do índice coberto")
        for ano, n, total, peso in linhas:
            print(f" {ano}        {n:3d} de {total:3d}              {peso:5.1f}%")
        if linhas and linhas[-1][1] == 0:
            print("\nZero em todos os anos quer dizer que o patrimônio não foi lido "
                  "ou que o\nnº de ações não resolveu — as duas coisas aparecem no "
                  "log acima, antes\ndesta tabela.")
        print("\nSem --diagnostico, o cálculo roda e grava a série.")
        return {}

    precos = precos_diarios(papeis, date(desde, 1, 1), fim + timedelta(days=1))
    log.info("Preços: %d pregões, %d papéis", len(precos), len(precos.columns))

    serie, cobertura_min, sem_dado = [], 1.0, 0
    for quando, linha in precos.iterrows():
        d = quando.date()
        vpas = pvp.vpa_na_data(painel, acoes, mapa, d)
        if not vpas:
            sem_dado += 1
            continue
        do_dia = {t: float(v) for t, v in linha.items() if v == v}
        res = pvp.calcular(papeis, do_dia, vpas)
        if res.pvp is None:
            sem_dado += 1
            continue
        serie.append([d.isoformat(), round(res.pvp, 4)])
        cobertura_min = min(cobertura_min, res.cobertura)

    log.info("Série: %d pontos, de %s a %s; %d pregões sem dado suficiente",
             len(serie), serie[0][0] if serie else "—",
             serie[-1][0] if serie else "—", sem_dado)
    log.info("Pior cobertura do índice num dia: %.1f%%", cobertura_min * 100)
    return {"serie": serie, "coberturaMinima": cobertura_min}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", type=int, default=2015,
                    help="primeiro ano da série (padrão 2015; a CVM tem "
                         "arquivos estruturados desde 2010)")
    ap.add_argument("--diagnostico", action="store_true",
                    help="só relata a cobertura ano a ano, sem calcular")
    ap.add_argument("--zips", default=None,
                    help="pasta com os zips da CVM já baixados, para não "
                         "acessar a rede")
    ap.add_argument("--saida", default=str(SAIDA))
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        r = gerar(args.desde, pasta_zips=args.zips, diagnostico=args.diagnostico)
    except Exception as exc:                                   # noqa: BLE001
        print(f"\nFALHOU: {exc}", file=sys.stderr)
        return 1
    if args.diagnostico:
        return 0

    serie = r["serie"]
    if len(serie) < 100:
        print(f"\nSó {len(serie)} pontos. Alguma coisa está errada — não vou "
              "sobrescrever o arquivo. Rode com --diagnostico.", file=sys.stderr)
        return 1

    # A série de hoje, acumulada pelo robô, tem prioridade sobre a
    # reconstruída: ela foi calculada com o fundamentos.json do dia.
    from mercado import arquivo
    ja_tinha = {d: v for d, v in arquivo.carregar_historico_pvp(args.saida)}
    junta = {d: v for d, v in serie}
    junta.update(ja_tinha)
    final = [[d, round(v, 4)] for d, v in sorted(junta.items())]

    Path(args.saida).write_text(json.dumps(final, separators=(",", ":")),
                                encoding="utf-8")
    print(f"\n{args.saida}: {len(final)} pontos, de {final[0][0]} a {final[-1][0]}.")
    print(f"Pior cobertura do índice num dia: {r['coberturaMinima']:.1%}")
    print("Confira o gráfico antes de publicar: `python -m http.server` em "
          "web/public e abra mercado.html.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
