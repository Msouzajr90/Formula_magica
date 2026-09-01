# -*- coding: utf-8 -*-
"""Fórmula Mágica B3 — plataforma de montagem de carteiras.

Rode com:  streamlit run app.py
"""
from __future__ import annotations

import traceback
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from magicb3 import backtest, config as C, demo, optimizer, pipeline, prices, ranking, report

# --- paleta validada (dataviz) ---------------------------------------------
AZUL, LARANJA, AQUA, CINZA = "#2a78d6", "#eb6834", "#1baf7a", "#8a8a85"
GRID = "rgba(138,138,133,0.22)"
TINTA, TINTA2 = "#0b0b0b", "#52514e"

st.set_page_config(page_title="Fórmula Mágica B3", page_icon="📈", layout="wide")

st.markdown("""
<style>
  .block-container {padding-top: 2.2rem; max-width: 1400px;}
  [data-testid="stMetricValue"] {font-size: 1.6rem;}
  .stTabs [data-baseweb="tab"] {font-size: 0.95rem;}
</style>
""", unsafe_allow_html=True)


def _layout(fig: go.Figure, titulo: str, x: str, y: str, altura: int = 420) -> go.Figure:
    fig.update_layout(
        title=dict(text=titulo, font=dict(size=16, color=TINTA)),
        xaxis_title=x, yaxis_title=y, height=altura,
        margin=dict(l=10, r=10, t=50, b=10),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color=TINTA2, size=12),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1),
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, linecolor=GRID, zeroline=False)
    return fig


def pct(x, casas=1):
    return "—" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x*100:.{casas}f}%"


# ===========================================================================
# Barra lateral — parâmetros
# ===========================================================================
st.sidebar.title("⚙️ Parâmetros")

modo = st.sidebar.radio(
    "Fonte dos dados", ["Dados reais (CVM + B3)", "Demonstração (offline)"],
    help="A demonstração usa dados sintéticos e serve para conhecer a interface "
         "sem esperar o download da CVM.")
demo_mode = modo.startswith("Demonstração")

with st.sidebar.expander("Universo de ações", expanded=True):
    liq = st.number_input("Liquidez mínima (R$/dia)", 0, 500_000_000, 1_000_000, 250_000,
                          help="Volume financeiro médio dos últimos 3 meses.")
    excluir_setores = st.checkbox(
        "Excluir utilities (e financeiras, se sem vagas)", True,
        help="Greenblatt exclui esses setores: em instituições financeiras a dívida "
             "é matéria-prima, não financiamento, e ROIC/EV perdem sentido.")
    uma_classe = st.checkbox("Só a classe mais líquida por empresa", True,
                             help="Evita PETR3 e PETR4 competindo na mesma carteira.")
    vagas_fin = st.number_input(
        "Vagas para bancos e seguradoras", 0, 20, 0,
        help="Financeiras não têm ROIC nem EV com sentido econômico — nelas "
             "'dívida' é depósito de cliente. Se você reservar vagas, elas são "
             "ranqueadas à parte por ROE e Lucro/Preço, nunca misturadas com as "
             "demais. Com 0, ficam de fora, como manda Greenblatt.")

with st.sidebar.expander("Fórmula mágica", expanded=True):
    n_acoes = st.slider("Nº de ações no ranking", 10, 60, 30,
                        help="Greenblatt recomenda de 20 a 30.")
    base_ey = st.selectbox(
        "Cálculo do Earnings Yield",
        ["ebit_ev", "lucro_preco", "lpa_original_tcc"], index=0,
        format_func=lambda v: {
            "ebit_ev": "EBIT / EV  (fórmula do livro)",
            "lucro_preco": "EBIT / Valor de mercado",
            "lpa_original_tcc": "LPA em R$  (versão original do TCC)"}[v])
    base_roic = st.selectbox(
        "Cálculo do ROIC",
        ["capital_tangivel", "ativo_total", "patrimonio_liquido"], index=0,
        format_func=lambda v: {
            "capital_tangivel": "EBIT / capital tangível  (fórmula do livro)",
            "ativo_total": "EBIT / ativo total  (= ROA, versão do TCC)",
            "patrimonio_liquido": "EBIT / patrimônio líquido  (= ROE)"}[v])
    usar_ltm = st.checkbox("Usar 12 meses móveis (DFP + ITR)", True,
                           help="Sem isso, os indicadores ficam até 15 meses defasados.")

with st.sidebar.expander("Markowitz", expanded=False):
    peso_max = st.slider("Peso máximo por ação", 0.05, 1.0, 0.15, 0.01)
    n_cart = st.slider("Carteiras na fronteira", 5, 50, 20)
    met_cov = st.selectbox("Covariância", ["ledoit_wolf", "ewma", "hist"], 0,
                           format_func=lambda v: {"ledoit_wolf": "Ledoit-Wolf (recomendado)",
                                                  "ewma": "EWMA", "hist": "Histórica (TCC)"}[v])
    met_mu = st.selectbox("Retorno esperado", ["ewma", "media_ponderada", "hist"], 0,
                          format_func=lambda v: {"ewma": "Média exponencial",
                                                 "media_ponderada": "Média encolhida",
                                                 "hist": "Média histórica (TCC)"}[v])
    janela = st.slider("Janela de retornos (pregões)", 120, 756, 252, 21)
    selic = st.number_input("Taxa livre de risco (% a.a.)", 0.0, 30.0, 10.5, 0.25) / 100

with st.sidebar.expander("Custos e backtest", expanded=False):
    custo = st.number_input("Custo por ponta (bps)", 0.0, 200.0, 15.0, 5.0,
                            help="15 bps ≈ 0,15% entre corretagem, emolumentos e spread.")

params = C.Params(
    liquidez_minima_diaria=float(liq),
    excluir_setores=C.SETORES_EXCLUIDOS_PADRAO if excluir_setores else (),
    apenas_um_ticker_por_empresa=uma_classe, vagas_financeiras=int(vagas_fin),
    n_acoes_ranking=int(n_acoes), base_ey=base_ey, base_roic=base_roic,
    usar_ltm=usar_ltm, peso_maximo_ativo=float(peso_max),
    n_carteiras_fronteira=int(n_cart), metodo_covariancia=met_cov,
    metodo_retorno=met_mu, janela_retornos_dias=int(janela),
    taxa_livre_risco_aa=float(selic), custo_transacao_bps=float(custo),
)

st.sidebar.divider()
rodar = st.sidebar.button("▶️  Montar carteira", type="primary", use_container_width=True)
if st.sidebar.button("🗑️  Limpar cache de dados", use_container_width=True):
    import shutil
    shutil.rmtree(C.CACHE_DIR, ignore_errors=True)
    st.sidebar.success("Cache apagado. A próxima execução rebaixa tudo.")

st.sidebar.caption(
    "Ferramenta de estudo. Não é recomendação de investimento — "
    "rentabilidade passada não garante rentabilidade futura.")


# ===========================================================================
# Execução
# ===========================================================================
@st.cache_data(show_spinner=False, ttl=60 * 60 * 12)
def _executar(p_dict: dict, demo_mode: bool):
    p = C.Params(**{**p_dict, "excluir_setores": tuple(p_dict["excluir_setores"])})
    if demo_mode:
        return demo.resultado_demo(p)
    barra = st.progress(0.0, text="Iniciando...")
    res = pipeline.montar_carteira(p, progresso=lambda m, v=None: barra.progress(v or 0.0, text=m))
    barra.empty()
    return res


st.title("📈 Fórmula Mágica B3")
st.caption("Ranking de Greenblatt (ROIC + Earnings Yield) para seleção de ações "
           "e modelo de Markowitz para alocação — dados da CVM e da B3.")

if rodar:
    st.session_state.pop("res", None)
    try:
        with st.spinner("Processando..."):
            st.session_state["res"] = _executar(params.to_dict(), demo_mode)
            st.session_state["params"] = params
    except Exception as exc:                                # noqa: BLE001
        st.error(f"Falhou: {exc}")
        with st.expander("Detalhes técnicos"):
            st.code(traceback.format_exc())

res = st.session_state.get("res")
if res is None:
    st.info("Ajuste os parâmetros na barra lateral e clique em **Montar carteira**. "
            "Na primeira execução com dados reais o download da CVM leva alguns "
            "minutos; depois fica em cache.")
    st.stop()

p = st.session_state.get("params", params)
pesos = res.pesos[res.pesos > 0].sort_values(ascending=False)
sel = res.selecionadas.set_index("TICKER")

# ---- indicadores de topo ---------------------------------------------------
esperado = float(res.mu.reindex(pesos.index).fillna(0) @ pesos)
vol = float(np.sqrt(pesos @ res.cov.reindex(index=pesos.index, columns=pesos.index).fillna(0) @ pesos))
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Ações na carteira", f"{len(pesos)}")
c2.metric("Retorno esperado (a.a.)", pct(esperado))
c3.metric("Volatilidade (a.a.)", pct(vol))
c4.metric("Sharpe esperado", f"{(esperado - p.taxa_livre_risco_aa)/vol:.2f}" if vol > 0 else "—")
c5.metric("Maior posição", pct(float(pesos.max())))

aba1, aba2, aba3, aba4, aba5 = st.tabs(
    ["🧺 Carteira", "🏆 Ranking", "📉 Fronteira eficiente", "⏱️ Backtest", "🔎 Diagnóstico"])

# ===========================================================================
with aba1:
    esq, dir_ = st.columns([3, 2])
    with esq:
        rot = [f"{t.replace('.SA','')}" for t in pesos.index]
        fig = go.Figure(go.Bar(
            x=pesos.values * 100, y=rot, orientation="h",
            marker=dict(color=AZUL, line=dict(width=2, color="rgba(0,0,0,0)")),
            text=[f"{v*100:.1f}%" for v in pesos.values],
            textposition="outside", textfont=dict(color=TINTA2),
            hovertemplate="%{y}: %{x:.2f}%<extra></extra>"))
        fig.update_yaxes(autorange="reversed")
        fig.update_xaxes(range=[0, float(pesos.max()) * 118])
        st.plotly_chart(_layout(fig, "Alocação sugerida", "Peso (%)", "",
                                altura=max(360, 26 * len(pesos))),
                        use_container_width=True)
    with dir_:
        st.subheader("Ordem de compra")
        capital = st.number_input("Capital a investir (R$)", 1_000, 100_000_000,
                                  100_000, 1_000)
        ordem = pd.DataFrame({
            "Ticker": [t.replace(".SA", "") for t in pesos.index],
            "Peso": pesos.values,
            "Preço": [sel["PRECO"].get(t, np.nan) for t in pesos.index],
        })
        ordem["Valor (R$)"] = ordem["Peso"] * capital
        ordem["Ações"] = np.floor(ordem["Valor (R$)"] / ordem["Preço"]).fillna(0)
        ordem["Financeiro (R$)"] = ordem["Ações"] * ordem["Preço"]
        st.dataframe(
            ordem.style.format({"Peso": "{:.2%}", "Preço": "R$ {:,.2f}",
                                "Valor (R$)": "R$ {:,.0f}", "Ações": "{:,.0f}",
                                "Financeiro (R$)": "R$ {:,.0f}"}),
            use_container_width=True, hide_index=True, height=460)
        sobra = capital - ordem["Financeiro (R$)"].sum()
        st.caption(f"Sobra em caixa por arredondamento de lote: R$ {sobra:,.0f}")

    st.download_button(
        "⬇️  Baixar planilha completa (.xlsx)",
        data=report.exportar_excel(res, p),
        file_name=f"carteira_formula_magica_{date.today():%Y%m%d}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ===========================================================================
with aba2:
    st.subheader("Ranking combinado de Greenblatt")
    st.caption("Posição no ranking de ROIC + posição no ranking de Earnings Yield. "
               "Menor soma = melhor combinação de qualidade e preço.")
    if "TIPO" in res.ranking.columns and (res.ranking["TIPO"] == "financeira").any():
        st.info("As linhas marcadas como **financeira** são ranqueadas entre si, "
                "com **ROE** no lugar do ROIC e **Lucro/Preço** no lugar do "
                "EBIT/EV. As duas escalas não são comparáveis — por isso os "
                "grupos têm numeração própria.", icon="ℹ️")
    tab = ranking.resumo(res.ranking, n=min(120, len(res.ranking)))
    ren = {"POSICAO": "#", "TIPO": "Tipo", "TICKER": "Ticker",
           "DENOM_CIA": "Empresa", "SETOR": "Setor",
           "POS_ROIC": "Rk ROIC", "POS_EY": "Rk EY", "RANK_FINAL": "Soma",
           "PRECO": "Preço", "VALOR_MERCADO": "Valor de mercado", "EV": "EV",
           "EBIT_LTM": "EBIT 12m", "LIQUIDEZ_MEDIA": "Liquidez/dia",
           "DT_BASE": "Data-base", "FONTE": "Fonte"}
    tab = tab.rename(columns=ren)
    st.dataframe(
        tab.style.format({"ROIC": "{:.1%}", "EY": "{:.1%}", "Preço": "R$ {:,.2f}",
                          "Valor de mercado": "R$ {:,.0f}", "EV": "R$ {:,.0f}",
                          "EBIT 12m": "R$ {:,.0f}", "Liquidez/dia": "R$ {:,.0f}"}),
        use_container_width=True, hide_index=True, height=520)

    if len(res.rejeitadas):
        with st.expander(f"Ver {len(res.rejeitadas)} empresas excluídas e o motivo"):
            cols = [c for c in ["TICKER", "DENOM_CIA", "SETOR", "MOTIVO_EXCLUSAO"]
                    if c in res.rejeitadas.columns]
            st.dataframe(res.rejeitadas[cols], use_container_width=True, hide_index=True)

# ===========================================================================
with aba3:
    fr = res.fronteira
    st.subheader("Fronteira eficiente")
    st.caption("Cada ponto é uma carteira possível com as mesmas ações e pesos "
               "diferentes. A carteira 1 é a de menor variância.")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=fr.risco * 100, y=fr.retorno * 100, mode="lines+markers",
        line=dict(color=AZUL, width=2), marker=dict(size=9, color=AZUL,
                                                    line=dict(width=2, color="#ffffff")),
        name="Carteiras eficientes",
        customdata=np.stack([fr.sharpe, np.arange(1, len(fr.risco) + 1)], axis=-1),
        hovertemplate="Carteira %{customdata[1]:.0f}<br>Risco %{x:.1f}%"
                      "<br>Retorno %{y:.1f}%<br>Sharpe %{customdata[0]:.2f}<extra></extra>"))
    fig.add_trace(go.Scatter(
        x=[fr.risco[0] * 100], y=[fr.retorno[0] * 100], mode="markers+text",
        marker=dict(size=15, color=LARANJA, symbol="star",
                    line=dict(width=2, color="#ffffff")),
        text=["mínima variância"], textposition="top center",
        textfont=dict(color=TINTA2), name="Carteira 1"))
    fig.update_layout(hovermode="closest")
    st.plotly_chart(_layout(fig, "Risco × retorno esperado (ao ano)",
                            "Volatilidade (%)", "Retorno esperado (%)"),
                    use_container_width=True)

    i = st.slider("Escolher outra carteira da fronteira", 1, fr.pesos.shape[1], 1)
    w_i = optimizer.limpar_pesos(fr.pesos.iloc[:, i - 1])
    w_i = w_i[w_i > 0].sort_values(ascending=False)
    ca, cb = st.columns([2, 3])
    ca.metric("Retorno esperado", pct(fr.retorno[i - 1]))
    ca.metric("Volatilidade", pct(fr.risco[i - 1]))
    ca.metric("Sharpe", f"{fr.sharpe[i-1]:.2f}")
    cb.dataframe(w_i.rename("Peso").to_frame().style.format({"Peso": "{:.2%}"}),
                 use_container_width=True, height=320)

    with st.expander("Matriz de correlação dos ativos selecionados"):
        corr = res.retornos.corr()
        fig2 = go.Figure(go.Heatmap(
            z=corr.values, x=[c.replace(".SA", "") for c in corr.columns],
            y=[c.replace(".SA", "") for c in corr.index],
            colorscale=[[0, "#ffffff"], [1, AZUL]], zmin=0, zmax=1,
            colorbar=dict(title="ρ"),
            hovertemplate="%{y} × %{x}: %{z:.2f}<extra></extra>"))
        st.plotly_chart(_layout(fig2, "Correlação dos retornos diários", "", "",
                                altura=560), use_container_width=True)

# ===========================================================================
with aba4:
    st.subheader("Backtest")
    st.caption("Compra no primeiro dia útil do período e mantém até o fim, "
               "com custo de transação nas duas pontas.")
    ca, cb, cc = st.columns(3)
    ini = ca.date_input("Início", date(date.today().year - 1, 1, 2))
    fim = cb.date_input("Fim", date.today())
    cc.write("")
    ir = cc.button("Rodar backtest", use_container_width=True)

    st.warning(
        "Este backtest simula **a carteira de hoje** aplicada ao passado — os "
        "indicadores usados para escolher as ações são os atuais, não os que "
        "existiam no início do período. Serve para ver o comportamento dos papéis, "
        "**não** para validar a estratégia. Para isso use `backtest_historico.py`, "
        "que reconstrói o ranking em cada data.", icon="⚠️")

    if ir:
        with st.spinner("Baixando cotações..."):
            if demo_mode:
                rp, rb = demo.backtest_demo(pesos, ini, fim, p)
            else:
                hist = prices.baixar_historico(list(pesos.index), ini, fim)
                px = hist["preco"]
                rets = prices.retornos(px[[c for c in pesos.index if c in px.columns]])
                bh = prices.baixar_historico([p.benchmark], ini, fim)
                rb = prices.retornos(bh["preco"]).iloc[:, 0]
                rp = backtest.retorno_carteira(rets, pesos, custo_bps=p.custo_transacao_bps)
        m = backtest.calcular_metricas(rp, rb, p.taxa_livre_risco_aa)
        mb = backtest.calcular_metricas(rb, rb, p.taxa_livre_risco_aa)

        acp, acb = backtest.acumulado(rp) * 100, backtest.acumulado(rb) * 100
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=acp.index, y=acp.values, name="Carteira",
                                 line=dict(color=AZUL, width=2),
                                 hovertemplate="Carteira: %{y:.1f}%<extra></extra>"))
        fig.add_trace(go.Scatter(x=acb.index, y=acb.values, name="Ibovespa",
                                 line=dict(color=LARANJA, width=2),
                                 hovertemplate="Ibovespa: %{y:.1f}%<extra></extra>"))
        st.plotly_chart(_layout(fig, "Retorno acumulado", "", "Retorno (%)"),
                        use_container_width=True)

        comp = pd.DataFrame({"Carteira": m.to_dict(), "Ibovespa": mb.to_dict()})
        fmt = ["Retorno total", "Retorno anualizado", "Volatilidade anual",
               "Drawdown máximo", "Alfa anual", "Tracking error"]
        comp_fmt = comp.copy().astype(object)
        for k in fmt:
            comp_fmt.loc[k] = [pct(v) for v in comp.loc[k]]
        for k in ["Sharpe", "Beta", "Information ratio"]:
            comp_fmt.loc[k] = [f"{v:.2f}" if np.isfinite(v) else "—" for v in comp.loc[k]]
        st.dataframe(comp_fmt, use_container_width=True)

# ===========================================================================
with aba5:
    st.subheader("Diagnóstico da execução")
    st.json(res.diagnostico)
    st.subheader("Parâmetros usados")
    st.json({k: (list(v) if isinstance(v, tuple) else v) for k, v in p.to_dict().items()})
    st.subheader("Retorno esperado e risco por ativo")
    diag = pd.DataFrame({
        "Retorno esperado (a.a.)": res.mu,
        "Volatilidade (a.a.)": np.sqrt(np.diag(res.cov)),
        "Peso": res.pesos.reindex(res.mu.index).fillna(0),
    })
    st.dataframe(diag.style.format("{:.2%}"), use_container_width=True, height=420)
