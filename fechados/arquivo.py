"""A ponte entre o PC no Brasil e o site — mesma ideia de `arquivo_informe.py`.

`dados.cvm.gov.br` recusa conexões vindas de fora do país e o GitHub Actions
roda nos Estados Unidos. A divisão é a de sempre:

    baixar_fechados.py (no PC do Marco)  ->  fundos_fechados.json  ->  repositório
    robô do GitHub                       ->  copia para o site

A diferença em relação ao FII é que aqui **não há etapa de mercado**: fundo
fechado de balcão não tem preço nem proventos no Yahoo, então o arquivo gerado
já é o conteúdo final da aba. O robô não precisa acrescentar nada — o que
simplifica, e também quer dizer que o arquivo envelhece com o informe: mensal
para FII e Fiagro, quadrimestral para FIP.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

from . import config as C

VERSAO = 1

TEXTO = ("CNPJ", "NOME", "TIPO", "COMPETENCIA", "DT_INFORME", "PERIODICIDADE",
         "PRAZO", "DT_VENCIMENTO", "DT_INICIO", "PUBLICO", "ADMINISTRADOR",
         "SEGMENTO")
NUMERO = ("ANOS_RESTANTES", "IDADE_ANOS", "COTISTAS", "COTISTAS_PF",
          "COTISTAS_VAR_12M", "COTISTAS_VAR_ULTIMO", "PL", "VP_COTA", "COTAS",
          "RENT_MES", "RENT_12M", "RENT_VP_12M", "MESES_DESCARTADOS",
          "DY_MES", "DY_12M", "AMORT_MES", "AMORT_12M",
          "MESES_COM_AMORT", "TAXA_ADM", "N_INFORMES")
BOOLEANO = ("PRAZO_SUSPEITO", "PRAZO_VENCIDO", "ROTULO_CONFLITA",
            "EXCLUSIVO", "BOLSA", "CETIP", "MBO")

# Nome curto no JSON — o arquivo é lido pelo navegador, e 574 fundos vezes 37
# campos com nome longo custa caro à toa.
CURTO = {
    "CNPJ": "cnpj", "NOME": "nome", "TIPO": "tipo", "COMPETENCIA": "comp",
    "DT_INFORME": "dtInforme", "PERIODICIDADE": "periodo", "PRAZO": "prazo",
    "DT_VENCIMENTO": "vence", "ANOS_RESTANTES": "anosRest",
    "PRAZO_SUSPEITO": "prazoSuspeito", "PRAZO_VENCIDO": "prazoVencido",
    "ROTULO_CONFLITA": "prazoConflita",
    "DT_INICIO": "inicio", "IDADE_ANOS": "idade", "COTISTAS": "cotistas",
    "COTISTAS_PF": "cotistasPf", "COTISTAS_VAR_12M": "cotistasVar12",
    "COTISTAS_VAR_ULTIMO": "cotistasVarUlt", "PL": "pl", "VP_COTA": "vpCota",
    "COTAS": "cotas", "RENT_MES": "rentMes", "RENT_12M": "rent12",
    "RENT_VP_12M": "rentVp12", "MESES_DESCARTADOS": "mesesDescartados",
    "DY_MES": "dyMes", "DY_12M": "dy12", "AMORT_MES": "amortMes",
    "AMORT_12M": "amort12", "MESES_COM_AMORT": "mesesAmort",
    "TAXA_ADM": "taxaAdm", "PUBLICO": "publico", "EXCLUSIVO": "exclusivo",
    "BOLSA": "bolsa", "CETIP": "cetip", "MBO": "mbo",
    "ADMINISTRADOR": "admin", "SEGMENTO": "segmento", "N_INFORMES": "nInformes",
}


def _n(x):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(v) or math.isinf(v)) else round(v, 8)


def _t(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    s = str(x).strip()
    return s if s and s.lower() not in ("nan", "nat", "<na>", "none") else None


def _b(x):
    if x is None or (isinstance(x, float) and math.isnan(x)) or x is pd.NA:
        return None
    if isinstance(x, str):
        return {"s": True, "n": False, "true": True, "false": False}.get(
            x.strip().lower())
    try:
        return bool(x)
    except (TypeError, ValueError):
        return None


def exportar(df: pd.DataFrame, caminho: Path | str, *,
             avisos: list[str] | None = None,
             params: C.ParamsFechados | None = None) -> dict:
    """Grava o consolidado. Os avisos vão junto: quem publica precisa vê-los."""
    fundos = []
    for _, linha in df.iterrows():
        cnpj = _t(linha.get("CNPJ"))
        if not cnpj:
            continue
        # Campo nulo sai do objeto em vez de virar `"x":null`. Num universo com
        # FIP — que não publica prazo, rentabilidade nem taxa — isso corta
        # perto de um terço do arquivo, e o lado JavaScript já precisa tratar
        # ausência de qualquer jeito, porque "sem dado" é situação real aqui.
        item: dict = {}
        for grupo, converte in ((TEXTO, _t), (NUMERO, _n), (BOOLEANO, _b)):
            for coluna in grupo:
                valor = converte(linha.get(coluna))
                if valor is not None:
                    item[CURTO[coluna]] = valor
        item["cnpj"] = cnpj
        fundos.append(item)

    por_tipo: dict[str, int] = {}
    if "TIPO" in df.columns and len(df):
        por_tipo = {str(k): int(v) for k, v in df["TIPO"].value_counts().items()}
    com_prazo = int((df.get("PRAZO") == C.PRAZO_DETERMINADO).sum()) if len(df) else 0

    dados = {
        "meta": {
            "versao": VERSAO,
            "geradoEm": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
            "nFundos": len(fundos),
            "porTipo": por_tipo,
            "comPrazoDeterminado": com_prazo,
            "competencia": (str(df["COMPETENCIA"].dropna().max())
                            if len(df) and "COMPETENCIA" in df else ""),
            "origem": "dados.cvm.gov.br — informe mensal de FII e Fiagro, "
                      "informe quadrimestral de FIP",
            "params": (params or C.ParamsFechados()).to_dict(),
            "avisos": list(avisos or []),
        },
        "fundos": fundos,
    }
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(dados, ensure_ascii=False,
                                  separators=(",", ":")), encoding="utf-8")
    return dados


def importar(caminho: Path | str) -> pd.DataFrame:
    """Lê de volta no formato consolidado — usado pelos testes e pelo robô."""
    caminho = Path(caminho)
    if not caminho.exists():
        raise FileNotFoundError(
            f"{caminho} não existe. Esse arquivo é gerado por "
            "`python baixar_fechados.py`, que precisa rodar num computador no "
            "Brasil — a CVM recusa conexões do exterior.")
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    fundos = pd.DataFrame(dados.get("fundos") or [])
    if fundos.empty:
        raise ValueError(f"{caminho} não tem fundos.")
    invertido = {v: k for k, v in CURTO.items()}
    out = fundos.rename(columns=invertido)
    for coluna in C.COLUNAS:
        if coluna not in out.columns:
            out[coluna] = None
    out["CNPJ"] = (out["CNPJ"].astype("string")
                   .str.replace(r"\D", "", regex=True).str.zfill(14))
    return out[list(C.COLUNAS)]
