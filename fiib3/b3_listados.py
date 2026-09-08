"""A lista de fundos listados da B3 — quem negocia e com que código.

De onde vem: b3.com.br → Produtos e Serviços → Renda Variável → Fundos →
(Fiagro / Fundos de Infraestrutura) → botão de download. Sai um CSV com três
colunas — razão social, nome de pregão e código — e é a **única** fonte pública
que liga o nome de um fundo ao seu código de negociação. A CVM não publica esse
vínculo: o informe diário não tem ISIN, e o cadastro novo
(`registro_fundo_classe.zip`, 136 mil linhas) só tem `Codigo_CVM`, que é o
número de registro na autarquia.

Por que ela vale mesmo onde o ISIN funciona
-------------------------------------------
Para o Fiagro o ISIN do informe da CVM já dá um código. Medido na competência
07/2026, contra a lista da B3 de 49 Fiagro listados:

    38 códigos coincidem
    11 fundos listados na B3 não têm ISIN no informe — RURA11 entre eles
     9 códigos derivados do ISIN não estão listados na B3

Ou seja: sozinho, o ISIN perde onze fundos negociados e inventa nove que não
negociam — cada um deles uma consulta perdida ao Yahoo e uma linha de "sem
cotação" escondendo os casos em que a ausência significa alguma coisa. A lista
da B3 é o que o mercado efetivamente negocia, e por isso ela ganha do ISIN
quando as duas discordam.

O arquivo é externo e entra no repositório como veio, só reconvertido para
UTF-8. Trocar por uma versão nova é substituir o arquivo.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from . import casamento
from .cvm_fii import ticker_do_isin

log = logging.getLogger(__name__)

PASTA = Path(__file__).parent / "b3"
EXPORT_FIAGRO = PASTA / "fiagro.csv"
EXPORT_FIINFRA = PASTA / "fiinfra.csv"
COLUNAS = ("CODIGO", "TICKER", "PREGAO", "RAZAO")


def ler_export(caminho: Path | str) -> pd.DataFrame:
    """Lê um CSV de fundos listados da B3. Devolve CODIGO, TICKER, PREGAO, RAZAO.

    O arquivo tem três colunas no cabeçalho e um ponto e vírgula sobrando no fim
    de cada linha, o que faz o pandas tratar a primeira coluna como índice se a
    leitura for ingênua — daí os nomes serem passados na mão.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        return pd.DataFrame(columns=list(COLUNAS), dtype="string")
    bruto = caminho.read_bytes()
    for codificacao in ("utf-8-sig", "utf-8", "ISO-8859-1"):
        try:
            texto = bruto.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    else:                                                      # pragma: no cover
        texto = bruto.decode("ISO-8859-1", errors="replace")

    import io
    df = pd.read_csv(io.StringIO(texto), sep=";", dtype="string", header=0,
                     names=["RAZAO", "PREGAO", "CODIGO", "_"], index_col=False)
    df = df[df["CODIGO"].notna()].copy()
    df["CODIGO"] = df["CODIGO"].str.strip().str.upper()
    df = df[df["CODIGO"].str.fullmatch(r"[A-Z]{4}", na=False)]
    # Todo fundo listado negocia com o sufixo 11; a B3 publica só o prefixo.
    df["TICKER"] = df["CODIGO"] + "11"
    df["RAZAO"] = df["RAZAO"].str.strip()
    df["PREGAO"] = df["PREGAO"].str.strip()
    return df[list(COLUNAS)].drop_duplicates(subset=["CODIGO"]).reset_index(drop=True)


def aplicar_tickers(informe: pd.DataFrame,
                    export: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Cruza o informe com a lista da B3: preenche TICKER e confirma o mercado.

    O cruzamento tem **duas passadas, nesta ordem**, e a ordem é o que faz a
    coisa funcionar:

    1. **Pelo código do ISIN.** Quando o informe traz ISIN, o código já está
       determinado (`BRCRAACTF008` → `CRAA11`) e basta ver se ele consta da
       lista da B3. É comparação exata, sem risco.
    2. **Pelo nome**, só para o que sobrou. Casar razão social é caro e
       falível; usar isso onde o ISIN já respondeu seria trocar certeza por
       heurística. Medido: o CRAA11 tem ISIN e casa na primeira passada,
       enquanto o nome dele — a CVM abrevia para "SPARTA FIAGRO FUNDO DE I. NAS
       CADEIAS P. A. R. LIMITADA" — tirava 47% na segunda.

    E há uma terceira coisa, que não é sobre o código: **estar na lista da B3
    define que o fundo negocia em bolsa**. O informe da CVM tem um campo de
    mercado de negociação, e ele erra — o CRAA11 vem marcado como `BALCAO`
    mesmo estando listado. Entre um campo cadastral e a lista da própria bolsa,
    vale a bolsa; sem isso o fundo era cortado por "não negociado em bolsa" e
    sumia da tela.

    Devolve `(informe, avisos)`.
    """
    avisos: list[str] = []
    if informe.empty or export.empty:
        return informe, avisos

    df = informe.copy()
    if "TICKER" in df.columns:
        do_isin = df["TICKER"].astype("string").str.strip().str.upper()
    else:
        do_isin = pd.Series(pd.NA, index=df.index, dtype="string")
    if "ISIN" in df.columns:
        derivado = df["ISIN"].map(ticker_do_isin)
        derivado = pd.Series(derivado, index=df.index, dtype="string")
        derivado = derivado.where(derivado.isna(), derivado + "11")
        do_isin = do_isin.fillna(derivado)

    listados = set(export["TICKER"].dropna())
    achado = do_isin.where(do_isin.isin(listados))

    # Segunda passada: nome, só para os códigos da B3 que ninguém reivindicou.
    restantes = export[~export["TICKER"].isin(set(achado.dropna()))]
    sem_par: list[str] = []
    if len(restantes):
        casador = casamento.Casador(pd.DataFrame(
            {"CNPJ": df["CNPJ"].to_numpy(), "NOME": df["NOME"].to_numpy()}))
        por_cnpj: dict[str, str] = {}
        for r in restantes.itertuples():
            cnpj, _, _ = casador.casar(r.RAZAO)
            if cnpj is None:
                sem_par.append(f"{r.TICKER} ({str(r.RAZAO)[:40]})")
            else:
                por_cnpj[cnpj] = r.TICKER
        achado = achado.fillna(df["CNPJ"].map(por_cnpj).astype("string"))

    na_b3 = achado.notna()
    df["TICKER"] = achado.fillna(do_isin)
    df["ORIGEM_TICKER"] = na_b3.map({True: "b3", False: pd.NA}).astype("string")
    df.loc[na_b3, "NEGOCIA_BOLSA"] = "S"

    fantasmas = int((do_isin.notna() & ~na_b3).sum())
    if sem_par:
        avisos.append(f"{len(sem_par)} fundo(s) listados na B3 não foram achados "
                      f"no informe da CVM: {', '.join(sem_par[:6])}"
                      + (" ..." if len(sem_par) > 6 else ""))
    if fantasmas:
        avisos.append(f"{fantasmas} código(s) derivados do ISIN não estão na lista "
                      f"da B3; eles seguem no universo e caem no filtro de "
                      f"liquidez se não negociarem.")
    log.info("B3: %d de %d listados achados no informe; %d fundos confirmados "
             "como negociados em bolsa.", int(na_b3.sum()), len(listados),
             int(na_b3.sum()))
    return df, avisos
