# -*- coding: utf-8 -*-
"""O dados.json exportado tem que carregar as financeiras.

O site aplica a cota de bancos e seguradoras no navegador. Se a coleta ja
excluir esse grupo, o controle da tela nao tem o que selecionar e o site fica
sem bancos de novo — que foi o que aconteceu em producao depois que a Action
rodou com a cota padrao 0.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _gerar(tmp_path, vagas):
    saida = tmp_path / "dados.json"
    r = subprocess.run(
        [sys.executable, "atualizar_dados.py", "--demo", "--pool", "80",
         "--vagas-financeiras", str(vagas), "--saida", str(saida)],
        capture_output=True, text=True, cwd=str(RAIZ))
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(saida.read_text(encoding="utf-8"))


def _financeiras(d):
    return [e for e in d["empresas"] if e.get("tipo") == "financeira"]


def test_exporta_financeiras_mesmo_com_cota_zero(tmp_path):
    d = _gerar(tmp_path, 0)
    assert _financeiras(d), (
        "sem financeiras no arquivo o controle de vagas do site nao funciona")


def test_cota_zero_continua_sendo_o_padrao_sugerido(tmp_path):
    """Carregar bancos no arquivo nao pode virar bancos na carteira sem pedir."""
    d = _gerar(tmp_path, 0)
    assert d["meta"]["vagasFinanceiras"] == 0
    assert d["meta"]["financeirasNoArquivo"] > 0


def test_cota_escolhida_pelo_usuario_e_respeitada_no_meta(tmp_path):
    d = _gerar(tmp_path, 5)
    assert d["meta"]["vagasFinanceiras"] == 5
