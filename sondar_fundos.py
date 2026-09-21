# -*- coding: utf-8 -*-
"""Sonda as fontes da CVM para a aba de fundos fechados.

PRECISA RODAR NUM COMPUTADOR NO BRASIL — `dados.cvm.gov.br` recusa conexões do
exterior, mesma restrição de `baixar_informe_fii.py`.

O universo
----------
Fundos fechados que se compram por oferta pública ou no secundário de balcão da
corretora: FII, Fiagro e FIP. Não têm preço de tela, têm prazo, amortizam, e o
deságio contra o valor patrimonial é conferido à mão na plataforma — o que se
quer aqui é o fundamento do fundo, não o preço.

FII e Fiagro já vêm no zip que `baixar_informe_fii.py` baixa todo mês: são 574
fundos depois do filtro (não exclusivo, 100+ cotistas, público geral ou
qualificado), e os seis fundos de referência abaixo estão todos lá. **FIP é o
buraco**: informe TRIMESTRAL, dataset separado, nunca lido por este projeto.
Numa tela do secundário da XP com quatorze fundos, oito eram FIP.

O que este script mede
----------------------
1. **O que o dataset de FIP publica.** Existe cota? Patrimônio? Número de
   cotistas? Prazo? A periodicidade trimestral já é conhecida; o conteúdo, não.
2. **`Prazo_Duracao` vem preenchida?** No informe de Fiagro a coluna existe, e
   nos 9 fundos da amostra que está no repositório ela veio `"0 ANO/ANOS"` em
   todos — valor de campo ignorado pelo administrador, não de fundo sem prazo.
   O mesmo em `Percentual_Amortizacao_Cotas_Mes`, zerada nos 9. É o modo de
   falha que derrubou `Mandato` e `Patrimonio_Liquido` na primeira execução da
   aba de FII: coluna presente, conteúdo vazio, nenhum erro.
3. **As mesmas colunas existem no informe de FII?** O layout é irmão do de
   Fiagro, mas isso é suposição enquanto ninguém abrir o zip.

Nada é calculado aqui. O script abre, conta e mostra — e os endereços dos
arquivos são **descobertos no índice do diretório**, não chutados, porque a CVM
renomeia arquivo sem avisar.

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

# Campos que descrevem um fundo fechado. Busca tolerante (`cvm_fii.coluna`)
# porque o vocabulário muda de dataset para dataset.
ALVOS = {
    "prazo":       ("prazo_duracao", "prazo"),
    "amortizacao": ("percentual_amortizacao_cotas_mes", "amortizacao"),
    "mercado":     ("mercado_negociacao", "mercado_negociacao_bolsa"),
    "cotistas":    ("numero_cotistas", "quantidade_cotistas", "cotistas"),
    "inicio":      ("data_funcionamento", "data_inicio_atividade", "data_registro"),
    "publico":     ("publico_alvo",),
    "exclusivo":   ("fundo_exclusivo", "exclusivo"),
    "taxa_adm":    ("percentual_despesas_taxa_administracao", "taxa_administracao"),
    "pl":          ("patrimonio_liquido",),
    "vp_cota":     ("valor_patrimonial_cotas", "valor_patrimonial_cota",
                    "valor_cota"),
    "rentab":      ("rentabilidade_efetiva_mes", "rentabilidade"),
    "nome":        ("nome_classe", "nome_fundo_classe", "denominacao_social"),
    "cnpj":        ("cnpj_classe", "cnpj_fundo_classe", "cnpj_fundo", "cnpj"),
}

# Fundos conferidos no informe_fii.json de 07/2026. Servem de caso-teste: o que
# o script disser do universo tem que bater com o que se sabe deles.
REFERENCIAS = {
    "40265671000107": "KIJANI ASATALA FIAGRO",
    "44625562000104": "TG REAL ESTATE FII (TGRE11)",
    "43741205000130": "JGP CREDITO AGRO FIAGRO",
    "59987139000113": "RIZA VISEU FII",
    "61922643000187": "LCP PREFIXADO FEEDER FII",
    "63608356000122": "XP AGRO RENDA FEEDER FIAGRO",
}
# Na tela do secundário esses aparecem como FIP. Se o dataset de FIP trouxer
# nome, devem ser encontráveis por aqui.
PISTAS_FIP = ("NEWAVE", "JIVE", "KINEA PE", "XP INFRA", "XP SPECIAL",
              "XP PRIVATE EQUITY", "SPX PRIVATE", "XP SELECTION")

MAX_LINHAS_AMOSTRA = 300


# ---------------------------------------------------------------------------
# Descoberta: ler o índice do diretório em vez de chutar o nome do arquivo
# ---------------------------------------------------------------------------
def listar_diretorio(url: str) -> list[str]:
    """Nomes de arquivo publicados num diretório de dados abertos da CVM."""
    try:
        html = cvm_fii._baixar(url, timeout=120).decode("utf-8", "ignore")
    except Exception as exc:                                       # noqa: BLE001
        print(f"   nao consegui listar {url}: {str(exc)[:90]}")
        return []
    nomes = re.findall(r'href="([^"?]+\.(?:zip|csv))"', html, flags=re.I)
    return sorted({n.rsplit("/", 1)[-1] for n in nomes})


def baixar_para_zip(url: str, *, usar_cache: bool):
    """Devolve um ZipFile, ou um DataFrame quando o endereço é um CSV solto."""
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


# ---------------------------------------------------------------------------
# Perfil
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
        item = {"preenchidos": int(cheia.sum()),
                "pct": round(100 * int(cheia.sum()) / max(n, 1), 1)}
        distintos = serie.dropna().nunique()
        if distintos and distintos <= 25:
            item["valores"] = {str(k): int(v)
                               for k, v in Counter(serie.dropna()).most_common(10)}
        else:
            item["exemplos"] = [str(v) for v in serie.dropna().head(3)]
        campos[c] = item
    return {"linhas": n, "colunas": list(df.columns), "campos": campos}


def localizar(df: pd.DataFrame) -> dict[str, str | None]:
    return {rotulo: cvm_fii.coluna(df, *padroes, obrigatoria=False)
            for rotulo, padroes in ALVOS.items()}


def util(df: pd.DataFrame, achadas: dict, rotulo: str) -> pd.Series | None:
    c = achadas.get(rotulo)
    return df[c] if c else None


def preenchimento_util(serie: pd.Series | None, vazios=()) -> dict:
    """Quanto da coluna diz alguma coisa — e não só quanto é não-nulo.

    Sem `vazios`, uma coluna inteira de `"0 ANO/ANOS"` passa por 100%
    preenchida. É a diferença entre o campo existir e o campo servir.
    """
    if serie is None:
        return {"existe": False}
    s = serie.fillna("").astype("string").str.strip()
    nao_vazia = s.ne("")
    inutil = s.str.upper().isin([v.upper() for v in vazios])
    n = max(len(s), 1)
    return {"existe": True,
            "pct_preenchida": round(100 * int(nao_vazia.sum()) / n, 1),
            "pct_util": round(100 * int((nao_vazia & ~inutil).sum()) / n, 1),
            "valores": {str(k): int(v)
                        for k, v in Counter(s[nao_vazia]).most_common(8)}}


MEDIDAS = (("prazo", ("0 ANO/ANOS", "0", "0 ANO", "NAO SE APLICA")),
           ("amortizacao", ("0.0000", "0", "0,0000", "0.00")),
           ("mercado", ()),
           ("cotistas", ("0",)),
           ("inicio", ()),
           ("vp_cota", ("0", "0.00")),
           ("rentab", ()))


# ---------------------------------------------------------------------------
def dimensionar(df: pd.DataFrame, achadas: dict) -> dict:
    """Quantos fundos sobram no filtro que a aba pretende usar.

    O filtro é o que sobrou de três tentativas: "não exclusivo, 100 cotistas ou
    mais, público geral ou qualificado". Cortar por "não negocia em bolsa"
    derrubava o XP Agro Renda, que tem registro em bolsa e nenhuma liquidez;
    cortar por "investidores em geral" derrubava o Riza Viseu, que é
    qualificado. Exclusivo e fundo de 1 ou 2 cotistas saem porque são master de
    estrutura, e o master tem sempre número melhor que o feeder que se compra.
    """
    passos: dict[str, int] = {}
    if not achadas.get("cnpj"):
        return {"erro": "nao achei a coluna de CNPJ"}
    d = df.drop_duplicates(subset=[achadas["cnpj"]], keep="last")
    passos["fundos no informe"] = len(d)

    def texto(rotulo):
        s = util(d, achadas, rotulo)
        return None if s is None else s.fillna("").astype("string").str.upper()

    publico, exclusivo, mercado = texto("publico"), texto("exclusivo"), texto("mercado")
    cotistas = util(d, achadas, "cotistas")
    n_cot = pd.to_numeric(cotistas, errors="coerce") if cotistas is not None else None

    if mercado is not None:
        passos["negociam em bolsa"] = int(mercado.str.contains("BOLSA|^S$", regex=True).sum())
        passos["balcao"] = int(mercado.str.contains("BALCAO").sum())
    if publico is not None:
        for rotulo, pista in (("publico geral", "GERAL"),
                              ("qualificado", "QUALIFICADO"),
                              ("profissional", "PROFISSIONAL")):
            passos[rotulo] = int(publico.str.contains(pista).sum())
    if n_cot is not None:
        for corte in (100, 500):
            passos[f"{corte}+ cotistas"] = int((n_cot >= corte).sum())

    if publico is not None and n_cot is not None:
        alvo = (publico.str.contains("GERAL|QUALIFICADO", regex=True)
                & (n_cot >= 100))
        if exclusivo is not None:
            alvo &= ~exclusivo.str.strip().eq("S")
        passos["UNIVERSO (nao exclusivo, 100+ cotistas, geral ou qualif.)"] = int(alvo.sum())
    return passos


def conferir_referencias(df: pd.DataFrame, achadas: dict) -> dict:
    out: dict = {}
    if not achadas.get("cnpj"):
        return out
    limpo = cvm_fii._cnpj_limpo(df[achadas["cnpj"]])
    for cnpj, rotulo in REFERENCIAS.items():
        achou = df[limpo.eq(cnpj)]
        if achou.empty:
            continue
        linha = achou.iloc[-1]
        out[rotulo] = {r: (None if achadas.get(r) is None
                           else str(linha.get(achadas[r]))) for r in ALVOS}
    if achadas.get("nome"):
        nomes = df[achadas["nome"]].fillna("").astype("string").str.upper()
        encontrados = {p: sorted({str(x) for x in df.loc[nomes.str.contains(p, na=False),
                                                         achadas["nome"]]})[:6]
                       for p in PISTAS_FIP}
        out["_por_nome"] = {k: v for k, v in encontrados.items() if v}
    return out


# ---------------------------------------------------------------------------
def tabelas_do_zip(zf: zipfile.ZipFile, familia: str,
                   quantos: int = 1) -> dict[str, pd.DataFrame]:
    """Os CSVs mais recentes de uma família, sem o arquivo de subclasse.

    A subclasse tem seis colunas e nenhuma das que interessam, e no zip de
    Fiagro vem depois do arquivo principal na ordem alfabética — pegar "o
    último" sem filtrar traria justamente a tabela errada.
    """
    nomes = [n for n in cvm_fii._membros(zf, familia)
             if "subclasse" not in n.lower()]
    return {n: cvm_fii._ler_csv(zf, n) for n in nomes[-max(1, quantos):]}


def analisar(apelido: str, nome: str, df: pd.DataFrame, saida: Path) -> dict:
    """Perfila uma tabela e imprime o que importa decidir."""
    achadas = localizar(df)
    perfil = perfilar(df)
    perfil["procurados"] = achadas
    print(f"\n  {nome}: {perfil['linhas']:,} linhas, {len(perfil['colunas'])} colunas")

    perfil["medidas"] = {}
    for rotulo, vazios in MEDIDAS:
        medida = preenchimento_util(util(df, achadas, rotulo), vazios)
        perfil["medidas"][rotulo] = medida
        if not medida["existe"]:
            print(f"    {rotulo:12s}: NAO EXISTE")
            continue
        print(f"    {rotulo:12s}: {achadas[rotulo]} — "
              f"{medida['pct_preenchida']:.0f}% preenchida, "
              f"{medida['pct_util']:.0f}% util")
        if rotulo in ("prazo", "mercado"):
            for v, n in list(medida["valores"].items())[:5]:
                print(f"                  {n:6,}x  {v[:46]}")

    if achadas.get("cnpj"):
        dimensoes = dimensionar(df, achadas)
        perfil["universo"] = dimensoes
        if "erro" not in dimensoes:
            print("    universo:")
            for k, v in dimensoes.items():
                print(f"      {k:56s}: {v:,}")
        refs = conferir_referencias(df, achadas)
        perfil["referencias"] = refs
        for rotulo, dado in refs.items():
            if rotulo == "_por_nome":
                for pista, achados in dado.items():
                    print(f"    nome ~ {pista}: {len(achados)} fundo(s)")
                    for a in achados[:3]:
                        print(f"        {a[:60]}")
            else:
                print(f"    {rotulo}: prazo={dado.get('prazo')!r} "
                      f"cotistas={dado.get('cotistas')!r}")

    df.head(MAX_LINHAS_AMOSTRA).to_csv(
        saida / f"{apelido}__{Path(nome).stem}.csv", sep=";", index=False,
        encoding="utf-8")
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

    print("=" * 74)
    print("  SONDANDO AS FONTES — FUNDOS FECHADOS (FII, FIAGRO, FIP)")
    print(f"  FII: ano {args.ano} | Fiagro: {args.comp} | FIP: descoberto no indice")
    print("=" * 74)

    resumo: dict = {"gerado_em": str(pd.Timestamp.now())[:16],
                    "ano": args.ano, "comp": args.comp, "fontes": {}}

    # ---- FII e Fiagro: já conhecidos --------------------------------------
    for apelido, abrir, familias in (
        ("fii", lambda: cvm_fii.baixar_informe_mensal(args.ano, usar_cache=usar_cache),
         ("geral", "complemento")),
        ("fiagro", lambda: cvm_fii.baixar_informe_fiagro(args.comp, usar_cache=usar_cache),
         ("fiagro",)),
    ):
        print(f"\n{'=' * 74}\n  {apelido.upper()}\n{'=' * 74}")
        try:
            zf = abrir()
        except Exception as exc:                                   # noqa: BLE001
            print(f"  FALHOU: {str(exc)[:140]}")
            resumo["fontes"][apelido] = {"erro": str(exc)[:200]}
            continue
        bloco: dict = {"membros": zf.namelist()[:24], "tabelas": {}}
        for familia in familias:
            for nome, df in tabelas_do_zip(zf, familia).items():
                if not df.empty:
                    bloco["tabelas"][nome] = analisar(apelido, nome, df, saida)
        resumo["fontes"][apelido] = bloco

    # ---- FIP: o buraco ----------------------------------------------------
    print(f"\n{'=' * 74}\n  FIP — informe trimestral (nunca lido por este projeto)\n{'=' * 74}")
    bloco = {"diretorio": DIR_FIP, "tabelas": {}}
    arquivos = listar_diretorio(DIR_FIP)
    print(f"  {len(arquivos)} arquivo(s) no indice: {arquivos[-6:]}")
    bloco["arquivos_no_indice"] = arquivos
    if arquivos:
        alvo = arquivos[-1]
        print(f"  abrindo o mais recente: {alvo}")
        try:
            obj = baixar_para_zip(DIR_FIP + alvo, usar_cache=usar_cache)
            tabelas = ({n: cvm_fii._ler_csv(obj, n) for n in obj.namelist()
                        if n.lower().endswith(".csv")}
                       if isinstance(obj, zipfile.ZipFile) else {alvo: obj})
            print(f"  {len(tabelas)} tabela(s) no arquivo")
            for nome, df in list(tabelas.items())[:8]:
                if not df.empty:
                    bloco["tabelas"][nome] = analisar("fip", nome, df, saida)
        except Exception as exc:                                   # noqa: BLE001
            print(f"  FALHOU: {str(exc)[:140]}")
            bloco["erro"] = str(exc)[:200]
    cad = listar_diretorio(DIR_FIP_CAD)
    print(f"  cadastro de FIP: {cad[:6] or 'nada no indice'}")
    bloco["cadastro_no_indice"] = cad
    resumo["fontes"]["fip"] = bloco

    destino = saida / "resumo_fundos.json"
    destino.write_text(json.dumps(resumo, ensure_ascii=False, indent=1,
                                  default=str), encoding="utf-8")
    print(f"\n{'=' * 74}")
    print(f"  Gravado em {destino}")
    print(f"  Amostras em {saida}")
    print("\n  O que olhar primeiro:")
    print("   - 'prazo' com pct_util baixo => o prazo nao sai do informe e fica")
    print("     no regulamento (PDF no FNET).")
    print("   - se o FIP nao trouxer cotistas nem cota, a aba mostra FIP com")
    print("     menos colunas que FII, e isso tem que aparecer na tela.")
    print("\nMe avise quando terminar — eu leio o resumo direto da pasta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
