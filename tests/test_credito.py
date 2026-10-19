# -*- coding: utf-8 -*-
"""Testes dos spreads de crédito privado. Nenhum acessa a rede.

As amostras em `tests/amostras/` são recortes dos arquivos reais de
30/09/2026: 17 linhas do `db260930.txt` da ANBIMA escolhidas para cobrir cada
caso (DI+, % do DI, IGP-M, IPCA isenta e não isenta, papel sem taxa, cláusula
em exercício, duração curta), as NTN-B do `ms260930.txt`, a tabela da curva
de crédito do dia e um recorte da exportação do SND.

Os spreads esperados abaixo não foram calculados por este código: saíram de
uma conta feita à parte, no navegador, sobre o arquivo inteiro da ANBIMA.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from mercado import credito

AMOSTRAS = Path(__file__).parent / "amostras"


def _ler(nome, binario=False):
    p = AMOSTRAS / nome
    return p.read_bytes().decode("latin-1") if binario else p.read_text(encoding="utf-8")


@pytest.fixture
def papeis():
    return credito.ler_debentures(_ler("anbima_db260930_recorte.txt"))


@pytest.fixture
def ntnb():
    return credito.ler_titulos_publicos(_ler("anbima_ms260930_ntnb.txt"))


# Cadastro do SND para os 17 papéis da amostra, como estava em 01/10/2026.
ISENTAS = {"ACRC21": True, "AEAB11": True, "AESLA5": True, "AESLA7": True,
           "ALGE16": True, "ASAB11": False, "CSAN33": False, "CSMGB8": False,
           "AALM12": False, "ACOV15": False, "BCPSA6": False, "CASN14": False,
           "AEGE16": False, "AEGP17": False, "ABSP12": False, "KLBNA2": False,
           "CVRDA6": False}


@pytest.fixture
def calculados(papeis, ntnb):
    return credito.calcular(papeis, ntnb, ISENTAS, ipca_esperado=4.5)


def _por(ps, codigo):
    return next(p for p in ps if p.codigo == codigo)


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def test_le_todas_as_linhas_do_arquivo_de_debentures(papeis):
    assert len(papeis) == 17
    assert {p.indexador for p in papeis} == {"di", "diPercentual", "ipca", "outro"}


def test_classifica_o_indexador():
    assert credito.indexador("DI + 1,6%") == "di"
    assert credito.indexador("114,65% do DI") == "diPercentual"
    assert credito.indexador("IPCA + 7,415%") == "ipca"
    assert credito.indexador("IGP-M") == "outro"


def test_numeros_em_formato_brasileiro_e_lacunas(papeis):
    a = _por(papeis, "ACRC21")
    assert a.taxa == pytest.approx(8.5166)
    assert a.duracao_du == pytest.approx(1695.09)
    assert a.ref_ntnb == date(2035, 5, 15)
    assert a.vencimento == date(2044, 7, 15)
    sem = _por(papeis, "ABSP12")              # "--" e "N/D" no arquivo
    assert sem.taxa is None and sem.duracao_du is None


def test_asterisco_e_resgate_antecipado_nao_incentivo(papeis):
    """O erro fácil: achar que o asterisco da ANBIMA marca debênture
    incentivada. A legenda da própria ANBIMA diz que (*) é cláusula de resgate
    e (**) é cláusula já em exercício. A Claro (BCPSA6) não tem asterisco
    nenhum e não é incentivada; a ACRC21 tem um e é."""
    claro, acrc = _por(papeis, "BCPSA6"), _por(papeis, "ACRC21")
    assert not claro.resgate and not claro.exercicio
    assert acrc.resgate and not acrc.exercicio
    assert _por(papeis, "AEGE16").exercicio
    assert acrc.isenta is None                 # só o SND diz isso


def test_nome_do_emissor_sai_sem_os_asteriscos(papeis):
    assert _por(papeis, "AEGE16").emissor == "EQUIPAV SANEAMENTO S.A."


def test_cabecalho_ausente_e_erro_explicito():
    with pytest.raises(ValueError, match="Cabeçalho"):
        credito.ler_debentures("arquivo sem cabeçalho\nAALM12@x@y")


def test_titulos_publicos_so_ntnb(ntnb):
    assert len(ntnb) == 14
    assert ntnb[date(2035, 5, 15)] == pytest.approx(7.57)
    assert ntnb[date(2060, 8, 15)] == pytest.approx(7.1152)
    assert all(v > 3 for v in ntnb.values())   # nenhuma LTN de 13% entrou


def test_data_do_arquivo_de_titulos():
    assert credito.data_do_arquivo_titulos(_ler("anbima_ms260930_ntnb.txt")) == date(2026, 9, 30)


def test_cadastro_do_snd_pela_coluna_da_lei():
    m = credito.ler_snd(_ler("snd_caracteristicas_recorte.txt", binario=True))
    assert m == {"ACRC21": True, "AESLA5": True, "ZXEI31": True,
                 "BCPSA6": False, "CSAN33": False, "ZZDT12": False}


def test_snd_sem_a_coluna_da_lei_falha_alto():
    texto = _ler("snd_caracteristicas_recorte.txt", binario=True).replace(
        "Deb. Incent. (Lei 12.431)", "Outra coisa")
    with pytest.raises(ValueError, match="12.431"):
        credito.ler_snd(texto)


def test_curva_de_credito_por_rating():
    c = credito.ler_curvas_credito(_ler("anbima_curvas_credito_260930.html"))
    assert c["data"] == date(2026, 9, 30)
    assert len(c["vertices"]) == 21
    assert c["vertices"][0] == 0.5 and c["vertices"][-1] == 10.5
    assert credito.ponto_de_curva(c, 3.0) == {"AAA": 0.5864, "AA": 0.9193, "A": 1.9136}
    # A ordem que a curva tem que respeitar em todo vértice
    for a, aa, a1 in zip(c["AAA"], c["AA"], c["A"]):
        assert a < aa < a1


def test_dia_sem_curva_devolve_none():
    """A página responde 200 sem a tabela quando a data não tem curva."""
    html = ("<html><body>Curvas de Crédito | XLS | CSV A divulgação das curvas "
            "por nível de risco está sujeita à existência de séries…</body></html>")
    assert credito.ler_curvas_credito(html) is None


def test_curva_com_colunas_trocadas_falha_alto():
    html = _ler("anbima_curvas_credito_260930.html").replace(
        "<th>AA</th>", "<th>XX</th>")
    with pytest.raises(ValueError, match="Colunas"):
        credito.ler_curvas_credito(html)


# ---------------------------------------------------------------------------
# Cálculo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("codigo, esperado", [
    ("ACRC21", 0.9466),    # 8,5166 − NTN-B 2035 (7,5700)
    ("AEAB11", 0.7907),    # 8,3339 − NTN-B 2037 (7,5432)
    ("AESLA5", 0.0319),
    ("ALGE16", -0.0903),   # isenta abaixo da NTN-B: existe, e é o normal hoje
    ("ASAB11", 3.5264),
    ("CSAN33", 2.4970),
    ("CSMGB8", 0.5321),
])
def test_spread_ipca_contra_a_ntnb_de_referencia(calculados, codigo, esperado):
    assert _por(calculados, codigo).spread == pytest.approx(esperado, abs=1e-4)


def test_spread_di_e_a_propria_taxa(calculados):
    assert _por(calculados, "AALM12").spread == pytest.approx(0.7461)
    assert _por(calculados, "BCPSA6").spread == pytest.approx(0.3599)


def test_motivos_de_exclusao(calculados):
    motivo = {p.codigo: p.fora for p in calculados}
    assert motivo["ABSP12"] == "semTaxa"
    assert motivo["AEGE16"] == "resgateEmExercicio"
    assert motivo["AEGP17"] == "resgateEmExercicio"    # também é curta; vale o 1º
    assert motivo["KLBNA2"] == "indexador"
    assert motivo["CVRDA6"] == "indexador"
    assert motivo["ACRC21"] is None


def test_duracao_curta_fica_de_fora(papeis, ntnb):
    p = _por(papeis, "BCPSA6")
    p.duracao_du = 100                                     # 0,4 ano
    credito.calcular([p], ntnb, ISENTAS)
    assert p.fora == "curta"


def test_papel_fora_do_cadastro_nao_e_chutado(papeis, ntnb):
    """Sem o SND, a isenção é desconhecida — e desconhecida não vira 'não
    isenta' por omissão, que contaminaria o grupo das não isentas com as
    incentivadas novas que o cadastro guardado ainda não tem."""
    ps = credito.calcular(papeis, ntnb, {})
    assert {p.fora for p in ps if p.indexador in ("di", "ipca") and p.taxa
            and not p.exercicio} == {"semCadastro"}


def test_ntnb_de_referencia_ausente(papeis):
    ps = credito.calcular(papeis, {}, ISENTAS)
    assert _por(ps, "ACRC21").fora == "semNtnb"
    assert _por(ps, "AALM12").fora is None                 # DI+ não precisa


def test_equivalente_bruto_conta_a_mao():
    """ALGE16: 7,5237 real isento, NTN-B 7,614, IPCA esperado 4,5%.
    Nominal líquido 12,362%; bruto 12,362/0,85 = 14,544%; real bruto 9,612%;
    menos a NTN-B: +1,998 p.p."""
    v = credito.equivalente_bruto(7.5237, 7.614, 4.5)
    assert v == pytest.approx(1.998, abs=1e-3)
    # sem IR, o equivalente é o próprio spread
    assert credito.equivalente_bruto(7.5237, 7.614, 4.5, aliquota=0) == pytest.approx(-0.0903, abs=1e-4)


def test_bruto_so_nas_isentas(calculados):
    assert _por(calculados, "ALGE16").spread_bruto == pytest.approx(1.998, abs=1e-3)
    assert _por(calculados, "CSAN33").spread_bruto is None


def test_sem_inflacao_esperada_nao_ha_bruto(papeis, ntnb):
    ps = credito.calcular(papeis, ntnb, ISENTAS, ipca_esperado=None)
    assert all(p.spread_bruto is None for p in ps)
    r = credito.resumir(ps, None)
    assert r["grupos"]["ipcaIsenta"]["bruto"]["n"] == 0
    assert r["aliquotaIR"] is None


def test_resumo_por_grupo(calculados):
    r = credito.resumir(calculados, 4.5)
    g = r["grupos"]
    assert g["diSpread"]["n"] == 4            # AALM12, ACOV15, BCPSA6, CASN14
    assert g["ipcaIsenta"]["n"] == 5
    assert g["ipcaNaoIsenta"]["n"] == 3
    # mediana de quatro = média dos dois do meio: (0,7461 + 1,5668) / 2
    assert g["diSpread"]["mediana"] == pytest.approx(1.15645, abs=1e-4)
    assert g["ipcaIsenta"]["mediana"] == pytest.approx(0.0999, abs=1e-4)
    assert r["excluidos"] == {"semTaxa": 1, "resgateEmExercicio": 2, "indexador": 2}
    assert r["total"] == 17


def test_faixas_de_duracao(calculados):
    f = {x["faixa"]: x for x in credito.resumir(calculados)["grupos"]["ipcaIsenta"]["faixas"]}
    assert f["até 3 anos"]["n"] == 0
    assert f["3 a 6 anos"]["n"] == 3          # AESLA5, AESLA7, ALGE16
    assert f["acima de 6 anos"]["n"] == 2     # ACRC21, AEAB11
    assert f["3 a 6 anos"]["mediana"] == pytest.approx(0.0319, abs=1e-4)


def test_mediana_nao_e_arrastada_por_papel_estressado(papeis, ntnb):
    ps = credito.calcular(papeis, ntnb, ISENTAS)
    base = credito.resumir(ps)["grupos"]["diSpread"]["mediana"]
    _por(ps, "CASN14").spread = 40.0          # emissor em recuperação
    assert credito.resumir(ps)["grupos"]["diSpread"]["mediana"] == pytest.approx(base)


def test_quantil_igual_ao_numpy():
    np = pytest.importorskip("numpy")
    v = [0.3, -0.1, 2.5, 0.9, 1.1, 0.0, 4.2]
    for q in (0.25, 0.5, 0.75):
        assert credito.quantil(v, q) == pytest.approx(float(np.quantile(v, q)))


def test_tabela_de_papeis(calculados):
    t = credito.papeis_para_tabela(calculados)
    assert len(t["linhas"]) == 12             # 17 menos os 5 de fora
    i = t["colunas"].index("spread")
    spreads = [l[i] for l in t["linhas"]]
    assert spreads == sorted(spreads, reverse=True)
    assert t["linhas"][0][0] == "ASAB11"


# ---------------------------------------------------------------------------
# Histórico acumulado
# ---------------------------------------------------------------------------
def test_linha_do_historico(calculados):
    curva = credito.ler_curvas_credito(_ler("anbima_curvas_credito_260930.html"))
    r = credito.resumir(calculados, 4.5)
    linha = credito.linha_historico(r, curva)
    assert linha["AA_3"] == 0.9193 and linha["A_5"] == 2.0432 and linha["AAA_1"] == 0.399
    # A amostra tem menos papéis por grupo que o mínimo: vira lacuna
    assert linha["diSpread"] is None and linha["ipcaIsenta"] is None


def test_grupo_com_papeis_suficientes_entra_no_historico():
    r = {"grupos": {"diSpread": {"n": 497, "mediana": 0.899},
                    "ipcaIsenta": {"n": 580, "mediana": 0.427,
                                   "bruto": {"n": 580, "mediana": 2.6}},
                    "ipcaNaoIsenta": {"n": 9, "mediana": 1.7}}}
    linha = credito.linha_historico(r)
    assert linha["diSpread"] == 0.899 and linha["ipcaIsentaBruta"] == 2.6
    assert linha["ipcaNaoIsenta"] is None     # 9 papéis: abaixo do mínimo
    assert linha["AAA_3"] is None


def test_fundir_historico_none_nao_apaga_e_novo_substitui():
    h = credito.fundir_historico(None, {date(2026, 9, 29): {"diSpread": 0.90, "AA_3": 0.98}})
    # Execução seguinte: a curva de 29/09 não veio de novo, e a mediana foi
    # retificada; 30/09 chega só com as medianas.
    h = credito.fundir_historico(h, {date(2026, 9, 29): {"diSpread": 0.91, "AA_3": None},
                                     date(2026, 9, 30): {"diSpread": 0.899}})
    assert h["datas"] == ["2026-09-29", "2026-09-30"]
    assert h["diSpread"] == [0.91, 0.899]
    assert h["AA_3"] == [0.98, None]
    # E a curva de 30/09, que só sai depois do robô, entra no dia seguinte
    h = credito.fundir_historico(h, {date(2026, 9, 30): {"AA_3": 0.9193}})
    assert h["AA_3"] == [0.98, 0.9193] and h["diSpread"] == [0.91, 0.899]
    assert all(len(h[k]) == 2 for k in credito.chaves_historico())


def test_fundir_preserva_dias_que_sairam_da_janela():
    antigo = credito.fundir_historico(None, {date(2026, 1, 5): {"diSpread": 1.2}})
    novo = credito.fundir_historico(antigo, {date(2026, 9, 30): {"diSpread": 0.9}})
    assert novo["datas"] == ["2026-01-05", "2026-09-30"]


def test_dias_uteis_recentes_sem_fim_de_semana():
    d = credito.dias_uteis_recentes(date(2026, 10, 1))
    assert d[-1] == date(2026, 10, 1) and d[0] == date(2026, 9, 21)
    assert all(x.weekday() < 5 for x in d)
    assert date(2026, 9, 26) not in d          # sábado


# ---------------------------------------------------------------------------
# A coleta inteira, com uma sessão falsa
# ---------------------------------------------------------------------------
class _Resp:
    def __init__(self, status, corpo=""):
        self.status_code = status
        self.content = corpo.encode("latin-1") if isinstance(corpo, str) else corpo

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Sessao:
    """Só 30/09/2026 está no ar. O SND pode responder ou não."""

    def __init__(self, snd_ok=True):
        self.snd_ok = snd_ok
        self.db = (AMOSTRAS / "anbima_db260930_recorte.txt").read_text(encoding="utf-8")
        self.ms = (AMOSTRAS / "anbima_ms260930_ntnb.txt").read_text(encoding="utf-8")
        self.cv = (AMOSTRAS / "anbima_curvas_credito_260930.html").read_text(encoding="utf-8")
        self.snd = (AMOSTRAS / "snd_caracteristicas_recorte.txt").read_bytes()

    def get(self, url, timeout=None, **kw):
        if "debentures.com.br" in url:
            return _Resp(200, self.snd) if self.snd_ok else _Resp(503)
        if url.endswith("db260930.txt"):
            return _Resp(200, self.db)
        if url.endswith("ms260930.txt"):
            return _Resp(200, self.ms)
        return _Resp(404, "<html>404 - File or directory not found.</html>")

    def post(self, url, data=None, timeout=None, **kw):
        if data["Dt_Ref"] == "30/09/2026":
            return _Resp(200, self.cv)
        return _Resp(200, "<html>Curvas de Crédito | XLS | CSV</html>")


@pytest.fixture
def coletar(monkeypatch, tmp_path):
    import atualizar_mercado as am
    monkeypatch.setattr(credito, "SND_MINIMO", 1)       # o recorte tem 6 linhas
    monkeypatch.setattr(am, "HISTORICO_SPREAD", tmp_path / "nao_existe.json")
    return am.coletar_credito


def test_coleta_offline_monta_o_arquivo(coletar):
    # O SND do recorte não traz todos os 17 papéis; os que faltam vêm do
    # cadastro do arquivo anterior.
    anterior = {"cadastro": {"S": ["AEAB11", "AESLA7", "ALGE16"],
                             "N": ["AALM12", "ACOV15", "CASN14", "ASAB11", "CSMGB8"]}}
    dados, avisos = coletar(_Sessao(), anterior, hoje=date(2026, 10, 1))
    assert dados["hoje"]["data"] == "2026-09-30"
    assert dados["curvas"]["data"] == "2026-09-30"
    assert dados["historico"]["datas"] == ["2026-09-30"]
    assert dados["historico"]["AA_3"] == [0.9193]
    assert dados["cadastro"]["origem"] == "SND"
    assert "ACRC21" in dados["cadastro"]["S"] and "BCPSA6" in dados["cadastro"]["N"]
    assert dados["hoje"]["grupos"]["ipcaIsenta"]["n"] == 5
    assert dados["hoje"]["ipcaEsperado"] is None    # sem spread_historico.json
    assert avisos == []
    json.dumps(dados)                                # serializável


def test_snd_fora_do_ar_usa_cadastro_guardado_e_avisa(coletar):
    anterior = {"cadastro": {"data": "2026-09-29", "S": ["ACRC21"], "N": ["BCPSA6"]}}
    dados, avisos = coletar(_Sessao(snd_ok=False), anterior, hoje=date(2026, 10, 1))
    assert any("SND" in a and "2026-09-29" in a for a in avisos)
    assert dados["cadastro"]["origem"] == "arquivo"
    # Quem não está no cadastro guardado fica fora, não vira não isenta
    assert dados["hoje"]["excluidos"].get("semCadastro", 0) > 0


def test_historico_acumula_entre_execucoes(coletar):
    anterior = {"historico": {"datas": ["2026-09-01"], "diSpread": [1.05],
                              **{k: [None] for k in credito.chaves_historico()
                                 if k != "diSpread"}}}
    dados, _ = coletar(_Sessao(), anterior, hoje=date(2026, 10, 1))
    assert dados["historico"]["datas"] == ["2026-09-01", "2026-09-30"]
    assert dados["historico"]["diSpread"][0] == 1.05


def test_snd_cortado_nao_substitui_o_cadastro(coletar, monkeypatch):
    monkeypatch.setattr(credito, "SND_MINIMO", 1000)
    anterior = {"cadastro": {"data": "2026-09-29", "S": ["ACRC21"], "N": ["BCPSA6"]}}
    dados, avisos = coletar(_Sessao(), anterior, hoje=date(2026, 10, 1))
    assert dados["cadastro"]["origem"] == "arquivo"
    assert any("só 6 debêntures" in a for a in avisos)


def test_sem_nenhum_arquivo_da_anbima_falha(coletar):
    class Vazia(_Sessao):
        def get(self, url, timeout=None, **kw):
            if "debentures.com.br" in url:
                return super().get(url)
            return _Resp(404)
    with pytest.raises(RuntimeError, match="Nenhum arquivo"):
        coletar(Vazia(), None, hoje=date(2026, 10, 1))


# ---------------------------------------------------------------------------
# Publicação e conferência
# ---------------------------------------------------------------------------
RAIZ = Path(__file__).parent.parent


@pytest.mark.parametrize("yml", [".github/workflows/atualizar-mercado.yml",
                                 "atualizar-mercado.yml"])
def test_robo_publica_o_credito_json(yml):
    """O mesmo erro do spread_historico.json, que ficou uma semana sendo
    gerado e jogado fora: arquivo fora da lista do passo de publicação é
    apagado pelo `git reset --hard`. Com o credito.json seria pior — o
    histórico dele é acumulado e não volta."""
    passo = (RAIZ / yml).read_text(encoding="utf-8").split("name: Publicar", 1)[1]
    assert "cp web/public/credito.json /tmp/gerado/" in passo
    assert "credito.json; do" in passo
    assert "git add web/public/credito.json" in passo


def _credito_valido(**troca):
    c = {"meta": {"demo": False},
         "hoje": {"data": date.today().isoformat(), "grupos": {
             "diSpread": {"n": 497, "p25": 0.61, "mediana": 0.899, "p75": 1.45},
             "ipcaIsenta": {"n": 580, "p25": 0.15, "mediana": 0.427, "p75": 0.96},
             "ipcaNaoIsenta": {"n": 17, "p25": 1.08, "mediana": 1.769, "p75": 5.23}}},
         "curvas": {"data": date.today().isoformat(), "vertices": [1.0, 3.0],
                    "AAA": [0.399, 0.5864], "AA": [0.7318, 0.9193], "A": [1.7261, 1.9136]},
         "historico": {"datas": ["2026-09-29", "2026-09-30"], "diSpread": [0.9, 0.899]}}
    c.update(troca)
    return c


def _conferir(tmp_path, dados):
    import validar_mercado as vm
    p = tmp_path / "credito.json"
    p.write_text(json.dumps(dados), encoding="utf-8")
    return vm.conferir_credito(p, [])


def test_validador_aceita_o_arquivo_normal(tmp_path):
    assert _conferir(tmp_path, _credito_valido()) == []


def test_validador_pega_taxa_no_lugar_de_spread(tmp_path):
    c = _credito_valido()
    c["hoje"]["grupos"]["ipcaIsenta"].update(mediana=8.52, p25=8.1, p75=9.0)
    assert any("IPCA isentas" in e for e in _conferir(tmp_path, c))


def test_validador_pega_ratings_trocados(tmp_path):
    c = _credito_valido()
    c["curvas"]["AA"], c["curvas"]["A"] = c["curvas"]["A"], c["curvas"]["AA"]
    assert any("fora de ordem" in e for e in _conferir(tmp_path, c))


def test_validador_pega_grupo_cortado(tmp_path):
    c = _credito_valido()
    c["hoje"]["grupos"]["diSpread"]["n"] = 12
    assert any("só 12 papéis" in e for e in _conferir(tmp_path, c))


def test_validador_recusa_o_fixture(tmp_path):
    c = _credito_valido(meta={"demo": True})
    assert any("fixture" in e for e in _conferir(tmp_path, c))


def test_validador_pega_historico_desalinhado(tmp_path):
    c = _credito_valido()
    c["historico"]["AA_3"] = [0.9]
    assert any("AA_3" in e for e in _conferir(tmp_path, c))
