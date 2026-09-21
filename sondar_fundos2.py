# -*- coding: utf-8 -*-
"""Sonda as fontes da CVM para a aba de fundos fechados.

PRECISA RODAR NUM COMPUTADOR NO BRASIL — `dados.cvm.gov.br` recusa conexões do
exterior, mesma restrição de `baixar_informe_fii.py`.

O que a primeira sondagem respondeu
-----------------------------------
`Prazo_Duracao` **existe no informe de FII e vem preenchida**: 7.446 linhas
"Indeterminado" contra 1.554 "Determinado", nenhuma vazia. O `"0 ANO/ANOS"` que
assustou na amostra era coisa do informe de Fiagro, com nove fundos obscuros.
O LCP Prefixado, feeder e master, aparece como **Determinado**.

Junto dela veio uma coluna que ninguém tinha procurado: **`Data_Prazo_Duracao`**
— a data de vencimento do fundo. E, no mesmo arquivo,
`Entidade_Administradora_CETIP`, que é literalmente o marcador de cetipado.

O que esta versão corrige
-------------------------
A primeira rodada errou três coisas, todas visíveis na saída:

1. **Pegou a coluna errada de cotistas.** `Cotistas_Vinculo_Familiar` e
   `Data_Informacao_Numero_Cotistas` casaram antes de `Total_Numero_Cotistas`,
   porque o padrão "cotistas" era genérico demais. Todo filtro por número de
   cotistas saiu zerado por causa disso.
2. **Contou bolsa e balcão como texto.** `Mercado_Negociacao_Bolsa` responde
   `S`/`N`, não "BOLSA"/"BALCAO" — procurar a palavra devolvia zero para os dois.
3. **Não juntou as tabelas.** Prazo e público-alvo estão no `geral`; cotistas,
   patrimônio, rentabilidade e amortização estão no `complemento`. Medir o
   universo exige as duas na mesma linha, e cada tabela tem 6 ou 7 competências
   por fundo — sem reduzir à mais recente, um fundo conta sete vezes.

O que ainda falta saber
-----------------------
- **`Data_Prazo_Duracao` vem preenchida nos fundos de prazo determinado?** Nas
  300 linhas da amostra local só havia "Indeterminado", então ela apareceu 100%
  vazia sem que isso queira dizer nada. É a pergunta que decide se a tela mostra
  "vence em 03/2030" ou só "prazo determinado".
- **O que o FIP publica.** Informe trimestral, dataset separado, nunca lido por
  este projeto. Numa tela do secundário da XP com quatorze fundos, oito eram FIP.

Uso:
    python sondar_fundos.py
    python sondar_fundos.py --ano 2026 --comp 202608
    python sondar_fundos.py --sem-cache
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd

from fiib3 import cvm_fii

RAIZ = Path(__file__).parent
SAIDA = RAIZ / "amostra_fontes" / "fundos"

BASE = "https://dados.cvm.gov.br/dados"
DIR_FIP = f"{BASE}/FIP/DOC/INF_TRIMESTRAL/DADOS/"
DIR_FIP_CAD = f"{BASE}/FIP/CAD/DADOS/"

# Os padrões são testados em ordem e o primeiro que casa vence, então o mais
# específico vem primeiro. Foi a falta disso que fez "cotistas" casar com
# `Cotistas_Vinculo_Familiar` na primeira rodada.
ALVOS = {
    "cnpj":        ("cnpj_fundo_classe", "cnpj_classe", "cnpj_fundo", "cnpj"),
    "nome":        ("nome_fundo_classe", "nome_classe", "denominacao_social"),
    "data_ref":    ("data_referencia", "data_competencia"),
    "versao":      ("versao",),
    "prazo":       ("prazo_duracao",),
    "data_prazo":  ("data_prazo_duracao",),
    "inicio":      ("data_funcionamento", "data_inicio_atividade", "data_registro"),
    "publico":     ("publico_alvo",),
    "exclusivo":   ("fundo_exclusivo", "exclusivo"),
    "bolsa":       ("mercado_negociacao_bolsa",),
    "mbo":         ("mercado_negociacao_mbo",),
    "cetip":       ("entidade_administradora_cetip",),
    "mercado":     ("mercado_negociacao",),
    "cotistas":    ("total_numero_cotistas", "numero_cotistas"),
    "cotistas_pf": ("numero_cotistas_pessoa_fisica", "numero_cotistas_pessoa_natural"),
    "pl":          ("patrimonio_liquido",),
    "vp_cota":     ("valor_patrimonial_cotas", "valor_patrimonial_cota", "valor_cota"),
    "cotas":       ("cotas_emitidas", "quantidade_cotas_emitidas"),
    "rentab":      ("percentual_rentabilidade_efetiva_mes", "rentabilidade_efetiva_mes"),
    "dy":          ("percentual_dividend_yield_mes", "dividend_yield_mes"),
    "amortizacao": ("percentual_amortizacao_cotas_mes",),
    "taxa_adm":    ("percentual_despesas_taxa_administracao", "taxa_administracao"),
}

# Fundos conferidos no informe_fii.json de 07/2026.
REFERENCIAS = {
    "40265671000107": "KIJANI ASATALA FIAGRO",
    "44625562000104": "TG REAL ESTATE FII (TGRE11)",
    "43741205000130": "JGP CREDITO AGRO FIAGRO",
    "59987139000113": "RIZA VISEU FII",
    "61922643000187": "LCP PREFIXADO FEEDER FII",
    "61918522000161": "LCP PREFIXADO MASTER FII",
    "63608356000122": "XP AGRO RENDA FEEDER FIAGRO",
}
PISTAS_FIP = ("NEWAVE", "JIVE", "KINEA PE", "XP INFRA", "XP SPECIAL",
              "XP PRIVATE EQUITY", "SPX PRIVATE", "XP SELECTION")

MAX_LINHAS_AMOSTRA = 400


# ---------------------------------------------------------------------------
def localizar(df: pd.DataFrame) -> dict[str, str | None]:
    return {rotulo: cvm_fii.coluna(df, *padroes, obrigatoria=False)
            for rotulo, padroes in ALVOS.items()}


def col(df: pd.DataFrame, achadas: dict, rotulo: str) -> pd.Series | None:
    c = achadas.get(rotulo)
    return df[c] if c and c in df.columns else None


def texto(df: pd.DataFrame, achadas: dict, rotulo: str) -> pd.Series | None:
    s = col(df, achadas, rotulo)
    return None if s is None else s.fillna("").astype("string").str.strip().str.upper()


def numero(df: pd.DataFrame, achadas: dict, rotulo: str) -> pd.Series | None:
    s = col(df, achadas, rotulo)
    return None if s is None else cvm_fii._numero(s)


def ultimo_por_fundo(df: pd.DataFrame, achadas: dict) -> pd.DataFrame:
    """Uma linha por CNPJ: competência mais recente, maior versão.

    Sem isto o mesmo fundo conta seis ou sete vezes — o zip anual traz uma
    competência por mês — e todo número do universo sai inflado.
    """
    if not (achadas.get("cnpj") and achadas.get("data_ref")):
        return df
    return cvm_fii._ultimo_por_fundo(df, achadas["cnpj"], achadas["data_ref"],
                                     achadas.get("versao"))


# ---------------------------------------------------------------------------
def perfilar(df: pd.DataFrame) -> dict:
    n = len(df)
    campos = {}
    for c in df.columns:
        serie = df[c]
        try:
            cheia = serie.fillna("").astype("string").str.strip().ne("")
        except (AttributeError, TypeError):
            cheia = serie.notna()
        item = {"pct": round(100 * int(cheia.sum()) / max(n, 1), 1)}
        distintos = serie.dropna().nunique()
        if distintos and distintos <= 20:
            item["valores"] = {str(k): int(v)
                               for k, v in Counter(serie.dropna()).most_common(8)}
        else:
            item["exemplos"] = [str(v) for v in serie.dropna().head(2)]
        campos[c] = item
    return {"linhas": n, "colunas": list(df.columns), "campos": campos}


# ---------------------------------------------------------------------------
def analisar_fii(geral: pd.DataFrame, compl: pd.DataFrame) -> dict:
    """O informe de FII com `geral` e `complemento` na mesma linha."""
    ag, ac = localizar(geral), localizar(compl)
    g = ultimo_por_fundo(geral, ag)
    c = ultimo_por_fundo(compl, ac)
    print(f"  geral: {len(geral):,} linhas -> {len(g):,} fundos")
    print(f"  complemento: {len(compl):,} linhas -> {len(c):,} fundos")

    g = g.copy()
    g["_cnpj"] = cvm_fii._cnpj_limpo(g[ag["cnpj"]])
    c = c.copy()
    c["_cnpj"] = cvm_fii._cnpj_limpo(c[ac["cnpj"]])
    reduzido = c[["_cnpj"] + [v for k, v in ac.items()
                              if v and k in ("cotistas", "cotistas_pf", "pl",
                                             "vp_cota", "cotas", "rentab", "dy",
                                             "amortizacao", "taxa_adm")]]
    d = g.merge(reduzido, on="_cnpj", how="left", suffixes=("", "_c"))
    # O mapa final prefere o `geral` e completa com o `complemento`: prazo e
    # público vêm de um, cotistas e patrimônio do outro.
    achadas = dict(ag)
    for k, v in ac.items():
        if v and not achadas.get(k):
            achadas[k] = v
    print(f"  juntos: {len(d):,} fundos")

    out: dict = {"fundos": len(d)}

    # ---- prazo, que é o campo que define o universo ----------------------
    prazo = texto(d, achadas, "prazo")
    data_prazo = col(d, achadas, "data_prazo")
    if prazo is not None:
        contagem = {str(k): int(v) for k, v in Counter(prazo).most_common(6)}
        out["prazo_duracao"] = contagem
        print("\n  PRAZO DE DURACAO (por fundo):")
        for k, v in contagem.items():
            print(f"    {v:6,}x  {k or '(vazio)'}")
        det = prazo.eq("DETERMINADO")
        if data_prazo is not None:
            dp = data_prazo.fillna("").astype("string").str.strip()
            com_data = int((det & dp.ne("")).sum())
            out["determinado_com_data"] = com_data
            out["determinado_total"] = int(det.sum())
            pct = 100 * com_data / max(int(det.sum()), 1)
            print(f"\n  DATA DE VENCIMENTO: {com_data:,} dos {int(det.sum()):,} "
                  f"de prazo determinado ({pct:.0f}%)")
            anos = Counter(x[:4] for x in dp[det & dp.ne("")])
            out["vencimentos_por_ano"] = {k: int(v) for k, v in sorted(anos.items())}
            print("    " + ", ".join(f"{k}: {v}" for k, v in sorted(anos.items())))
        else:
            print("\n  DATA DE VENCIMENTO: coluna nao existe")

    # ---- onde negocia ----------------------------------------------------
    for rotulo, legenda in (("bolsa", "negociam em bolsa"),
                            ("cetip", "administrados na CETIP"),
                            ("mbo", "mercado de balcao organizado")):
        s = texto(d, achadas, rotulo)
        if s is not None:
            n = int(s.eq("S").sum())
            out[rotulo] = n
            print(f"  {legenda:32s}: {n:,}")

    # ---- o universo ------------------------------------------------------
    publico = texto(d, achadas, "publico")
    exclusivo = texto(d, achadas, "exclusivo")
    cotistas = numero(d, achadas, "cotistas")
    print("\n  UNIVERSO:")
    passos: dict[str, int] = {"total": len(d)}
    alvo = pd.Series(True, index=d.index)
    if exclusivo is not None:
        alvo &= ~exclusivo.eq("S")
        passos["nao exclusivo"] = int(alvo.sum())
    if publico is not None:
        alvo &= publico.str.contains("GERAL|QUALIFICADO", regex=True, na=False)
        passos["+ geral ou qualificado"] = int(alvo.sum())
    if cotistas is not None:
        alvo &= cotistas.ge(100)
        passos["+ 100 cotistas ou mais"] = int(alvo.sum())
    if prazo is not None:
        passos["... destes, prazo DETERMINADO"] = int((alvo & prazo.eq("DETERMINADO")).sum())
    for k, v in passos.items():
        print(f"    {k:34s}: {v:,}")
    out["universo"] = passos

    # ---- referências -----------------------------------------------------
    print("\n  REFERENCIAS:")
    refs: dict = {}
    for cnpj, rotulo in REFERENCIAS.items():
        achou = d[d["_cnpj"].eq(cnpj)]
        if achou.empty:
            print(f"    {rotulo:30s}: nao esta neste informe")
            continue
        linha = achou.iloc[-1]
        dado = {r: (None if not achadas.get(r) else str(linha.get(achadas[r])))
                for r in ALVOS}
        refs[rotulo] = dado
        print(f"    {rotulo:30s}: prazo={dado.get('prazo')} "
              f"vence={dado.get('data_prazo')} cotistas={dado.get('cotistas')} "
              f"bolsa={dado.get('bolsa')} cetip={dado.get('cetip')}")
    out["referencias"] = refs
    return out, d


# ---------------------------------------------------------------------------
def listar_diretorio(url: str) -> list[str]:
    """Nomes publicados num diretório de dados abertos — em vez de chutar."""
    try:
        html = cvm_fii._baixar(url, timeout=120).decode("utf-8", "ignore")
    except Exception as exc:                                       # noqa: BLE001
        print(f"   nao consegui listar {url}: {str(exc)[:90]}")
        return []
    nomes = re.findall(r'href="([^"?]+\.(?:zip|csv))"', html, flags=re.I)
    return sorted({n.rsplit("/", 1)[-1] for n in nomes})


def abrir(url: str, *, usar_cache: bool):
    nome = url.rsplit("/", 1)[-1]
    arq = cvm_fii._cache(nome)
    if usar_cache and arq.exists() and arq.stat().st_size > 1024:
        conteudo = arq.read_bytes()
    else:
        conteudo = cvm_fii._baixar(url, timeout=900)
        if usar_cache:
            arq.write_bytes(conteudo)
    if conteudo[:2] == b"PK":
        return zipfile.ZipFile(io.BytesIO(conteudo))
    return pd.read_csv(io.BytesIO(conteudo), sep=";", encoding="ISO-8859-1",
                       dtype="string", low_memory=False)


def analisar_generico(nome: str, df: pd.DataFrame) -> dict:
    """Para o FIP, de quem ainda não se sabe nada."""
    achadas = localizar(df)
    perfil = perfilar(df)
    perfil["procurados"] = achadas
    print(f"\n  {nome}: {perfil['linhas']:,} linhas, {len(perfil['colunas'])} colunas")
    achou = {k: v for k, v in achadas.items() if v}
    print(f"    campos reconhecidos: {', '.join(sorted(achou)) or 'nenhum'}")
    faltam = [k for k in ("cotistas", "pl", "vp_cota", "prazo", "data_prazo")
              if not achadas.get(k)]
    if faltam:
        print(f"    NAO ACHEI: {', '.join(faltam)}")
    print(f"    colunas: {', '.join(perfil['colunas'][:18])}"
          + (" ..." if len(perfil["colunas"]) > 18 else ""))
    if achadas.get("nome"):
        nomes = df[achadas["nome"]].fillna("").astype("string").str.upper()
        for p in PISTAS_FIP:
            bateu = sorted({str(x) for x in df.loc[nomes.str.contains(p, na=False),
                                                   achadas["nome"]]})[:4]
            if bateu:
                print(f"    nome ~ {p}: {bateu[0][:56]}")
    return perfil


# ---------------------------------------------------------------------------
def main() -> int:
    hoje = date.today()
    anterior = hoje.replace(day=1) - pd.Timedelta(days=1)
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", type=int, default=hoje.year)
    ap.add_argument("--comp", default=anterior.strftime("%Y%m"))
    ap.add_argument("--sem-cache", action="store_true")
    ap.add_argument("--saida", default=str(SAIDA))
    args = ap.parse_args()

    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    usar_cache = not args.sem_cache
    resumo: dict = {"gerado_em": str(pd.Timestamp.now())[:16], "ano": args.ano}

    print("=" * 74)
    print("  SONDAGEM v2 — FUNDOS FECHADOS (FII, FIAGRO, FIP)")
    print("=" * 74)

    # ---- FII ---------------------------------------------------------------
    print(f"\n{'=' * 74}\n  FII — informe mensal {args.ano}\n{'=' * 74}")
    try:
        zf = cvm_fii.baixar_informe_mensal(args.ano, usar_cache=usar_cache)
        geral = cvm_fii._concatenar(zf, "geral", 12)
        compl = cvm_fii._concatenar(zf, "complemento", 12)
        if geral.empty or compl.empty:
            raise RuntimeError(f"faltou tabela; membros: {zf.namelist()[:8]}")
        bloco, juntos = analisar_fii(geral, compl)
        resumo["fii"] = bloco
        juntos.head(MAX_LINHAS_AMOSTRA).to_csv(saida / "fii__juntos.csv", sep=";",
                                               index=False, encoding="utf-8")
        det = juntos[texto(juntos, localizar(juntos), "prazo").eq("DETERMINADO")]
        det.head(MAX_LINHAS_AMOSTRA).to_csv(saida / "fii__prazo_determinado.csv",
                                            sep=";", index=False, encoding="utf-8")
        print(f"\n  gravei {min(len(det), MAX_LINHAS_AMOSTRA)} fundos de prazo "
              f"determinado em fii__prazo_determinado.csv")
    except Exception as exc:                                       # noqa: BLE001
        print(f"  FALHOU: {str(exc)[:160]}")
        resumo["fii"] = {"erro": str(exc)[:200]}

    # ---- Fiagro ------------------------------------------------------------
    print(f"\n{'=' * 74}\n  FIAGRO — informe mensal {args.comp}\n{'=' * 74}")
    try:
        zfa = cvm_fii.baixar_informe_fiagro(args.comp, usar_cache=usar_cache)
        nomes = [n for n in zfa.namelist()
                 if n.lower().endswith(".csv") and "subclasse" not in n.lower()]
        df = cvm_fii._ler_csv(zfa, nomes[-1]) if nomes else pd.DataFrame()
        if df.empty:
            raise RuntimeError(f"sem tabela util; membros: {zfa.namelist()}")
        achadas = localizar(df)
        d = ultimo_por_fundo(df, achadas)
        print(f"  {len(df):,} linhas -> {len(d):,} fundos")
        prazo = texto(d, achadas, "prazo")
        if prazo is not None:
            cont = {str(k): int(v) for k, v in Counter(prazo).most_common(6)}
            resumo.setdefault("fiagro", {})["prazo_duracao"] = cont
            print("  PRAZO DE DURACAO:")
            for k, v in cont.items():
                print(f"    {v:6,}x  {k or '(vazio)'}")
        resumo.setdefault("fiagro", {})["perfil"] = perfilar(d)
        d.head(MAX_LINHAS_AMOSTRA).to_csv(saida / "fiagro__juntos.csv", sep=";",
                                          index=False, encoding="utf-8")
    except Exception as exc:                                       # noqa: BLE001
        print(f"  FALHOU: {str(exc)[:160]}")
        resumo["fiagro"] = {"erro": str(exc)[:200]}

    # ---- FIP ---------------------------------------------------------------
    print(f"\n{'=' * 74}\n  FIP — informe trimestral (nunca lido)\n{'=' * 74}")
    bloco: dict = {"diretorio": DIR_FIP, "tabelas": {}}
    arquivos = listar_diretorio(DIR_FIP)
    bloco["arquivos_no_indice"] = arquivos
    print(f"  {len(arquivos)} arquivo(s): {arquivos[-6:]}")
    if arquivos:
        alvo = arquivos[-1]
        print(f"  abrindo {alvo}")
        try:
            obj = abrir(DIR_FIP + alvo, usar_cache=usar_cache)
            tabelas = ({n: cvm_fii._ler_csv(obj, n) for n in obj.namelist()
                        if n.lower().endswith(".csv")}
                       if isinstance(obj, zipfile.ZipFile) else {alvo: obj})
            print(f"  {len(tabelas)} tabela(s)")
            for nome, df in list(tabelas.items())[:10]:
                if df.empty:
                    continue
                bloco["tabelas"][nome] = analisar_generico(nome, df)
                df.head(MAX_LINHAS_AMOSTRA).to_csv(
                    saida / f"fip__{Path(nome).stem[:40]}.csv", sep=";",
                    index=False, encoding="utf-8")
        except Exception as exc:                                   # noqa: BLE001
            print(f"  FALHOU: {str(exc)[:160]}")
            bloco["erro"] = str(exc)[:200]
    bloco["cadastro_no_indice"] = listar_diretorio(DIR_FIP_CAD)
    print(f"  cadastro: {bloco['cadastro_no_indice'][:6] or 'nada no indice'}")
    resumo["fip"] = bloco

    destino = saida / "resumo_fundos.json"
    destino.write_text(json.dumps(resumo, ensure_ascii=False, indent=1,
                                  default=str), encoding="utf-8")
    print(f"\n{'=' * 74}\n  Gravado em {destino}")
    print("\nMe avise quando terminar — eu leio o resumo direto da pasta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
