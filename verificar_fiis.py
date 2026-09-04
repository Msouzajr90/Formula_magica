# -*- coding: utf-8 -*-
"""Diagnostico das fontes de dados de fundos imobiliarios.

Mesma funcao do `verificar_dados.py` do lado das acoes: testa cada fonte
isoladamente e diz qual quebrou e o que isso afeta. Rode-o antes da primeira
coleta e sempre que algo parar de funcionar.

Ha uma coisa a mais aqui. A CVM renomeia colunas dos arquivos de FII entre
safras e a documentacao vem num zip separado. Por isso este script IMPRIME as
colunas que encontrou em cada arquivo: se um indicador sair vazio, a resposta
esta nessa lista, e o conserto e acrescentar um padrao em `fiib3/cvm_fii.py`.

Uso:
    python verificar_fiis.py
    python verificar_fiis.py --colunas     # despeja todas as colunas dos CSVs
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date

OK, FALHA, AVISO = "[ok]  ", "[FALHA]", "[aviso]"


def _titulo(t: str) -> None:
    print(f"\n{t}\n{'-' * len(t)}")


def _erro(exc: Exception, detalhado: bool) -> None:
    print(f"{FALHA} {type(exc).__name__}: {str(exc)[:400]}")
    if detalhado:
        traceback.print_exc()


def checar_rede(detalhado: bool) -> bool:
    _titulo("1. Conexao com dados.cvm.gov.br")
    try:
        from magicb3 import rede
        print(rede.relatorio("dados.cvm.gov.br"))
        d = rede.diagnosticar("dados.cvm.gov.br")
        return bool(d["ipv4"] or d["ipv6"])
    except Exception as exc:                                   # noqa: BLE001
        _erro(exc, detalhado)
        return False


def checar_arquivo(caminho: str, detalhado: bool) -> bool:
    """Quando ha arquivo, e ele que manda: a CVM nem e procurada."""
    _titulo(f"2. Informe lido do arquivo ({caminho})")
    try:
        from fiib3 import arquivo_informe as arqi
        informe, cadastro = arqi.importar(caminho)
        idade = arqi.idade_em_dias(caminho)
        print(f"{OK} {len(informe)} fundos | competencia {arqi.competencia(caminho)} "
              f"| gerado ha {idade} dias")
        if idade is not None and idade > 45:
            print(f"{AVISO} o arquivo tem {idade} dias. Rode baixar_informe_fii.py "
                  "de novo num computador no Brasil.")
        for campo, rotulo in (("PL", "patrimonio liquido"),
                              ("VP_COTA", "valor patrimonial por cota"),
                              ("COTAS", "numero de cotas"),
                              ("NOME", "razao social"),
                              ("PCT_IMOVEIS", "composicao da carteira"),
                              ("ISIN", "codigo ISIN")):
            n = int(informe[campo].notna().sum()) if campo in informe.columns else 0
            frac = n / max(len(informe), 1)
            marca = OK if frac > 0.7 else (AVISO if frac > 0.2 else FALHA)
            print(f"{marca} {rotulo:32s}: {n}/{len(informe)} preenchidos")
        return True
    except Exception as exc:                                   # noqa: BLE001
        _erro(exc, detalhado)
        return False


def checar_informe(ano: int, detalhado: bool, listar: bool) -> bool:
    _titulo(f"2. Informe mensal de FII ({ano})")
    try:
        from fiib3 import cvm_fii
        zf = cvm_fii.baixar_informe_mensal(ano)
        nomes = zf.namelist()
        print(f"{OK} zip baixado: {len(nomes)} arquivos")
        for fam in ("geral", "complemento", "ativo_passivo"):
            achados = cvm_fii._membros(zf, fam)
            marca = OK if achados else FALHA
            print(f"{marca} {fam:16s}: {len(achados)} arquivos"
                  f"{'  ultimo: ' + achados[-1] if achados else ''}")
            if achados and listar:
                df = cvm_fii._ler_csv(zf, achados[-1])
                print(f"        {len(df)} linhas, colunas:")
                for c in df.columns:
                    print(f"          - {c}")

        df = cvm_fii.ler_informe(ano)
        print(f"{OK} consolidado: {len(df)} fundos, "
              f"competencia {df['COMPETENCIA'].max()}")
        for campo, rotulo in (("PL", "patrimonio liquido"),
                              ("VP_COTA", "valor patrimonial por cota"),
                              ("COTAS", "numero de cotas"),
                              ("COTISTAS", "numero de cotistas"),
                              ("ISIN", "codigo ISIN"),
                              ("SEGMENTO", "segmento de atuacao"),
                              ("MANDATO", "mandato")):
            preenchidos = int(df[campo].notna().sum()) if campo in df.columns else 0
            frac = preenchidos / max(len(df), 1)
            marca = OK if frac > 0.7 else (AVISO if frac > 0.2 else FALHA)
            print(f"{marca} {rotulo:32s}: {preenchidos}/{len(df)} preenchidos")
            if frac <= 0.2:
                print("        -> rode com --colunas e acrescente o nome real "
                      "em fiib3/cvm_fii.py")
        return True
    except Exception as exc:                                   # noqa: BLE001
        _erro(exc, detalhado)
        print("        sem isto nada funciona: e a fonte de PL, VP/cota e segmento.")
        return False


def checar_cadastro(detalhado: bool) -> bool:
    # Opcional desde que a CVM tirou o cad_fii.csv do ar: o nome do fundo passou
    # a sair do proprio informe. Fica no diagnostico so para avisar se voltar.
    _titulo("3. Cadastro de fundos (cad_fii.csv) — opcional")
    try:
        from fiib3 import cvm_fii
        df = cvm_fii.baixar_cadastro()
        print(f"{OK} {len(df)} fundos, {int(df['NOME'].notna().sum())} com razao social")
        return True
    except Exception as exc:                                   # noqa: BLE001
        _erro(exc, detalhado)
        print("        impacto: nenhum. O nome do fundo vem do informe mensal.")
        return True


def checar_b3(detalhado: bool) -> bool:
    # Desligada por padrao no pipeline: a API mudou de contrato e devolve lista
    # vazia. Todos os fundos negociados em bolsa tem ISIN no informe da CVM.
    _titulo("4. API de fundos listados da B3 — opcional")
    try:
        from fiib3 import tickers_fii
        df = tickers_fii.baixar_fundos_b3()
        if df.empty:
            print(f"{AVISO} a B3 devolveu lista vazia (contrato mudou).")
            print("        impacto: nenhum. Os codigos saem do ISIN da CVM,")
            print("        que cobre 100% dos fundos negociados em bolsa.")
            return True
        print(f"{OK} {len(df)} FII listados; exemplo: "
              f"{', '.join(df['SIGLA'].head(5))}")
        return True
    except Exception as exc:                                   # noqa: BLE001
        _erro(exc, detalhado)
        return False


def checar_yahoo(detalhado: bool) -> bool:
    _titulo("5. Yahoo Finance (preco, volume e proventos)")
    testes = ["MXRF11.SA", "KNRI11.SA", "HGLG11.SA"]
    try:
        from fiib3 import mercado
        px = mercado.baixar_cotacoes(testes, anos=1.2, usar_cache=False)
        vivos = [t for t in testes if t in px["preco"].columns]
        marca = OK if len(vivos) == len(testes) else AVISO
        print(f"{marca} cotacoes: {len(vivos)}/{len(testes)} — {vivos}")
        if vivos:
            print(f"        ultimo preco de {vivos[0]}: "
                  f"{px['preco'][vivos[0]].dropna().iloc[-1]:.2f}")

        prov = mercado.baixar_proventos(vivos, meses=13, usar_cache=False)
        resumo = mercado.resumo_proventos(prov)
        if resumo.empty:
            print(f"{FALHA} nenhum provento retornado.")
            print("        impacto: sem DY e sem consistencia — a tela perde o sentido.")
            return False
        for t in resumo.index:
            print(f"{OK} {t}: {int(resumo.loc[t, 'MESES_PAGOS_12M'])} meses pagos, "
                  f"R$ {resumo.loc[t, 'PROV_12M']:.2f} em 12 meses")
        return True
    except Exception as exc:                                   # noqa: BLE001
        _erro(exc, detalhado)
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--colunas", action="store_true",
                    help="lista todas as colunas dos CSVs da CVM")
    ap.add_argument("--detalhado", action="store_true", help="mostra o traceback")
    ap.add_argument("--ano", type=int, default=date.today().year)
    ap.add_argument("--informe", default=None,
                    help="caminho do informe_fii.json; com ele a CVM nao e "
                         "testada (e o modo do GitHub Actions)")
    args = ap.parse_args()

    print("Verificacao das fontes de dados de FII")
    print("=" * 44)

    if args.informe:
        # No GitHub Actions a CVM nunca responde — testa-la ali so produziria um
        # erro assustador e irrelevante. O que importa checar e o arquivo.
        r = {
            "arquivo": checar_arquivo(args.informe, args.detalhado),
            "b3": checar_b3(args.detalhado),
            "yahoo": checar_yahoo(args.detalhado),
        }
        criticos = ["arquivo", "yahoo"]
    else:
        r = {
            "rede": checar_rede(args.detalhado),
            "informe": checar_informe(args.ano, args.detalhado, args.colunas),
            "cadastro": checar_cadastro(args.detalhado),
            "b3": checar_b3(args.detalhado),
            "yahoo": checar_yahoo(args.detalhado),
        }
        criticos = ["informe", "yahoo"]

    _titulo("Resumo")
    for k, v in r.items():
        print(f"  {'ok    ' if v else 'FALHOU'}  {k}")

    if all(r[k] for k in criticos):
        sufixo = f" --informe {args.informe}" if args.informe else ""
        print(f"\nAs fontes criticas responderam. Pode rodar: "
              f"python atualizar_fiis.py{sufixo}")
        return 0
    print("\nAlguma fonte critica falhou. O que ela afeta esta descrito acima.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
