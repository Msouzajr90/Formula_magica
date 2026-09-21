# -*- coding: utf-8 -*-
"""Sonda o que faltou: o informe de FIP atual e o Fiagro em várias competências.

PRECISA RODAR NUM COMPUTADOR NO BRASIL.

Duas pendências da sondagem anterior
------------------------------------
**FIP.** O `INF_TRIMESTRAL` existe de 2010 a 2023 e para ali. Não foi
descontinuado: virou **informe QUADRIMESTRAL** a partir de 2024, em dataset
próprio. Este script lista o diretório novo e abre o arquivo mais recente. O
que se sabe do de 2023: `VL_PATRIM_LIQ`, `VL_CAP_COMPROM`, `VL_CAP_INTEGR`,
`NR_TOTAL_COTST_SUBSCR` e `VL_QUOTA_CLASSE` vêm preenchidos, enquanto
`NR_COTST`, `QT_COTA` e `VL_PATRIM_COTA` vêm **vazios** — as três colunas de
nome mais óbvio são justamente as que não servem.

**Fiagro.** O zip da competência 202608 trouxe **9 fundos**, e o informe
consolidado do projeto tem 285 Fiagro. Ou aquela competência saiu quase vazia,
ou o arquivo está partido. Este script lê seis competências seguidas e mostra
quantos fundos há em cada uma, para separar as duas hipóteses.

Uso:
    python sondar_fip.py
    python sondar_fip.py --competencias 12
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path

import pandas as pd

from fiib3 import cvm_fii

RAIZ = Path(__file__).parent
SAIDA = RAIZ / "amostra_fontes" / "fundos"
BASE = "https://dados.cvm.gov.br/dados"

# Candidatos, em ordem de aposta. O índice de cada um é lido de verdade — se o
# diretório não existir, o script diz isso e passa para o próximo, em vez de
# inventar um nome de arquivo.
DIRETORIOS_FIP = (
    ("quadrimestral", f"{BASE}/FIP/DOC/INF_QUADRIMESTRAL/DADOS/"),
    ("trimestral", f"{BASE}/FIP/DOC/INF_TRIMESTRAL/DADOS/"),
    ("cadastro", f"{BASE}/FIP/CAD/DADOS/"),
    ("raiz FIP", f"{BASE}/FIP/DOC/"),
)

# Os FIP que aparecem na tela do secundário da XP.
PISTAS = ("NEWAVE", "JIVE", "KINEA", "XP INFRA", "XP SPECIAL",
          "XP PRIVATE EQUITY", "SPX", "XP SELECTION", "SPX PRIVATE")

INTERESSAM = ("CNPJ", "DENOM", "DT_COMPTC", "VL_PATRIM_LIQ", "NR_COTST",
              "NR_TOTAL_COTST_SUBSCR", "VL_QUOTA_CLASSE", "VL_PATRIM_COTA",
              "VL_CAP_COMPROM", "VL_CAP_INTEGR", "PUBLICO_ALVO", "CLASSE_COTA",
              "PRAZO", "DT_")


def listar(url: str) -> list[str]:
    try:
        html = cvm_fii._baixar(url, timeout=120).decode("utf-8", "ignore")
    except Exception as exc:                                       # noqa: BLE001
        print(f"    indisponivel ({str(exc)[:70]})")
        return []
    achados = re.findall(r'href="([^"?]+\.(?:zip|csv))"', html, flags=re.I)
    return sorted({a.rsplit("/", 1)[-1] for a in achados})


def abrir(url: str):
    nome = url.rsplit("/", 1)[-1]
    arq = cvm_fii._cache(nome)
    if arq.exists() and arq.stat().st_size > 1024:
        conteudo = arq.read_bytes()
    else:
        conteudo = cvm_fii._baixar(url, timeout=900)
        arq.write_bytes(conteudo)
    if conteudo[:2] == b"PK":
        zf = zipfile.ZipFile(io.BytesIO(conteudo))
        nomes = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        return {n: cvm_fii._ler_csv(zf, n) for n in nomes}
    return {nome: pd.read_csv(io.BytesIO(conteudo), sep=";",
                              encoding="ISO-8859-1", dtype="string",
                              low_memory=False)}


def preenchidas(df: pd.DataFrame, colunas) -> dict:
    out = {}
    for c in colunas:
        s = df[c].fillna("").astype("string").str.strip()
        nao_vazio = s.ne("") & s.ne("0") & ~s.str.fullmatch(r"0[.,]0*", na=False)
        out[c] = round(100 * int(nao_vazio.sum()) / max(len(s), 1), 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--competencias", type=int, default=6,
                    help="quantas competencias de Fiagro conferir")
    args = ap.parse_args()
    SAIDA.mkdir(parents=True, exist_ok=True)
    resumo: dict = {"gerado_em": str(pd.Timestamp.now())[:16]}

    # ---- FIP ---------------------------------------------------------------
    print("=" * 72)
    print("  FIP — procurando o informe atual")
    print("=" * 72)
    resumo["fip"] = {}
    escolhido = None
    for rotulo, url in DIRETORIOS_FIP:
        print(f"\n  [{rotulo}] {url}")
        arquivos = listar(url)
        resumo["fip"][rotulo] = arquivos
        if arquivos:
            print(f"    {len(arquivos)} arquivo(s); ultimos: {arquivos[-4:]}")
            if escolhido is None and rotulo in ("quadrimestral", "trimestral"):
                escolhido = (url, arquivos[-1])
        else:
            print("    nada no indice")

    if escolhido:
        url, nome = escolhido
        print(f"\n  abrindo {nome}")
        try:
            tabelas = abrir(url + nome)
            for tab, df in list(tabelas.items())[:4]:
                if df.empty:
                    continue
                print(f"\n  {tab}: {len(df):,} linhas, {len(df.columns)} colunas")
                c_data = cvm_fii.coluna(df, "dt_comptc", "data_referencia",
                                        obrigatoria=False)
                if c_data:
                    comps = Counter(df[c_data].dropna())
                    print(f"    competencias: "
                          f"{[c for c, _ in comps.most_common(6)]}")
                alvo = [c for c in df.columns
                        if any(p in c.upper() for p in INTERESSAM)]
                medidas = preenchidas(df, alvo)
                print("    preenchimento das colunas que interessam:")
                for c, pct in medidas.items():
                    marca = "ok  " if pct > 50 else "VAZIA"
                    print(f"      [{marca}] {c:32s} {pct:5.1f}%")
                resumo["fip"].setdefault("medidas", {})[tab] = medidas

                c_nome = cvm_fii.coluna(df, "denom_social", "nome",
                                        obrigatoria=False)
                if c_nome:
                    nomes = df[c_nome].fillna("").astype("string").str.upper()
                    print("    fundos da tela do secundario:")
                    achou_algum = False
                    for p in PISTAS:
                        bate = sorted({str(x) for x in
                                       df.loc[nomes.str.contains(p, na=False), c_nome]})
                        if bate:
                            achou_algum = True
                            print(f"      {p}: {len(bate)} fundo(s) — {bate[0][:52]}")
                    if not achou_algum:
                        print("      nenhum dos oito apareceu")
                df.head(400).to_csv(SAIDA / f"fip2__{Path(tab).stem[:40]}.csv",
                                    sep=";", index=False, encoding="utf-8")
        except Exception as exc:                                   # noqa: BLE001
            print(f"  FALHOU: {str(exc)[:140]}")
            resumo["fip"]["erro"] = str(exc)[:200]

    # ---- Fiagro ------------------------------------------------------------
    print(f"\n{'=' * 72}")
    print("  FIAGRO — quantos fundos por competencia")
    print("=" * 72)
    hoje = pd.Timestamp.today()
    linhas = {}
    for i in range(1, args.competencias + 1):
        comp = (hoje - pd.DateOffset(months=i)).strftime("%Y%m")
        try:
            zf = cvm_fii.baixar_informe_fiagro(comp, usar_cache=True)
            nomes = [n for n in zf.namelist()
                     if n.lower().endswith(".csv") and "subclasse" not in n.lower()]
            df = cvm_fii._ler_csv(zf, nomes[-1]) if nomes else pd.DataFrame()
            c_cnpj = cvm_fii.coluna(df, "cnpj_classe", "cnpj", obrigatoria=False)
            n = df[c_cnpj].nunique() if c_cnpj else 0
            prazo = cvm_fii.coluna(df, "prazo_duracao", obrigatoria=False)
            vals = (dict(Counter(df[prazo].dropna()).most_common(3))
                    if prazo else {})
            linhas[comp] = {"fundos": int(n), "prazo": {str(k): int(v)
                                                        for k, v in vals.items()}}
            print(f"  {comp}: {n:4d} fundos | prazo: {vals}")
        except Exception as exc:                                   # noqa: BLE001
            linhas[comp] = {"erro": str(exc)[:80]}
            print(f"  {comp}: falhou ({str(exc)[:70]})")
    resumo["fiagro_por_competencia"] = linhas

    destino = SAIDA / "resumo_fip.json"
    destino.write_text(json.dumps(resumo, ensure_ascii=False, indent=1,
                                  default=str), encoding="utf-8")
    print(f"\n  Gravado em {destino}")
    print("\nMe avise quando terminar — eu leio direto da pasta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
