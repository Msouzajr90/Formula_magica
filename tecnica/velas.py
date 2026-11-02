# -*- coding: utf-8 -*-
"""Velas (abertura, máxima, mínima, volume) das ações, no calendário da base.

Arquivo `web/public/precos/ohlc/PETR4.json`:

    {"t": "PETR4", "v": 1, "i0": 0, "esc": 10000, "vesc": 1000,
     "a": [...], "x": [...], "m": [...], "f": [...],
     "ult": ["2026-10-30", 30.12]}

* `a[k]`, `x[k]`, `m[k]`: abertura, máxima e mínima do pregão `pregoes[i0+k]`,
  como (preço ÷ fechamento do MESMO dia − 1) × 10.000. Ver `config.ESCALA_RAZAO`.
* `f[k]`: volume financeiro do dia em R$ mil (fechamento bruto × quantidade).
* `ult`: último pregão com vela e o fechamento BRUTO dele, em reais. A tela
  reconstrói o fechamento ajustado pela base de retornos (`precos/PETR4.json`)
  e multiplica a curva inteira para o último ponto bater com este preço — é o
  "gráfico ajustado" que qualquer home broker mostra.

Pregão sem negócio (ou que o Yahoo não tem) dentro do intervalo: vela parada,
`a = x = m = 0`, volume 0. É o mesmo tratamento da base de retornos, onde esse
pregão tem retorno zero.

Nada aqui toca a rede. `Gravador` é o que `simulacao.base.atualizar` chama:
ele recebe o MESMO download que já serviu para os retornos.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from simulacao import series as S

from . import config as C

log = logging.getLogger(__name__)

CHAVES = ("a", "x", "m", "f")
ARQ_ESTADO = "_estado.json"
REAVALIAR_DIAS = 30
# Máxima mais de 50% acima do fechamento, ou mínima mais de 50% abaixo, no
# mesmo dia: é erro de cotação do Yahoo (aparece como um "pavio" absurdo), não
# negócio. A vela daquele dia vira parada; o retorno do dia não é afetado.
RAZAO_ABSURDA = 0.5


# ---------------------------------------------------------------------------
# Cálculo puro
# ---------------------------------------------------------------------------
def _serie(x) -> pd.Series:
    if x is None:
        return pd.Series(dtype=float)
    s = pd.to_numeric(x, errors="coerce")
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    return s


def velas_no_calendario(abertura, maxima, minima, fechamento, volume,
                        pregoes: list[str]) -> tuple[int, dict, list] | None:
    """(i0, {'a','x','m','f'}, [data, fechamento bruto]) ou None.

    Datas fora do calendário vão para o pregão seguinte, como nos retornos;
    duas datas no mesmo pregão viram uma vela só (abertura da primeira,
    fechamento da última, máxima e mínima do conjunto, volumes somados).
    """
    if not pregoes:
        return None
    c = _serie(fechamento)
    c = c[(c > 0) & np.isfinite(c)]
    if c.empty:
        return None
    df = pd.DataFrame({"c": c})
    for nome, x in (("o", abertura), ("h", maxima), ("l", minima), ("v", volume)):
        df[nome] = _serie(x).reindex(df.index)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df = df[df.index >= pd.Timestamp(pregoes[0])]
    if df.empty:
        return None
    pos = S._posicoes(df.index, pregoes)
    df = df[pos >= 0]
    pos = pos[pos >= 0]
    if df.empty:
        return None
    df = df.assign(p=pos)
    g = df.groupby("p", sort=True)
    agg = pd.DataFrame({
        "o": g["o"].first(), "h": g["h"].max(), "l": g["l"].min(),
        "c": g["c"].last(), "v": g["v"].sum(min_count=1),
    })
    p_ini, p_fim = int(agg.index.min()), int(agg.index.max())
    agg = agg.reindex(range(p_ini, p_fim + 1))

    n = len(agg)
    a, x, m, f = (np.zeros(n, dtype=np.int64) for _ in range(4))
    o_, h_, l_, c_, v_ = (agg[k].to_numpy(float) for k in "ohlcv")
    for k in range(n):
        ck, vk = c_[k], v_[k]
        if not (math.isfinite(ck) and ck > 0):
            continue                                    # pregão sem vela
        if math.isfinite(vk) and vk > 0:
            f[k] = int(round(ck * vk / C.ESCALA_VOLUME))
        else:
            continue                                    # sem negócio: vela parada
        ok, hk, lk = o_[k], h_[k], l_[k]
        if not all(math.isfinite(z) and z > 0 for z in (ok, hk, lk)):
            continue
        hk = max(hk, ok, ck)                            # o Yahoo às vezes
        lk = min(lk, ok, ck)                            # inverte as pontas
        if hk / ck - 1 > RAZAO_ABSURDA or 1 - lk / ck > RAZAO_ABSURDA:
            continue
        a[k] = int(round((ok / ck - 1) * C.ESCALA_RAZAO))
        x[k] = int(round((hk / ck - 1) * C.ESCALA_RAZAO))
        m[k] = int(round((lk / ck - 1) * C.ESCALA_RAZAO))
    ult_c = float(c_[n - 1])
    return p_ini, {"a": a.tolist(), "x": x.tolist(), "m": m.tolist(), "f": f.tolist()}, \
        [pregoes[p_fim], round(ult_c, 4)]


def emendar(velho: dict, i0_novo: int, novo: dict) -> tuple[int, dict] | None:
    """Emenda o trecho novo no fim do arquivo gravado (o novo vence na
    sobreposição). None se houver buraco entre os dois."""
    out, i0 = {}, None
    for k in CHAVES:
        em = S.emendar(velho["i0"], velho[k], i0_novo, novo[k], tolerancia=10 ** 12)
        if em is None:
            return None
        if i0 is None:
            i0 = em[0]
        out[k] = em[1]
    return i0, out


def realinhar(arq: dict, pregoes_velhos: list[str], pregoes_novos: list[str]) -> dict | None:
    """Leva as velas de um calendário para outro, pela data de cada uma."""
    i0, n = arq["i0"], len(arq["a"])
    if i0 < 0 or i0 + n > len(pregoes_velhos):
        return None
    datas = pd.DatetimeIndex(pregoes_velhos[i0:i0 + n])
    pos = S._posicoes(datas, pregoes_novos)
    ok = pos >= 0
    if not ok.any():
        return None
    p_ini, p_fim = int(pos[ok].min()), int(pos[ok].max())
    novo = {k: [0] * (p_fim - p_ini + 1) for k in CHAVES}
    for j in np.flatnonzero(ok):
        for k in CHAVES:
            novo[k][int(pos[j]) - p_ini] = arq[k][j]
    out = dict(arq)
    out.update({"i0": p_ini, **novo})
    return out


def arquivo_velas(t: str, i0: int, vel: dict, ult: list) -> dict:
    return {"t": t, "v": C.VERSAO_VELAS, "i0": int(i0), "esc": C.ESCALA_RAZAO,
            "vesc": C.ESCALA_VOLUME, **{k: [int(v) for v in vel[k]] for k in CHAVES},
            "ult": [ult[0], float(ult[1])]}


# ---------------------------------------------------------------------------
# Disco
# ---------------------------------------------------------------------------
def caminho(pasta: Path, t: str) -> Path:
    return Path(pasta) / f"{t}.json"


def ler(pasta: Path, t: str) -> dict | None:
    try:
        d = json.loads(caminho(pasta, t).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(d, dict) or d.get("v") != C.VERSAO_VELAS or "i0" not in d:
        return None
    if any(k not in d for k in CHAVES) or len({len(d[k]) for k in CHAVES}) != 1:
        return None
    return d


def _ler_estado(pasta: Path) -> dict:
    try:
        return json.loads((Path(pasta) / ARQ_ESTADO).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def gravar(pasta: Path, dados: dict) -> bool:
    from simulacao import arquivo
    return arquivo.gravar_se_mudou(caminho(pasta, dados["t"]), dados)


# ---------------------------------------------------------------------------
# O que o robô da base de preços chama
# ---------------------------------------------------------------------------
class Gravador:
    """Acompanha `simulacao.base.atualizar` e grava as velas das ações.

    `receber` é chamado para cada papel cujo retorno acabou de ser gravado,
    com o MESMO dicionário de download. No modo incremental, ação que ainda
    não tem arquivo de velas (a primeira execução depois desta aba existir)
    ou cujo arquivo não emenda vai para `faltando`; `completar` baixa o
    histórico inteiro só delas, uma vez.
    """

    def __init__(self, pasta_precos: Path, pregoes: list[str], *,
                 pregoes_velhos: list[str] | None = None, calendario_mudou: bool = False,
                 hoje=None):
        from datetime import date
        self.pasta = Path(pasta_precos) / C.PASTA_VELAS.name
        self.hoje = hoje or date.today()
        # Ação que o Yahoo não devolveu nem com o histórico inteiro (deslistada
        # há anos, por exemplo) é anotada e só tentada de novo depois de
        # `REAVALIAR_DIAS` — senão cada execução rebaixaria 16 anos dela.
        estado = _ler_estado(self.pasta)
        self.tentados: dict[str, str] = dict(estado.get("semVelas") or {})
        self.pregoes = pregoes
        self.pregoes_velhos = pregoes_velhos or []
        self.calendario_mudou = calendario_mudou
        self.faltando: list[str] = []
        self.gravados = 0
        self.com_velas: set[str] = set()
        self.sem_velas: list[str] = []
        self.avisos: list[str] = []

    @staticmethod
    def _col(dados: dict, chave: str, t: str):
        df = dados.get(chave)
        if df is None or getattr(df, "empty", True) or t not in df.columns:
            return None
        return df[t]

    def receber(self, t: str, classe: str, dados: dict, *, emendar_no_gravado: bool) -> str:
        if classe not in C.CLASSES:
            return "fora"
        col = lambda k: self._col(dados, k, t)          # noqa: E731
        if col("abertura") is None or col("fechamento") is None:
            # download sem os campos (cache antigo): tenta o histórico inteiro
            if emendar_no_gravado:
                self.faltando.append(t)
                return "faltando"
            self.sem_velas.append(t)
            return "sem_velas"
        res = velas_no_calendario(col("abertura"), col("maxima"), col("minima"),
                                  col("fechamento"), col("volume"), self.pregoes)
        if res is None:
            if emendar_no_gravado:
                self.faltando.append(t)
                return "faltando"
            self.sem_velas.append(t)
            return "sem_velas"
        i0, vel, ult = res
        if emendar_no_gravado:
            velho = ler(self.pasta, t)
            em = emendar(velho, i0, vel) if velho else None
            if em is None:
                self.faltando.append(t)
                return "faltando"
            i0, vel = em
            if ult[0] < (velho.get("ult") or [""])[0]:
                ult = velho["ult"]
        self.gravados += gravar(self.pasta, arquivo_velas(t, i0, vel, ult))
        self.com_velas.add(t)
        return "ok"

    def manter(self, t: str, classe: str) -> None:
        """Papel que não veio hoje: as velas de antes ficam, realinhadas se o
        calendário foi refeito. Sem velas ainda (deslistada antes de a aba
        existir): tenta o histórico inteiro, uma vez a cada `REAVALIAR_DIAS`."""
        if classe not in C.CLASSES:
            return
        velho = ler(self.pasta, t)
        if velho is None:
            if self._pode_tentar(t):
                self.faltando.append(t)
            return
        if self.calendario_mudou:
            novo = realinhar(velho, self.pregoes_velhos, self.pregoes)
            if novo is None:
                self.avisos.append(f"{t}: velas não realinharam ao calendário novo")
                return
            self.gravados += gravar(self.pasta, novo)
        self.com_velas.add(t)

    def _pode_tentar(self, t: str) -> bool:
        from datetime import timedelta
        quando = self.tentados.get(t)
        return not quando or quando < (self.hoje - timedelta(days=REAVALIAR_DIAS)).isoformat()

    def completar(self, baixar, inicio, hoje) -> None:
        faltando = sorted(set(self.faltando) - self.com_velas)
        self.faltando = []
        if faltando and self._completar(faltando, baixar, inicio, hoje):
            for t in faltando:
                if t not in self.com_velas:
                    self.tentados[t] = self.hoje.isoformat()
        for t in list(self.tentados):
            if t in self.com_velas:
                self.tentados.pop(t)
        if self.tentados or (self.pasta / ARQ_ESTADO).exists():
            from simulacao import arquivo
            self.gravados += arquivo.gravar_se_mudou(
                self.pasta / ARQ_ESTADO,
                {"semVelas": {t: self.tentados[t] for t in sorted(self.tentados)}}, compacto=False)

    def _completar(self, faltando, baixar, inicio, hoje) -> bool:
        log.info("Velas: baixando o histórico inteiro de %d ações sem arquivo.", len(faltando))
        try:
            dados = baixar(faltando, inicio, hoje)
        except Exception as exc:                        # noqa: BLE001
            self.avisos.append(f"velas de {len(faltando)} ações não baixaram ({exc}); "
                               "ficam para a próxima execução")
            return False
        for t in faltando:
            self.receber(t, "acao", dados, emendar_no_gravado=False)
        return True
