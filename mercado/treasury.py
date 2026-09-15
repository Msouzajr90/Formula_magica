# -*- coding: utf-8 -*-
"""Curvas americanas — nominal e de TIPS — do Tesouro dos Estados Unidos.

Duas séries, o mesmo formato:

  * `daily_treasury_yield_curve` — par yields nominais, de 1 mês a 30 anos;
  * `daily_treasury_real_yield_curve` — yields reais (TIPS), de 5 a 30 anos.

O TIPS mais curto publicado é o de 5 anos. É por isso que a comparação real
com a NTN-B começa em 5 anos e a nominal começa em 1.

A conversão de base, que muda o resultado
-----------------------------------------
O Treasury publica *bond-equivalent yield*: juro com capitalização semestral.
A taxa brasileira é efetiva ao ano. Subtrair uma da outra direto — que é o que
quase todo mundo faz — mistura duas convenções e infla o spread.

    (1 + 4,97%/2)^2 - 1 = 5,03%

Seis pontos-base num vértice de 10 anos. Pouco para uma manchete, demais para
um número que a tela apresenta como "a diferença de juros entre Brasil e EUA".
Tudo aqui sai já convertido para efetiva ao ano, e a tela diz isso.
"""
from __future__ import annotations

import io
import logging
from datetime import date

import pandas as pd

log = logging.getLogger(__name__)

BASE = ("https://home.treasury.gov/resource-center/data-chart-center/"
        "interest-rates/daily-treasury-rates.csv/{ano}/all"
        "?type={tipo}&field_tdr_date_value={ano}&page&_format=csv")

TIPO_NOMINAL = "daily_treasury_yield_curve"
TIPO_REAL = "daily_treasury_real_yield_curve"

# Cabeçalhos das colunas -> prazo em anos. O Treasury já escreveu "1.5 Month",
# "1 Mo" e "1 YR"/"1 Yr" em anos diferentes, então o mapa é por texto
# normalizado, e o que não estiver no mapa é ignorado em vez de quebrar.
_UNIDADE = {"mo": 1 / 12, "month": 1 / 12, "yr": 1.0, "year": 1.0}


def prazo_da_coluna(nome: str) -> float | None:
    partes = nome.strip().strip('"').lower().replace("-", " ").split()
    if len(partes) != 2:
        return None
    try:
        n = float(partes[0])
    except ValueError:
        return None
    u = _UNIDADE.get(partes[1].rstrip("s"))
    return n * u if u else None


def para_efetiva_ao_ano(taxa_semestral_pct: float) -> float:
    """Bond-equivalent (capitalização semestral) -> efetiva ao ano. Ambas em %."""
    y = taxa_semestral_pct / 100.0
    return ((1 + y / 2) ** 2 - 1) * 100.0


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
def baixar_csv(tipo: str, ano: int, sessao=None, timeout: int = 120) -> str:
    import requests

    s = sessao or requests
    r = s.get(BASE.format(ano=ano, tipo=tipo), timeout=timeout)
    r.raise_for_status()
    return r.text


def baixar(tipo: str, anos: list[int], sessao=None) -> pd.DataFrame:
    """Junta um ou mais anos. Seis meses de histórico às vezes cruza o ano."""
    pedacos = []
    for ano in anos:
        try:
            pedacos.append(ler_csv(baixar_csv(tipo, ano, sessao)))
        except Exception as exc:                               # noqa: BLE001
            log.warning("Treasury %s de %s falhou: %s", tipo, ano, exc)
    if not pedacos:
        raise RuntimeError(f"Nenhum ano do Treasury ({tipo}) foi baixado.")
    return (pd.concat(pedacos, ignore_index=True)
            .drop_duplicates(subset=["DATA", "PRAZO"], keep="last")
            .sort_values(["DATA", "PRAZO"]).reset_index(drop=True))


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def ler_csv(texto: str) -> pd.DataFrame:
    """CSV do Treasury -> tabela longa DATA, PRAZO, TAXA (efetiva ao ano)."""
    df = pd.read_csv(io.StringIO(texto))
    df.columns = [c.strip() for c in df.columns]
    if "Date" not in df.columns:
        raise ValueError(f"CSV do Treasury sem coluna Date: {list(df.columns)[:6]}")

    prazos = {c: prazo_da_coluna(c) for c in df.columns if c != "Date"}
    prazos = {c: p for c, p in prazos.items() if p}
    if not prazos:
        raise ValueError(f"Nenhuma coluna de prazo reconhecida: {list(df.columns)}")

    longo = df.melt(id_vars="Date", value_vars=list(prazos),
                    var_name="COLUNA", value_name="BRUTA")
    longo["DATA"] = pd.to_datetime(longo["Date"], format="%m/%d/%Y", errors="coerce")
    longo["PRAZO"] = longo["COLUNA"].map(prazos)
    longo["BRUTA"] = pd.to_numeric(longo["BRUTA"], errors="coerce")
    longo = longo.dropna(subset=["DATA", "PRAZO", "BRUTA"])
    longo["TAXA"] = longo["BRUTA"].map(para_efetiva_ao_ano)
    return longo[["DATA", "PRAZO", "TAXA", "BRUTA"]].reset_index(drop=True)


def curva(df: pd.DataFrame, quando: date) -> list[tuple[float, float]]:
    """(prazo, taxa efetiva) no pregão de `quando` ou no último antes dele.

    Os feriados não coincidem: 7 de setembro fecha o Brasil e não os Estados
    Unidos, o Memorial Day o contrário. Casar as fotos por data exata deixaria
    buracos, então vale o último pregão americano até a data brasileira.
    """
    datas = sorted({d.date() for d in df["DATA"].unique()})
    anteriores = [d for d in datas if d <= quando]
    if not anteriores:
        return []
    d = max(anteriores)
    sel = df[df["DATA"] == pd.Timestamp(d)].sort_values("PRAZO")
    return [(float(r.PRAZO), float(r.TAXA)) for r in sel.itertuples()]


def data_efetiva(df: pd.DataFrame, quando: date) -> date | None:
    datas = sorted({d.date() for d in df["DATA"].unique()})
    anteriores = [d for d in datas if d <= quando]
    return max(anteriores) if anteriores else None
