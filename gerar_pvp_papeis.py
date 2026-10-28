# -*- coding: utf-8 -*-
r"""Reconstrói o histórico semanal do P/VP de cada papel. RODA NO SEU COMPUTADOR.

Pelo mesmo motivo do `gerar_pvp_historico.py`: a CVM recusa conexões do
exterior, e os balanços antigos têm que vir de uma máquina no Brasil. O robô
do GitHub só move o preço da semana (`atualizar_pvp_papeis.py`); balanço novo
entra quando este script roda de novo. Vale rodar depois de cada temporada de
ITR (meados de maio, agosto e novembro) e da DFP (fim de março).

No Windows, duplo clique em `pvp_papeis.bat`. Pela linha de comando:

    .venv\Scripts\python.exe gerar_pvp_papeis.py --desde 2015

Quais papéis
------------
Todos os do `dados.json` (ranking e excluídas) e todos os da carteira do
Ibovespa. A B3, fora do ranking por decisão de método, continua aqui: o P/VP
dela não sofre do problema que a tirou do ranking.

Saída: `web/public/pvp_papeis.json`, que o site só baixa quando alguém abre o
gráfico de um papel.
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

DADOS = RAIZ / "web" / "public" / "dados.json"
CARTEIRA = RAIZ / "web" / "public" / "ibov_carteira.json"
MAPA_CVM = RAIZ / "web" / "public" / "mapa_cvm.json"
FUNDAMENTOS = RAIZ / "web" / "public" / "fundamentos.json"
SAIDA = RAIZ / "web" / "public" / "pvp_papeis.json"

log = logging.getLogger("pvp-papeis")

MINIMO_DE_PAPEIS = 40      # menos que isso é falha de coleta, não universo


def universo() -> tuple[dict[str, str], dict[str, int]]:
    """({ticker: nome}, {ticker: código CVM conhecido}) do site e do índice."""
    nomes, cvm = {}, {}
    if DADOS.exists():
        d = json.loads(DADOS.read_text(encoding="utf-8"))
        for e in (d.get("empresas") or []) + (d.get("excluidas") or []):
            t = str(e.get("ticker") or "").upper()
            if not t:
                continue
            nomes.setdefault(t, e.get("nome"))
            if e.get("cvm"):
                cvm[t] = int(e["cvm"])
    if CARTEIRA.exists():
        for p in json.loads(CARTEIRA.read_text(encoding="utf-8")).get("papeis") or []:
            t = str(p.get("ticker") or "").upper()
            if t:
                nomes.setdefault(t, p.get("nome"))
    return nomes, cvm


def mapa_prefixos(tickers, cvm_conhecido: dict[str, int]) -> dict[str, int]:
    """Prefixo -> código CVM. B3 primeiro; se ela não responder, o que houver."""
    from magicb3 import rede
    from mercado import empresas

    mapa: dict[str, int] = {}
    try:
        mapa = empresas.baixar_mapa(rede.sessao())
    except Exception as exc:                                   # noqa: BLE001
        log.warning("API de companhias da B3 indisponível (%s); usando os "
                    "códigos guardados.", exc)
    if MAPA_CVM.exists():
        for k, v in json.loads(MAPA_CVM.read_text(encoding="utf-8")).items():
            mapa.setdefault(k.upper(), int(v))
    for t, c in cvm_conhecido.items():
        mapa.setdefault(t[:4], c)
    precisa = {t[:4] for t in tickers}
    return {k: v for k, v in mapa.items() if k in precisa}


def acoes_por_ticker(tickers, mapa: dict[str, int], nomes: dict[str, str]
                     ) -> dict[str, dict]:
    """{ticker: {cvm, acoes, fonte, nome}} pela mesma conciliação do índice.

    Só o NÚMERO DE AÇÕES sai daqui; o patrimônio vem do painel, data a data.
    Por isso não se usa `pvp.vpa_por_prefixo`, que descarta a empresa sem
    patrimônio positivo no fundamentos.json: a Minerva sumia do gráfico porque
    o arquivo trazia o PL dela de 03/2025, negativo, embora o de 06/2026 seja
    R$ 1,6 bi. Empresa ausente do fundamentos (Assaí, Bradespar) também fica,
    com o nº de ações implícito no valor de mercado.
    """
    from mercado import acoes as mod_acoes, pvp

    empresas = []
    if FUNDAMENTOS.exists():
        empresas = json.loads(FUNDAMENTOS.read_text(encoding="utf-8")).get("empresas") or []
    else:
        log.warning("%s não existe; o nº de ações virá só do valor de mercado "
                    "(units ficam de fora).", FUNDAMENTOS.name)
    cvm_acoes = {}
    for e in empresas:
        try:
            cvm_acoes[int(e["cvm"])] = (e.get("acoes"), e.get("nome"))
        except (KeyError, TypeError, ValueError):
            continue

    log.info("Consultando valor de mercado de %d papéis no Yahoo (segunda fonte "
             "do nº de ações)…", len(tickers))
    implicitas = mod_acoes.implicitas_por_prefixo(mod_acoes.valor_de_mercado(list(tickers)))

    saida = {}
    for t in tickers:
        cvm = mapa.get(t[:4])
        if cvm is None:
            continue
        acoes_cvm, nome_cvm = cvm_acoes.get(cvm, (None, None))
        n, fonte = pvp.acoes_da_empresa(acoes_cvm, implicitas.get(t[:4]))
        if n is None:
            continue
        saida[t] = {"cvm": cvm, "acoes": n,
                    "fonte": "cvm" if fonte == "cvm" else "mercado",
                    "nome": nomes.get(t) or nome_cvm}
    log.info("Nº de ações resolvido para %d de %d papéis", len(saida), len(tickers))
    return saida


def baixar_painel(anos: list[int], pasta_zips=None, cvms: set[int] | None = None):
    """Patrimônio dos controladores por empresa e data, de DFP e ITR.

    Consolidado primeiro; o individual só para quem não publica consolidado.
    Em 2026, 222 companhias abertas entregam só o individual — entre elas a
    Sendas (ASAI3), a Bradespar (BRAP4) e a Sanepar. Lendo só o consolidado,
    elas ficavam com o último balanço consolidado que tinham (2021 e 2023) e
    um P/VP calculado sobre patrimônio de anos atrás.
    """
    import pandas as pd

    from magicb3 import config as C, cvm
    from mercado import pvp_papeis

    partes = []
    ano_corrente = date.today().year
    for tipo in ("dfp", "itr"):
        for ano in anos:
            # O ano corrente sempre do zero: o cache de setembro não tem o ITR
            # de novembro, e o arquivo da CVM é o mesmo nome o ano todo.
            # Consolidado sem filtro de contas, de propósito: é o mesmo cache
            # que o `gerar_pvp_historico.py` já deixou no seu computador.
            bruto = cvm.carregar_demonstracoes([ano], tipo=tipo, pasta_zips=pasta_zips,
                                               usar_cache=(ano < ano_corrente))
            bpp = bruto.get("BPP")
            con = (pvp_papeis.painel_controladores(bpp, C.DS_PATRIMONIO_LIQUIDO)
                   if bpp is not None and not bpp.empty else None)
            if con is not None and not con.empty:
                partes.append(con)

            # Individual: só o passivo até o 3º nível ("2.0*"), onde está o PL
            # em qualquer plano de contas, e só das empresas que interessam.
            ind = cvm.carregar_demonstracoes([ano], tipo=tipo, pasta_zips=pasta_zips,
                                             consolidado=False, contas={"2.0*"},
                                             usar_cache=(ano < ano_corrente)).get("BPP")
            if ind is None or ind.empty:
                continue
            if cvms is not None:
                ind = ind[ind["CD_CVM"].isin(cvms)]
            if con is not None and not con.empty:
                tem = set(zip(con["CD_CVM"], pd.to_datetime(con["DT_REFER"])))
                chave = list(zip(ind["CD_CVM"], pd.to_datetime(ind["DT_REFER"])))
                ind = ind[[k not in tem for k in chave]]
            if not ind.empty:
                # No individual a conta se chama só "Patrimônio Líquido".
                partes.append(pvp_papeis.painel_controladores(ind, "patrimônio líquido"))
    if not partes:
        raise RuntimeError("Nenhum patrimônio líquido foi lido da CVM.")
    todo = pd.concat(partes, ignore_index=True)
    # DFP e ITR se sobrepõem no 4º trimestre; fica a DFP (a primeira lida).
    return todo.drop_duplicates(subset=["CD_CVM", "DT_REFER"], keep="first")


def gerar(desde: int, pasta_zips=None) -> dict:
    from magicb3 import prices
    from mercado import pvp_papeis

    nomes, cvm_conhecido = universo()
    tickers = sorted(nomes)
    log.info("Universo: %d papéis (site + Ibovespa)", len(tickers))
    mapa = mapa_prefixos(tickers, cvm_conhecido)
    papeis = acoes_por_ticker(tickers, mapa, nomes)

    fim = date.today()
    painel = baixar_painel(list(range(desde - 1, fim.year + 1)), pasta_zips,
                           cvms={int(i["cvm"]) for i in papeis.values()})
    log.info("Painel: %d balanços de %d empresas", len(painel), painel["CD_CVM"].nunique())

    blocos = prices.baixar_historico([t + ".SA" for t in papeis],
                                     date(desde, 1, 1), fim + timedelta(days=1))
    # Fechamento BRUTO (ajustado só por desdobramento, como o Yahoo entrega),
    # não o ajustado por proventos: é ele que multiplica o nº de ações de hoje.
    fech = blocos["fechamento"]
    fech.columns = [str(c).replace(".SA", "") for c in fech.columns]
    datas = pvp_papeis.datas_semanais(fech.dropna(how="all").index)
    log.info("Preços: %d pregões, %d papéis -> %d semanas", len(fech),
             len(fech.columns), len(datas))

    r = pvp_papeis.construir(painel, papeis, fech, datas)
    # Quem ficou de fora antes do cálculo também é declarado no arquivo.
    for t in tickers:
        if t not in papeis and t not in r["fora"]:
            r["fora"][t] = "sem código CVM ou sem nº de ações"
    return pvp_papeis.montar_arquivo(r, datas, desde)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--desde", type=int, default=2015)
    ap.add_argument("--zips", default=None,
                    help="pasta com os zips da CVM já baixados")
    ap.add_argument("--saida", default=str(SAIDA))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    try:
        dados = gerar(args.desde, pasta_zips=args.zips)
    except Exception as exc:                                   # noqa: BLE001
        print(f"\nFALHOU: {exc}", file=sys.stderr)
        return 1

    n = len(dados["papeis"])
    if n < MINIMO_DE_PAPEIS:
        print(f"\nSó {n} papéis com série. Alguma coisa falhou na coleta — não "
              "vou sobrescrever o arquivo.", file=sys.stderr)
        return 1
    Path(args.saida).write_text(json.dumps(dados, ensure_ascii=False,
                                           separators=(",", ":")), encoding="utf-8")
    kb = Path(args.saida).stat().st_size / 1024
    print(f"\n{args.saida}: {n} papéis, {len(dados['datas'])} semanas "
          f"({dados['datas'][0]} a {dados['datas'][-1]}), {kb:,.0f} KB.")
    fora = dados["meta"]["fora"]
    if fora:
        print(f"Fora ({len(fora)}): " + ", ".join(sorted(fora)))
    print("Confira um papel antes de publicar: `python -m http.server` em "
          "web/public e abra mercado.html#pvp=PETR4.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
