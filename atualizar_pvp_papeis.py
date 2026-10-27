# -*- coding: utf-8 -*-
"""Grava o ponto semanal do P/VP de cada papel. Roda no robô, sem rede.

O histórico (`pvp_papeis.json`) nasce no seu computador, com
`gerar_pvp_papeis.py`, porque os balanços antigos vêm da CVM. Daqui em diante
o robô só acrescenta o preço: lê o fechamento do dia no `dados.json`, que a
coleta acabou de gravar, divide pelo patrimônio por papel guardado e grava o
ponto da semana.

Só às sextas (ou com --forcar). Um ponto por semana é o que o arquivo guarda;
reescrevê-lo todo dia geraria um commit diário de centenas de KB sem mudar o
desenho. O ponto de HOJE o site calcula sozinho, com o preço do `dados.json`.

Balanço novo não entra por aqui: o VPA só muda quando o script local roda de
novo. A tela mostra a data do balanço usado.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).parent
sys.path.insert(0, str(RAIZ))

DADOS = RAIZ / "web" / "public" / "dados.json"
ARQUIVO = RAIZ / "web" / "public" / "pvp_papeis.json"


def precos_do_dia(dados: dict) -> dict[str, float]:
    precos = {}
    for e in (dados.get("empresas") or []) + (dados.get("excluidas") or []):
        t, p = e.get("ticker"), e.get("preco")
        if t and isinstance(p, (int, float)) and p > 0:
            precos[str(t).upper()] = float(p)
    return precos


def main(argv=None) -> int:
    from mercado import pvp_papeis

    ap = argparse.ArgumentParser()
    ap.add_argument("--forcar", action="store_true", help="grava mesmo fora da sexta")
    ap.add_argument("--hoje", default=None, help="data AAAA-MM-DD (testes)")
    ap.add_argument("--dados", default=str(DADOS))
    ap.add_argument("--arquivo", default=str(ARQUIVO))
    args = ap.parse_args(argv)

    hoje = date.fromisoformat(args.hoje) if args.hoje else date.today()
    arq = Path(args.arquivo)
    if not arq.exists():
        print(f"{arq.name} ainda não existe; gere com gerar_pvp_papeis.py. Nada a fazer.")
        return 0
    if hoje.weekday() != 4 and not args.forcar:
        print("Não é sexta; o ponto da semana fica para sexta.")
        return 0

    historico = json.loads(arq.read_text(encoding="utf-8"))
    dados = json.loads(Path(args.dados).read_text(encoding="utf-8"))
    precos = precos_do_dia(dados)
    if not pvp_papeis.atualizar_semana(historico, precos, hoje):
        print("P/VP por papel: nada mudou.")
        return 0
    arq.write_text(json.dumps(historico, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    com = sum(1 for p in historico["papeis"].values() if (p.get("s") or [None])[-1] is not None)
    print(f"P/VP por papel: ponto de {hoje} gravado para {com} de "
          f"{len(historico['papeis'])} papéis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
