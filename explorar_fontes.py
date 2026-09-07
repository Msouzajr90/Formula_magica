# -*- coding: utf-8 -*-
"""Script TEMPORARIO, segunda passada: o registro de fundos e classes da CVM.

A primeira passada respondeu o Fiagro e deixou o FI-Infra travado num ponto:
falta ligar o CNPJ do fundo ao codigo de negociacao na B3. O `cad_fi.csv` nao
tem ISIN, e os 194 fundos com "INFRAESTRUTURA" no nome estao todos com situacao
CANCELADA — sao o registro antigo, anterior a Resolucao 175.

Resta o `registro_fundo_classe.zip` (6 MB), que e o cadastro novo. Se houver
ISIN ou codigo de negociacao ali, o FI-Infra entra; se nao houver, entra so com
uma lista mantida a mao, e isso muda a conversa.

Roda no seu PC. Nao altera nada do projeto.

Uso:
    .venv\\Scripts\\python.exe explorar_fontes.py
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pandas as pd

from fiib3.cvm_fii import _sessao

SAIDA = Path(__file__).parent / "amostra_fontes"
REGISTRO = "https://dados.cvm.gov.br/dados/FI/CAD/DADOS/registro_fundo_classe.zip"

# Se algum destes aparecer, o FI-Infra esta resolvido.
PISTAS_TICKER = ("ISIN", "NEGOCIAC", "TICKER", "CODIGO", "SIGLA", "BOLSA", "B3")
# Os fundos que o Marco citou, para conferir no meio de dezenas de milhares.
NOMES_ALVO = ("SPARTA INFRA", "SPARTA FIAGRO")


def main() -> int:
    SAIDA.mkdir(exist_ok=True)
    print(f"Baixando {REGISTRO} ...")
    r = _sessao().get(REGISTRO, timeout=600)
    r.raise_for_status()
    print(f"  {len(r.content)/1024/1024:,.1f} MB")
    (SAIDA / "registro_fundo_classe.zip").write_bytes(r.content)

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    print(f"\nArquivos no zip: {zf.namelist()}")

    achados = {}
    for nome in zf.namelist():
        if not nome.lower().endswith(".csv"):
            continue
        df = pd.read_csv(zf.open(nome), sep=";", encoding="ISO-8859-1",
                         dtype="string", low_memory=False, nrows=200_000)
        print(f"\n{'=' * 68}\n### {nome}: {len(df):,} linhas lidas, "
              f"{len(df.columns)} colunas\n{'=' * 68}")
        for c in df.columns:
            marca = "  <<< PISTA" if any(p in c.upper() for p in PISTAS_TICKER) else ""
            print(f"   - {c}{marca}")

        pistas = [c for c in df.columns if any(p in c.upper() for p in PISTAS_TICKER)]
        achados[nome] = {"linhas": int(len(df)), "colunas": list(df.columns),
                         "pistas": pistas}

        # tipo de fundo: o FI-Infra tem rotulo proprio?
        for c in df.columns:
            if any(p in c.upper() for p in ("TP_", "TIPO", "CLASSE", "CATEG", "SIT")):
                vc = df[c].value_counts(dropna=False).head(10).to_dict()
                print(f"\n  valores de {c}: {vc}")

        col_nome = next((c for c in df.columns
                         if "DENOM" in c.upper() or "NOME" in c.upper()), None)
        if col_nome:
            alvo = df[df[col_nome].str.contains("|".join(NOMES_ALVO),
                                                case=False, na=False)]
            print(f"\n  fundos Sparta encontrados: {len(alvo)}")
            if len(alvo):
                mostrar = [c for c in df.columns
                           if c in pistas or c == col_nome
                           or "CNPJ" in c.upper() or "SIT" in c.upper()][:8]
                print(alvo[mostrar].head(6).to_string(index=False, max_colwidth=38))
                alvo.to_csv(SAIDA / f"sparta_{Path(nome).stem}.csv", sep=";",
                            index=False, encoding="utf-8")

            infra = df[df[col_nome].str.contains("INFRAESTRUTURA", case=False, na=False)]
            print(f"  fundos com INFRAESTRUTURA no nome: {len(infra):,}")
            if len(infra):
                infra.head(400).to_csv(SAIDA / f"infra_{Path(nome).stem}.csv",
                                       sep=";", index=False, encoding="utf-8")

    (SAIDA / "resumo_registro.json").write_text(
        json.dumps(achados, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{'=' * 68}")
    print(f"  Pronto. Amostras em {SAIDA}")
    print("  Me avise que eu leio daqui.")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
