"""Mapeamento CD_CVM / CNPJ <-> ticker da B3.

O TCC dependia de uma planilha manual no Google Drive. Isso trouxe dois
problemas: (a) a planilha refletia o universo de 2023, então empresas
deslistadas entre 2018 e 2022 sumiam do backtest (viés de sobrevivência);
(b) a coluna LIQUIDEZ era estática, aplicada a todos os anos.

Aqui o mapa é reconstruído a partir da API pública de companhias listadas
da B3, que devolve `codeCVM` — a mesma chave dos arquivos da CVM.
Há três fontes, em ordem de preferência:
  1. cache local (parquet)
  2. API da B3
  3. CSV informado pelo usuário (mesmo formato da planilha antiga)
"""
from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path

import pandas as pd

from . import rede
from .config import CACHE_DIR

log = logging.getLogger(__name__)

B3_URL = ("https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy"
          "/CompanyCall/GetInitialCompanies/{payload}")
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

SUFIXOS_CANDIDATOS = ("3", "4", "11", "5", "6")

# Um código de negociação da B3 tem quatro caracteres alfanuméricos começando
# por letra — não quatro LETRAS. A regra antiga era `[A-Z]{4}`, e o comentário
# dela dizia estar cortando os emissores sem ação negociada. Não estava: das
# 3.189 companhias que a API devolve (já sem BDR), 3.111 passavam por ela,
# incluindo 2.612 SPEs e securitizadoras sem segmento. Quem de fato faz esse
# corte é o passo seguinte do pipeline, que só mantém quem tem EBIT nos
# arquivos da CVM, e depois o filtro de liquidez.
#
# O que `[A-Z]{4}` fazia mesmo era derrubar a B3 S.A. — prefixo B3SA, com um
# dígito no meio —, que pesa 3,3% do Ibovespa e nunca entrou no ranking.
# Ampliar a regra admite 70 prefixos a mais; 68 são SPEs sem DFP, que morrem
# no filtro de EBIT. As duas companhias reais são B3SA e B100.
PREFIXO_VALIDO = r"[A-Z][A-Z0-9]{3}"

# O parquet gravado antes desta correção foi filtrado pela regra estreita e não
# tem a B3 S.A. Trocar o nome do arquivo aposenta esse cache sozinho — sem isso
# a correção só apareceria quando alguém apagasse o cache na mão.
ARQUIVO_CACHE = "b3_empresas_v2.parquet"
CACHES_ANTIGOS = ("b3_empresas.parquet",)


def _cache(nome: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / nome


def _cache_de_emergencia() -> Path | None:
    """Qualquer mapa em disco, para quando a B3 não responde.

    Só é consultado no recuo. Um mapa velho é melhor que perder a rodada, mas
    o da regra antiga não tem a B3 S.A. — daí o aviso separado lá embaixo.
    """
    for nome in (ARQUIVO_CACHE,) + CACHES_ANTIGOS:
        arq = _cache(nome)
        if arq.exists():
            return arq
    return None


# A API da B3 responde em segundos na maior parte do tempo e simplesmente para
# de responder de vez em quando — em produção deu "Read timed out" com 90s de
# espera. Como é a única fonte do mapa prefixo -> CD_CVM, uma pane dela derruba
# a coleta inteira. Daí a insistência, a página menor na segunda tentativa e,
# adiante, o recuo para o cache antigo.
ESPERAS_B3 = (5.0, 20.0, 60.0)


def _pagina_b3(pagina: int, tamanho: int = 120) -> dict:
    ultimo = None
    for n, espera in enumerate((0.0,) + ESPERAS_B3):
        if espera:
            time.sleep(espera)
        # se a página cheia não veio, tenta uma menor: costuma ser o volume
        # da resposta que estoura o tempo, não a indisponibilidade do serviço
        tam = tamanho if n < 2 else max(30, tamanho // 2)
        payload = base64.b64encode(json.dumps(
            {"language": "pt-br", "pageNumber": pagina, "pageSize": tam}
        ).encode()).decode()
        try:
            r = rede.sessao().get(B3_URL.format(payload=payload),
                                  headers=HEADERS, timeout=120)
            r.raise_for_status()
            return r.json()
        except Exception as exc:                            # noqa: BLE001
            ultimo = exc
            log.warning("B3 não respondeu (página %d, tentativa %d/%d): %s",
                        pagina, n + 1, len(ESPERAS_B3) + 1, str(exc)[:140])
    raise RuntimeError(f"B3 não respondeu na página {pagina}: {ultimo}")


def _todas_as_paginas() -> list[dict]:
    linhas, pagina = [], 1
    while True:
        js = _pagina_b3(pagina)
        linhas.extend(js.get("results", []))
        total = js.get("page", {}).get("totalPages", 1)
        if pagina >= total:
            break
        pagina += 1
    return linhas


def baixar_empresas_b3(usar_cache: bool = True) -> pd.DataFrame:
    """Companhias listadas: codeCVM, prefixo do ticker, razão social, segmento."""
    arq = _cache(ARQUIVO_CACHE)
    if usar_cache and arq.exists():
        return pd.read_parquet(arq)

    try:
        linhas = _todas_as_paginas()
    except Exception as exc:                                # noqa: BLE001
        # Recuo para o cache antigo. Um mapa de ontem é infinitamente melhor
        # que nenhum: os prefixos da B3 mudam devagar, e sem ele a coleta do
        # dia inteira é perdida por causa de uma indisponibilidade de terceiro.
        antigo = _cache_de_emergencia()
        if antigo is not None:
            log.warning("%s — usando o mapa em cache de %s.", exc,
                        pd.Timestamp(antigo.stat().st_mtime, unit="s").date())
            if antigo.name != ARQUIVO_CACHE:
                log.warning("Esse cache é anterior à correção do filtro de "
                            "prefixo: a B3 S.A. (B3SA) não está nele.")
            return pd.read_parquet(antigo)
        raise RuntimeError(
            f"{exc}\nNão há cache anterior para usar no lugar. A B3 é a única "
            "fonte do mapa prefixo->CD_CVM; espere alguns minutos e rode de novo."
        ) from exc
    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    bruto = len(df)
    df = df.rename(columns={
        "codeCVM": "CD_CVM", "issuingCompany": "PREFIXO",
        "companyName": "DENOM_CIA", "tradingName": "NOME_PREGAO",
        "cnpj": "CNPJ", "segment": "SEGMENTO",
    })
    df["CD_CVM"] = pd.to_numeric(df["CD_CVM"], errors="coerce")
    df = df.dropna(subset=["CD_CVM", "PREFIXO"])
    df["CD_CVM"] = df["CD_CVM"].astype(int)

    # A API devolve todos os emissores registrados (~3.500), não apenas as
    # companhias com ações negociadas (~500). O corte de verdade vem depois,
    # no pipeline: só entra quem tem EBIT nos arquivos da CVM e passa no filtro
    # de liquidez. Aqui ficam as duas exclusões que dependem da própria B3.
    if "typeBDR" in df.columns:                    # BDRs: lastro estrangeiro
        vazio = df["typeBDR"].isna() | (df["typeBDR"].astype(str).str.strip() == "")
        df = df[vazio]
    df["PREFIXO"] = df["PREFIXO"].astype(str).str.strip().str.upper()
    df = df[df["PREFIXO"].str.fullmatch(PREFIXO_VALIDO)]
    df = df.sort_values("CD_CVM").drop_duplicates(subset=["PREFIXO"], keep="first")
    log.info("B3: %d emissores registrados -> %d prefixos de negociação", bruto, len(df))
    cols = [c for c in ["CD_CVM", "PREFIXO", "DENOM_CIA", "NOME_PREGAO", "CNPJ", "SEGMENTO"]
            if c in df.columns]
    df = df[cols].drop_duplicates()
    if usar_cache:
        df.to_parquet(arq, index=False)
    return df


def candidatos_de_ticker(empresas: pd.DataFrame,
                         sufixos: tuple[str, ...] = SUFIXOS_CANDIDATOS) -> pd.DataFrame:
    """Expande cada prefixo nos códigos possíveis (PETR -> PETR3, PETR4, ...)."""
    linhas = []
    for _, row in empresas.iterrows():
        for s in sufixos:
            linhas.append({"CD_CVM": row["CD_CVM"],
                           "TICKER": f"{row['PREFIXO']}{s}.SA",
                           "DENOM_CIA": row.get("DENOM_CIA"),
                           "SEGMENTO": row.get("SEGMENTO")})
    return pd.DataFrame(linhas)


def carregar_csv_usuario(caminho: str | Path) -> pd.DataFrame:
    """Aceita a planilha antiga (CNPJ_CIA;EMPRESA;TICKER;ACOES_CIRC;LIQUIDEZ)."""
    df = pd.read_csv(caminho, sep=None, engine="python", encoding="latin-1")
    df.columns = [c.strip().upper() for c in df.columns]
    ren = {"CNPJ_CIA": "CNPJ", "EMPRESA": "DENOM_CIA", "ACOES_CIRC": "ACOES"}
    df = df.rename(columns={k: v for k, v in ren.items() if k in df.columns})
    if "TICKER" in df.columns:
        df["TICKER"] = (df["TICKER"].astype(str).str.strip().str.upper()
                        .where(lambda s: s.str.endswith(".SA"),
                               lambda s: s + ".SA"))
    return df


def mapa_setorial(empresas: pd.DataFrame, cadastro_cvm: pd.DataFrame) -> pd.DataFrame:
    """Une o segmento da B3 com o setor de atividade do cadastro da CVM.

    O setor é o que permite excluir bancos, seguradoras e utilities,
    exclusão que o TCC não fez (e que Greenblatt considera obrigatória,
    porque ROIC e EV não fazem sentido para instituições financeiras).
    """
    cad = cadastro_cvm.copy()
    cad.columns = [c.strip().upper() for c in cad.columns]
    col_setor = next((c for c in ("SETOR_ATIV", "SETOR_ATIVIDADE", "SETOR")
                      if c in cad.columns), None)
    if col_setor is None:
        empresas = empresas.copy()
        empresas["SETOR"] = pd.NA
        return empresas
    cad = cad.rename(columns={col_setor: "SETOR"})
    if "CD_CVM" in cad.columns:
        cad["CD_CVM"] = pd.to_numeric(cad["CD_CVM"], errors="coerce")
    sit = cad["SIT"].astype(str).str.upper() if "SIT" in cad.columns else None
    if sit is not None:
        cad = cad[sit.str.contains("ATIVO", na=False)]
    cad = cad[["CD_CVM", "SETOR"]].dropna().drop_duplicates(subset=["CD_CVM"])
    return empresas.merge(cad, on="CD_CVM", how="left")
