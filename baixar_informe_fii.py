# -*- coding: utf-8 -*-
"""Baixa o informe mensal de FII da CVM e grava web/public/informe_fii.json.

PRECISA RODAR NUM COMPUTADOR NO BRASIL.

Mesma restrição do `baixar_fundamentos.py`: `dados.cvm.gov.br` recusa conexões
vindas do exterior, e os servidores do GitHub Actions ficam nos Estados Unidos.
Yahoo Finance e a API da B3 respondem de qualquer lugar. A divisão fica assim:

    este script (no seu PC)  ->  informe_fii.json  ->  versionado no repositório
    robô do GitHub           ->  lê o arquivo + preços e proventos  ->  fiis.json

O informe mensal sai até o 15º dia útil do mês seguinte, então rodar uma vez por
mês, depois do dia 20, mantém o arquivo sempre na competência mais recente. Se
passar do prazo não quebra nada: patrimônio e número de cotas mudam devagar, e o
que envelhece é a precisão do P/VP. O robô avisa quando o arquivo passa de 45
dias, e o site mostra a competência que foi usada.

Uso:
    python baixar_informe_fii.py
    python baixar_informe_fii.py --ano 2026
    python baixar_informe_fii.py --sem-cache
    python baixar_informe_fii.py --zip inf_mensal_fii_2026.zip   # baixado a mao
"""
from __future__ import annotations

import argparse
import logging
import sys
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from fiib3 import arquivo_informe as arqi
from fiib3 import cvm_fii

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("informe-fii")

SAIDA = Path(__file__).parent / "web" / "public" / "informe_fii.json"


def _testar_rota() -> bool:
    try:
        from magicb3 import rede
    except ImportError:                                        # pragma: no cover
        return True
    print("\nTestando a rota ate a CVM...")
    diag = rede.diagnosticar("dados.cvm.gov.br", timeout=15.0)
    print(rede.relatorio_de(diag))
    if diag["ipv4"] or diag["ipv6"]:
        return True
    print("\nNao consigo alcancar a CVM desta maquina.")
    print("Se voce esta no Brasil, verifique firewall, antivirus ou VPN —")
    print("uma VPN com saida no exterior causa exatamente este erro.")
    print("Alternativa: baixe o zip a mao e use --zip <arquivo>.")
    print(f"  {cvm_fii.C.INF_MENSAL_ZIP.format(ano=date.today().year)}")
    return False


def _juntar(base: pd.DataFrame, extra: pd.DataFrame) -> pd.DataFrame:
    """Empilha um informe no outro, sem deixar o mesmo CNPJ duas vezes.

    Quem chega depois nao derruba quem ja estava: se um fundo aparecer nas duas
    fontes — nao deveria, mas a CVM ja reclassificou veiculo antes —, vale a
    linha do informe mensal de FII, que e a mais completa.
    """
    if extra is None or extra.empty:
        return base
    junto = pd.concat([base, extra], ignore_index=True)
    return junto.drop_duplicates(subset=["CNPJ"], keep="first").reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", type=int, default=date.today().year,
                    help="ano do zip do informe (padrao: o corrente)")
    ap.add_argument("--meses", type=int, default=3,
                    help="quantas competencias finais ler do zip (padrao: 3)")
    ap.add_argument("--saida", default=str(SAIDA))
    ap.add_argument("--sem-cache", action="store_true",
                    help="rebaixa, ignorando ~/.fiib3_cache")
    ap.add_argument("--zip", default=None,
                    help="caminho de um inf_mensal_fii_AAAA.zip ja baixado")
    ap.add_argument("--sem-fiagro", action="store_true",
                    help="nao baixa o informe mensal de Fiagro")
    ap.add_argument("--sem-fiinfra", action="store_true",
                    help="nao baixa o informe diario dos FI-Infra da lista")
    args = ap.parse_args()

    print("=" * 68)
    print("  BAIXANDO O INFORME MENSAL DE FII DA CVM")
    print(f"  ano: {args.ano}")
    print("=" * 68)

    if args.zip:
        origem = Path(args.zip)
        if not origem.exists():
            print(f"\nERRO: {origem} nao existe.")
            return 1
        destino = cvm_fii._cache(f"inf_mensal_fii_{args.ano}.zip")
        destino.write_bytes(origem.read_bytes())
        print(f"\nUsando o zip local {origem} (sem acessar a rede).")
        try:
            zipfile.ZipFile(destino)
        except zipfile.BadZipFile:
            print("ERRO: o arquivo nao e um zip valido.")
            return 1
    elif not _testar_rota():
        return 1

    print("\nLendo o informe mensal...")
    ano = args.ano
    try:
        informe = cvm_fii.ler_informe(ano, meses=args.meses,
                                      usar_cache=not args.sem_cache)
    except Exception as exc:                                   # noqa: BLE001
        # Em janeiro o zip do ano corrente ainda pode nao existir; a competencia
        # de dezembro esta no zip do ano anterior de qualquer forma.
        log.warning("Informe de %d falhou (%s); tentando %d.", ano, exc, ano - 1)
        ano -= 1
        informe = cvm_fii.ler_informe(ano, meses=args.meses,
                                      usar_cache=not args.sem_cache)

    print(f"  {len(informe):,} fundos | competencia {informe['COMPETENCIA'].max()}")
    for campo, rotulo in (("PL", "patrimonio liquido"),
                          ("NOME", "razao social"),
                          ("PCT_IMOVEIS", "composicao da carteira"),
                          ("VP_COTA", "valor patrimonial por cota"),
                          ("COTAS", "numero de cotas"),
                          ("COTISTAS", "numero de cotistas"),
                          ("ISIN", "codigo ISIN"),
                          ("SEGMENTO", "segmento de atuacao")):
        n = int(informe[campo].notna().sum()) if campo in informe.columns else 0
        frac = n / max(len(informe), 1)
        marca = "ok   " if frac > 0.7 else ("AVISO" if frac > 0.2 else "FALHA")
        print(f"  [{marca}] {rotulo:30s}: {n:,} preenchidos")
        if frac <= 0.2:
            print("          -> rode verificar_fiis.py --colunas: a CVM "
                  "provavelmente renomeou a coluna.")

    # ---- Fiagro e FI-Infra ------------------------------------------------
    # Os tres vao para a mesma tabela. Fiagro e FI-Infra sao ranqueados junto
    # com os FII de papel (ver `config.familia_do_fundo`), e a coluna TIPO_FUNDO
    # e o que o site mostra ao lado do codigo.
    if not args.sem_fiagro:
        print("\nLendo o informe mensal de Fiagro...")
        try:
            fiagro = cvm_fii.ler_informe_fiagro(usar_cache=not args.sem_cache)
            print(f"  {len(fiagro):,} fundos | competencia "
                  f"{fiagro['COMPETENCIA'].max() if len(fiagro) else '-'}")
            informe = _juntar(informe, fiagro)
        except Exception as exc:                               # noqa: BLE001
            log.warning("Fiagro falhou (%s).", str(exc)[:120])
            print("  AVISO: nao consegui ler o Fiagro; sigo so com FII.")

    if not args.sem_fiinfra:
        print("\nConferindo a lista de FI-Infra...")
        try:
            from fiib3 import fiinfra as _fiinfra
            infra, avisos = _fiinfra.coletar(usar_cache=not args.sem_cache)
            print(f"  {len(infra):,} fundos conferidos"
                  + (f" | competencia {infra['COMPETENCIA'].max()}" if len(infra) else ""))
            for aviso in avisos:
                print(f"  - {aviso}")
            informe = _juntar(informe, infra)
        except Exception as exc:                               # noqa: BLE001
            log.warning("FI-Infra falhou (%s).", str(exc)[:120])
            print("  AVISO: nao consegui montar os FI-Infra; sigo sem eles.")

    if "TIPO_FUNDO" in informe.columns:
        print("\nTotal por tipo de veiculo:")
        for tipo, n in informe["TIPO_FUNDO"].value_counts().items():
            print(f"  {tipo:10s}: {n:,}")

    # O cad_fii.csv responde 404 desde a reestruturacao dos arquivos de FII. Ele
    # so acrescentava a situacao cadastral: a razao social vem do proprio
    # informe (`Nome_Fundo_Classe`). Por isso a falha aqui e informativa.
    print("\nBaixando o cadastro de fundos (opcional)...")
    try:
        cadastro = cvm_fii.baixar_cadastro(usar_cache=not args.sem_cache)
        print(f"  {len(cadastro):,} fundos no cadastro")
    except Exception as exc:                                   # noqa: BLE001
        log.info("Cadastro indisponivel (%s).", str(exc)[:60])
        print("  cadastro fora do ar — sem impacto: o nome vem do informe.")
        cadastro = pd.DataFrame(columns=["CNPJ", "SITUACAO", "TIPO"])

    saida = Path(args.saida)
    dados = arqi.exportar(informe, cadastro, saida)

    print(f"\n  Gravado em {saida}")
    print(f"  {dados['meta']['nFundos']:,} fundos | "
          f"{saida.stat().st_size / 1024:,.0f} KB | "
          f"competencia {dados['meta']['competencia']}")
    print("\nProximo passo: suba este arquivo para o GitHub")
    print("  (web -> public -> Add file -> Upload files -> arraste informe_fii.json)")
    print("e rode a acao 'Atualizar FIIs' na aba Actions.")

    if dados["meta"]["nFundos"] < 100:
        print("\n  AVISO: pouquissimos fundos. Rode verificar_fiis.py --colunas.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
