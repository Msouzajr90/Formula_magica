"""Testes da parte de fundos imobiliários. Nenhum acessa a rede."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from fiib3 import cvm_fii, demo, indicadores, mercado, score, tickers_fii  # noqa: E402
from fiib3.config import ParamsFII, familia                               # noqa: E402


# ---------------------------------------------------------------------------
# Leitura tolerante dos arquivos da CVM
# ---------------------------------------------------------------------------
def test_coluna_ignora_acento_maiuscula_e_separador():
    df = pd.DataFrame(columns=["CNPJ_Fundo", "Data_Referência",
                               "Valor Patrimonial Cotas"])
    assert cvm_fii.coluna(df, "cnpj_fundo") == "CNPJ_Fundo"
    assert cvm_fii.coluna(df, "data_referencia") == "Data_Referência"
    assert cvm_fii.coluna(df, "valor_patrimonial_cotas") == "Valor Patrimonial Cotas"


def test_coluna_ausente_diz_quais_existem():
    df = pd.DataFrame(columns=["A", "B"])
    assert cvm_fii.coluna(df, "inexistente", obrigatoria=False) is None
    with pytest.raises(KeyError, match="'A', 'B'"):
        cvm_fii.coluna(df, "inexistente")


def test_numero_aceita_ponto_e_virgula_decimal():
    s = pd.Series(["1234.56", "7,89", "1.234,50", "", None])
    v = cvm_fii._numero(s)
    assert v[0] == pytest.approx(1234.56)
    assert v[1] == pytest.approx(7.89)
    assert v[2] == pytest.approx(1234.50)
    assert pd.isna(v[3]) and pd.isna(v[4])


def test_ticker_do_isin():
    assert cvm_fii.ticker_do_isin("BRMXRFCTF004") == "MXRF"
    assert cvm_fii.ticker_do_isin("brknri ctf001".replace(" ", "")) == "KNRI"
    assert cvm_fii.ticker_do_isin("US0378331005") is None
    assert cvm_fii.ticker_do_isin(None) is None


def test_mantem_apenas_a_versao_mais_recente():
    """Refazimento de informe não pode virar dois fundos no ranking."""
    bruto = pd.DataFrame({
        "CNPJ": ["1", "1", "2"],
        "DT": ["2026-07-31", "2026-07-31", "2026-07-31"],
        "V": ["1", "2", "1"],
        "PL": ["100", "180", "50"],
    })
    r = cvm_fii._ultimo_por_fundo(bruto, "CNPJ", "DT", "V")
    assert len(r) == 2
    assert r[r["CNPJ"] == "1"]["PL"].iloc[0] == "180"


def test_competencia_mais_recente_vence_a_anterior():
    bruto = pd.DataFrame({
        "CNPJ": ["1", "1"],
        "DT": ["2026-06-30", "2026-07-31"],
        "V": ["3", "1"],
        "PL": ["velho", "novo"],
    })
    r = cvm_fii._ultimo_por_fundo(bruto, "CNPJ", "DT", "V")
    assert r["PL"].iloc[0] == "novo"


def test_familia_classifica_papel_e_tijolo():
    assert familia("Títulos e Valores Mobiliários", None) == "Papel"
    assert familia("Renda", "Lajes Corporativas") == "Tijolo"
    assert familia("Híbrido", "Híbrido") == "Híbrido"
    assert familia(None, None) == "Outros"


# ---------------------------------------------------------------------------
# Proventos
# ---------------------------------------------------------------------------
def _proventos(valores, ticker="AAAA11.SA"):
    fim = pd.Timestamp.today().normalize().replace(day=15)
    datas = [fim - pd.DateOffset(months=i) for i in range(len(valores))][::-1]
    return pd.DataFrame({"TICKER": ticker, "DATA": datas, "VALOR": valores})


def test_mediana_ignora_o_rendimento_extraordinario():
    """O caso que mais engana em tela de FII: um mês fora da curva.

    Onze meses de R$ 0,10 e um de R$ 1,20 dão o mesmo DY anual que doze meses de
    R$ 0,19 — e não são a mesma coisa para quem conta com a renda.
    """
    normal = _proventos([0.10] * 12)
    com_evento = _proventos([0.10] * 11 + [1.20])

    r1 = mercado.resumo_proventos(normal)
    r2 = mercado.resumo_proventos(com_evento)

    assert r1["PROV_12M"].iloc[0] == pytest.approx(1.20)
    assert r2["PROV_12M"].iloc[0] == pytest.approx(2.30)
    # a mediana anualizada mal se mexe...
    assert r1["PROV_MEDIANA_12M"].iloc[0] == pytest.approx(1.20)
    assert r2["PROV_MEDIANA_12M"].iloc[0] == pytest.approx(1.20)
    # ...e a razão denuncia o evento
    assert r1["RAZAO_EXTRA"].iloc[0] == pytest.approx(1.0)
    assert r2["RAZAO_EXTRA"].iloc[0] > 1.9


def test_meses_sem_pagamento_aparecem_na_contagem():
    r = mercado.resumo_proventos(_proventos([0.1, 0.1, 0.1, 0.1, 0.1, 0.1]))
    assert r["MESES_PAGOS_12M"].iloc[0] == 6


def test_dois_pagamentos_no_mesmo_mes_somam():
    hoje = pd.Timestamp.today().normalize().replace(day=10)
    prov = pd.DataFrame({
        "TICKER": ["AAAA11.SA"] * 2,
        "DATA": [hoje, hoje + pd.Timedelta(days=5)],
        "VALOR": [0.10, 0.90],
    })
    tab = mercado.mensalizar(prov)
    assert tab.iloc[-1, 0] == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------
def test_percentil_trata_empate_e_ausente():
    s = pd.Series([1.0, 2.0, 2.0, 4.0, np.nan])
    p = score.percentil(s, maior_melhor=True)
    assert p.iloc[0] == pytest.approx(0.25)
    assert p.iloc[1] == p.iloc[2] == pytest.approx(0.625)   # média de 2 e 3, /4
    assert p.iloc[3] == pytest.approx(1.0)
    assert p.iloc[4] == pytest.approx(0.5)                  # ausente vai ao meio


def test_percentil_inverte_quando_menor_e_melhor():
    s = pd.Series([1.0, 2.0, 3.0, 4.0])
    assert score.percentil(s, False).iloc[0] == pytest.approx(0.75)


def test_dy_do_score_usa_o_menor_entre_12m_e_mediano():
    df = pd.DataFrame({"DY_12M": [0.15, 0.08], "DY_MEDIANO": [0.09, 0.10]})
    v = score._dy_para_score(df, ParamsFII(usar_dy_mediano=True))
    assert list(v) == [0.09, 0.08]
    v2 = score._dy_para_score(df, ParamsFII(usar_dy_mediano=False))
    assert list(v2) == [0.15, 0.08]


def test_score_premia_dy_alto_e_pvp_baixo():
    df = pd.DataFrame({
        "TICKER": ["BOM11", "RUIM11"],
        "FAMILIA": ["Papel", "Papel"],
        "DY_12M": [0.12, 0.06], "DY_MEDIANO": [0.12, 0.06],
        "P_VP": [0.85, 1.20], "CONSISTENCIA": [1.0, 0.4],
        "LIQUIDEZ": [5e6, 1e6],
    })
    r = score.calcular(df, ParamsFII())
    assert r.iloc[0]["TICKER"] == "BOM11"
    assert r.iloc[0]["POSICAO"] == 1


def test_alerta_marca_rendimento_nao_recorrente():
    df = pd.DataFrame({"RAZAO_EXTRA": [2.0, 1.0], "DY_12M": [0.30, 0.09],
                       "P_VP": [1.0, 1.0]})
    a = score.alertas(df)
    assert "não recorrente" in a.iloc[0]
    assert a.iloc[1] == ""


# ---------------------------------------------------------------------------
# Paridade entre o Python e o JavaScript do site
# ---------------------------------------------------------------------------
def _tem_node() -> bool:
    return shutil.which("node") is not None


@pytest.mark.skipif(not _tem_node(), reason="node não está instalado")
@pytest.mark.parametrize("por_familia", [False, True])
def test_score_do_site_bate_com_o_do_python(por_familia):
    """A tela recalcula o score no navegador; os dois têm que concordar.

    Se divergirem, o usuário vê um ranking no site e outro na exportação em
    Excel do mesmo dia — e não tem como saber qual está certo.
    """
    rng = np.random.default_rng(3)
    n = 40
    df = pd.DataFrame({
        "TICKER": [f"F{i:03d}11" for i in range(n)],
        "FAMILIA": rng.choice(["Papel", "Tijolo", "Híbrido"], n),
        "DY_12M": np.round(rng.uniform(0.05, 0.16, n), 4),
        "DY_MEDIANO": np.round(rng.uniform(0.05, 0.16, n), 4),
        "P_VP": np.round(rng.uniform(0.7, 1.3, n), 3),
        "CONSISTENCIA": np.round(rng.uniform(0.2, 1.0, n), 3),
        "LIQUIDEZ": np.round(rng.uniform(1e5, 3e7, n), 0),
    })
    # empates de propósito: é onde as duas implementações costumam divergir
    df.loc[1, ["DY_12M", "DY_MEDIANO", "P_VP", "CONSISTENCIA", "LIQUIDEZ"]] = \
        df.loc[0, ["DY_12M", "DY_MEDIANO", "P_VP", "CONSISTENCIA", "LIQUIDEZ"]].values
    df.loc[5, "P_VP"] = df.loc[4, "P_VP"]

    p = ParamsFII()
    py = score.calcular(df, p, por_familia=por_familia)
    esperado = {r.TICKER: (r.SCORE, int(r.POSICAO)) for r in py.itertuples()}

    entrada = {
        "fundos": [{"ticker": r.TICKER, "familia": r.FAMILIA,
                    "dy12m": r.DY_12M, "dyMediano": r.DY_MEDIANO,
                    "pvp": r.P_VP, "consistencia": r.CONSISTENCIA,
                    "liquidez": r.LIQUIDEZ} for r in df.itertuples()],
        "pesos": {"dy": p.peso_dy, "pvp": p.peso_pvp,
                  "consistencia": p.peso_consistencia, "liquidez": p.peso_liquidez},
        "opcoes": {"usarMediano": True, "porFamilia": por_familia},
    }
    proc = subprocess.run(
        ["node", str(RAIZ / "tests" / "paridade_score.mjs")],
        input=json.dumps(entrada), capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    js = {f["ticker"]: (f["score"], f["posicao"]) for f in json.loads(proc.stdout)}

    assert set(js) == set(esperado)
    divergentes = {t: (esperado[t], js[t]) for t in esperado if esperado[t] != js[t]}
    assert not divergentes, f"score/posição diferentes entre Python e JS: {divergentes}"


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
def _linha(**kw):
    base = dict(TICKER="AAAA11", PRECO=100.0, VP_COTA=100.0, PL=5e8,
                COTISTAS=10_000, LIQUIDEZ=2e6, MESES_PAGOS_12M=12,
                IDADE_MESES=60, SITUACAO="EM FUNCIONAMENTO NORMAL",
                EXCLUSIVO="N", NEGOCIA_BOLSA="S")
    base.update(kw)
    return base


def test_filtro_guarda_o_motivo_de_cada_exclusao():
    df = pd.DataFrame([
        _linha(TICKER="OK11"),
        _linha(TICKER="PEQUENO11", PL=1e6),
        _linha(TICKER="SECO11", LIQUIDEZ=1_000),
        _linha(TICKER="NOVO11", IDADE_MESES=3),
        _linha(TICKER="SEMPRECO11", PRECO=np.nan),
    ])
    ok, fora = indicadores.filtrar(df, ParamsFII())
    assert list(ok["TICKER"]) == ["OK11"]
    motivos = dict(zip(fora["TICKER"], fora["MOTIVO_EXCLUSAO"]))
    assert "patrimônio" in motivos["PEQUENO11"]
    assert "liquidez" in motivos["SECO11"]
    assert "meses de funcionamento" in motivos["NOVO11"]
    assert "cotação" in motivos["SEMPRECO11"]


def test_campo_ausente_nao_exclui_sozinho():
    """NEGOCIA_BOLSA vazio não pode derrubar o fundo — só 'N' derruba."""
    df = pd.DataFrame([_linha(NEGOCIA_BOLSA=None)])
    ok, fora = indicadores.filtrar(df, ParamsFII())
    assert len(ok) == 1 and len(fora) == 0


def test_indicadores_calculam_pvp_e_dy():
    informe = pd.DataFrame([{
        "TICKER": "AAAA11", "CNPJ": "1", "VP_COTA": 100.0, "PL": 1e9,
        "MANDATO": "Renda", "SEGMENTO": "Logística",
        "DT_FUNCIONAMENTO": pd.Timestamp("2015-01-01"),
    }])
    preco = pd.Series({"AAAA11.SA": 80.0})
    liq = pd.Series({"AAAA11.SA": 3e6})
    var = pd.Series({"AAAA11.SA": -0.10})
    resumo = pd.DataFrame({
        "PROV_12M": [9.6], "PROV_MEDIANA_12M": [9.6], "MESES_PAGOS_12M": [12],
        "MESES_PAGOS_36M": [36], "CV_PROVENTOS": [0.05], "RAZAO_EXTRA": [1.0],
        "ULTIMO_PROVENTO": [0.8], "DT_ULTIMO_PROVENTO": [pd.Timestamp("2026-08-14")],
    }, index=["AAAA11.SA"])

    r = indicadores.montar(informe, pd.DataFrame(), preco, liq, var, resumo)
    assert r["P_VP"].iloc[0] == pytest.approx(0.80)
    assert r["DY_12M"].iloc[0] == pytest.approx(0.12)
    assert r["DY_SOBRE_VP"].iloc[0] == pytest.approx(0.096)
    assert r["RENDIMENTO_MENSAL"].iloc[0] == pytest.approx(0.8)
    assert r["RETORNO_12M"].iloc[0] == pytest.approx(0.02)
    assert r["FAMILIA"].iloc[0] == "Tijolo"
    assert r["CONSISTENCIA"].iloc[0] == pytest.approx(0.975)


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------
def test_json_de_demonstracao_sai_marcado_e_completo(tmp_path):
    import atualizar_fiis

    res = demo.coletar(ParamsFII())
    dados = atualizar_fiis.montar_json(res, ParamsFII())

    assert dados["meta"]["demo"] is True, "dado sorteado tem que sair etiquetado"
    assert len(dados["fundos"]) >= 15
    f = dados["fundos"][0]
    for campo in ("ticker", "preco", "pvp", "dy12m", "consistencia",
                  "liquidez", "pl", "serie", "familia"):
        assert campo in f, campo
    # JSON não aceita NaN: o arquivo tem que sobreviver a uma ida e volta
    texto = json.dumps(dados, ensure_ascii=False)
    assert "NaN" not in texto and "Infinity" not in texto
    assert json.loads(texto)["fundos"][0]["ticker"] == f["ticker"]
    assert len(f["serie"]) == len(dados["meses"])


# ---------------------------------------------------------------------------
# Arquivo de informe — a ponte para o GitHub Actions
# ---------------------------------------------------------------------------
def _informe_exemplo() -> pd.DataFrame:
    return pd.DataFrame([
        {"CNPJ": "00832480000117", "COMPETENCIA": "2026-07",
         "DT_INFORME": pd.Timestamp("2026-07-31"), "ISIN": "BRMXRFCTF004",
         "MANDATO": "Títulos e Valores Mobiliários", "SEGMENTO": "Títulos e Val. Mob.",
         "GESTAO": "Ativa", "ADMINISTRADOR": "BTG", "PUBLICO_ALVO": "Investidores em geral",
         "EXCLUSIVO": "N", "NEGOCIA_BOLSA": "S",
         "DT_FUNCIONAMENTO": pd.Timestamp("2012-03-01"),
         "COTAS": 6_000_000_000.0, "VP_COTA": 9.1234, "COTISTAS": 1_100_000.0,
         "PL": 5.4e9, "ATIVO_TOTAL": 5.6e9,
         "RENT_EFETIVA_MES": 0.87, "DY_MES_CVM": 0.95},
        {"CNPJ": "17098794000170", "COMPETENCIA": "2026-07",
         "DT_INFORME": pd.Timestamp("2026-07-31"), "ISIN": "BRKNRICTF001",
         "MANDATO": "Híbrido", "SEGMENTO": "Híbrido", "GESTAO": "Ativa",
         "ADMINISTRADOR": "Intrag", "PUBLICO_ALVO": "Investidores em geral",
         "EXCLUSIVO": "N", "NEGOCIA_BOLSA": "S",
         "DT_FUNCIONAMENTO": pd.Timestamp("2010-08-01"),
         "COTAS": 30_000_000.0, "VP_COTA": 168.55, "COTISTAS": 200_000.0,
         "PL": 5.05e9, "ATIVO_TOTAL": 5.2e9,
         "RENT_EFETIVA_MES": None, "DY_MES_CVM": None},
    ])


def test_arquivo_de_informe_sobrevive_a_ida_e_volta(tmp_path):
    from fiib3 import arquivo_informe as arqi

    informe = _informe_exemplo()
    cadastro = pd.DataFrame({"CNPJ": ["00832480000117", "17098794000170"],
                             "NOME": ["MAXI RENDA FII", "KINEA RENDA FII"],
                             "SITUACAO": ["EM FUNCIONAMENTO NORMAL"] * 2,
                             "TIPO": ["FII", "FII"]})
    caminho = tmp_path / "informe_fii.json"
    arqi.exportar(informe, cadastro, caminho)

    volta, cad = arqi.importar(caminho)
    assert len(volta) == 2
    linha = volta[volta["CNPJ"] == "00832480000117"].iloc[0]
    assert linha["VP_COTA"] == pytest.approx(9.1234)
    assert linha["PL"] == pytest.approx(5.4e9)
    assert linha["ISIN"] == "BRMXRFCTF004"
    assert linha["MANDATO"] == "Títulos e Valores Mobiliários"
    assert linha["DT_FUNCIONAMENTO"] == pd.Timestamp("2012-03-01")
    assert linha["COTISTAS"] == pytest.approx(1_100_000)
    assert cad.set_index("CNPJ").loc["00832480000117", "NOME"] == "MAXI RENDA FII"


def test_cnpj_nao_perde_o_zero_a_esquerda(tmp_path):
    """Se o zero sumir, o merge com o mapa da B3 falha em silencio."""
    from fiib3 import arquivo_informe as arqi

    informe = _informe_exemplo()
    arqi.exportar(informe, None, tmp_path / "i.json")
    volta, _ = arqi.importar(tmp_path / "i.json")
    assert "00832480000117" in set(volta["CNPJ"])
    assert volta["CNPJ"].str.len().eq(14).all()


def test_arquivo_ausente_diz_como_gerar(tmp_path):
    from fiib3 import arquivo_informe as arqi
    with pytest.raises(FileNotFoundError, match="baixar_informe_fii.py"):
        arqi.importar(tmp_path / "nao_existe.json")


def test_idade_do_arquivo_e_zero_no_dia(tmp_path):
    from fiib3 import arquivo_informe as arqi
    arqi.exportar(_informe_exemplo(), None, tmp_path / "i.json")
    assert arqi.idade_em_dias(tmp_path / "i.json") == 0
    assert arqi.competencia(tmp_path / "i.json") == "2026-07"


def test_informe_do_arquivo_chega_aos_indicadores(tmp_path):
    """Ponta a ponta sem rede: arquivo -> mapa de tickers -> P/VP.

    É o caminho que o GitHub Actions percorre. Se ele quebrar, o robô publica um
    fiis.json vazio sem levantar exceção nenhuma.
    """
    from fiib3 import arquivo_informe as arqi

    arqi.exportar(_informe_exemplo(), None, tmp_path / "i.json")
    informe, cadastro = arqi.importar(tmp_path / "i.json")

    mapa = tickers_fii.montar_mapa(informe, usar_b3=False)
    assert set(mapa["TICKER"]) == {"MXRF11", "KNRI11"}
    assert (mapa["ORIGEM_TICKER"] == "isin").all()

    preco = pd.Series({"MXRF11.SA": 9.50, "KNRI11.SA": 150.00})
    liq = pd.Series({"MXRF11.SA": 3e7, "KNRI11.SA": 8e6})
    var = pd.Series({"MXRF11.SA": 0.02, "KNRI11.SA": -0.05})
    resumo = pd.DataFrame({
        "PROV_12M": [1.14, 12.0], "PROV_MEDIANA_12M": [1.14, 12.0],
        "MESES_PAGOS_12M": [12, 12], "MESES_PAGOS_36M": [36, 36],
        "CV_PROVENTOS": [0.04, 0.06], "RAZAO_EXTRA": [1.0, 1.0],
        "ULTIMO_PROVENTO": [0.095, 1.0],
        "DT_ULTIMO_PROVENTO": [pd.Timestamp("2026-08-14")] * 2,
    }, index=["MXRF11.SA", "KNRI11.SA"])

    tabela = indicadores.montar(mapa, cadastro, preco, liq, var, resumo)
    ok, _fora = indicadores.filtrar(tabela, ParamsFII())
    assert set(ok["TICKER"]) == {"MXRF11", "KNRI11"}
    mxrf = ok[ok["TICKER"] == "MXRF11"].iloc[0]
    assert mxrf["P_VP"] == pytest.approx(9.50 / 9.1234, rel=1e-6)
    assert mxrf["DY_12M"] == pytest.approx(1.14 / 9.50, rel=1e-6)
    assert mxrf["FAMILIA"] == "Papel"


def test_pipeline_completo_com_arquivo_nao_toca_na_cvm(tmp_path, monkeypatch):
    """O caminho exato do robô, do arquivo ao fiis.json, sem rede nenhuma.

    Qualquer tentativa de acessar a CVM aqui levanta exceção de propósito: é
    assim que se garante que `--informe` realmente substitui a fonte, em vez de
    apenas complementá-la.
    """
    import atualizar_fiis
    from fiib3 import arquivo_informe as arqi
    from fiib3 import cvm_fii as cvm_mod
    from fiib3 import mercado as mercado_mod
    from fiib3 import pipeline

    def proibido(*a, **k):
        raise AssertionError("o pipeline tentou acessar a CVM com --informe")

    monkeypatch.setattr(cvm_mod, "ler_informe", proibido)
    monkeypatch.setattr(cvm_mod, "baixar_cadastro", proibido)

    datas = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=300)
    simbolos = ["MXRF11.SA", "KNRI11.SA"]
    precos = pd.DataFrame({"MXRF11.SA": np.linspace(9.0, 9.5, len(datas)),
                           "KNRI11.SA": np.linspace(140.0, 150.0, len(datas))},
                          index=datas)
    volume = pd.DataFrame({s: 3_000_000.0 for s in simbolos}, index=datas)
    monkeypatch.setattr(mercado_mod, "baixar_cotacoes",
                        lambda *a, **k: {"preco": precos, "fechamento": precos,
                                         "volume": volume})
    meses = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=12, freq="ME")
    monkeypatch.setattr(mercado_mod, "baixar_proventos", lambda tk, **k: pd.DataFrame(
        [{"TICKER": t, "DATA": d, "VALOR": 0.095 if t.startswith("MXRF") else 1.0}
         for t in tk for d in meses]))

    caminho = tmp_path / "informe_fii.json"
    arqi.exportar(_informe_exemplo(), None, caminho)

    res = pipeline.coletar(ParamsFII(), arquivo_informe=str(caminho), usar_b3=False)
    assert res["meta"]["origem_informe"] == "arquivo"
    assert res["meta"]["demo"] is False
    assert set(res["ranking"]["TICKER"]) == {"MXRF11", "KNRI11"}

    dados = atualizar_fiis.montar_json(res, ParamsFII())
    assert len(dados["fundos"]) == 2
    assert all(f["pvp"] and f["dy12m"] for f in dados["fundos"])
    assert "NaN" not in json.dumps(dados, ensure_ascii=False)


def test_workflow_do_github_usa_o_arquivo():
    """A CVM recusa os servidores do GitHub: o robô nunca pode ir buscá-la lá.

    Este teste existe porque o erro é invisível na leitura do YAML — o robô
    roda, falha 20 minutos depois num timeout de rede, e a mensagem não diz que
    a causa é geográfica.
    """
    yml = (RAIZ / ".github" / "workflows" / "atualizar-fiis.yml").read_text(encoding="utf-8")
    assert "--informe web/public/informe_fii.json" in yml, (
        "o passo de coleta precisa passar --informe; sem isso ele tenta baixar "
        "da CVM e falha por bloqueio de IP estrangeiro")
    assert "atualizar_fiis.py --informe" in yml


def test_para_yahoo_e_idempotente():
    assert tickers_fii.para_yahoo(["MXRF11"]) == ["MXRF11.SA"]
    assert tickers_fii.para_yahoo(["MXRF11.SA"]) == ["MXRF11.SA"]
    assert tickers_fii.sem_sufixo("MXRF11.SA") == "MXRF11"
