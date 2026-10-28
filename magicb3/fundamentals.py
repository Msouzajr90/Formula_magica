"""Cálculo dos indicadores da fórmula mágica.

ROIC  = EBIT / Capital Tangível Empregado
        Capital Tangível = Capital de Giro Líquido + Ativo Imobilizado Líquido
                           (+ Investimentos; + Intangível nas concessionárias)
        Capital de Giro Líquido = (Ativo Circulante - Caixa - Aplicações Financeiras)
                                - (Passivo Circulante - Empréstimos de curto prazo)

EY    = EBIT / EV
        EV = Valor de Mercado + Dívida Bruta - Caixa e Aplicações Financeiras

Este é o cálculo do livro (Greenblatt, 2010, Apêndice). O TCC usou
ROA (EBIT/Ativo Total) e LPA em reais — ambos corrigidos aqui, mas as
variantes originais continuam disponíveis para comparação.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import config as C

log = logging.getLogger(__name__)


def capital_tangivel(bp: pd.DataFrame, incluir_investimentos: bool = True,
                     concessao=None) -> pd.Series:
    """Capital de giro líquido + imobilizado (+ investimentos), giro com piso em zero.

    `incluir_investimentos` soma a conta 1.02.02. Sem ela, empresas cujo ativo
    operacional não está no imobilizado ficam com denominador quase nulo e ROIC
    absurdo. Medido nos dados de 30/06/2026: a Allos tem R$ 0,11 bi de
    imobilizado e R$ 20,0 bi em Investimentos (os shoppings), o que produzia
    ROIC de 1.358%; incluindo a conta, cai para 7,5%. Na SYN, 7.622% -> 8,4%.

    `concessao` (máscara booleana, ver `eh_concessao`) soma o intangível 1.02.04
    nas linhas marcadas. É o mesmo problema dos shoppings com outra conta: na
    concessionária o ativo operacional — a rodovia — está no intangível.
    """
    ac = bp.get(C.CD_ATIVO_CIRCULANTE, 0.0)
    caixa = bp.get(C.CD_CAIXA, 0.0)
    aplic = bp.get(C.CD_APLIC_FINANCEIRAS, 0.0)
    pc = bp.get(C.CD_PASSIVO_CIRCULANTE, 0.0)
    div_cp = bp.get(C.CD_EMPRESTIMOS_CP, 0.0)
    imob = bp.get(C.CD_IMOBILIZADO, 0.0)
    invest = bp.get(C.CD_INVESTIMENTOS, 0.0) if incluir_investimentos else 0.0

    giro = (ac - caixa - aplic) - (pc - div_cp)
    giro = giro.clip(lower=0) if isinstance(giro, pd.Series) else max(giro, 0.0)
    total = giro + imob + invest
    if concessao is not None:
        intang = pd.to_numeric(bp.get(C.CD_INTANGIVEL, 0.0), errors="coerce")
        if isinstance(intang, pd.Series):
            intang = intang.fillna(0.0)
        mask = pd.Series(concessao, index=bp.index).fillna(False).astype(bool)
        total = total + np.where(mask, intang, 0.0)
    return total


def _texto_setorial(df: pd.DataFrame, campos=("SETOR", "SEGMENTO")) -> pd.Series:
    campos = [c for c in campos if c in df.columns]
    if not campos:
        return pd.Series("", index=df.index)
    texto = df[campos[0]].fillna("").astype(str)
    for c in campos[1:]:
        texto = texto + " | " + df[c].fillna("").astype(str)
    return texto


def eh_concessao(df: pd.DataFrame, padroes: tuple[str, ...] = C.SETORES_CONCESSAO
                 ) -> pd.Series:
    """Concessionária cujo ativo operacional está no intangível (ICPC 01).

    Duas condições, as duas necessárias: setor de concessão (transporte ou
    utilidade pública, pelo SETOR da CVM) e intangível maior que imobilizado +
    investimentos. A segunda separa a rodovia (intangível = a própria estrada)
    da locadora do mesmo setor (intangível = ágio, que continua fora).
    """
    if df.empty:
        return pd.Series(dtype=bool)
    texto = _texto_setorial(df, ("SETOR",))
    padrao = "|".join(f"(?:{x})" for x in padroes)
    do_setor = texto.str.contains(padrao, case=False, na=False, regex=True)

    def _conta(cd):
        v = df.get(cd)
        if v is None:
            return pd.Series(0.0, index=df.index)
        return pd.to_numeric(v, errors="coerce").fillna(0.0)

    intang = _conta(C.CD_INTANGIVEL)
    fixo = _conta(C.CD_IMOBILIZADO) + _conta(C.CD_INVESTIMENTOS)
    return do_setor & (intang > 0) & (intang > fixo)


def eh_financeira(df: pd.DataFrame, padroes: tuple[str, ...] = C.SETORES_FINANCEIROS
                  ) -> pd.Series:
    """Marca bancos, seguradoras e afins pelo setor.

    Nessas empresas os códigos de conta significam outra coisa (ver
    `cvm.patrimonio_liquido`), e nem ROIC nem EV têm sentido econômico:
    "dívida" é depósito de cliente e "caixa" é estoque. Por isso elas ganham
    métricas próprias — ROE e Lucro/Preço — e ranking separado.
    """
    if df.empty:
        return pd.Series(dtype=bool)
    campos = [c for c in ("SETOR", "SEGMENTO") if c in df.columns]
    if not campos:
        return pd.Series(False, index=df.index)
    texto = df[campos[0]].fillna("").astype(str)
    for c in campos[1:]:
        texto = texto + " | " + df[c].fillna("").astype(str)
    padrao = "|".join(f"(?:{x})" for x in padroes)
    return texto.str.contains(padrao, case=False, na=False, regex=True)


def divida_bruta(bp: pd.DataFrame) -> pd.Series:
    return bp.get(C.CD_EMPRESTIMOS_CP, 0.0) + bp.get(C.CD_EMPRESTIMOS_LP, 0.0)


def caixa_total(bp: pd.DataFrame) -> pd.Series:
    return bp.get(C.CD_CAIXA, 0.0) + bp.get(C.CD_APLIC_FINANCEIRAS, 0.0)


def montar_indicadores(
    ebit: pd.DataFrame,
    bp: pd.DataFrame,
    mercado: pd.DataFrame,
    params: C.Params,
) -> pd.DataFrame:
    """Junta EBIT (LTM), balanço e dados de mercado e devolve ROIC e EY.

    `mercado` precisa de: CD_CVM, TICKER, PRECO, VALOR_MERCADO, LIQUIDEZ_MEDIA, SETOR
    """
    # CD_CVM percorre três fontes (CVM, B3, Yahoo) e basta uma delas trazer o
    # código como texto ou float para o merge não casar nada — e o universo sair
    # vazio, sem erro nenhum. Padronizar o tipo antes elimina essa classe inteira
    # de falha silenciosa.
    def _chave(d: pd.DataFrame, nome: str) -> pd.DataFrame:
        d = d.copy()
        d["CD_CVM"] = pd.to_numeric(d["CD_CVM"], errors="coerce").astype("Int64")
        antes = len(d)
        d = d.dropna(subset=["CD_CVM"])
        if len(d) < antes:
            log.warning("%s: %d linhas sem CD_CVM válido", nome, antes - len(d))
        return d

    ebit, bp, mercado = (_chave(ebit, "ebit"), _chave(bp, "balanço"),
                         _chave(mercado, "mercado"))

    df = ebit.merge(bp, on="CD_CVM", how="inner").merge(mercado, on="CD_CVM", how="inner")
    log.info("cruzamento: ebit=%d balanço=%d mercado=%d -> universo=%d",
             len(ebit), len(bp), len(mercado), len(df))
    if df.empty:
        comuns = set(ebit["CD_CVM"]) & set(bp["CD_CVM"]) & set(mercado["CD_CVM"])
        raise ValueError(
            "O cruzamento entre demonstrações, balanço e mercado não devolveu "
            f"nenhuma empresa (ebit={len(ebit)}, balanço={len(bp)}, "
            f"mercado={len(mercado)}, CD_CVM em comum={len(comuns)}). "
            "Verifique se o mapeamento CD_CVM <-> ticker da B3 está atualizado.")

    df["CONCESSAO"] = (eh_concessao(df) if params.incluir_intangivel_concessao
                       else pd.Series(False, index=df.index))
    if df["CONCESSAO"].any():
        log.info("intangível somado ao capital de %d concessionárias: %s",
                 int(df["CONCESSAO"].sum()),
                 ", ".join(df.loc[df["CONCESSAO"], "TICKER"].astype(str).head(20)))
    df["CAPITAL_TANGIVEL"] = capital_tangivel(df, params.incluir_investimentos,
                                              concessao=df["CONCESSAO"])
    df["DIVIDA_BRUTA"] = divida_bruta(df)
    df["CAIXA"] = caixa_total(df)
    df["DIVIDA_LIQUIDA"] = df["DIVIDA_BRUTA"] - df["CAIXA"]
    df["EV"] = df["VALOR_MERCADO"] + df["DIVIDA_LIQUIDA"]

    # ---- ROIC -----------------------------------------------------------
    if params.base_roic == "capital_tangivel":
        base = df["CAPITAL_TANGIVEL"]
    elif params.base_roic == "ativo_total":
        base = df.get(C.CD_ATIVO_TOTAL, np.nan)
    else:
        base = df.get(C.CD_PATRIMONIO_LIQUIDO, np.nan)
    df["ROIC"] = np.where(base > 0, df["EBIT_LTM"] / base, np.nan)

    # ---- Earnings Yield -------------------------------------------------
    if params.base_ey == "ebit_ev":
        df["EY"] = np.where(df["EV"] > 0, df["EBIT_LTM"] / df["EV"], np.nan)
    elif params.base_ey == "lucro_preco":
        df["EY"] = np.where(df["VALOR_MERCADO"] > 0,
                            df["EBIT_LTM"] / df["VALOR_MERCADO"], np.nan)
    else:  # replica o bug do TCC: "LPA" = EBIT / nº de ações, em R$ por ação
        df["EY"] = df["EBIT_LTM"] / df["ACOES"].replace(0, np.nan)

    # ---- financeiras: ROE e Lucro/Preço no lugar de ROIC e EBIT/EV -------
    # Três grupos, não dois. A concessionária continua sendo medida por ROIC e
    # EBIT/EV — as contas fazem sentido nela —, mas ranqueada entre as suas: o
    # ROIC dela é fixado pelo regulador, então compará-lo com o de uma indústria
    # é comparar régua com termômetro.
    df["TIPO"] = np.where(
        eh_financeira(df), "financeira",
        np.where(eh_financeira(df, C.SETORES_UTILIDADE_PUBLICA),
                 "utilidade", "operacional"))
    fin = df["TIPO"] == "financeira"
    if fin.any():
        pl = pd.to_numeric(df.get("PATRIMONIO"), errors="coerce")
        lucro = pd.to_numeric(df.get("LUCRO_LTM"), errors="coerce")
        if pl is not None and lucro is not None:
            roe = np.where(pl > 0, lucro / pl, np.nan)
            ep = np.where(df["VALOR_MERCADO"] > 0, lucro / df["VALOR_MERCADO"], np.nan)
            df.loc[fin, "ROIC"] = pd.Series(roe, index=df.index)[fin]
            df.loc[fin, "EY"] = pd.Series(ep, index=df.index)[fin]
        else:
            df.loc[fin, ["ROIC", "EY"]] = np.nan
        log.info("%d financeiras avaliadas por ROE e Lucro/Preço", int(fin.sum()))

    return df


def _motivos_incalculavel(df: pd.DataFrame) -> dict[str, pd.Series]:
    """Agrupa as empresas sem indicador pelo ingrediente que faltou."""
    rotulos = {
        "LUCRO_LTM": "lucro líquido",
        "PATRIMONIO": "patrimônio líquido",
        "EBIT_LTM": "EBIT",
        "EV": "EV",
        "VALOR_MERCADO": "valor de mercado (nº de ações)",
        "CAPITAL_TANGIVEL": "capital tangível",
    }
    ehfin = df["TIPO"].eq("financeira") if "TIPO" in df.columns else pd.Series(False, index=df.index)
    motivos = {}
    for i in df.index:
        cols = (("LUCRO_LTM", "PATRIMONIO", "VALOR_MERCADO") if bool(ehfin.get(i, False))
                else ("EBIT_LTM", "EV", "VALOR_MERCADO", "CAPITAL_TANGIVEL"))
        faltas = [rotulos[c] for c in cols
                  if c not in df.columns or pd.isna(df.at[i, c])]
        chave = ("sem " + ", ".join(faltas)) if faltas else "indicador não calculável"
        motivos.setdefault(chave, []).append(i)
    return {k: pd.Series(True, index=pd.Index(v)).reindex(df.index, fill_value=False)
            for k, v in motivos.items()}


# Faixa de Preço/Valor Patrimonial que uma empresa listada ocupa na prática.
# Larga de propósito: não é para julgar se a ação está cara, é só para separar
# duas hipóteses que diferem por mil vezes.
PVP_MINIMO, PVP_MAXIMO = 0.05, 50.0
# Quantidade de ações que uma companhia da B3 de fato tem. A segunda trava:
# sozinho, o P/VP erraria por mil numa ação muito descontada — se o P/VP real
# for 0,02, a hipótese "unidades" cai fora da faixa e a errada (mil vezes
# maior) entraria no lugar. Com esta, a errada viraria 1 trilhão de ações e é
# recusada também, e a função devolve NaN em vez de um número inventado.
ACOES_MINIMO, ACOES_MAXIMO = 1e6, 3e10


def escala_por_patrimonio(bruto, preco, patrimonio):
    """Decide se o nº de ações da CVM está em unidades ou em milhares.

    O arquivo de composição do capital da CVM não tem coluna de escala: umas
    companhias informam em unidades, outras em milhares. A inferência principal
    compara com as ações implícitas em `lucro ÷ lucro por ação` — mas quem não
    publica o LPA na conta esperada fica sem resposta, e a empresa some do
    ranking. Foi o caso da VALE3.

    Aqui entra um segundo sinal, independente do LPA: o patrimônio líquido.
    Das duas hipóteses, só uma produz um P/VP que existe no mundo real. Na
    Vale, com PL de R$ 208,7 bi: em unidades o valor de mercado daria R$ 272
    milhões (P/VP de 0,001, absurdo); em milhares dá R$ 272 bi (P/VP de 1,3).
    Não é chute — é a única leitura compatível com o balanço.

    Devolve o número de ações, ou NaN quando as duas hipóteses são plausíveis
    (ou nenhuma), caso em que é melhor não ter número do que ter o errado.
    """
    vals = [pd.to_numeric(x, errors="coerce") for x in (bruto, preco, patrimonio)]
    bruto, preco, patrimonio = vals
    if any(v is None or pd.isna(v) for v in vals) or bruto <= 0 or preco <= 0 or patrimonio <= 0:
        return np.nan
    candidatos = [float(bruto), float(bruto) * 1000.0]
    viaveis = [c for c in candidatos
               if ACOES_MINIMO <= c <= ACOES_MAXIMO
               and PVP_MINIMO <= (preco * c) / patrimonio <= PVP_MAXIMO]
    return viaveis[0] if len(viaveis) == 1 else np.nan


# Patrimônio por ação que uma companhia da B3 de fato tem, em R$. Larga de
# propósito, como a faixa de P/VP acima: só separa duas hipóteses mil vezes
# distantes.
VPA_MINIMO, VPA_MAXIMO = 0.01, 3000.0


def escala_por_vpa(bruto, patrimonio):
    """A mesma decisão de `escala_por_patrimonio`, sem precisar do preço.

    Serve a `cvm.composicao_capital`, que roda antes de haver cotação. Bancos
    entregam o lucro por ação zerado nos arquivos estruturados (BTG e
    Santander, DFP 2025), e sem o LPA a escala não era confirmada: as duas
    units ficavam sem nº de ações e fora do P/VP. Das hipóteses "unidades" e
    "milhares", vale a única que dá um nº de ações e um patrimônio por ação
    possíveis; as duas possíveis (ou nenhuma) devolvem NaN.

    BTG: 11,6 bi de ações em unidades dá VPA de R$ 5,9; em milhares seriam 11,6
    trilhões de ações. Santander: 7,5 mi "em unidades" daria VPA de R$ 16 mil;
    em milhares, R$ 16.
    """
    vals = [pd.to_numeric(x, errors="coerce") for x in (bruto, patrimonio)]
    bruto, patrimonio = vals
    if any(v is None or pd.isna(v) for v in vals) or bruto <= 0 or patrimonio <= 0:
        return np.nan
    viaveis = [c for c in (float(bruto), float(bruto) * 1000.0)
               if ACOES_MINIMO <= c <= ACOES_MAXIMO
               and VPA_MINIMO <= patrimonio / c <= VPA_MAXIMO]
    return viaveis[0] if len(viaveis) == 1 else np.nan


def valor_de_mercado_units(tickers: pd.Series, preco: pd.Series, acoes: pd.Series,
                           acoes_da_cvm: pd.Series) -> pd.Series:
    """Valor de mercado com as units corrigidas.

    Para ação comum é preço × ações. Para unit, o preço é o de várias ações,
    então divide pelo fator (`config.ACOES_POR_UNIT`) — mas só quando o nº de
    ações é o TOTAL da companhia, que é o que a CVM informa. Unit sem fator
    conhecido, ou com nº de ações vindo do Yahoo (que não diz se conta units
    ou ações), fica sem valor de mercado e sai do ranking com o motivo.
    """
    t = tickers.astype(str).str.upper().str.replace(".SA", "", regex=False)
    vm = preco * acoes
    unit = t.str.endswith("11")
    fator = t.map(C.ACOES_POR_UNIT)
    ok = unit & fator.notna() & acoes_da_cvm.fillna(False).astype(bool)
    vm = vm.where(~ok, preco * acoes / fator)
    return vm.where(~unit | ok, np.nan)


def aplicar_filtros(df: pd.DataFrame, params: C.Params) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Remove o que Greenblatt manda remover. Devolve (aprovados, rejeitados+motivo)."""
    df = df.copy()
    motivos: list[pd.DataFrame] = []

    def corta(mask: pd.Series, motivo: str) -> pd.DataFrame:
        nonlocal df
        fora = df[mask].copy()
        if not fora.empty:
            fora["MOTIVO_EXCLUSAO"] = motivo
            motivos.append(fora)
        return df[~mask]

    # Exclusões caso a caso (config.EXCLUSOES_MANUAIS) vêm antes de tudo, para
    # que o motivo registrado seja a decisão de método, e não um filtro
    # genérico que por acaso também a pegaria.
    if C.EXCLUSOES_MANUAIS and "TICKER" in df.columns and not df.empty:
        for pfx, (motivo, nota) in C.EXCLUSOES_MANUAIS.items():
            prefixo = df["TICKER"].astype(str).str.upper().str[:4]
            mask = prefixo == pfx.upper()
            if mask.any():
                df.loc[mask, "NOTA_EXCLUSAO"] = nota
                df = corta(mask, motivo)

    # Cada grupo tem a sua própria chave. Antes as duas exclusões estavam
    # amarradas no mesmo `if`, o que tornava impossível pedir bancos sem pedir
    # concessionárias junto — e difícil de enxergar qual das duas estava agindo.
    if params.excluir_setores and not df.empty:
        dispensados = set()
        if params.vagas_financeiras > 0:
            dispensados |= set(C.SETORES_FINANCEIROS)
        if params.vagas_utilidades > 0:
            dispensados |= set(C.SETORES_UTILIDADE_PUBLICA)
        padroes = [p for p in params.excluir_setores if p not in dispensados]

        campos = [c for c in ("SETOR", "SEGMENTO") if c in df.columns]
        if padroes and campos:
            # Concatenação explícita: `df[campos].agg(" | ".join, axis=1)` devolve
            # um DataFrame (não uma Series) quando o DataFrame está vazio, e aí
            # o .str seguinte quebra. Aconteceu em produção.
            texto = df[campos[0]].fillna("").astype(str)
            for c in campos[1:]:
                texto = texto + " | " + df[c].fillna("").astype(str)
            padrao = "|".join(f"(?:{p})" for p in padroes)
            mask = texto.str.contains(padrao, case=False, na=False, regex=True)
            fica_fin = set(C.SETORES_FINANCEIROS) - dispensados
            fica_uti = set(C.SETORES_UTILIDADE_PUBLICA) - dispensados
            quais = " e ".join(
                x for x in ("financeiro/seguros" if fica_fin else "",
                            "utilidade pública" if fica_uti else "") if x)
            df = corta(mask, f"setor excluído ({quais})" if quais else "setor excluído")

    df = corta(df["LIQUIDEZ_MEDIA"].fillna(0) < params.liquidez_minima_diaria,
               f"liquidez < R$ {params.liquidez_minima_diaria:,.0f}/dia")

    fin = df["TIPO"].eq("financeira") if "TIPO" in df.columns else pd.Series(False, index=df.index)
    if params.exigir_ebit_positivo:
        df = corta((df["EBIT_LTM"] <= 0) & ~fin, "EBIT negativo ou nulo")
        fin = df["TIPO"].eq("financeira") if "TIPO" in df.columns else pd.Series(False, index=df.index)
    if params.exigir_ev_positivo:
        df = corta((df["EV"] <= 0) & ~fin, "EV negativo ou nulo")

    # "indicador não calculável" não ajuda ninguém: some com a empresa sem dizer
    # o que faltou. Nomear o ingrediente ausente transformou uma investigação de
    # dois dias (o caso ITUB4) em algo que a própria execução responde.
    sem_conta = df["ROIC"].isna() | df["EY"].isna()
    if sem_conta.any():
        for motivo, mask in _motivos_incalculavel(df[sem_conta]).items():
            alvo = pd.Series(False, index=df.index)
            alvo.loc[mask.index[mask]] = True
            df = corta(alvo, motivo)

    if params.apenas_um_ticker_por_empresa and not df.empty:
        # entre PETR3/PETR4 do mesmo CNPJ, fica o de maior liquidez
        df = df.sort_values("LIQUIDEZ_MEDIA", ascending=False)
        dup = df.duplicated(subset=["CD_CVM"], keep="first")
        df = corta(dup, "classe de ação menos líquida da mesma empresa")

    rejeitados = (pd.concat(motivos, ignore_index=True) if motivos
                  else pd.DataFrame(columns=list(df.columns) + ["MOTIVO_EXCLUSAO"]))
    return df.reset_index(drop=True), rejeitados
