# -*- coding: utf-8 -*-
"""Dólar, meta Selic, Focus e juro real ex-ante.

Nenhum teste aqui toca a rede. O que eles guardam são as três decisões que
mudam o número: a janela de 10 anos do SGS, a duplicata do Focus e a divisão
de Fisher no juro real.
"""
from __future__ import annotations

from datetime import date

import pytest

from mercado import bcb


# ---------------------------------------------------------------------------
# Fatiamento do SGS
# ---------------------------------------------------------------------------
def test_fatias_respeitam_o_limite_do_sgs():
    """O SGS responde 406 acima de 10 anos em série diária."""
    fatias = list(bcb._fatiar(date(2004, 12, 1), date(2026, 9, 22)))
    assert fatias[0][0] == date(2004, 12, 1)
    assert fatias[-1][1] == date(2026, 9, 22)
    for a, b in fatias:
        assert (b - a).days <= 10 * 365, f"{a}..{b} passa de 10 anos"


def test_fatias_nao_deixam_buraco_nem_sobreposicao():
    fatias = list(bcb._fatiar(date(2004, 1, 1), date(2026, 9, 22)))
    for (_, fim), (inicio, _) in zip(fatias, fatias[1:]):
        assert (inicio - fim).days == 1, "um dia sumiu ou apareceu duas vezes"


def test_periodo_curto_vira_uma_fatia_so():
    assert list(bcb._fatiar(date(2026, 1, 1), date(2026, 3, 1))) == [
        (date(2026, 1, 1), date(2026, 3, 1))]


# ---------------------------------------------------------------------------
# Alinhamento com o calendário de pregões
# ---------------------------------------------------------------------------
DIAS = [date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)]


def test_sem_tolerancia_exige_o_valor_do_proprio_dia():
    """A regra do resto do projeto: buraco é buraco, não é o valor de ontem."""
    mapa = {date(2026, 9, 14): 5.10, date(2026, 9, 16): 5.20}
    assert bcb.alinhar(mapa, DIAS) == [5.10, None, 5.20]


def test_antes_do_comeco_da_serie_e_none():
    mapa = {date(2026, 9, 16): 5.20}
    assert bcb.alinhar(mapa, DIAS) == [None, None, 5.20]


def test_tolerancia_carrega_o_ultimo_valor_ate_o_limite():
    """O Focus é apurado semanalmente e publicado com atraso."""
    mapa = {date(2026, 9, 11): 4.62}
    assert bcb.alinhar(mapa, DIAS, tolerancia=10) == [4.62, 4.62, 4.62]


def test_tolerancia_estourada_vira_none():
    """Fonte parada tem que aparecer, não ser escondida por repetição."""
    mapa = {date(2026, 8, 1): 4.62}
    assert bcb.alinhar(mapa, DIAS, tolerancia=10) == [None, None, None]


def test_mapa_vazio_nao_quebra():
    assert bcb.alinhar({}, DIAS) == [None, None, None]


# ---------------------------------------------------------------------------
# Juro real ex-ante
# ---------------------------------------------------------------------------
def test_fisher_nao_e_subtracao():
    """Com 14% de juro e 4,62% de inflação esperada, a subtração dá 9,38 e a
    conta certa dá 8,96. Quase meio ponto num número que se discute em
    décimos."""
    [v] = bcb.juro_real_ex_ante([14.0], [4.62])
    assert v == pytest.approx(8.965, abs=0.002)
    assert abs(v - (14.0 - 4.62)) > 0.4


def test_juro_real_pode_ser_negativo():
    """Foi o que aconteceu em 2020 e 2021, e o gráfico precisa mostrar."""
    [v] = bcb.juro_real_ex_ante([2.0], [6.0])
    assert v < 0


def test_falta_de_qualquer_lado_vira_none():
    assert bcb.juro_real_ex_ante([None, 10.0], [4.0, None]) == [None, None]


def test_inflacao_impossivel_nao_vira_divisao_por_zero():
    assert bcb.juro_real_ex_ante([10.0], [-100.0]) == [None]


# ---------------------------------------------------------------------------
# Ciclos da Selic
# ---------------------------------------------------------------------------
def _serie(valores):
    datas = [f"2020-01-{i + 1:02d}" for i in range(len(valores))]
    return datas, valores


def test_um_ciclo_de_alta_e_um_de_queda():
    datas, meta = _serie([2, 2, 3, 5, 8, 8, 6, 4, 2, 2])
    ciclos = bcb.ciclos_da_selic(datas, meta)
    assert [c["sentido"] for c in ciclos] == ["alta", "queda"]
    assert ciclos[0]["inicio"] == 2 and ciclos[0]["fim"] == 8
    assert ciclos[1]["inicio"] == 8 and ciclos[1]["fim"] == 2


def test_meta_parada_nao_gera_ciclo():
    datas, meta = _serie([14.0] * 8)
    assert bcb.ciclos_da_selic(datas, meta) == []


def test_ajuste_pequeno_revertido_nao_vira_ciclo():
    """0,25 p.p. para cima no meio de uma alta é ruído de reunião, não virada.
    Sem o filtro o gráfico ganharia três faixas onde há uma."""
    datas, meta = _serie([2, 4, 6, 5.75, 8, 10])
    ciclos = bcb.ciclos_da_selic(datas, meta, minimo_pp=0.5)
    assert len(ciclos) == 1
    assert ciclos[0]["sentido"] == "alta"
    assert (ciclos[0]["inicio"], ciclos[0]["fim"]) == (2, 10)


def test_as_faixas_nao_deixam_buraco_entre_si():
    """Um ciclo termina onde o próximo começa: é a mesma virada."""
    datas, meta = _serie([2, 5, 9, 9, 6, 3, 3, 7])
    ciclos = bcb.ciclos_da_selic(datas, meta)
    assert len(ciclos) >= 2
    for a, b in zip(ciclos, ciclos[1:]):
        assert a["ate"] == b["de"]
        assert a["fim"] == b["inicio"]


def test_o_ciclo_em_curso_entra():
    """A alta que ainda não virou é ciclo do mesmo jeito — é o de hoje."""
    datas, meta = _serie([2, 2, 4, 7, 10])
    ciclos = bcb.ciclos_da_selic(datas, meta)
    assert ciclos[-1]["sentido"] == "alta"
    assert ciclos[-1]["ate"] == datas[-1]


def test_serie_curta_demais_nao_quebra():
    assert bcb.ciclos_da_selic(["2020-01-01"], [14.0]) == []
    assert bcb.ciclos_da_selic([], []) == []


def test_buraco_no_meio_nao_inventa_virada():
    datas, meta = _serie([2, None, 4, None, 8])
    ciclos = bcb.ciclos_da_selic(datas, meta)
    assert len(ciclos) == 1 and ciclos[0]["sentido"] == "alta"
