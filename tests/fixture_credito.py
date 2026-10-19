# -*- coding: utf-8 -*-
"""Grava um `credito.json` de tela, para ver a aba de crédito sem coletar.

Diferente do `fixture_spread.py`, quase tudo aqui é número de verdade:

  * as medianas, quartis e contagens de 01/10/2026, calculadas sobre o
    arquivo inteiro da ANBIMA (1.290 debêntures) e o cadastro do SND;
  * a curva de rating de 30/09/2026, lida da amostra em `tests/amostras/`;
  * o histórico de 22/09 a 01/10/2026 — os sete pregões que a ANBIMA tinha
    no ar no dia em que a aba foi escrita.

O que é parcial é a **tabela de papéis**: só os doze da amostra que entram
na conta, não os 1.064 do dia. Por isso o arquivo sai com `"demo": true` —
a tela avisa em vermelho e o `validar_mercado.py` sai com código 1, para que
esquecê-lo no repositório não publique uma tabela de doze linhas.

Uso:
    python tests/fixture_credito.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ))

from mercado import credito  # noqa: E402

AMOSTRAS = Path(__file__).parent / "amostras"
SAIDA = RAIZ / "web" / "public" / "credito.json"

IPCA_ESPERADO = 4.6232     # Focus 12 meses de 18/09/2026, base de cálculo 0


def _faixas(lista, bruto=None):
    rot = [f[2] for f in credito.FAIXAS_DURACAO]
    saida = []
    for i, (n, p25, med, p75, dur) in enumerate(lista):
        f = {"faixa": rot[i], "n": n, "p25": p25, "mediana": med, "p75": p75,
             "duracaoMediana": dur}
        if bruto is not None:
            f["brutoMediana"] = bruto[i]
        saida.append(f)
    return saida


# 01/10/2026, arquivo inteiro.
HOJE = {
    "data": "2026-10-01",
    "grupos": {
        "diSpread": {
            "nome": credito.GRUPOS["diSpread"], "n": 469, "p25": 0.6167,
            "mediana": 0.9043, "p75": 1.4694, "duracaoMediana": 2.6408,
            "faixas": _faixas([(296, 0.5968, 1.0054, 1.7814, 2.0939),
                               (173, 0.6423, 0.7852, 1.228, 3.6525),
                               (0, None, None, None, None)])},
        "ipcaIsenta": {
            "nome": credito.GRUPOS["ipcaIsenta"], "n": 578, "p25": 0.1505,
            "mediana": 0.4599, "p75": 1.0228, "duracaoMediana": 5.212,
            "faixas": _faixas([(115, 0.0566, 0.3654, 0.9711, 1.8832),
                               (243, 0.1311, 0.4567, 1.2459, 4.5462),
                               (220, 0.2252, 0.5215, 0.7521, 7.0372)],
                              bruto=[2.4658, 2.6639, 2.7332]),
            "bruto": {"n": 578, "p25": 2.2868, "mediana": 2.635, "p75": 3.2521}},
        "ipcaNaoIsenta": {
            "nome": credito.GRUPOS["ipcaNaoIsenta"], "n": 17, "p25": 1.0715,
            "mediana": 1.802, "p75": 5.198, "duracaoMediana": 3.4086,
            "faixas": _faixas([(3, 1.1768, 1.8069, 3.5025, 2.2598),
                               (14, 1.1157, 1.7733, 4.8738, 3.4742),
                               (0, None, None, None, None)])},
    },
    "excluidos": {"semTaxa": 60, "resgateEmExercicio": 107, "curta": 31,
                  "indexador": 28},
    "total": 1290,
    "ipcaEsperado": IPCA_ESPERADO,
    "aliquotaIR": credito.ALIQUOTA_IR,
}

# [DI+, IPCA isenta, IPCA não isenta, isenta bruta, {vértice: [AAA, AA, A]}]
HISTORICO = {
    date(2026, 9, 22): [0.9053, 0.2277, 1.7205, 2.3743,
                        {1: [0.3915, 0.6834, 1.7867], 3: [0.5869, 0.8788, 1.982],
                         5: [0.7219, 1.0139, 2.1171]}],
    date(2026, 9, 23): [0.9034, 0.2658, 1.7915, 2.4214,
                        {1: [0.3784, 0.7463, 1.9319], 3: [0.5755, 0.9434, 2.129],
                         5: [0.7061, 1.074, 2.2596]}],
    date(2026, 9, 24): [0.8822, 0.3142, 1.7734, 2.4816,
                        {1: [0.3944, 0.7398, 1.8813], 3: [0.5786, 0.9239, 2.0655],
                         5: [0.7059, 1.0513, 2.1928]}],
    date(2026, 9, 25): [0.8844, 0.3662, 1.8436, 2.5435,
                        {1: [0.3939, 0.7352, 1.8627], 3: [0.5791, 0.9204, 2.048],
                         5: [0.7072, 1.0485, 2.176]}],
    date(2026, 9, 29): [0.8996, 0.4026, 1.7731, 2.5661,
                        {1: [0.4045, 0.804, 1.8472], 3: [0.5864, 0.9859, 2.029],
                         5: [0.7122, 1.1117, 2.1548]}],
    date(2026, 9, 30): [0.8992, 0.4309, 1.7695, 2.5982,
                        {1: [0.399, 0.7318, 1.7261], 3: [0.5864, 0.9193, 1.9136],
                         5: [0.716, 1.0489, 2.0432]}],
    date(2026, 10, 1): [0.9043, 0.4599, 1.802, 2.635, None],
}


def montar() -> dict:
    novos = {}
    for d, (di, isen, nao, bruta, curva) in HISTORICO.items():
        linha = {"diSpread": di, "ipcaIsenta": isen, "ipcaNaoIsenta": nao,
                 "ipcaIsentaBruta": bruta}
        for v, (a, aa, a1) in (curva or {}).items():
            linha.update({f"AAA_{v}": a, f"AA_{v}": aa, f"A_{v}": a1})
        novos[d] = linha

    curva = credito.ler_curvas_credito(
        (AMOSTRAS / "anbima_curvas_credito_260930.html").read_text(encoding="utf-8"))
    ps = credito.calcular(
        credito.ler_debentures((AMOSTRAS / "anbima_db260930_recorte.txt").read_text(encoding="utf-8")),
        credito.ler_titulos_publicos((AMOSTRAS / "anbima_ms260930_ntnb.txt").read_text(encoding="utf-8")),
        {"ACRC21": True, "AEAB11": True, "AESLA5": True, "AESLA7": True, "ALGE16": True,
         "ASAB11": False, "CSAN33": False, "CSMGB8": False, "AALM12": False,
         "ACOV15": False, "BCPSA6": False, "CASN14": False},
        IPCA_ESPERADO)

    return {
        "meta": {"versao": 1, "geradoEm": "fixture", "demo": True,
                 "avisos": ["Fixture de tela: a tabela de papéis tem só a amostra."]},
        "hoje": HOJE,
        "curvas": {"data": curva["data"].isoformat(), "vertices": curva["vertices"],
                   **{r: curva[r] for r in credito.RATINGS}},
        "papeis": credito.papeis_para_tabela(ps),
        "historico": credito.fundir_historico(None, novos),
        "cadastro": {"data": None, "origem": "fixture", "S": [], "N": []},
    }


if __name__ == "__main__":
    SAIDA.write_text(json.dumps(montar(), ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")
    print(f"{SAIDA} gravado — FIXTURE de tela, com \"demo\": true. Apague antes de publicar.")
