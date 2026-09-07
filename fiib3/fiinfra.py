"""FI-Infra: a lista de códigos, e a máquina que confere a lista.

Por que existe uma lista aqui e não no resto do projeto
-------------------------------------------------------
Todo o restante do `fiib3` deriva o código de negociação do ISIN publicado pela
CVM: `BRMXRFCTF008` -> `MXRF11`. Isso funciona para FII e para Fiagro porque o
informe mensal desses dois traz o ISIN.

O FI-Infra não tem informe mensal. Aos olhos da CVM ele é um fundo de
investimento comum — o que existe dele é o **informe diário** (cota, patrimônio
e cotistas), e o informe diário não traz ISIN. Procurei o vínculo nos três
arquivos do cadastro novo (`registro_fundo_classe.zip`, 136 mil linhas): a
única coluna parecida é `Codigo_CVM`, que é o número de registro na autarquia,
não o código da B3. Não há ISIN nem código de negociação em lugar nenhum do
dado aberto.

Então ou o FI-Infra fica de fora, ou entra por uma lista. Lista mantida à mão é
exatamente o tipo de coisa que a auditoria do TCC criticou — número escrito no
código que ninguém revalida e que envelhece em silêncio. A saída é fazer a
lista ser **conferida por máquina a cada execução**:

    1. o CNPJ tem que existir no cadastro da CVM;
    2. tem que estar "EM FUNCIONAMENTO NORMAL";
    3. a razão social gravada tem que continuar batendo com a da CVM.

Falhou qualquer um dos três, o fundo sai do universo e o motivo aparece no log e
na aba de excluídos. O erro possível vira dado faltando, nunca dado errado.

O CNPJ de cada código é descoberto pela máquina, não digitado: `resolver()` lê o
nome longo do fundo no Yahoo, normaliza e casa contra a razão social do cadastro
da CVM, exigindo semelhança alta e vantagem clara sobre o segundo colocado.
Depois de resolvido, o CNPJ fica gravado no CSV e as execuções seguintes só
conferem — sem depender do Yahoo para nada além de preço.
"""
from __future__ import annotations

import csv
import logging
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from . import config as C
from . import cvm_fii

log = logging.getLogger(__name__)

LISTA = Path(__file__).parent / "fiinfra.csv"
COLUNAS = ("TICKER", "CNPJ", "NOME_CVM", "CONFERIDO_EM")

# Semelhança mínima entre o nome do Yahoo e a razão social da CVM, e vantagem
# mínima sobre o segundo colocado. Os dois juntos: sem o primeiro, "SPARTA" casa
# com qualquer fundo da casa; sem o segundo, um fundo e sua classe de cotas
# (nomes quase idênticos) seriam escolhidos por sorteio.
SEMELHANCA_MINIMA = 0.80
VANTAGEM_MINIMA = 0.06

# Ruído comum nas duas pontas. Tirar antes de comparar é o que faz
# "SPARTA INFRA FIC FI INFRAESTRUTURA RESPONSABILIDADE LIMITADA" casar com
# "SPARTA INFRA FUNDO INCENTIVADO DE INVESTIMENTO EM INFRAESTRUTURA".
RUIDO = (
    "FUNDO DE INVESTIMENTO EM COTAS DE FUNDOS DE INVESTIMENTO",
    "FUNDO INCENTIVADO DE INVESTIMENTO EM INFRAESTRUTURA",
    "FUNDO DE INVESTIMENTO EM INFRAESTRUTURA",
    "FUNDO DE INVESTIMENTO",
    "RESPONSABILIDADE LIMITADA",
    "RENDA FIXA CREDITO PRIVADO",
    "CREDITO PRIVADO",
    "INFRAESTRUTURA",
    "MULTIMERCADO",
    "RENDA FIXA",
    "INCENTIVADO",
    "FICFI", "FIC", "FIM", "FIRF", "FI", "LP", "RL",
)


# ---------------------------------------------------------------------------
# A lista
# ---------------------------------------------------------------------------
def ler_lista(caminho: Path | str | None = None) -> pd.DataFrame:
    """Lê `fiinfra.csv`. Comentários (`#`) e linhas em branco são ignorados."""
    caminho = Path(caminho or LISTA)
    if not caminho.exists():
        return pd.DataFrame(columns=list(COLUNAS), dtype="string")
    linhas = [l for l in caminho.read_text(encoding="utf-8").splitlines()
              if l.strip() and not l.lstrip().startswith("#")]
    if not linhas:
        return pd.DataFrame(columns=list(COLUNAS), dtype="string")
    dados = list(csv.DictReader(linhas, delimiter=";"))
    df = pd.DataFrame(dados, dtype="string")
    for c in COLUNAS:
        if c not in df.columns:
            df[c] = pd.NA
    df["TICKER"] = df["TICKER"].str.strip().str.upper()
    df["CNPJ"] = (df["CNPJ"].fillna("").str.replace(r"\D", "", regex=True)
                  .replace("", pd.NA))
    df.loc[df["CNPJ"].notna(), "CNPJ"] = df["CNPJ"].dropna().str.zfill(14)
    return df[df["TICKER"].str.fullmatch(r"[A-Z]{4}\d{1,2}", na=False)][
        list(COLUNAS)].reset_index(drop=True)


def gravar_lista(df: pd.DataFrame, caminho: Path | str | None = None) -> None:
    """Regrava o CSV preservando o cabeçalho explicativo do arquivo original."""
    caminho = Path(caminho or LISTA)
    cabecalho = []
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if linha.lstrip().startswith("#"):
                cabecalho.append(linha)
            elif linha.strip():
                break
    corpo = [";".join(COLUNAS)]
    for r in df.sort_values("TICKER").itertuples():
        corpo.append(";".join(_vazio_se_nulo(getattr(r, c)) for c in COLUNAS))
    caminho.write_text("\n".join(cabecalho + corpo) + "\n", encoding="utf-8")


def _vazio_se_nulo(v) -> str:
    return "" if v is None or pd.isna(v) else str(v).strip()


# ---------------------------------------------------------------------------
# Casar código de negociação com CNPJ
# ---------------------------------------------------------------------------
def _normalizar(nome) -> str:
    if nome is None or pd.isna(nome):
        return ""
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9 ]", " ", s).upper()
    for termo in RUIDO:
        s = re.sub(rf"\b{re.escape(termo)}\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def nome_no_yahoo(ticker: str) -> str | None:
    """Nome longo do fundo, como o Yahoo publica. `None` se ele não souber."""
    try:
        import yfinance as yf
        info = yf.Ticker(f"{ticker}.SA").get_info() or {}
    except Exception as exc:                                    # noqa: BLE001
        log.warning("Yahoo não devolveu o cadastro de %s (%s).",
                    ticker, str(exc)[:70])
        return None
    for campo in ("longName", "shortName", "displayName"):
        valor = info.get(campo)
        if valor and str(valor).strip():
            return str(valor).strip()
    return None


def casar(nome: str, registro: pd.DataFrame) -> tuple[str | None, float, str]:
    """(CNPJ, semelhança, razão social) do fundo do cadastro que casa com `nome`.

    Devolve CNPJ `None` quando nenhum candidato passa nos dois cortes — é o
    resultado que interessa quando o dado está ambíguo: melhor não publicar.
    """
    alvo = _normalizar(nome)
    if not alvo or registro.empty:
        return None, 0.0, ""
    chaves = registro["NOME"].map(_normalizar)
    notas = chaves.map(lambda c: SequenceMatcher(None, alvo, c).ratio() if c else 0.0)
    ordem = notas.sort_values(ascending=False)
    melhor = ordem.index[0]
    nota = float(ordem.iloc[0])
    segunda = float(ordem.iloc[1]) if len(ordem) > 1 else 0.0
    if nota < SEMELHANCA_MINIMA or (nota - segunda) < VANTAGEM_MINIMA:
        return None, nota, str(registro.loc[melhor, "NOME"] or "")
    return (str(registro.loc[melhor, "CNPJ"]), nota,
            str(registro.loc[melhor, "NOME"] or ""))


def resolver(lista: pd.DataFrame, registro: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Descobre o CNPJ dos códigos que ainda não têm um. Precisa do Yahoo."""
    lista = lista.copy()
    avisos: list[str] = []
    pendentes = lista.index[lista["CNPJ"].isna()]
    if not len(pendentes):
        return lista, avisos

    hoje = pd.Timestamp.today().strftime("%Y-%m-%d")
    for i in pendentes:
        ticker = lista.at[i, "TICKER"]
        nome = nome_no_yahoo(ticker)
        if not nome:
            avisos.append(f"{ticker}: o Yahoo não tem o nome do fundo; "
                          f"não dá para descobrir o CNPJ sozinho.")
            continue
        cnpj, nota, candidato = casar(nome, registro)
        if cnpj is None:
            avisos.append(
                f"{ticker} ({nome}): nenhum fundo do cadastro da CVM casa com "
                f"segurança — o mais parecido foi \"{candidato}\" "
                f"({nota:.0%}). Preencha o CNPJ à mão em fiinfra.csv se "
                f"você conferir que é esse.")
            continue
        lista.at[i, "CNPJ"] = cnpj
        lista.at[i, "NOME_CVM"] = candidato
        lista.at[i, "CONFERIDO_EM"] = hoje
        log.info("FI-Infra %s -> %s (%s, semelhança %.0f%%).",
                 ticker, cnpj, candidato, nota * 100)
    return lista, avisos


# ---------------------------------------------------------------------------
# Conferência
# ---------------------------------------------------------------------------
def conferir(lista: pd.DataFrame, registro: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Deixa passar só as linhas que ainda batem com o cadastro da CVM."""
    if lista.empty:
        return lista, []
    reg = registro.drop_duplicates(subset=["CNPJ"]).set_index("CNPJ")
    boas, avisos = [], []
    hoje = pd.Timestamp.today().strftime("%Y-%m-%d")

    for r in lista.itertuples():
        ticker, cnpj = r.TICKER, r.CNPJ
        if cnpj is None or pd.isna(cnpj):
            avisos.append(f"{ticker}: sem CNPJ na lista — ficou de fora.")
            continue
        if cnpj not in reg.index:
            avisos.append(f"{ticker}: o CNPJ {_formatar(cnpj)} não está no "
                          f"cadastro da CVM — ficou de fora.")
            continue
        linha = reg.loc[cnpj]
        situacao = str(linha.get("SITUACAO") or "").strip().upper()
        if situacao != C.SITUACAO_ATIVA:
            avisos.append(f"{ticker}: situação na CVM é \"{situacao or 'vazia'}\", "
                          f"não \"{C.SITUACAO_ATIVA}\" — ficou de fora.")
            continue
        gravado = _normalizar(r.NOME_CVM)
        atual = _normalizar(linha.get("NOME"))
        if gravado and atual and gravado != atual:
            avisos.append(
                f"{ticker}: a razão social mudou no cadastro da CVM "
                f"(\"{r.NOME_CVM}\" -> \"{linha.get('NOME')}\") — ficou de fora "
                f"até alguém conferir se ainda é o mesmo fundo.")
            continue
        boas.append({"TICKER": ticker, "CNPJ": cnpj,
                     "NOME": linha.get("NOME"),
                     "SITUACAO": linha.get("SITUACAO"),
                     "DT_FUNCIONAMENTO": linha.get("DT_FUNCIONAMENTO"),
                     "CONFERIDO_EM": hoje})

    return pd.DataFrame(boas, columns=["TICKER", "CNPJ", "NOME", "SITUACAO",
                                       "DT_FUNCIONAMENTO", "CONFERIDO_EM"]), avisos


def _formatar(cnpj: str) -> str:
    s = str(cnpj).zfill(14)
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------
def coletar(*, usar_cache: bool = True, resolver_pendentes: bool = True,
            caminho: Path | str | None = None,
            competencias: int = 2) -> tuple[pd.DataFrame, list[str]]:
    """Informe dos FI-Infra da lista, no mesmo formato de `cvm_fii.ler_informe`.

    Devolve `(informe, avisos)`. A lista vazia devolve tabela vazia sem erro —
    o projeto tem que continuar rodando enquanto ninguém escolheu nenhum fundo.

    Duas competências bastam: o informe diário sai no dia seguinte ao pregão, e
    o arquivo do mês anterior sempre existe. Cada competência é um zip de
    dezenas de MB, então cada uma a mais custa minutos na primeira execução.
    """
    caminho = Path(caminho or LISTA)
    lista = ler_lista(caminho)
    if lista.empty:
        log.info("Nenhum FI-Infra na lista (%s).", caminho.name)
        return pd.DataFrame(), []

    registro = cvm_fii.baixar_registro_classes(usar_cache=usar_cache)
    avisos: list[str] = []
    if resolver_pendentes and lista["CNPJ"].isna().any():
        lista, novos = resolver(lista, registro)
        avisos += novos
        gravar_lista(lista, caminho)

    conferidos, problemas = conferir(lista, registro)
    avisos += problemas
    if conferidos.empty:
        log.warning("Nenhum FI-Infra passou na conferência.")
        return pd.DataFrame(), avisos

    diario = cvm_fii.ler_informe_diario(conferidos["CNPJ"],
                                        competencias=competencias,
                                        usar_cache=usar_cache)
    out = conferidos.merge(diario, on="CNPJ", how="left")
    sem_dado = out["PL"].isna() if "PL" in out.columns else pd.Series(True, index=out.index)
    for ticker in out.loc[sem_dado.fillna(True), "TICKER"]:
        avisos.append(f"{ticker}: não apareceu no informe diário da CVM nas "
                      f"últimas {competencias} competências.")
    out = out[~sem_dado.fillna(True)].copy()
    if out.empty:
        return pd.DataFrame(), avisos

    # O nº de cotas não vem no informe diário; sai da divisão, que é exata
    # porque a própria CVM calcula a cota como patrimônio dividido por cotas.
    out["COTAS"] = out["PL"] / out["VP_COTA"].where(out["VP_COTA"] > 0)
    out["TIPO_FUNDO"] = C.TIPO_FIINFRA
    out["SEGMENTO"] = C.SEGMENTO_FIINFRA
    out["NEGOCIA_BOLSA"] = "S"        # é o que define a lista: fundo listado
    out["MERCADO"] = "BOLSA"
    for coluna in ("ISIN", "MANDATO", "GESTAO", "ADMINISTRADOR", "PUBLICO_ALVO",
                   "EXCLUSIVO", "TIPO_CLASSE", "DT_ENTREGA", "ATIVO_TOTAL",
                   "RENT_EFETIVA_MES", "DY_MES_CVM", "PCT_IMOVEIS", "PCT_PAPEL",
                   "PCT_FOF", "TOTAL_INVESTIDO", "CAIXA", "PASSIVO"):
        out[coluna] = pd.NA
    log.info("FI-Infra: %d fundos conferidos, competência %s.",
             len(out), out["COMPETENCIA"].max())
    return out.reset_index(drop=True), avisos
