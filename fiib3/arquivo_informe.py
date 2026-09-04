"""Arquivo de informe — a mesma ponte que `magicb3/arquivo_fundamentos.py`.

Motivo de existir, igual ao do lado das ações: `dados.cvm.gov.br` recusa
conexões vindas de servidores no exterior. Do GitHub Actions o IPv4 expira por
descarte de pacotes e o IPv6 não tem rota; Yahoo Finance e a API da B3
respondem normalmente de lá. Isso está documentado em `COMO_ATUALIZAR.md`, com
o diagnóstico que provou o bloqueio.

A separação é a mesma:

    informe mensal (CVM)  -> muda 1x por mês  -> baixado de um PC no Brasil,
                                                 gravado aqui e versionado
    mercado (Yahoo/B3)    -> muda todo dia    -> baixado pelo robô na nuvem

A diferença em relação às ações é a cadência: balanço muda quatro vezes por ano,
informe de FII muda todo mês. Na prática o arquivo aguenta bem passar do prazo —
patrimônio e número de cotas mudam devagar, e o que se perde é precisão no P/VP,
não a tela inteira. O `idade_em_dias` existe para avisar quando passou da conta.

O arquivo fica em torno de 250 KB para os ~700 fundos ativos.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

VERSAO = 1

# coluna no DataFrame -> nome curto no JSON
CAMPOS_TEXTO = {
    "CNPJ": "cnpj", "COMPETENCIA": "comp", "ISIN": "isin",
    "MANDATO": "mandato", "SEGMENTO": "segmento", "GESTAO": "gestao",
    "ADMINISTRADOR": "admin", "PUBLICO_ALVO": "publico",
    "EXCLUSIVO": "exclusivo", "NEGOCIA_BOLSA": "bolsa",
    "NOME": "nome", "SITUACAO": "situacao", "TIPO": "tipo",
}
CAMPOS_NUMERO = {
    "COTAS": "cotas", "VP_COTA": "vpCota", "COTISTAS": "cotistas",
    "PL": "pl", "ATIVO_TOTAL": "ativo",
    "RENT_EFETIVA_MES": "rentMes", "DY_MES_CVM": "dyMes",
}
CAMPOS_DATA = {"DT_INFORME": "dtInforme", "DT_FUNCIONAMENTO": "dtFuncionamento"}

# Colunas que o pipeline espera receber de volta. Uma que falte vira coluna
# vazia na importação em vez de KeyError três funções adiante.
COLUNAS_INFORME = (list(CAMPOS_TEXTO) + list(CAMPOS_NUMERO) + list(CAMPOS_DATA))


def _n(x):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)


def _t(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    s = str(x).strip()
    return s if s and s.lower() not in ("nan", "nat", "<na>") else None


def _d(x):
    t = _t(x)
    return t[:10] if t else None


def exportar(informe: pd.DataFrame, cadastro: pd.DataFrame | None,
             caminho: Path | str) -> dict:
    """Grava o informe consolidado (já com o cadastro anexado)."""
    df = informe.copy()
    if cadastro is not None and not cadastro.empty:
        faltantes = [c for c in ("NOME", "SITUACAO", "TIPO")
                     if c in cadastro.columns and c not in df.columns]
        df = df.merge(cadastro[["CNPJ"] + faltantes], on="CNPJ", how="left")

    def col(nome: str) -> pd.Series:
        if nome in df.columns:
            return df[nome]
        return pd.Series([None] * len(df), index=df.index)

    textos = {alvo: col(origem) for origem, alvo in CAMPOS_TEXTO.items()}
    numeros = {alvo: col(origem) for origem, alvo in CAMPOS_NUMERO.items()}
    datas = {alvo: col(origem) for origem, alvo in CAMPOS_DATA.items()}

    fundos = []
    for i in df.index:
        if not _t(textos["cnpj"][i]):
            continue
        item = {k: _t(s[i]) for k, s in textos.items()}
        item.update({k: _n(s[i]) for k, s in numeros.items()})
        item.update({k: _d(s[i]) for k, s in datas.items()})
        fundos.append(item)

    competencia = ""
    if "COMPETENCIA" in df.columns and len(df):
        competencia = str(df["COMPETENCIA"].dropna().max() or "")

    dados = {
        "meta": {
            "versao": VERSAO,
            "geradoEm": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "competencia": competencia,
            "nFundos": len(fundos),
            "origem": "dados.cvm.gov.br (informe mensal de FII + cad_fii)",
        },
        "fundos": fundos,
    }

    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
    return dados


def importar(caminho: Path | str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Lê o arquivo e devolve (informe, cadastro) no formato do pipeline."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(
            f"{caminho} não existe.\n"
            "Esse arquivo é gerado por `python baixar_informe_fii.py`, que precisa "
            "rodar num computador no Brasil — a CVM recusa conexões do exterior."
        )
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    fundos = pd.DataFrame(dados.get("fundos") or [])
    if fundos.empty:
        raise ValueError(f"{caminho} não tem fundos.")

    informe = pd.DataFrame(index=fundos.index)
    for origem, alvo in CAMPOS_TEXTO.items():
        informe[origem] = fundos.get(alvo, pd.Series(pd.NA, index=fundos.index)
                                     ).astype("string")
    for origem, alvo in CAMPOS_NUMERO.items():
        informe[origem] = pd.to_numeric(fundos.get(alvo), errors="coerce")
    for origem, alvo in CAMPOS_DATA.items():
        informe[origem] = pd.to_datetime(fundos.get(alvo), errors="coerce")

    # O CNPJ vira chave de merge com o mapa da B3: precisa voltar com os 14
    # dígitos e os zeros à esquerda que o JSON preservou como texto.
    informe["CNPJ"] = (informe["CNPJ"].str.replace(r"\D", "", regex=True)
                       .str.zfill(14))

    cadastro = informe[["CNPJ", "NOME", "SITUACAO", "TIPO"]].copy()
    informe = informe.drop(columns=["NOME", "SITUACAO", "TIPO"])
    return informe.reset_index(drop=True), cadastro.reset_index(drop=True)


def idade_em_dias(caminho: Path | str) -> int | None:
    """Há quantos dias o arquivo foi gerado. Serve para avisar que envelheceu."""
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        gerado = pd.Timestamp(dados["meta"]["geradoEm"])
        return int((pd.Timestamp.now() - gerado).days)
    except Exception:                                          # noqa: BLE001
        return None


def competencia(caminho: Path | str) -> str | None:
    try:
        dados = json.loads(Path(caminho).read_text(encoding="utf-8"))
        return dados["meta"].get("competencia") or None
    except Exception:                                          # noqa: BLE001
        return None
