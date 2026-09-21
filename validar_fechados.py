# -*- coding: utf-8 -*-
"""Confere o fundos_fechados.json antes que ele vire tela.

Por que este arquivo nao tem um robo que "atualiza"
---------------------------------------------------
Nas abas de acoes e de FII o robo do GitHub faz trabalho de verdade: ele junta
o informe da CVM com preco e provento do Yahoo, e so entao existe o arquivo do
site. Aqui nao ha etapa de mercado — fundo fechado de balcao nao tem preco nem
provento — entao `baixar_fechados.py` ja produz o arquivo final no PC do Marco.
Um robo que regenerasse isso na nuvem nao teria o que regenerar, e nem
conseguiria: a CVM recusa conexoes de servidores no exterior.

O que sobra para a automacao, e que e o que importa, e **impedir que um arquivo
quebrado ou velho chegue ao ar em silencio**. E disso que este script trata.

As conferencias, e o que cada uma pega
--------------------------------------
    estrutura    -> upload interrompido, JSON truncado, versao antiga
    idade        -> o informe e mensal; arquivo de tres meses atras engana
    preenchimento-> a CVM renomeou coluna e o campo virou vazio (ja aconteceu
                    tres vezes neste projeto, sempre sem erro nenhum)
    sanidade     -> vencimento em 3035, prazo restante impossivel, CNPJ repetido
    referencias  -> fundos conhecidos sumiram do universo

Uso:
    python validar_fechados.py
    python validar_fechados.py --arquivo web/public/fundos_fechados.json
    python validar_fechados.py --idade-maxima 60
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PADRAO = Path(__file__).parent / "web" / "public" / "fundos_fechados.json"

VERSAO_MINIMA = 1
FUNDOS_MINIMO = 300
DETERMINADOS_MINIMO = 50

# Quanto de cada campo precisa estar preenchido, e sobre qual recorte. FIP nao
# publica prazo, rentabilidade nem taxa, entao exigir isso do universo inteiro
# reprovaria um arquivo correto — os limites abaixo consideram so quem deveria
# ter o campo.
COBERTURA = (
    ("cnpj", 1.00, None),
    ("nome", 1.00, None),
    ("cotistas", 0.95, None),
    ("pl", 0.95, None),
    ("vpCota", 0.90, None),
    ("inicio", 0.90, "naoFip"),
    ("rent12", 0.85, "naoFip"),
    ("taxaAdm", 0.80, "naoFip"),
)

# Fundos conferidos a mao contra o prospecto da oferta. Se algum sumir, ou a
# CVM mudou alguma coisa ou o filtro apertou demais — nos dois casos vale
# olhar antes de publicar.
REFERENCIAS = {
    "61922643000187": "LCP Prefixado Feeder FII",
    "40265671000107": "Kijani Asatala Fiagro",
    "63608356000122": "XP Agro Renda Feeder Fiagro",
}

ANOS_MAXIMOS = 60


class Conferencia:
    """Acumula erros e avisos — erro reprova, aviso so aparece."""

    def __init__(self) -> None:
        self.erros: list[str] = []
        self.avisos: list[str] = []

    def erro(self, msg: str) -> None:
        self.erros.append(msg)
        print(f"  [FALHA] {msg}")

    def aviso(self, msg: str) -> None:
        self.avisos.append(msg)
        print(f"  [aviso] {msg}")

    def ok(self, msg: str) -> None:
        print(f"  [ok]    {msg}")


def _pct(fundos: list[dict], campo: str, recorte: str | None) -> tuple[float, int]:
    alvo = [f for f in fundos
            if recorte != "naoFip" or f.get("tipo") != "FIP"]
    if not alvo:
        return 1.0, 0
    tem = sum(1 for f in alvo if f.get(campo) is not None)
    return tem / len(alvo), len(alvo)


def validar(caminho: Path, idade_maxima: int) -> Conferencia:
    c = Conferencia()

    print("\nEstrutura")
    if not caminho.exists():
        c.erro(f"{caminho} nao existe. Rode `python baixar_fechados.py` no seu "
               f"computador — a CVM recusa conexoes do exterior.")
        return c
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        c.erro(f"JSON invalido ({exc}). Upload interrompido?")
        return c

    meta = dados.get("meta") or {}
    fundos = dados.get("fundos") or []
    if meta.get("versao", 0) < VERSAO_MINIMA:
        c.erro(f"versao {meta.get('versao')} e anterior a {VERSAO_MINIMA}.")
    if len(fundos) != meta.get("nFundos"):
        c.erro(f"meta diz {meta.get('nFundos')} fundos, o arquivo tem {len(fundos)}.")
    if len(fundos) < FUNDOS_MINIMO:
        c.erro(f"so {len(fundos)} fundos — esperado ao menos {FUNDOS_MINIMO}.")
    else:
        c.ok(f"{len(fundos):,} fundos, versao {meta.get('versao')}")

    if not fundos:
        return c

    print("\nIdade")
    gerado = meta.get("geradoEm") or ""
    try:
        dias = (datetime.now() - datetime.strptime(gerado[:16], "%Y-%m-%d %H:%M")).days
        if dias > idade_maxima * 2:
            c.erro(f"gerado ha {dias} dias — o informe e mensal, isso e "
                   f"historia antiga.")
        elif dias > idade_maxima:
            c.aviso(f"gerado ha {dias} dias; rode `baixar_fechados.py` de novo.")
        else:
            c.ok(f"gerado ha {dias} dia(s), competencia {meta.get('competencia')}")
    except (ValueError, TypeError):
        c.aviso(f"nao consegui ler a data de geracao ({gerado!r}).")

    print("\nPreenchimento")
    for campo, minimo, recorte in COBERTURA:
        frac, n = _pct(fundos, campo, recorte)
        rotulo = f"{campo} ({'sem FIP' if recorte else 'todos'}, {n:,})"
        if frac < minimo:
            c.erro(f"{rotulo}: {frac:.0%} preenchido, minimo {minimo:.0%}. "
                   f"A CVM pode ter renomeado a coluna.")
        else:
            c.ok(f"{rotulo}: {frac:.0%}")

    print("\nO que define esta aba")
    det = [f for f in fundos if f.get("prazo") == "Determinado"]
    com_data = [f for f in det if f.get("vence")]
    if len(det) < DETERMINADOS_MINIMO:
        c.erro(f"so {len(det)} fundos de prazo determinado — esperado ao menos "
               f"{DETERMINADOS_MINIMO}. Sem eles a aba perde o proposito.")
    else:
        c.ok(f"{len(det)} de prazo determinado, {len(com_data)} com data")
    if det and len(com_data) < len(det) * 0.9:
        c.erro(f"{len(det) - len(com_data)} fundos de prazo determinado sem "
               f"data de vencimento; o normal e todos terem.")

    tipos = {f.get("tipo") for f in fundos}
    for esperado in ("FII", "Fiagro", "FIP"):
        if esperado not in tipos:
            c.aviso(f"nenhum {esperado} no arquivo — a fonte pode ter falhado.")

    print("\nSanidade")
    cnpjs = [f.get("cnpj") for f in fundos]
    repetidos = {x for x in cnpjs if cnpjs.count(x) > 1} if len(cnpjs) < 5000 else set()
    if repetidos:
        c.erro(f"{len(repetidos)} CNPJ repetido(s): "
               f"{', '.join(list(repetidos)[:3])}")
    torto = [x for x in cnpjs if not (x and len(str(x)) == 14 and str(x).isdigit())]
    if torto:
        c.erro(f"{len(torto)} CNPJ fora do formato de 14 digitos.")
    if not repetidos and not torto:
        c.ok("CNPJ unicos e no formato certo")

    longe = [f for f in fundos
             if f.get("anosRest") is not None and f["anosRest"] > ANOS_MAXIMOS]
    if longe:
        c.erro(f"{len(longe)} fundo(s) com prazo restante acima de "
               f"{ANOS_MAXIMOS} anos; o filtro de sanidade deveria ter pegado.")
    else:
        c.ok(f"nenhum prazo restante acima de {ANOS_MAXIMOS} anos")

    negativos = [f for f in fundos if (f.get("pl") or 0) < 0]
    if negativos:
        c.aviso(f"{len(negativos)} fundo(s) com patrimonio negativo — acontece "
                f"em fundo em liquidacao, mas vale conferir.")

    print("\nReferencias")
    indice = {f.get("cnpj"): f for f in fundos}
    for cnpj, nome in REFERENCIAS.items():
        f = indice.get(cnpj)
        if not f:
            c.aviso(f"{nome} nao esta no arquivo.")
        else:
            c.ok(f"{nome}: {int(f.get('cotistas') or 0):,} cotistas, "
                 f"prazo {f.get('prazo')}"
                 + (f", vence {f['vence']}" if f.get("vence") else ""))

    avisos_da_coleta = meta.get("avisos") or []
    if avisos_da_coleta:
        print("\nAvisos registrados na coleta")
        for a in avisos_da_coleta:
            print(f"  - {a}")

    return c


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arquivo", default=str(PADRAO))
    ap.add_argument("--idade-maxima", type=int, default=45,
                    help="dias antes de avisar (o dobro reprova)")
    args = ap.parse_args()

    print("=" * 66)
    print("  CONFERINDO O ARQUIVO DE FUNDOS FECHADOS")
    print("=" * 66)

    c = validar(Path(args.arquivo), args.idade_maxima)

    print("\n" + "=" * 66)
    if c.erros:
        print(f"  REPROVADO: {len(c.erros)} problema(s), "
              f"{len(c.avisos)} aviso(s)")
        print("=" * 66)
        return 1
    print(f"  APROVADO{f' com {len(c.avisos)} aviso(s)' if c.avisos else ''}")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    sys.exit(main())
