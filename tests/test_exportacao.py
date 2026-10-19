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


def test_exporta_concessionarias_mesmo_com_cota_zero(tmp_path):
    d = _gerar(tmp_path, 0)
    uti = [e for e in d["empresas"] if e.get("tipo") == "utilidade"]
    assert uti, "sem concessionarias no arquivo o controle do site nao funciona"
    assert d["meta"]["vagasUtilidades"] == 0
    assert d["meta"]["utilidadesNoArquivo"] > 0


def test_rodada_repetida_nao_reescreve_o_arquivo(tmp_path):
    """Sem isso o agendamento diario geraria um commit por dia sem dado novo."""
    saida = tmp_path / "dados.json"
    r1 = subprocess.run(
        [sys.executable, "atualizar_dados.py", "--demo", "--pool", "40",
         "--saida", str(saida)], capture_output=True, text=True, cwd=str(RAIZ))
    assert r1.returncode == 0, r1.stdout + r1.stderr
    antes = saida.read_text(encoding="utf-8")

    r2 = subprocess.run(
        [sys.executable, "atualizar_dados.py", "--demo", "--pool", "40",
         "--saida", str(saida)], capture_output=True, text=True, cwd=str(RAIZ))
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "Nada mudou" in r2.stdout
    assert saida.read_text(encoding="utf-8") == antes, "o arquivo foi tocado a toa"


def test_dado_novo_reescreve_normalmente(tmp_path):
    """A protecao acima nao pode impedir a atualizacao de verdade."""
    saida = tmp_path / "dados.json"
    _gerar(tmp_path, 0)
    d = json.loads((tmp_path / "dados.json").read_text(encoding="utf-8"))
    d["empresas"][0]["preco"] = (d["empresas"][0]["preco"] or 10) + 7.77
    saida.write_text(json.dumps(d), encoding="utf-8")

    r = subprocess.run(
        [sys.executable, "atualizar_dados.py", "--demo", "--pool", "80",
         "--saida", str(saida)], capture_output=True, text=True, cwd=str(RAIZ))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Nada mudou" not in r.stdout


def test_arquivo_leva_os_tres_grupos_e_nao_so_os_80_primeiros(tmp_path):
    """head(pool) decapitava financeiras e concessionarias: o ranking vem
    ordenado por grupo e as operacionais sozinhas passam do tamanho do pool."""
    d = _gerar(tmp_path, 0)
    tipos = {e["tipo"] for e in d["empresas"]}
    assert "financeira" in tipos, "as financeiras foram cortadas do arquivo"
    assert "utilidade" in tipos, "as concessionarias foram cortadas do arquivo"


def test_arquivo_leva_o_ranking_inteiro_e_nao_so_o_pool(tmp_path):
    """Quem passa nos filtros mas fica abaixo do corte tem que aparecer no site.

    Antes só as selecionadas eram exportadas, e uma empresa aprovada fora do
    corte (a VALE3) não estava nem no ranking nem nas excluídas — parecia ter
    sumido. O pool continua limitando quem tem série de preços.
    """
    saida = tmp_path / "dados.json"
    r = subprocess.run(
        [sys.executable, "atualizar_dados.py", "--demo", "--pool", "20",
         "--saida", str(saida)], capture_output=True, text=True, cwd=str(RAIZ))
    assert r.returncode == 0, r.stdout + r.stderr
    d = json.loads(saida.read_text(encoding="utf-8"))

    sel = [e for e in d["empresas"] if e["selecionada"]]
    fora = [e for e in d["empresas"] if not e["selecionada"]]
    assert fora, "as aprovadas abaixo do corte nao foram exportadas"
    assert len(sel) <= 20
    # estatística só de quem foi selecionado; o resto é só ranking
    assert set(d["estatisticas"]["tickers"]) <= {e["ticker"] for e in sel}
    # a exportação completa não pode repetir empresa nem perder o ranking
    assert len({e["ticker"] for e in d["empresas"]}) == len(d["empresas"])
    assert all(isinstance(e["rank"], int) for e in d["empresas"])
