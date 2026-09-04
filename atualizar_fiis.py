# -*- coding: utf-8 -*-
"""Gera o `web/public/fiis.json` que a aba de fundos imobiliários consome.

Mesma divisão de trabalho do `atualizar_dados.py`: o Python baixa e trata, o
navegador ranqueia e simula. O que sai daqui é matéria-prima — os indicadores
de cada fundo — e não uma carteira pronta, justamente para que os controles do
site (pesos dos fatores, filtros, escolha dos fundos) tenham o que recalcular.

Uso:
    python atualizar_fiis.py                  # dados reais
    python atualizar_fiis.py --demo           # sintéticos, para ver a tela
    python atualizar_fiis.py --liquidez 300000
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

from fiib3.config import ParamsFII

SAIDA = Path(__file__).parent / "web" / "public" / "fiis.json"
MESES_SERIE = 24          # série de rendimentos exportada por fundo


def _num(x, casas: int = 8):
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if (math.isnan(v) or math.isinf(v)) else round(v, casas)


def _texto(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    s = str(x).strip()
    return s if s and s.lower() not in ("nan", "nat", "<na>") else None


def _data(x):
    t = _texto(x)
    return t[:10] if t else None


def montar_json(res: dict, p: ParamsFII) -> dict:
    rk = res["ranking"]
    mensal = res.get("mensal")

    fundos = []
    for r in rk.itertuples():
        fundos.append({
            "ticker": _texto(r.TICKER),
            "nome": _texto(getattr(r, "NOME", None)) or _texto(getattr(r, "NOME_B3", None)),
            "cnpj": _texto(getattr(r, "CNPJ", None)),
            "familia": _texto(getattr(r, "FAMILIA", None)),
            "segmento": _texto(getattr(r, "SEGMENTO", None)),
            "mandato": _texto(getattr(r, "MANDATO", None)),
            "gestao": _texto(getattr(r, "GESTAO", None)),
            "pctImoveis": _num(getattr(r, "PCT_IMOVEIS", None), 4),
            "pctPapel": _num(getattr(r, "PCT_PAPEL", None), 4),
            "pctFof": _num(getattr(r, "PCT_FOF", None), 4),
            "admin": _texto(getattr(r, "ADMINISTRADOR", None)),
            "preco": _num(getattr(r, "PRECO", None), 2),
            "vpCota": _num(getattr(r, "VP_COTA", None), 4),
            "pvp": _num(getattr(r, "P_VP", None), 4),
            "dy12m": _num(getattr(r, "DY_12M", None), 6),
            "dyMediano": _num(getattr(r, "DY_MEDIANO", None), 6),
            "dySobreVp": _num(getattr(r, "DY_SOBRE_VP", None), 6),
            "rendMensal": _num(getattr(r, "RENDIMENTO_MENSAL", None), 6),
            "ultimoProvento": _num(getattr(r, "ULTIMO_PROVENTO", None), 6),
            "dtUltimoProvento": _data(getattr(r, "DT_ULTIMO_PROVENTO", None)),
            "mesesPagos12": _num(getattr(r, "MESES_PAGOS_12M", None), 0),
            "mesesPagos36": _num(getattr(r, "MESES_PAGOS_36M", None), 0),
            "cvProventos": _num(getattr(r, "CV_PROVENTOS", None), 4),
            "consistencia": _num(getattr(r, "CONSISTENCIA", None), 4),
            "razaoExtra": _num(getattr(r, "RAZAO_EXTRA", None), 4),
            "liquidez": _num(getattr(r, "LIQUIDEZ", None), 0),
            "pl": _num(getattr(r, "PL", None), 0),
            "cotas": _num(getattr(r, "COTAS", None), 0),
            "cotistas": _num(getattr(r, "COTISTAS", None), 0),
            "var12m": _num(getattr(r, "VAR_12M", None), 6),
            "retorno12m": _num(getattr(r, "RETORNO_12M", None), 6),
            "competencia": _texto(getattr(r, "COMPETENCIA", None)),
            "alerta": _texto(getattr(r, "ALERTA", None)),
            "serie": _serie(mensal, getattr(r, "TICKER", None)),
        })

    excluidos = []
    for r in res["excluidos"].head(500).itertuples():
        excluidos.append({
            "ticker": _texto(getattr(r, "TICKER", None)),
            "nome": _texto(getattr(r, "NOME", None)),
            "segmento": _texto(getattr(r, "SEGMENTO", None)),
            "motivo": _texto(getattr(r, "MOTIVO_EXCLUSAO", None)),
        })

    return {
        "meta": {**res["meta"], "versao": 1, "pesosPadrao": p.pesos_fatores(),
                 "filtros": {"liquidez": p.liquidez_minima_diaria,
                             "patrimonio": p.patrimonio_minimo,
                             "cotistas": p.cotistas_minimo,
                             "mesesComRendimento": p.meses_minimos_com_rendimento}},
        "fundos": fundos,
        "excluidos": excluidos,
        "meses": _meses(mensal),
    }


def _meses(mensal) -> list[str]:
    if mensal is None or len(mensal) == 0:
        return []
    return [str(m) for m in list(mensal.index)[-MESES_SERIE:]]


def _serie(mensal, ticker) -> list:
    """Rendimento mensal por cota dos últimos 24 meses, para o gráfico."""
    if mensal is None or len(mensal) == 0 or ticker is None:
        return []
    col = f"{ticker}.SA"
    if col not in mensal.columns:
        col = str(ticker)
        if col not in mensal.columns:
            return []
    return [_num(v, 6) for v in mensal[col].tail(MESES_SERIE).tolist()]


def _sem_carimbo(d: dict) -> dict:
    meta = {k: v for k, v in (d.get("meta") or {}).items() if k != "gerado_em"}
    return {**d, "meta": meta}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true",
                    help="dados sintéticos, sem acessar a rede")
    ap.add_argument("--liquidez", type=float, default=500_000.0)
    ap.add_argument("--patrimonio", type=float, default=100_000_000.0)
    ap.add_argument("--com-b3", action="store_true",
                    help="tambem consulta a API de fundos listados da B3; ela "
                         "mudou de contrato e hoje devolve lista vazia, e o ISIN "
                         "do informe ja cobre 100%% dos fundos negociados")
    ap.add_argument("--por-familia", action="store_true",
                    help="ranqueia papel, tijolo e híbrido em listas separadas")
    ap.add_argument("--sem-cache", action="store_true")
    ap.add_argument("--informe", default=None,
                    help="caminho do informe_fii.json; com ele a CVM nao e "
                         "acessada (obrigatorio fora do Brasil, ver "
                         "baixar_informe_fii.py)")
    ap.add_argument("--saida", default=str(SAIDA))
    args = ap.parse_args()

    p = ParamsFII(liquidez_minima_diaria=args.liquidez,
                  patrimonio_minimo=args.patrimonio)

    if args.demo:
        from fiib3 import demo
        print("Modo demonstração: números sorteados, não use para investir.")
        res = demo.coletar(p, por_familia=args.por_familia)
    else:
        from fiib3 import pipeline
        res = pipeline.coletar(
            p, usar_cache=not args.sem_cache, usar_b3=args.com_b3,
            por_familia=args.por_familia, arquivo_informe=args.informe,
            progresso=lambda f, t: print(f"  [{f * 100:3.0f}%] {t}", flush=True))

    dados = montar_json(res, p)
    saida = Path(args.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)

    if saida.exists():
        try:
            antigo = json.loads(saida.read_text(encoding="utf-8"))
            if _sem_carimbo(antigo) == _sem_carimbo(dados):
                print(f"\nNada mudou; {saida} ficou como estava.")
                return 0
        except (json.JSONDecodeError, OSError):
            pass

    saida.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")

    m = dados["meta"]
    print(f"\nGravado em {saida}  ({saida.stat().st_size / 1024:,.0f} KB)")
    print(f"  competência do informe : {m.get('competencia_informe')}")
    print(f"  fundos no informe      : {m.get('fundos_no_informe')}")
    print(f"  com código de negociação: {m.get('fundos_com_ticker')}")
    print(f"  com cotação            : {m.get('fundos_com_cotacao')}")
    print(f"  elegíveis (no site)    : {len(dados['fundos'])}")
    print(f"  excluídos              : {len(dados['excluidos'])}")
    for aviso in m.get("avisos", []):
        print(f"  aviso: {aviso}")

    if len(dados["fundos"]) < 20:
        print("\n  AVISO: pouquíssimos fundos elegíveis. Rode verificar_fiis.py.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
