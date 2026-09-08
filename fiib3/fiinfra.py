"""FI-Infra: da lista da B3 até patrimônio e cota, com conferência a cada passo.

O problema, em uma frase
------------------------
O FI-Infra é o único veículo do projeto cujo código de negociação não sai do
dado da CVM. FII e Fiagro publicam ISIN no informe mensal, e do ISIN sai o
código (`BRMXRFCTF008` → `MXRF11`). O FI-Infra não tem informe mensal: aos
olhos da CVM ele é um fundo de investimento comum, e o que existe dele é o
informe diário, que não traz ISIN. O cadastro novo também não — procurei nos
três CSVs do `registro_fundo_classe.zip`, 136 mil linhas, e a única coluna
parecida é `Codigo_CVM`, que é o número de registro na autarquia.

A ponte que faltava
-------------------
A B3 publica a lista dos fundos de infraestrutura listados, com razão social e
código de negociação (`fiib3/b3/fiinfra.csv`). Ela diz *quem negocia e com que
código*; falta o CNPJ, que é a chave do informe diário. O CNPJ vem de casar a
razão social da B3 com a do cadastro da CVM — ver `fiib3/casamento.py`, que
explica por que isso é comparação de palavras pesadas por raridade e não
semelhança de texto.

Medido contra os arquivos reais: dos 41 fundos listados, 28 casam sozinhos e
nenhum dos 28 está errado. Os outros 13 são casos em que dois fundos do mesmo
gestor têm nomes que só diferem por uma palavra — o fundo e o FIC que investe
nele, por exemplo. Aí a máquina não escolhe: escreve os cinco candidatos com
CNPJ em `fiinfra_pendentes.txt` e espera alguém confirmar.

O que impede a lista de envelhecer em silêncio
----------------------------------------------
Lista mantida à mão é o que a auditoria deste projeto critica. Esta não é
mantida à mão — é sincronizada com a B3 e reconferida a cada execução:

    1. o código tem que continuar na lista da B3 (senão saiu de negociação);
    2. o CNPJ tem que existir no cadastro da CVM;
    3. tem que estar "Em Funcionamento Normal";
    4. a razão social da CVM tem que continuar a mesma;
    5. o fundo tem que aparecer no informe diário recente.

Falhou qualquer uma, o fundo sai do universo com o motivo registrado. O erro
possível é "faltou um fundo", nunca "publicou o fundo errado".
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

import pandas as pd

from . import b3_listados, casamento, config as C, cvm_fii

log = logging.getLogger(__name__)

LISTA = Path(__file__).parent / "fiinfra.csv"
EXPORT_B3 = b3_listados.EXPORT_FIINFRA
# Diagnóstico, não dado: fica na raiz para ser aberto e lido, e o .gitignore
# cuida para não virar arquivo versionado.
RELATORIO = Path(__file__).parent.parent / "fiinfra_pendentes.txt"

COLUNAS = ("TICKER", "RAZAO_B3", "CNPJ", "NOME_CVM", "CONFERIDO_EM")


# ---------------------------------------------------------------------------
# A lista resolvida
# ---------------------------------------------------------------------------
def ler_lista(caminho: Path | str | None = None) -> pd.DataFrame:
    """Lê `fiinfra.csv`. Comentários (`#`) e linhas em branco são ignorados."""
    caminho = Path(caminho or LISTA)
    vazia = pd.DataFrame(columns=list(COLUNAS), dtype="string")
    if not caminho.exists():
        return vazia
    linhas = [l for l in caminho.read_text(encoding="utf-8").splitlines()
              if l.strip() and not l.lstrip().startswith("#")]
    if len(linhas) < 2:
        return vazia
    df = pd.DataFrame(list(csv.DictReader(linhas, delimiter=";")), dtype="string")
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
    """Regrava o CSV preservando o cabeçalho explicativo do arquivo."""
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


def sincronizar(lista: pd.DataFrame,
                export: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Alinha a lista resolvida com a lista da B3, sem perder o já conferido.

    Três casos, e cada um com uma decisão explícita:

    - código novo na B3 → entra sem CNPJ, para ser resolvido;
    - código que sumiu da B3 → sai, porque deixou de negociar;
    - razão social mudou na B3 → o CNPJ conferido é **apagado**. Pode ser só
      reescrita do nome, mas pode ser incorporação ou troca de gestor, e manter
      o CNPJ antigo publicaria o patrimônio de um fundo sob o código de outro.
      Resolver de novo custa uma execução; errar aí não aparece na tela.
    """
    avisos: list[str] = []
    if export.empty:
        return lista, ["A lista da B3 está vazia; mantive a lista atual."]

    antes = {r.TICKER: r for r in lista.itertuples()} if not lista.empty else {}
    linhas, novos, mudados = [], [], []
    for r in export.itertuples():
        velho = antes.get(r.TICKER)
        item = {"TICKER": r.TICKER, "RAZAO_B3": r.RAZAO,
                "CNPJ": pd.NA, "NOME_CVM": pd.NA, "CONFERIDO_EM": pd.NA}
        if velho is None:
            novos.append(r.TICKER)
        elif casamento.normalizar(velho.RAZAO_B3) != casamento.normalizar(r.RAZAO):
            mudados.append(r.TICKER)
        else:
            item.update({"CNPJ": velho.CNPJ, "NOME_CVM": velho.NOME_CVM,
                         "CONFERIDO_EM": velho.CONFERIDO_EM})
        linhas.append(item)

    saiu = sorted(set(antes) - set(export["TICKER"]))
    if novos:
        avisos.append(f"{len(novos)} código(s) novos na B3: {', '.join(novos)}.")
    if mudados:
        avisos.append(f"{len(mudados)} tiveram a razão social alterada na B3 e "
                      f"precisam ser resolvidos de novo: {', '.join(mudados)}.")
    if saiu:
        avisos.append(f"{len(saiu)} saíram da lista da B3 e do universo: "
                      f"{', '.join(saiu)}.")
    return pd.DataFrame(linhas, columns=list(COLUNAS), dtype="string"), avisos


# ---------------------------------------------------------------------------
# Resolver o CNPJ
# ---------------------------------------------------------------------------
def resolver(lista: pd.DataFrame,
             registro: pd.DataFrame) -> tuple[pd.DataFrame, list[str], str]:
    """Descobre o CNPJ dos códigos que ainda não têm um.

    Devolve `(lista, avisos, relatorio)`. O relatório é o que salva o dia quando
    a máquina se recusa a escolher: traz os cinco fundos mais parecidos com CNPJ,
    razão social e situação, prontos para colar. Recusar sem mostrar o que se viu
    transferiria para a pessoa um garimpo em oitenta mil linhas de cadastro.
    """
    lista = lista.copy()
    avisos: list[str] = []
    blocos: list[str] = []
    pendentes = lista.index[lista["CNPJ"].isna()]
    if not len(pendentes):
        return lista, avisos, ""

    casador = casamento.Casador(registro)
    hoje = pd.Timestamp.today().strftime("%Y-%m-%d")
    for i in pendentes:
        ticker, razao = lista.at[i, "TICKER"], lista.at[i, "RAZAO_B3"]
        cnpj, nota, candidato = casador.casar(razao)
        if cnpj is None:
            avisos.append(
                f"{ticker}: nenhum fundo do cadastro da CVM casou com segurança "
                f"(melhor: {nota:.0%}). Os candidatos estão em {RELATORIO.name}.")
            blocos.append(_bloco_candidatos(casador, ticker, razao))
            continue
        lista.at[i, "CNPJ"] = cnpj
        lista.at[i, "NOME_CVM"] = candidato
        lista.at[i, "CONFERIDO_EM"] = hoje
        log.info("FI-Infra %s -> %s (%s, cobertura %.0f%%).",
                 ticker, cnpj, candidato, nota * 100)
    return lista, avisos, "\n".join(blocos)


def _bloco_candidatos(casador: casamento.Casador, ticker: str, razao: str) -> str:
    linhas = [f"{ticker}",
              f"  razão social na B3: {razao}",
              f"  candidatos no cadastro da CVM — confira e cole o CNPJ certo na "
              f"coluna CNPJ de {LISTA.name}:"]
    for r in casador.candidatos(razao).itertuples():
        situacao = str(getattr(r, "SITUACAO", "") or "")
        linhas.append(f"    {r.NOTA:.0%}  {_formatar(r.CNPJ)}  {r.NOME}"
                      + (f"  [{situacao}]" if situacao else ""))
    return "\n".join(linhas) + "\n"


def _formatar(cnpj: str) -> str:
    s = str(cnpj).zfill(14)
    return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"


# ---------------------------------------------------------------------------
# Conferência
# ---------------------------------------------------------------------------
def conferir(lista: pd.DataFrame,
             registro: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Deixa passar só as linhas que ainda batem com o cadastro da CVM."""
    colunas = ["TICKER", "CNPJ", "NOME", "SITUACAO", "DT_FUNCIONAMENTO"]
    if lista.empty:
        return pd.DataFrame(columns=colunas), []
    reg = registro.drop_duplicates(subset=["CNPJ"]).set_index("CNPJ")
    boas, avisos = [], []

    for r in lista.itertuples():
        ticker, cnpj = r.TICKER, r.CNPJ
        if cnpj is None or pd.isna(cnpj):
            avisos.append(f"{ticker}: ainda sem CNPJ — ficou de fora.")
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
        gravado = casamento.normalizar(r.NOME_CVM)
        atual = casamento.normalizar(linha.get("NOME"))
        if gravado and atual and gravado != atual:
            avisos.append(
                f"{ticker}: a razão social mudou no cadastro da CVM "
                f"(\"{r.NOME_CVM}\" -> \"{linha.get('NOME')}\") — ficou de fora "
                f"até alguém conferir se ainda é o mesmo fundo.")
            continue
        boas.append({"TICKER": ticker, "CNPJ": cnpj, "NOME": linha.get("NOME"),
                     "SITUACAO": linha.get("SITUACAO"),
                     "DT_FUNCIONAMENTO": linha.get("DT_FUNCIONAMENTO")})

    return pd.DataFrame(boas, columns=colunas), avisos


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------
def coletar(*, usar_cache: bool = True, resolver_pendentes: bool = True,
            caminho: Path | str | None = None,
            export: Path | str | None = None,
            competencias: int = 2) -> tuple[pd.DataFrame, list[str]]:
    """Informe dos FI-Infra listados, no formato de `cvm_fii.ler_informe`.

    Devolve `(informe, avisos)`. Lista vazia devolve tabela vazia sem erro — o
    projeto tem que continuar rodando mesmo que a lista da B3 não esteja lá.

    Duas competências do informe diário bastam: ele sai no dia seguinte ao
    pregão, e o arquivo do mês anterior sempre existe. Cada competência a mais é
    um zip de dezenas de MB.
    """
    caminho = Path(caminho or LISTA)
    avisos: list[str] = []

    lista, alertas = sincronizar(ler_lista(caminho),
                                 b3_listados.ler_export(export or EXPORT_B3))
    avisos += alertas
    if lista.empty:
        log.info("Nenhum FI-Infra na lista.")
        gravar_lista(lista, caminho)
        return pd.DataFrame(), avisos

    registro = cvm_fii.baixar_registro_classes(usar_cache=usar_cache)
    # Só fundos ativos entram como candidatos: casar contra os 44 mil cancelados
    # só cria empate com fundos que não existem mais.
    ativos = registro[registro["SITUACAO"].str.upper().str.strip().eq(
        C.SITUACAO_ATIVA).fillna(False)].reset_index(drop=True)

    if resolver_pendentes and lista["CNPJ"].isna().any():
        lista, novos, relatorio = resolver(lista, ativos)
        avisos += novos
        _gravar_relatorio(relatorio)
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
    sem_dado = (out["PL"].isna() if "PL" in out.columns
                else pd.Series(True, index=out.index)).fillna(True)
    for ticker in out.loc[sem_dado, "TICKER"]:
        avisos.append(f"{ticker}: não apareceu no informe diário da CVM nas "
                      f"últimas {competencias} competências.")
    out = out[~sem_dado].copy()
    if out.empty:
        return pd.DataFrame(), avisos

    # O nº de cotas não vem no informe diário; sai da divisão, que é exata
    # porque a própria CVM calcula a cota como patrimônio dividido por cotas.
    out["COTAS"] = out["PL"] / out["VP_COTA"].where(out["VP_COTA"] > 0)
    out["TIPO_FUNDO"] = C.TIPO_FIINFRA
    out["SEGMENTO"] = C.SEGMENTO_FIINFRA
    out["NEGOCIA_BOLSA"] = "S"        # é o que define a lista: fundo listado
    out["MERCADO"] = "BOLSA"
    out["ORIGEM_TICKER"] = "b3"
    for coluna in ("ISIN", "MANDATO", "GESTAO", "ADMINISTRADOR", "PUBLICO_ALVO",
                   "EXCLUSIVO", "TIPO_CLASSE", "DT_ENTREGA", "ATIVO_TOTAL",
                   "RENT_EFETIVA_MES", "DY_MES_CVM", "PCT_IMOVEIS", "PCT_PAPEL",
                   "PCT_FOF", "TOTAL_INVESTIDO", "CAIXA", "PASSIVO"):
        out[coluna] = pd.NA
    log.info("FI-Infra: %d fundos conferidos, competência %s.",
             len(out), out["COMPETENCIA"].max())
    return out.reset_index(drop=True), avisos


def _gravar_relatorio(relatorio: str) -> None:
    if relatorio:
        RELATORIO.write_text(
            "Códigos de FI-Infra que a máquina não conseguiu casar sozinha.\n"
            f"Confira e cole o CNPJ na coluna CNPJ de fiib3/{LISTA.name}.\n"
            f"Gerado em {pd.Timestamp.now():%Y-%m-%d %H:%M}.\n\n" + relatorio,
            encoding="utf-8")
    elif RELATORIO.exists():
        RELATORIO.write_text("Nenhum código pendente.\n", encoding="utf-8")
