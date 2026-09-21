# -*- coding: utf-8 -*-
"""Gera web/public/fundos_fechados.json — a aba de fundos fechados.

PRECISA RODAR NUM COMPUTADOR NO BRASIL.

Mesma restricao de `baixar_informe_fii.py`: `dados.cvm.gov.br` recusa conexoes
vindas do exterior, e o GitHub Actions roda nos Estados Unidos.

A diferenca em relacao as outras duas abas e que aqui **nao ha etapa de
mercado**. Fundo fechado de balcao nao tem preco nem provento no Yahoo, entao
o arquivo gerado ja e o conteudo final da tela: o robo so copia.

    este script (no seu PC)  ->  fundos_fechados.json  ->  versionado
    robo do GitHub           ->  publica

Tres fontes, periodicidades diferentes:

    FII     informe mensal        prazo, vencimento, cotistas, rentabilidade
    Fiagro  informe mensal        idem, menos o prazo (o campo vem inutil)
    FIP     informe quadrimestral patrimonio, cotistas, cota — sem prazo

Uso:
    python baixar_fechados.py
    python baixar_fechados.py --ano 2026
    python baixar_fechados.py --sem-fip
    python baixar_fechados.py --sem-cache
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from fechados import arquivo, coleta, config as C, indicadores

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("fechados")

SAIDA = Path(__file__).parent / "web" / "public" / "fundos_fechados.json"


def _linha(rotulo: str, valor) -> None:
    print(f"  {rotulo:38s}: {valor}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", type=int, default=date.today().year)
    ap.add_argument("--saida", default=str(SAIDA))
    ap.add_argument("--sem-cache", action="store_true")
    ap.add_argument("--sem-fip", action="store_true",
                    help="pula o informe quadrimestral de FIP")
    ap.add_argument("--competencias-fiagro", type=int, default=6)
    ap.add_argument("--cotistas-minimo", type=int,
                    default=C.ParamsFechados.cotistas_minimo)
    ap.add_argument("--tudo", action="store_true",
                    help="exporta o universo inteiro, sem aplicar o filtro")
    args = ap.parse_args()

    params = C.ParamsFechados(cotistas_minimo=args.cotistas_minimo)

    print("=" * 70)
    print("  FUNDOS FECHADOS — FII, FIAGRO E FIP")
    print(f"  ano {args.ano}")
    print("=" * 70)

    print("\nBaixando os informes...")
    longo, avisos = coleta.coletar(
        args.ano, usar_cache=not args.sem_cache, com_fip=not args.sem_fip,
        competencias_fiagro=args.competencias_fiagro)
    if longo.empty:
        print("\nERRO: nenhuma fonte respondeu.")
        for aviso in avisos:
            print(f"  - {aviso}")
        return 1

    print(f"\n  {len(longo):,} linhas lidas")
    for tipo, n in longo["TIPO"].value_counts().items():
        fundos = longo.loc[longo["TIPO"].eq(tipo), "CNPJ"].nunique()
        _linha(f"{tipo}", f"{fundos:,} fundos em {n:,} informes")

    print("\nConsolidando...")
    cons, mais_avisos = indicadores.consolidar(longo, params)
    avisos += mais_avisos
    _linha("fundos no universo bruto", f"{len(cons):,}")

    ok = indicadores.elegiveis(cons, params)
    _linha("passam no filtro", f"{int(ok.sum()):,}")
    publicar = cons if args.tudo else cons[ok].reset_index(drop=True)
    # Os avisos que importam sao os do que vai para a tela. Os do universo
    # bruto falam de fundos que o filtro acabou de descartar.
    avisos = [a for a in avisos if not a.startswith("universo bruto")]
    avisos += indicadores.conferir(publicar, "publicado")

    # Conferencias que o olho nao faz sozinho.
    print("\nO que foi publicado:")
    for tipo, n in publicar["TIPO"].value_counts().items():
        _linha(f"  {tipo}", f"{n:,}")
    determinado = publicar["PRAZO"].eq(C.PRAZO_DETERMINADO)
    _linha("com prazo determinado", f"{int(determinado.sum()):,}")
    com_venc = publicar["DT_VENCIMENTO"].notna()
    _linha("com data de vencimento", f"{int(com_venc.sum()):,}")
    _linha("vencidos e ainda informando",
           f"{int(publicar['PRAZO_VENCIDO'].fillna(False).sum()):,}")
    _linha("vencimento fora de escala",
           f"{int(publicar['PRAZO_SUSPEITO'].fillna(False).sum()):,}")
    _linha("rotulo conflita com a data",
           f"{int(publicar['ROTULO_CONFLITA'].fillna(False).sum()):,}")
    _linha("amortizaram nos ultimos 12 informes",
           f"{int((pd.to_numeric(publicar['MESES_COM_AMORT'], errors='coerce') > 0).sum()):,}")

    cotistas = pd.to_numeric(publicar["COTISTAS"], errors="coerce")
    _linha("cotistas (mediana)", f"{cotistas.median():,.0f}")
    pl = pd.to_numeric(publicar["PL"], errors="coerce")
    _linha("patrimonio somado", f"R$ {pl.sum() / 1e9:,.1f} bi")

    # Campo vazio em massa e o modo de falha que este projeto ja viu tres
    # vezes. Vale gritar antes de publicar, nao depois.
    print("\nPreenchimento das colunas que a tela usa:")
    for coluna in ("COTISTAS", "PL", "VP_COTA", "DT_INICIO", "RENT_12M",
                   "DT_VENCIMENTO", "TAXA_ADM"):
        frac = publicar[coluna].notna().mean() if len(publicar) else 0.0
        marca = "ok   " if frac > 0.6 else ("AVISO" if frac > 0.2 else "FALHA")
        print(f"  [{marca}] {coluna:16s} {frac:6.1%}")
        if frac <= 0.2 and coluna in ("COTISTAS", "PL"):
            avisos.append(f"{coluna} veio preenchida em {frac:.0%} — conferir "
                          f"se a CVM renomeou a coluna.")

    if avisos:
        print("\nAvisos:")
        for aviso in avisos:
            print(f"  - {aviso}")

    destino = Path(args.saida)
    dados = arquivo.exportar(publicar, destino, avisos=avisos, params=params)
    print(f"\n  Gravado em {destino}")
    print(f"  {dados['meta']['nFundos']:,} fundos | "
          f"{destino.stat().st_size / 1024:,.0f} KB | "
          f"competencia {dados['meta']['competencia']}")

    print("\nProximo passo: suba este arquivo para o GitHub")
    print("  (web -> public -> Add file -> Upload files)")

    if len(publicar) < 50:
        print("\n  AVISO: pouquissimos fundos. Rode sondar_fundos2.py para ver")
        print("  se a CVM mexeu nos arquivos.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
