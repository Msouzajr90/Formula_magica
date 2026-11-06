# -*- coding: utf-8 -*-
"""Monta e atualiza a base de preços. É o que `atualizar_precos.py` chama.

Dois modos:

* **incremental** (o diário): baixa só os últimos `JANELA_INCREMENTAL_DIAS`
  de quem já está na base e emenda no fim de cada arquivo. Candidato novo
  baixa o histórico inteiro e passa pelo corte de liquidez.
* **completo**: rebaixa tudo desde `INICIO`. Para quando o calendário precisa
  ser refeito ou o Yahoo reajustou um desdobramento no passado.

Nos dois, papel que já estava na base e que o Yahoo não devolve mais
(deslistado, renomeado) **fica com o arquivo antigo**: a base é acumulativa,
e é por isso que se pode testar uma carteira de 2015 com papéis que não
existem mais.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from . import arquivo, coleta, config as C, series as S, universo

log = logging.getLogger(__name__)


@dataclass
class Relatorio:
    modo: str = ""
    pregoes: int = 0
    ultimo_pregao: str = ""
    na_base: int = 0
    entraram: list = field(default_factory=list)
    recusados: int = 0
    sem_cotacao: list = field(default_factory=list)
    nao_atualizados: list = field(default_factory=list)
    reconstruidos: list = field(default_factory=list)
    divergencias: dict = field(default_factory=dict)
    gravados: int = 0
    velas: int = 0                # ações com arquivo de velas (aba técnica)
    velas_gravadas: int = 0
    sem_velas: list = field(default_factory=list)
    adiados: list = field(default_factory=list)   # [(data, fração com preço)]
    avisos: list = field(default_factory=list)

    def texto(self) -> str:
        linhas = [
            f"modo              : {self.modo}",
            f"pregões           : {self.pregoes} (último {self.ultimo_pregao})"
            + (" — adiados: " + ", ".join(f"{d} ({f:.0%} dos papéis com preço)"
                                           for d, f in self.adiados)
               if self.adiados else ""),
            f"ativos na base    : {self.na_base}",
            f"entraram agora    : {len(self.entraram)}"
            + (f" — {', '.join(self.entraram[:15])}{' …' if len(self.entraram) > 15 else ''}"
               if self.entraram else ""),
            f"recusados (total) : {self.recusados}",
            f"sem atualização   : {len(self.nao_atualizados)}"
            + (f" — {', '.join(self.nao_atualizados[:15])}" if self.nao_atualizados else ""),
            f"reconstruídos     : {len(self.reconstruidos)}"
            + (f" — {', '.join(self.reconstruidos[:15])}" if self.reconstruidos else ""),
            f"arquivos gravados : {self.gravados}",
            f"velas (técnica)   : {self.velas} ações, {self.velas_gravadas} arquivos gravados"
            + (f"; sem velas: {', '.join(self.sem_velas[:15])}" if self.sem_velas else ""),
        ]
        if self.divergencias:
            pior = sorted(self.divergencias.items(), key=lambda kv: -kv[1])[:10]
            linhas.append("divergências      : " + ", ".join(f"{t} {n}" for t, n in pior))
        for a in self.avisos:
            linhas.append(f"AVISO: {a}")
        return "\n".join(linhas)


def fontes_reais() -> SimpleNamespace:
    return SimpleNamespace(precos=coleta.baixar_precos, ibov=coleta.baixar_ibov,
                           cdi=coleta.baixar_cdi)


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def _coluna(df: pd.DataFrame | None, t: str) -> pd.Series | None:
    if df is None or df.empty or t not in df.columns:
        return None
    s = df[t].dropna()
    return s if len(s) else None


def realinhar(i0: int, r: list[int], escala: int, pregoes_velhos: list[str],
              pregoes_novos: list[str]) -> tuple[int, list[int]] | None:
    """Leva uma série gravada num calendário para outro.

    Reconstrói o caminho de preço nas datas antigas e o recorta no calendário
    novo — o retorno de um pregão que deixou de existir cai no seguinte.
    """
    if not r or i0 < 1 or i0 + len(r) > len(pregoes_velhos):
        return None
    datas = pd.DatetimeIndex(pregoes_velhos[i0 - 1:i0 + len(r)])
    preco = np.concatenate([[1.0], np.cumprod(1.0 + np.asarray(r, float) / escala)])
    res = S.retornos_no_calendario(pd.Series(preco, index=datas), pregoes_novos)
    if res is None:
        return None
    return res[0], S.compactar(res[1], escala)


def _entrada(t: str, info: dict, i0: int, r: list[int], pregoes: list[str],
             liq: dict, anterior: dict | None) -> dict:
    """Linha do índice. Liquidez: a máxima nunca diminui (é "em algum momento
    desde 2010"); a atual e a fração de pregões com negócio vêm da coleta de
    hoje, ou ficam as de antes se hoje não veio volume."""
    ant = anterior or {}
    liq_max = liq.get("max")
    if ant.get("liqMax") is not None:
        liq_max = max(liq_max or 0.0, ant["liqMax"])
    atual = liq.get("atual") if liq.get("atual") is not None else ant.get("liq")
    neg = liq.get("neg") if liq.get("neg") is not None else ant.get("neg")
    e = {
        "t": t,
        "nome": info.get("nome") or ant.get("nome") or "",
        "classe": info.get("classe") or ant.get("classe") or "acao",
        "i0": int(i0),
        "n": len(r),
        "liqMax": None if liq_max is None else round(float(liq_max)),
        "liq": None if atual is None else round(float(atual)),
        "neg": None if neg is None else round(float(neg), 3),
    }
    sal = S.saltos(i0, r, pregoes)
    if sal:
        e["saltos"] = sal[:20]
    return e


# ---------------------------------------------------------------------------
# Atualização
# ---------------------------------------------------------------------------
def atualizar(pasta: Path = C.PASTA_PRECOS, *, completo: bool = False,
              hoje: date | None = None, fontes=None, candidatos: dict | None = None,
              inicio: date = C.INICIO) -> Relatorio:
    pasta = Path(pasta)
    hoje = hoje or C.hoje()
    fontes = fontes or fontes_reais()
    rel = Relatorio()

    anterior = arquivo.ler_indice(pasta)
    if anterior and anterior.get("demo"):
        log.warning("A base atual é de demonstração; refazendo do zero com dados reais.")
        anterior = None
        completo = True
    if anterior and anterior.get("v") != C.VERSAO_FORMATO:
        rel.avisos.append("formato do índice mudou; refazendo do zero")
        anterior = None
        completo = True
    incremental = anterior is not None and not completo
    rel.modo = "incremental" if incremental else "completo"
    pregoes_velhos = (anterior or {}).get("pregoes") or []

    if incremental:
        ini_janela = date.fromisoformat(pregoes_velhos[-1]) - timedelta(days=C.JANELA_INCREMENTAL_DIAS)
    else:
        ini_janela = inicio

    # ---- 0. preços de quem já está na base ------------------------------
    # Baixados ANTES do calendário: é com eles que se decide se o último
    # pregão do Ibovespa já está fechado também para as ações.
    base_anterior = {a["t"]: a for a in (anterior or {}).get("ativos") or []}
    ja_na_base = sorted(base_anterior)
    dados_base = (fontes.precos(ja_na_base, ini_janela if incremental else inicio, hoje)
                  if ja_na_base else {})

    # ---- 1. calendário e Ibovespa --------------------------------------
    ibov = fontes.ibov(ini_janela, hoje)
    novas = S.calendario_de(ibov)
    novas, adiados = S.sem_pregoes_incompletos(
        novas, dados_base.get("preco") if dados_base else None,
        C.FRACAO_MINIMA_PREGAO_NOVO,
        protegido=pregoes_velhos[-1] if incremental and pregoes_velhos else None)
    if adiados:
        rel.adiados = list(reversed(adiados))
        rel.avisos.append(
            "pregão " + ", ".join(d for d, _ in rel.adiados) + " adiado: o Ibovespa "
            "já tem o dia, mas só " + ", ".join(f"{f:.0%}" for _, f in rel.adiados)
            + " dos papéis têm preço nele (o Yahoo ainda não fechou o dia). "
            "Entra na próxima rodada.")
    pregoes = S.estender_calendario(pregoes_velhos if incremental else [], novas)
    if len(pregoes) < 2:
        raise RuntimeError("Calendário de pregões vazio: o Ibovespa veio sem dados.")
    rel.pregoes, rel.ultimo_pregao = len(pregoes), pregoes[-1]
    calendario_mudou = bool(pregoes_velhos) and not incremental and \
        pregoes[:len(pregoes_velhos)] != pregoes_velhos

    gravados = 0

    def emendar_ou_trocar(nome, velho, i0n, rn, escala):
        """Série final de uma referência ou papel, dado o trecho baixado."""
        if velho and incremental:
            em = S.emendar(velho["i0"], velho["r"], i0n, rn)
            if em is not None:
                return em[0], em[1], em[2]
            log.warning("%s: buraco entre o gravado e o baixado.", nome)
            return None
        return i0n, rn, 0

    res = S.retornos_no_calendario(ibov, pregoes)
    if res is None:
        raise RuntimeError("Ibovespa sem dois pregões no calendário.")
    velho = arquivo.ler_serie(pasta, C.ARQ_IBOV)
    em = emendar_ou_trocar("Ibovespa", velho, res[0], S.compactar(res[1]), C.ESCALA)
    if em is None:
        raise RuntimeError("O Ibovespa gravado não emenda no baixado. Rode "
                           "`python atualizar_precos.py --completo`.")
    i0_ibov, r_ibov, _ = em
    gravados += arquivo.gravar_se_mudou(arquivo.caminho_serie(pasta, C.ARQ_IBOV),
                                        arquivo.serie("IBOV", i0_ibov, r_ibov))

    # ---- 2. CDI ---------------------------------------------------------
    velho_cdi = arquivo.ler_serie(pasta, C.ARQ_CDI)
    i0_cdi = r_cdi = None
    try:
        cdi = fontes.cdi(ini_janela - timedelta(days=10), hoje)
        res = S.cdi_no_calendario(cdi, pregoes)
        if res is None:
            raise RuntimeError("SGS 12 sem dados no período")
        em = emendar_ou_trocar("CDI", velho_cdi, res[0],
                               S.compactar(res[1], C.ESCALA_CDI), C.ESCALA_CDI)
        if em is None:
            raise RuntimeError("CDI gravado não emenda no baixado")
        i0_cdi, r_cdi, _ = em
    except Exception as exc:                                   # noqa: BLE001
        rel.avisos.append(f"CDI não atualizou ({exc}); segue o gravado")
        if velho_cdi:
            i0_cdi, r_cdi = velho_cdi["i0"], velho_cdi["r"]
            if calendario_mudou:
                ra = realinhar(i0_cdi, r_cdi, C.ESCALA_CDI, pregoes_velhos, pregoes)
                if ra:
                    i0_cdi, r_cdi = ra
    if r_cdi is None:
        raise RuntimeError("Sem CDI, nem baixado nem gravado: o Sharpe não tem "
                           "taxa livre de risco. Nada publicado.")
    gravados += arquivo.gravar_se_mudou(arquivo.caminho_serie(pasta, C.ARQ_CDI),
                                        arquivo.serie("CDI", i0_cdi, r_cdi, C.ESCALA_CDI))

    # ---- 3. ativos ------------------------------------------------------
    recusados = dict((anterior or {}).get("recusados") or {})
    cands = candidatos if candidatos is not None else universo.candidatos()
    info = {t: dict(v) for t, v in cands.items()}
    for t, a in base_anterior.items():
        info.setdefault(t, {"nome": a.get("nome", ""), "classe": a.get("classe", "acao")})

    corte_recusa = (hoje - timedelta(days=C.REAVALIAR_RECUSADOS_DIAS)).isoformat()
    novos = sorted(t for t in cands if t not in base_anterior
                   and not (t in recusados and recusados[t].get("em", "") >= corte_recusa))

    ativos: dict[str, dict] = {}

    # Velas da aba de análise técnica: mesmo download, nenhuma requisição a
    # mais no dia a dia (ver `tecnica.velas.Gravador`).
    from tecnica import velas as V
    gv = V.Gravador(pasta, pregoes, pregoes_velhos=pregoes_velhos,
                    calendario_mudou=calendario_mudou, hoje=hoje)

    def processar(t, dados, anterior_e, velho_s, modo_emenda):
        """Grava a série de `t`. Devolve 'ok', 'sem_dados' ou 'buraco'."""
        nonlocal gravados
        px = _coluna(dados.get("preco"), t)
        if px is None:
            return "sem_dados"
        res = S.retornos_no_calendario(px, pregoes)
        if res is None:
            return "sem_dados"
        rn = S.compactar(res[1])
        if modo_emenda and velho_s:
            em = S.emendar(velho_s["i0"], velho_s["r"], res[0], rn, tolerancia=1)
            if em is None:
                return "buraco"
            i0, r, div = em
            if div > 3:
                rel.divergencias[t] = div
        else:
            i0, r = res[0], rn
        fech, vol = _coluna(dados.get("fechamento"), t), _coluna(dados.get("volume"), t)
        liq = (S.liquidez(fech, vol) if fech is not None and vol is not None
               else {"max": None, "atual": None, "neg": None})
        e = _entrada(t, info.get(t, {}), i0, r, pregoes, liq, anterior_e)
        if not anterior_e and (e["liqMax"] or 0) < C.LIQUIDEZ_MINIMA:
            recusados[t] = {"liqMax": e["liqMax"], "em": hoje.isoformat()}
            return "recusado"
        gravados += arquivo.gravar_se_mudou(arquivo.caminho_serie(pasta, t),
                                            arquivo.serie(t, i0, r))
        ativos[t] = e
        recusados.pop(t, None)
        gv.receber(t, e["classe"], dados, emendar_no_gravado=bool(modo_emenda and velho_s))
        return "ok"

    def manter_antigo(t):
        """Papel da base que não veio hoje: fica o arquivo de antes."""
        velho_s = arquivo.ler_serie(pasta, t)
        a = dict(base_anterior[t])
        if velho_s is None:
            rel.avisos.append(f"{t}: estava no índice e o arquivo sumiu; fora da base")
            return
        i0, r = velho_s["i0"], velho_s["r"]
        if calendario_mudou:
            ra = realinhar(i0, r, velho_s.get("esc", C.ESCALA), pregoes_velhos, pregoes)
            if ra is None:
                rel.avisos.append(f"{t}: não consegui realinhar ao calendário novo")
                return
            i0, r = ra
            gravar_serie(t, i0, r)
        a.update({"i0": i0, "n": len(r)})
        gv.manter(t, a.get("classe", "acao"))
        sal = S.saltos(i0, r, pregoes)
        if sal:
            a["saltos"] = sal[:20]
        else:
            a.pop("saltos", None)
        ativos[t] = a

    def gravar_serie(t, i0, r):
        nonlocal gravados
        gravados += arquivo.gravar_se_mudou(arquivo.caminho_serie(pasta, t),
                                            arquivo.serie(t, i0, r))

    if incremental:
        dados = dados_base
        refazer = []
        for t in ja_na_base:
            st = processar(t, dados, base_anterior[t], arquivo.ler_serie(pasta, t), True)
            if st == "buraco":
                refazer.append(t)
            elif st != "ok":
                rel.nao_atualizados.append(t)
                manter_antigo(t)
        if refazer:
            dados = fontes.precos(refazer, inicio, hoje)
            for t in refazer:
                st = processar(t, dados, base_anterior[t], None, False)
                if st == "ok":
                    rel.reconstruidos.append(t)
                else:
                    rel.nao_atualizados.append(t)
                    manter_antigo(t)
    elif ja_na_base:
        dados = dados_base
        for t in ja_na_base:
            st = processar(t, dados, base_anterior[t], None, False)
            if st != "ok":
                rel.nao_atualizados.append(t)
                manter_antigo(t)

    if novos:
        dados = fontes.precos(novos, inicio, hoje)
        for t in novos:
            st = processar(t, dados, None, None, False)
            if st == "ok":
                rel.entraram.append(t)
            elif st == "sem_dados":
                rel.sem_cotacao.append(t)
                recusados[t] = {"liqMax": None, "em": hoje.isoformat(), "motivo": "sem cotação"}

    # ação que ainda não tinha velas: histórico inteiro, uma vez
    gv.completar(fontes.precos, inicio, hoje)
    rel.velas = len(gv.com_velas)
    rel.velas_gravadas = gv.gravados
    rel.sem_velas = sorted(set(gv.sem_velas))
    rel.avisos.extend(gv.avisos)

    # ---- 4. índice ------------------------------------------------------
    for t in list(recusados):
        if t in ativos:
            recusados.pop(t)
    rel.na_base, rel.recusados = len(ativos), len(recusados)

    indice = {
        "v": C.VERSAO_FORMATO,
        "geradoEm": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "demo": False,
        "escala": C.ESCALA,
        "corteLiquidez": C.LIQUIDEZ_MINIMA,
        "janelaLiquidez": C.JANELA_LIQUIDEZ,
        "inicio": inicio.isoformat(),
        "bench": {
            "IBOV": {"nome": "Ibovespa", "arquivo": C.ARQ_IBOV, "i0": i0_ibov,
                     "n": len(r_ibov), "esc": C.ESCALA},
            "CDI": {"nome": "CDI", "arquivo": C.ARQ_CDI, "i0": i0_cdi,
                    "n": len(r_cdi), "esc": C.ESCALA_CDI},
        },
        "avisos": rel.avisos,
        "ativos": [ativos[t] for t in sorted(ativos)],
        "recusados": {t: recusados[t] for t in sorted(recusados)},
        "pregoes": pregoes,
    }
    gravados += arquivo.gravar_indice(pasta, indice)
    rel.gravados = gravados
    return rel
