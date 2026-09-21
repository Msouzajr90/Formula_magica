"""Da tabela longa para uma linha por fundo, com as métricas da série.

Duas decisões aqui merecem leitura antes do código.

**As escalas não batem entre as fontes.** Medido nos arquivos reais:
`Percentual_Rentabilidade_Efetiva_Mes` tem mediana 0,00104 e p90 0,0169 no
informe de FII — é **fração**, 1,69% ao mês no percentil 90. No informe de
Fiagro a mediana do mesmo conceito é 0,32, que só faz sentido como
**percentual** (0,32% ao mês); como fração seriam 32% ao mês. Somar os dois sem
converter erraria por cem vezes, e o número sairia bonito o bastante para
ninguém desconfiar. `ESCALA` abaixo é a correção, por fonte.

**Prazo vem da data, não do rótulo.** O Riza Viseu FII vem declarado
"Indeterminado" e com `Data_Prazo_Duracao` = 12/05/2032, contra início em
12/05/2025 — sete anos exatos. O rótulo mente; a data, não. Então a data manda,
o rótulo vira reforço, e o desacordo entre os dois é publicado em
`ROTULO_CONFLITA` em vez de ser resolvido no escuro.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import config as C

log = logging.getLogger(__name__)

# Fator que leva o valor da fonte para fração (0,015 = 1,5%).
ESCALA = {C.TIPO_FII: 1.0, C.TIPO_FIAGRO: 0.01, C.TIPO_FIP: 1.0}
COLUNAS_EM_ESCALA = ("RENT_MES", "DY_MES", "AMORT_MES", "TAXA_ADM")

# Acima disso, a "rentabilidade mensal" não é rentabilidade — é erro de escala
# ou de digitação. Serve de alarme, não de filtro: o valor é mantido e o aviso
# sobe para quem publica.
RENTABILIDADE_MENSAL_ABSURDA = 1.0          # 100% num mês


def normalizar_escala(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Converte percentual em fração conforme a fonte, e avisa se não bater."""
    out = df.copy()
    avisos: list[str] = []
    for tipo, fator in ESCALA.items():
        linhas = out["TIPO"].eq(tipo)
        if not linhas.any():
            continue
        for coluna in COLUNAS_EM_ESCALA:
            out.loc[linhas, coluna] = (
                pd.to_numeric(out.loc[linhas, coluna], errors="coerce") * fator)
        mediana = pd.to_numeric(out.loc[linhas, "RENT_MES"],
                                errors="coerce").abs().median()
        # Depois de convertida, a mediana da rentabilidade mensal tem que ser
        # pequena. Se não for, a CVM mudou a escala e `ESCALA` ficou velha.
        if pd.notna(mediana) and mediana > 0.10:
            avisos.append(
                f"{tipo}: mediana da rentabilidade mensal em {mediana:.1%} "
                f"depois da conversão — a escala da fonte provavelmente mudou.")
    return out, avisos


# ---------------------------------------------------------------------------
# Prazo
# ---------------------------------------------------------------------------
def resolver_prazo(linha: pd.Series, hoje: pd.Timestamp) -> dict:
    """Prazo, vencimento e anos restantes, com a procedência declarada.

    Quatro situações, e cada uma com saída própria:

    - data plausível        -> Determinado, com anos restantes;
    - data fora de escala   -> Determinado, sem anos restantes, marcado
                               suspeito (existe vencimento em 3035 no informe);
    - só o rótulo           -> o que o rótulo disser, sem data;
    - nada                  -> Sem dado. FIP inteiro cai aqui: o informe
                               quadrimestral não tem nenhuma coluna de prazo.
    """
    rotulo = linha.get("ROTULO_PRAZO")
    rotulo = None if pd.isna(rotulo) else str(rotulo).strip().capitalize()
    venc = linha.get("DT_VENCIMENTO")
    tem_data = pd.notna(venc)

    if not tem_data:
        return {"PRAZO": rotulo or C.PRAZO_SEM_DADO, "DT_VENCIMENTO": None,
                "ANOS_RESTANTES": None, "PRAZO_SUSPEITO": False,
                "PRAZO_VENCIDO": False, "ROTULO_CONFLITA": False}

    venc = pd.Timestamp(venc)
    plausivel = C.vencimento_plausivel(venc, hoje)
    anos = round((venc - hoje).days / 365.25, 2) if plausivel else None
    return {
        "PRAZO": C.PRAZO_DETERMINADO,
        "DT_VENCIMENTO": venc.strftime("%Y-%m-%d"),
        "ANOS_RESTANTES": anos,
        "PRAZO_SUSPEITO": not plausivel,
        # Vencimento no passado com o fundo ainda entregando informe. Acontece
        # de verdade: o Vector Queluz vence em 07/2021 e segue informando em
        # 2026. Ou a assembleia prorrogou e o informe não acompanhou, ou o
        # fundo está em liquidação. Nos dois casos o número negativo é
        # informação — "deveria ter vencido" —, e não um prazo a ranquear.
        "PRAZO_VENCIDO": bool(anos is not None and anos < 0),
        # O fundo tem data de vencimento mas se declara indeterminado.
        "ROTULO_CONFLITA": rotulo == C.PRAZO_INDETERMINADO,
    }


# ---------------------------------------------------------------------------
# Séries
# ---------------------------------------------------------------------------
def _limpar_retornos(serie: pd.Series) -> tuple[pd.Series, int]:
    """Descarta o mês cujo retorno não é retorno, e conta quantos foram.

    Medido no primeiro arquivo gerado de verdade: 2 dos 813 fundos publicados
    trazem retorno mensal acima de 100% — o Packem Fiagro com -380% e o Pátria
    Logística com +253%. Um mês assim não é rentabilidade, é remarcação de
    ativo, erro de escala na origem ou dígito trocado; composto com os outros
    onze, contamina o acumulado inteiro e some dentro de um número que ainda
    parece plausível.

    Descartar é melhor que truncar: um valor truncado vira um retorno inventado
    por nós, enquanto o mês ausente deixa o acumulado sobre os meses que
    sobraram e o fundo marcado.
    """
    v = pd.to_numeric(serie, errors="coerce").dropna()
    if v.empty:
        return v, 0
    fora = v.abs() > RENTABILIDADE_MENSAL_ABSURDA
    return v[~fora], int(fora.sum())


def _composto(serie: pd.Series) -> float | None:
    """Retorno acumulado de uma série de retornos mensais em fração."""
    v, _ = _limpar_retornos(serie)
    if v.empty:
        return None
    return float(np.prod(1.0 + v.to_numpy()) - 1.0)


def _retorno_pela_cota(g: pd.DataFrame) -> float | None:
    """Variação do valor patrimonial da cota na janela — conferência cruzada.

    Não é retorno total: o VP/cota cai quando o fundo distribui rendimento ou
    amortiza, então este número subestima o ganho de quem recebeu o caixa. Vale
    como contraprova de escala, que é justamente onde a rentabilidade declarada
    falha: VP/cota está em reais e não tem ambiguidade de unidade.
    """
    v = pd.to_numeric(g["VP_COTA"], errors="coerce").dropna()
    if len(v) < 2 or v.iloc[0] <= 0:
        return None
    return float(v.iloc[-1] / v.iloc[0] - 1.0)


def metricas_da_serie(g: pd.DataFrame, janela: int) -> dict:
    """O que só a série diz: acumulados, e para onde os cotistas foram."""
    g = g.sort_values("DATA")
    ultimos = g.tail(janela)

    cot = pd.to_numeric(ultimos["COTISTAS"], errors="coerce").dropna()
    var_janela = var_ultimo = None
    if len(cot) >= 2 and cot.iloc[0] > 0:
        var_janela = float(cot.iloc[-1] / cot.iloc[0] - 1.0)
        if cot.iloc[-2] > 0:
            var_ultimo = float(cot.iloc[-1] / cot.iloc[-2] - 1.0)

    amort = pd.to_numeric(ultimos["AMORT_MES"], errors="coerce").fillna(0.0)
    dy = pd.to_numeric(ultimos["DY_MES"], errors="coerce").dropna()
    _, descartados = _limpar_retornos(ultimos["RENT_MES"])

    return {
        "N_INFORMES": int(len(g)),
        "RENT_12M": _composto(ultimos["RENT_MES"]),
        "RENT_VP_12M": _retorno_pela_cota(ultimos),
        "MESES_DESCARTADOS": descartados,
        # DY não compõe: o mercado soma os doze rendimentos e divide pelo
        # preço. Somar a série mensal é a tradução direta disso.
        "DY_12M": float(dy.sum()) if not dy.empty else None,
        "AMORT_12M": float(amort.sum()) if len(amort) else None,
        "MESES_COM_AMORT": int((amort > 0).sum()),
        "COTISTAS_VAR_12M": var_janela,
        "COTISTAS_VAR_ULTIMO": var_ultimo,
    }


# ---------------------------------------------------------------------------
def consolidar(longo: pd.DataFrame, params: C.ParamsFechados | None = None,
               hoje: pd.Timestamp | None = None
               ) -> tuple[pd.DataFrame, list[str]]:
    """Uma linha por fundo: o último informe mais as métricas da série."""
    params = params or C.ParamsFechados()
    hoje = pd.Timestamp(hoje or pd.Timestamp.today()).normalize()
    if longo.empty:
        return pd.DataFrame(columns=list(C.COLUNAS)), ["Tabela vazia."]

    df, avisos = normalizar_escala(longo)
    df = df.copy()
    df["DATA"] = pd.to_datetime(df["DATA"], errors="coerce")
    df = df.dropna(subset=["DATA"]).sort_values(["CNPJ", "DATA"])

    # A CVM republica informe corrigido mantendo o original no arquivo; ficar
    # com a última linha de cada (CNPJ, DATA) evita contar o mesmo mês duas
    # vezes no acumulado. Mesma armadilha do lado das ações.
    df = df.drop_duplicates(subset=["CNPJ", "DATA"], keep="last")

    linhas = []
    for cnpj, g in df.groupby("CNPJ", sort=False):
        ultima = g.iloc[-1]
        item = {
            "CNPJ": cnpj,
            "NOME": ultima.get("NOME"),
            "TIPO": ultima.get("TIPO"),
            "COMPETENCIA": ultima["DATA"].strftime("%Y-%m"),
            "DT_INFORME": ultima["DATA"].strftime("%Y-%m-%d"),
            "PERIODICIDADE": C.PERIODICIDADE.get(ultima.get("TIPO"), "mensal"),
            "COTISTAS": ultima.get("COTISTAS"),
            "COTISTAS_PF": ultima.get("COTISTAS_PF"),
            "PL": ultima.get("PL"),
            "VP_COTA": ultima.get("VP_COTA"),
            "COTAS": ultima.get("COTAS"),
            "RENT_MES": ultima.get("RENT_MES"),
            "DY_MES": ultima.get("DY_MES"),
            "AMORT_MES": ultima.get("AMORT_MES"),
            "TAXA_ADM": ultima.get("TAXA_ADM"),
            "PUBLICO": ultima.get("PUBLICO"),
            "EXCLUSIVO": ultima.get("EXCLUSIVO"),
            "BOLSA": ultima.get("BOLSA"),
            "CETIP": ultima.get("CETIP"),
            "MBO": ultima.get("MBO"),
            "ADMINISTRADOR": ultima.get("ADMINISTRADOR"),
            "SEGMENTO": ultima.get("SEGMENTO"),
        }
        item.update(resolver_prazo(ultima, hoje))
        item.update(metricas_da_serie(g, params.janela_meses))

        inicio = ultima.get("DT_INICIO")
        if pd.notna(inicio):
            inicio = pd.Timestamp(inicio)
            item["DT_INICIO"] = inicio.strftime("%Y-%m-%d")
            item["IDADE_ANOS"] = round((hoje - inicio).days / 365.25, 2)
        else:
            item["DT_INICIO"] = None
            item["IDADE_ANOS"] = None
        linhas.append(item)

    out = pd.DataFrame(linhas)
    for coluna in C.COLUNAS:
        if coluna not in out.columns:
            out[coluna] = None
    out = out[list(C.COLUNAS)]

    return out.reset_index(drop=True), avisos + conferir(out, "universo bruto")


def conferir(df: pd.DataFrame, onde: str = "publicado") -> list[str]:
    """O que merece ser dito sobre um conjunto antes de publicá-lo.

    Recebe o conjunto como parâmetro de propósito: a primeira versão media
    sempre o universo bruto, e o relatório avisava sobre 14 fundos com retorno
    absurdo e 2 com vencimento em 3035 que o filtro tinha acabado de descartar.
    Aviso sobre fundo que não vai para a tela treina quem lê a ignorar.
    """
    if df.empty:
        return [f"{onde}: nenhum fundo."]
    avisos: list[str] = []
    absurdas = pd.to_numeric(df["RENT_MES"], errors="coerce").abs() > \
        RENTABILIDADE_MENSAL_ABSURDA
    if absurdas.any():
        nomes = ", ".join(str(n)[:28] for n in df.loc[absurdas, "NOME"].head(3))
        avisos.append(f"{onde}: {int(absurdas.sum())} fundo(s) com "
                      f"rentabilidade no último mês acima de 100% ({nomes}).")
    if "MESES_DESCARTADOS" in df.columns:
        descartes = pd.to_numeric(df["MESES_DESCARTADOS"],
                                  errors="coerce").fillna(0)
        if (descartes > 0).any():
            avisos.append(
                f"{onde}: {int((descartes > 0).sum())} fundo(s) tiveram "
                f"{int(descartes.sum())} mês(es) fora do acumulado por retorno "
                f"acima de 100%.")
    suspeitos = df["PRAZO_SUSPEITO"].fillna(False).astype(bool)
    if suspeitos.any():
        avisos.append(f"{onde}: {int(suspeitos.sum())} fundo(s) com data de "
                      f"vencimento fora de escala; ficam sem prazo restante.")
    vencidos = df["PRAZO_VENCIDO"].fillna(False).astype(bool)
    if vencidos.any():
        avisos.append(f"{onde}: {int(vencidos.sum())} fundo(s) com vencimento "
                      f"no passado e ainda entregando informe.")
    return avisos


# ---------------------------------------------------------------------------
def elegiveis(df: pd.DataFrame,
              params: C.ParamsFechados | None = None) -> pd.Series:
    """Máscara do universo publicável — ver `ParamsFechados` para o porquê."""
    params = params or C.ParamsFechados()
    publico = df["PUBLICO"].fillna("").astype("string").str.upper()
    e_fip = df["TIPO"].eq(C.TIPO_FIP)

    aceitos = publico.str.contains("|".join(params.publicos_aceitos),
                                   regex=True, na=False)
    aceitos_fip = publico.str.contains("|".join(params.publicos_aceitos_fip),
                                       regex=True, na=False)
    ok = (aceitos & ~e_fip) | (aceitos_fip & e_fip)

    if params.excluir_exclusivos:
        # Nulo não exclui: FIP não informa o campo, e tratá-lo como exclusivo
        # apagaria a fonte inteira.
        ok &= ~df["EXCLUSIVO"].fillna(False).astype(bool)
    # O corte de cotistas é por fonte: no FIP o número conta subscritores, que
    # é outra medida — ver `ParamsFechados.cotistas_minimo_fip`.
    cotistas = pd.to_numeric(df["COTISTAS"], errors="coerce").fillna(0)
    minimo = pd.Series(params.cotistas_minimo, index=df.index)
    minimo[e_fip] = params.cotistas_minimo_fip
    ok &= cotistas >= minimo
    if params.patrimonio_minimo:
        ok &= pd.to_numeric(df["PL"], errors="coerce").fillna(0) >= \
            params.patrimonio_minimo
    return ok
