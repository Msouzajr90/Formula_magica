"""Monta a tabela de indicadores e aplica os filtros de universo.

Os indicadores, e por que cada um está aqui:

  P/VP          preço da cota dividido pelo valor patrimonial por cota. É o
                indicador mais citado e o mais mal usado: ele compara o preço
                com uma *avaliação contábil*. Em fundo de tijolo, o laudo é
                anual e defasado; em fundo de papel, o VP acompanha a marcação
                dos CRI e o P/VP fica quase sempre perto de 1, o que torna a
                comparação entre as duas famílias sem sentido. Por isso o
                ranking do site pode ser rodado dentro de cada família.

  DY 12m        proventos dos últimos 12 meses sobre o preço atual. Convenção
                de mercado. Sobe com qualquer rendimento extraordinário.

  DY mediano    mediana dos rendimentos mensais anualizada, sobre o preço.
                É o DY que sobra quando se tira o evento não recorrente.

  Consistência  quantos dos últimos 12 meses tiveram pagamento e quão estáveis
                foram. Um fundo que pagou 12 vezes valores parecidos e outro
                que pagou 5 vezes com o mesmo total anual não são a mesma coisa
                para quem vive de renda.

  Liquidez      volume financeiro médio diário. Em FII isso é restrição de
                verdade: metade do mercado não negocia R$ 500 mil por dia, e
                sair de uma posição relevante nesses fundos leva semanas.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C
from .config import ParamsFII


def montar(informe: pd.DataFrame, cadastro: pd.DataFrame,
           preco: pd.Series, liq: pd.Series, var12: pd.Series,
           resumo: pd.DataFrame) -> pd.DataFrame:
    """Junta CVM + mercado numa linha por ticker."""
    df = informe.copy()
    df = df[df["TICKER"].notna()]

    # O informe já traz a razão social; do cadastro só entra o que ele acrescenta.
    # Sem esta checagem o merge criaria NOME_x e NOME_y, e o resto do código
    # procuraria por NOME e não acharia nenhuma das duas.
    if cadastro is not None and not cadastro.empty:
        novas = [c for c in cadastro.columns if c == "CNPJ" or c not in df.columns]
        if len(novas) > 1:
            df = df.merge(cadastro[novas], on="CNPJ", how="left")
    for col in ("NOME", "SITUACAO"):
        if col not in df.columns:
            df[col] = pd.NA

    chave = df["TICKER"].astype(str).str.upper() + ".SA"
    df["PRECO"] = chave.map(preco)
    df["LIQUIDEZ"] = chave.map(liq)
    df["VAR_12M"] = chave.map(var12)
    for col in resumo.columns:
        df[col] = chave.map(resumo[col])
    # Se o Yahoo não devolver provento nenhum, o resumo vem sem colunas e o
    # cálculo abaixo quebraria com KeyError. Melhor a tela sair com o DY vazio
    # e o filtro de "pagou em menos de N meses" cortando os fundos: o problema
    # fica visível na aba Excluídos em vez de derrubar a coleta inteira.
    for col in ("PROV_12M", "PROV_MEDIANA_12M", "MESES_PAGOS_12M",
                "MESES_PAGOS_36M", "CV_PROVENTOS", "RAZAO_EXTRA",
                "ULTIMO_PROVENTO", "DT_ULTIMO_PROVENTO"):
        if col not in df.columns:
            df[col] = pd.NA

    vazio = pd.Series(float("nan"), index=df.index)
    if "TIPO_FUNDO" not in df.columns:
        df["TIPO_FUNDO"] = C.TIPO_FII
    df["TIPO_FUNDO"] = df["TIPO_FUNDO"].fillna(C.TIPO_FII)
    df["FAMILIA"] = [C.familia_do_fundo(t, i, p, f) for t, i, p, f in
                     zip(df["TIPO_FUNDO"],
                         df.get("PCT_IMOVEIS", vazio),
                         df.get("PCT_PAPEL", vazio),
                         df.get("PCT_FOF", vazio))]

    # ---- indicadores -----------------------------------------------------
    vp = pd.to_numeric(df["VP_COTA"], errors="coerce")
    df["P_VP"] = np.where(vp > 0, df["PRECO"] / vp, np.nan)

    preco_ok = pd.to_numeric(df["PRECO"], errors="coerce").where(lambda s: s > 0)
    df["DY_12M"] = df["PROV_12M"] / preco_ok
    df["DY_MEDIANO"] = df["PROV_MEDIANA_12M"] / preco_ok
    df["DY_SOBRE_VP"] = df["PROV_12M"] / vp.where(vp > 0)
    df["RENDIMENTO_MENSAL"] = df["PROV_12M"] / 12.0

    # Retorno total do cotista: variação do preço + rendimentos recebidos.
    df["RETORNO_12M"] = df["VAR_12M"] + df["DY_12M"]

    # Consistência em [0, 1]: metade vem de ter pago todos os meses, metade de
    # ter pago valores estáveis. Um fundo que paga sempre R$ 0,10 tira 1,0;
    # um que paga em 6 meses com valores erráticos fica perto de 0,2.
    regular = (df["MESES_PAGOS_12M"] / 12.0).clip(0, 1)
    estavel = (1.0 - df["CV_PROVENTOS"].fillna(1.0)).clip(0, 1)
    df["CONSISTENCIA"] = 0.5 * regular + 0.5 * estavel

    df["IDADE_MESES"] = _idade_meses(df.get("DT_FUNCIONAMENTO"))
    return df.reset_index(drop=True)


def _idade_meses(dt) -> pd.Series:
    if dt is None:
        return pd.Series(dtype=float)
    d = pd.to_datetime(dt, errors="coerce")
    hoje = pd.Timestamp.today().normalize()
    return ((hoje - d).dt.days / 30.44).round(0)


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
def filtrar(df: pd.DataFrame, p: ParamsFII) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Separa o universo elegível dos excluídos, com o motivo de cada exclusão.

    O motivo importa tanto quanto a exclusão. No lado das ações, a lista de
    empresas cortadas é uma aba do site — a mesma ideia vale aqui, porque um
    fundo conhecido que sumiu da tela sem explicação parece um defeito.
    """
    df = df.copy()
    motivos: list[pd.Series] = []

    def regra(mascara: pd.Series, texto: str) -> None:
        # fillna(False): campo ausente não exclui ninguém — quem exclui por
        # ausência é a regra específica ("sem cotação", "sem valor patrimonial").
        m = pd.Series(mascara, index=df.index).fillna(False).astype(bool)
        motivos.append(pd.Series(np.where(m, texto, ""), index=df.index))

    situacao = df.get("SITUACAO", pd.Series("", index=df.index)).astype("string")
    regra(situacao.str.contains("cancelad|liquidad", case=False, na=False),
          "registro cancelado ou em liquidação")

    if p.excluir_fundos_exclusivos:
        exc = df.get("EXCLUSIVO", pd.Series("", index=df.index)).astype("string")
        regra(exc.str.strip().str.upper().eq("S"), "fundo exclusivo")

    negocia = df.get("NEGOCIA_BOLSA", pd.Series(pd.NA, index=df.index)).astype("string")
    regra(negocia.str.strip().str.upper().eq("N"), "não negociado em bolsa")

    regra(df["PRECO"].isna(), "sem cotação no Yahoo")
    regra(df["VP_COTA"].isna() | (df["VP_COTA"] <= 0), "sem valor patrimonial")
    regra(df["PL"].fillna(0) < p.patrimonio_minimo,
          f"patrimônio abaixo de {_brl(p.patrimonio_minimo)}")
    regra(df["COTISTAS"].fillna(0) < p.cotistas_minimo,
          f"menos de {p.cotistas_minimo} cotistas")
    regra(df["LIQUIDEZ"].fillna(0) < p.liquidez_minima_diaria,
          f"liquidez abaixo de {_brl(p.liquidez_minima_diaria)}/dia")
    regra(df["MESES_PAGOS_12M"].fillna(0) < p.meses_minimos_com_rendimento,
          f"pagou rendimento em menos de {p.meses_minimos_com_rendimento} dos últimos 12 meses")
    regra(df["IDADE_MESES"].fillna(999) < p.idade_minima_meses,
          f"menos de {p.idade_minima_meses} meses de funcionamento")

    # O FI-Infra é o único veículo cuja identidade é *inferida*: o CNPJ sai de
    # casar a razão social da B3 com a do cadastro da CVM, porque nenhum arquivo
    # público liga as duas coisas (ver `fiib3/casamento.py`). Um casamento errado
    # não deixa rastro no dado — ele publica o patrimônio de um fundo sob o
    # código de outro, com aparência de normalidade.
    #
    # Esta regra é a conferência independente: FI-Infra carrega debênture
    # marcada a mercado, então o preço da cota anda colado no valor patrimonial.
    # Um P/VP fora de [0,7; 1,4] não é oportunidade, é sinal de que o VP/cota
    # veio do fundo errado — foi assim que um casamento com o fundo master, cuja
    # cota valia R$ 1,55 contra R$ 100 do fundo listado, apareceu. A faixa é
    # larga de propósito: ela existe para pegar erro de ordem de grandeza, não
    # para julgar preço.
    tipo = df.get("TIPO_FUNDO", pd.Series(C.TIPO_FII, index=df.index)).astype("string")
    pvp = pd.to_numeric(df.get("P_VP", pd.Series(float("nan"), index=df.index)),
                        errors="coerce")
    regra(tipo.eq(C.TIPO_FIINFRA) & pvp.notna() & ((pvp < 0.7) | (pvp > 1.4)),
          "P/VP fora do que um fundo de debênture comporta — o CNPJ da lista de "
          "FI-Infra provavelmente aponta para outro fundo")

    # O arquivo da CVM traz o ano inteiro e guardamos a última competência de
    # cada fundo. Um fundo que parou de entregar informe há meses provavelmente
    # foi liquidado ou incorporado — e seguiria no ranking com patrimônio velho,
    # que é pior que não aparecer.
    #
    # A comparação é feita DENTRO de cada tipo de fundo, e não na tabela toda,
    # porque as três fontes têm calendários diferentes: o informe diário do
    # FI-Infra sai no dia seguinte, o mensal do FII sai até o 15º dia útil do mês
    # seguinte, e o arquivo-ponte do FII costuma ser gerado uma vez por mês. Uma
    # régua só, tirada do máximo global, cortaria o mercado inteiro de FII
    # sempre que o arquivo-ponte atrasasse duas competências.
    if "COMPETENCIA" in df.columns:
        tipos = df.get("TIPO_FUNDO", pd.Series(C.TIPO_FII, index=df.index))
        tipos = tipos.fillna(C.TIPO_FII).astype("string")
        for tipo in tipos.dropna().unique():
            no_tipo = tipos.eq(tipo).fillna(False)
            comps = df.loc[no_tipo, "COMPETENCIA"].dropna()
            if not len(comps):
                continue
            atual = comps.max()
            limite = _competencia_anterior(atual, 2)
            atrasado = no_tipo & (df["COMPETENCIA"].fillna("") < limite)
            regra(atrasado, f"último informe é de antes de {limite} "
                            f"(atual em {tipo}: {atual})")

    juntos = pd.concat(motivos, axis=1)
    primeiro = juntos.apply(lambda linha: next((m for m in linha if m), ""), axis=1)
    df["MOTIVO_EXCLUSAO"] = primeiro
    elegiveis = df[primeiro == ""].drop(columns=["MOTIVO_EXCLUSAO"])
    excluidos = df[primeiro != ""]
    return elegiveis.reset_index(drop=True), excluidos.reset_index(drop=True)


def _competencia_anterior(comp: str, meses: int) -> str:
    """'2026-07' recuado 2 meses -> '2026-05'."""
    try:
        p = pd.Period(str(comp), freq="M") - meses
        return str(p)
    except Exception:                                          # noqa: BLE001
        return ""


def _brl(v: float) -> str:
    if v >= 1_000_000:
        return f"R$ {v / 1_000_000:.0f} mi"
    if v >= 1_000:
        return f"R$ {v / 1_000:.0f} mil"
    return f"R$ {v:.0f}"
