# -*- coding: utf-8 -*-
"""Verificador das fontes de dados — RODE ISTO PRIMEIRO.

Testa, uma a uma, todas as conexões de que a plataforma depende, e diz
exatamente o que funcionou e o que não funcionou. Como as APIs da CVM, da B3 e
do Yahoo mudam de tempos em tempos sem aviso, este script é a forma rápida de
descobrir se algo quebrou — e o quê.

Uso:
    python verificar_dados.py            # verificação rápida (~2 a 5 min)
    python verificar_dados.py --completo # inclui um teste ponta a ponta
"""
from __future__ import annotations

import argparse
import io
import sys
import time
import traceback
import zipfile
from datetime import date, timedelta

OK, FALHA, AVISO = "  [OK]   ", "  [FALHA]", "  [AVISO]"
_res: list[tuple[str, bool, str]] = []


def _titulo(t: str) -> None:
    print(f"\n{'-' * 72}\n{t}\n{'-' * 72}")


def _checar(nome: str, fn):
    inicio = time.time()
    try:
        detalhe = fn()
        print(f"{OK} {nome}  ({time.time()-inicio:.1f}s)")
        if detalhe:
            for linha in str(detalhe).splitlines():
                print(f"         {linha}")
        _res.append((nome, True, ""))
        return True
    except Exception as exc:                                  # noqa: BLE001
        print(f"{FALHA} {nome}  ({time.time()-inicio:.1f}s)")
        print(f"         {type(exc).__name__}: {exc}")
        _res.append((nome, False, f"{type(exc).__name__}: {exc}"))
        return False


# ===========================================================================
def t_bibliotecas():
    import numpy, pandas, plotly, requests, scipy, streamlit, yfinance
    faltando = []
    if tuple(int(x) for x in pandas.__version__.split(".")[:2]) < (2, 0):
        faltando.append("pandas < 2.0 (atualize)")
    if faltando:
        raise RuntimeError("; ".join(faltando))
    return (f"pandas {pandas.__version__} | numpy {numpy.__version__} | "
            f"scipy {scipy.__version__}\nyfinance {yfinance.__version__} | "
            f"streamlit {streamlit.__version__} | plotly {plotly.__version__}")


def t_internet():
    import requests
    r = requests.get("https://www.google.com", timeout=20)
    r.raise_for_status()
    return "conexão de saída funcionando"


def t_cvm_portal():
    import requests
    from magicb3.cvm import BASE_DFP
    r = requests.get(f"{BASE_DFP}/", timeout=60)
    r.raise_for_status()
    return f"portal de dados abertos respondeu ({len(r.content):,} bytes)"


def t_cvm_zip():
    """Baixa o DFP do último ano fechado e confere o conteúdo do zip."""
    import requests
    from magicb3.cvm import BASE_DFP
    ano = date.today().year - 1
    url = f"{BASE_DFP}/dfp_cia_aberta_{ano}.zip"
    r = requests.get(url, timeout=300)
    if r.status_code == 404:
        ano -= 1
        url = f"{BASE_DFP}/dfp_cia_aberta_{ano}.zip"
        r = requests.get(url, timeout=300)
    r.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    nomes = zf.namelist()
    precisa = [f"dfp_cia_aberta_{g}_con_{ano}.csv" for g in ("DRE", "BPA", "BPP")]
    ausentes = [n for n in precisa if n not in nomes]
    if ausentes:
        raise RuntimeError(f"arquivos esperados ausentes: {ausentes}\n"
                           f"o zip contém: {nomes[:12]}")
    return (f"DFP {ano}: {len(r.content)/1e6:.1f} MB, {len(nomes)} arquivos, "
            f"DRE/BPA/BPP presentes")


def t_cvm_parse():
    """Lê de verdade e confere se as contas que usamos existem."""
    from magicb3 import cvm
    from magicb3.pipeline import CONTAS_USADAS
    import magicb3.config as C
    ano = date.today().year - 1
    d = cvm.carregar_demonstracoes([ano], tipo="dfp", contas=CONTAS_USADAS)
    dre, bpa = d["DRE"], d["BPA"]
    if dre.empty:
        raise RuntimeError("DRE veio vazia após a normalização")
    n_ebit = (dre["CD_CONTA"] == C.CD_EBIT).sum()
    if n_ebit < 100:
        raise RuntimeError(f"só {n_ebit} empresas com a conta {C.CD_EBIT} (EBIT); "
                           "o plano de contas pode ter mudado")
    escalas = dre["ESCALA_MOEDA"].astype(str).unique().tolist()
    return (f"{n_ebit} empresas com EBIT ({C.CD_EBIT}) em {ano}\n"
            f"{bpa['CD_CVM'].nunique()} empresas no balanço\n"
            f"escalas encontradas: {escalas}")


def t_cvm_itr():
    from magicb3 import cvm
    from magicb3.pipeline import CONTAS_USADAS
    ano = date.today().year
    d = cvm.carregar_demonstracoes([ano], tipo="itr", contas=CONTAS_USADAS)
    if d["DRE"].empty:
        d = cvm.carregar_demonstracoes([ano - 1], tipo="itr", contas=CONTAS_USADAS)
        ano -= 1
    if d["DRE"].empty:
        raise RuntimeError("nenhum ITR encontrado — o cálculo de 12 meses móveis "
                           "vai cair para o balanço anual")
    ult = d["DRE"]["DT_REFER"].max()
    return f"ITR {ano}: última data de referência {ult:%d/%m/%Y}"


def t_cvm_dt_receb():
    from magicb3 import cvm
    from magicb3.pipeline import CONTAS_USADAS
    ano = date.today().year - 1
    d = cvm.carregar_demonstracoes([ano], tipo="dfp", contas=CONTAS_USADAS)
    dre = d["DRE"]
    if "DT_RECEB" not in dre.columns or dre["DT_RECEB"].isna().all():
        raise RuntimeError("DT_RECEB ausente — o backtest point-in-time vai usar "
                           "a aproximação de +90 dias em vez da data real")
    atraso = (dre["DT_RECEB"] - dre["DT_REFER"]).dt.days.median()
    return f"data de entrega disponível; atraso mediano de {atraso:.0f} dias"


def t_cadastro():
    from magicb3 import cvm
    cad = cvm.carregar_cadastro()
    cols = [c.upper() for c in cad.columns]
    if not any(c.startswith("SETOR") for c in cols):
        raise RuntimeError(f"nenhuma coluna de setor encontrada. Colunas: {cols[:15]}")
    return f"{len(cad):,} companhias no cadastro"


def t_b3():
    from magicb3 import tickers
    emp = tickers.baixar_empresas_b3()
    if emp.empty:
        raise RuntimeError("a API da B3 devolveu lista vazia")
    if len(emp) < 200:
        raise RuntimeError(f"só {len(emp)} empresas — esperado 300+; "
                           "a API pode ter mudado de formato")
    if "CD_CVM" not in emp.columns:
        raise RuntimeError(f"campo codeCVM ausente. Colunas: {list(emp.columns)}")
    exemplos = emp["PREFIXO"].head(6).tolist()
    return f"{len(emp)} companhias listadas; prefixos de exemplo: {exemplos}"


def t_yahoo_cotacao():
    from magicb3 import prices
    alvo = ["PETR4.SA", "VALE3.SA", "ITUB4.SA", "WEGE3.SA", "^BVSP"]
    h = prices.baixar_historico(alvo, date.today() - timedelta(days=90),
                                date.today(), usar_cache=False)
    px = h["preco"]
    if px.empty:
        raise RuntimeError("nenhuma cotação devolvida")
    faltando = [t for t in alvo if t not in px.columns or px[t].isna().all()]
    if faltando:
        raise RuntimeError(f"sem dados para: {faltando}")
    ult = px.dropna(how="all").index.max()
    idade = (date.today() - ult.date()).days
    aviso = "  <-- ATENÇÃO: dado velho" if idade > 5 else ""
    return (f"último pregão: {ult:%d/%m/%Y} ({idade} dias atrás){aviso}\n"
            f"PETR4 fechou a R$ {px['PETR4.SA'].dropna().iloc[-1]:.2f}")


def t_yahoo_volume():
    from magicb3 import prices
    h = prices.baixar_historico(["PETR4.SA", "VALE3.SA"],
                                date.today() - timedelta(days=90), date.today(),
                                usar_cache=False)
    liq = prices.liquidez_media_diaria(h["fechamento"], h["volume"], janela=63)
    if liq.empty or liq.isna().all() or (liq <= 0).all():
        raise RuntimeError("volume financeiro não pôde ser calculado — o filtro "
                           "de liquidez não vai funcionar")
    return "liquidez média diária:\n" + "\n".join(
        f"  {t}: R$ {v/1e6:,.1f} milhões/dia" for t, v in liq.items())


def t_yahoo_acoes():
    from magicb3 import prices
    alvo = ["PETR4.SA", "VALE3.SA", "WEGE3.SA"]
    s = prices.acoes_em_circulacao(alvo, usar_cache=False)
    if s.isna().all():
        raise RuntimeError("nº de ações indisponível — o EV não pode ser calculado. "
                           "Este é o ponto mais frágil da cadeia.")
    faltando = s[s.isna()].index.tolist()
    linhas = [f"  {t}: {v/1e9:,.2f} bilhões de ações" for t, v in s.dropna().items()]
    if faltando:
        linhas.append(f"  sem dado para: {faltando}")
    return "\n".join(linhas)


def t_ponta_a_ponta():
    """Roda o pipeline completo com parâmetros enxutos."""
    from magicb3 import config as C, pipeline
    p = C.Params(n_acoes_ranking=15, liquidez_minima_diaria=5_000_000,
                 n_carteiras_fronteira=5)
    res = pipeline.montar_carteira(p, progresso=lambda m, v=None: print(f"         . {m}"))
    if res.selecionadas.empty:
        raise RuntimeError("nenhuma ação selecionada — verifique os filtros")
    pesos = res.pesos[res.pesos > 0]
    if abs(float(pesos.sum()) - 1.0) > 1e-4:
        raise RuntimeError(f"pesos não somam 1: {pesos.sum()}")
    top = res.selecionadas.head(5)
    linhas = [f"  {r.TICKER:<12} ROIC {r.ROIC:6.1%}   EY {r.EY:6.1%}"
              for r in top.itertuples()]
    return (f"universo: {res.diagnostico.get('universo_bruto')} | "
            f"aprovadas: {res.diagnostico.get('aprovados_nos_filtros')}\n"
            f"carteira: {len(pesos)} ativos\n"
            "5 primeiras do ranking:\n" + "\n".join(linhas))


# ===========================================================================
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--completo", action="store_true",
                    help="inclui o teste ponta a ponta (mais demorado)")
    args = ap.parse_args()

    print("=" * 72)
    print("  VERIFICAÇÃO DAS FONTES DE DADOS — Fórmula Mágica B3")
    print(f"  {date.today():%d/%m/%Y}")
    print("=" * 72)

    _titulo("1. Ambiente")
    if not _checar("Bibliotecas Python instaladas", t_bibliotecas):
        print("\nInstale as dependências antes de continuar:\n"
              "    pip install -r requirements.txt")
        return 1
    if not _checar("Acesso à internet", t_internet):
        return 1

    _titulo("2. CVM — demonstrações financeiras")
    _checar("Portal de dados abertos acessível", t_cvm_portal)
    _checar("Download e estrutura do zip DFP", t_cvm_zip)
    _checar("Leitura e códigos de conta (EBIT, balanço)", t_cvm_parse)
    _checar("ITR trimestral (para os 12 meses móveis)", t_cvm_itr)
    _checar("Data de entrega (DT_RECEB)", t_cvm_dt_receb)
    _checar("Cadastro de companhias e setor", t_cadastro)

    _titulo("3. B3 — mapeamento de tickers")
    _checar("API de companhias listadas", t_b3)

    _titulo("4. Yahoo Finance — mercado")
    _checar("Cotações e Ibovespa", t_yahoo_cotacao)
    _checar("Volume financeiro (filtro de liquidez)", t_yahoo_volume)
    _checar("Número de ações (para o valor de mercado)", t_yahoo_acoes)

    if args.completo:
        _titulo("5. Teste ponta a ponta")
        _checar("Pipeline completo", t_ponta_a_ponta)

    _titulo("RESUMO")
    falhas = [r for r in _res if not r[1]]
    print(f"  {len(_res) - len(falhas)} de {len(_res)} verificações passaram.")
    if falhas:
        print("\n  Falhou:")
        for nome, _, erro in falhas:
            print(f"    - {nome}\n      {erro}")
        print("\n  Copie este resultado e me mande — dá para consertar cada caso.")
    else:
        print("\n  Tudo funcionando. Rode a plataforma com:\n"
              "      streamlit run app.py")
    print()
    return 1 if falhas else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrompido.")
        sys.exit(130)
    except Exception:                                          # noqa: BLE001
        traceback.print_exc()
        sys.exit(1)
