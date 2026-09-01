"""Cotações, liquidez e valor de mercado via Yahoo Finance, com cache em disco."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import CACHE_DIR

log = logging.getLogger(__name__)
SUFIXO_B3 = ".SA"


def _yf():
    import yfinance as yf
    return yf


def _cache(nome: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / nome


def _chave(*partes) -> str:
    """Identificador estável para nome de arquivo de cache.

    O `hash()` do Python é embaralhado a cada processo (PYTHONHASHSEED
    aleatório), então a chave antiga mudava a cada execução e o cache de
    cotações nunca era reaproveitado entre uma rodada e a seguinte. Com
    blake2b a mesma lista de tickers gera sempre o mesmo arquivo.
    """
    bruto = "|".join(str(p) for p in partes).encode("utf-8")
    return hashlib.blake2b(bruto, digest_size=8).hexdigest()


def _achatar(df: pd.DataFrame, campo: str, tickers: list[str]) -> pd.DataFrame:
    """Extrai um campo do resultado do yf.download em qualquer layout de colunas."""
    if isinstance(df.columns, pd.MultiIndex):
        nivel0 = df.columns.get_level_values(0)
        if campo in set(nivel0):
            out = df.xs(campo, axis=1, level=0)
        else:                                   # layout (ticker, campo)
            out = df.xs(campo, axis=1, level=1)
    else:
        if campo not in df.columns:
            return pd.DataFrame()
        out = df[[campo]]
        out.columns = tickers[:1]
    return out.sort_index()


# O Yahoo devolve "Too Many Requests. Rate limited" quando o pedido é grande
# demais ou os lotes vêm rápido demais. Aconteceu em produção: 129 símbolos
# perdidos num lote só, o que esvaziou o cruzamento adiante.
TAMANHO_LOTE = 50
PAUSA_ENTRE_LOTES = 1.5          # segundos
PAUSA_MAXIMA = 15.0              # teto do recuo entre lotes
ESPERA_BLOQUEIO = (60.0, 180.0, 300.0)   # recuo dentro do lote (uso pontual)
RODADAS_DE_REPESCAGEM = 3                # ondas de retorno aos barrados
ESPERA_ENTRE_RODADAS = (120.0, 300.0, 600.0)
ORCAMENTO_ESPERA_S = 30 * 60             # teto do tempo total parado esperando
FRACAO_MAXIMA_PERDIDA = 0.15             # acima disso o histórico não presta


ARQ_INEXISTENTES = "tickers_inexistentes.json"

# Prefixo dos arquivos de cotação em cache. A versão anterior gravava também o
# lote mutilado por bloqueio — 1 papel de 50 — e esse arquivo seria relido para
# sempre, congelando a perda. Trocar o prefixo aposenta os arquivos ruins sem
# jogar fora o resto do cache: os downloads da CVM e a lista de símbolos
# inexistentes, que custaram caro e continuam válidos.
VERSAO_CACHE = "v2"


class BloqueioYahoo(RuntimeError):
    """O Yahoo está barrando as requisições — não adianta insistir agora."""


def _carregar_inexistentes() -> set[str]:
    """Símbolos que o Yahoo já confirmou não existir.

    A B3 devolve o prefixo do emissor, não os papéis negociados, então o
    código testa PREFIXO + 3/4/5/6/11 — cerca de 2.000 tentativas para ~400
    empresas. Guardar as que não existem evita repetir o mesmo desperdício a
    cada rodada, que é justamente o que atrai o bloqueio.
    """
    arq = _cache(ARQ_INEXISTENTES)
    if not arq.exists():
        return set()
    try:
        return set(json.loads(arq.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def _gravar_inexistentes(novos: set[str]) -> None:
    if not novos:
        return
    todos = _carregar_inexistentes() | set(novos)
    _cache(ARQ_INEXISTENTES).write_text(
        json.dumps(sorted(todos)), encoding="utf-8")
    log.info("%d símbolos inexistentes anotados (%d no total).",
             len(novos), len(todos))


# Um "429" solto não serve como sinal: a mensagem de erro traz a lista de
# símbolos, e tickers como Z0429 ou GLPO4 dariam falso positivo — foi assim que
# um lote de papéis inexistentes passou por bloqueio no teste.
_SINAL_BLOQUEIO = re.compile(
    r"too many requests|rate.?limit|\b(?:http|status|code|erro?r?)\D{0,12}429\b",
    re.IGNORECASE)


def _bloqueado(texto) -> bool:
    return bool(_SINAL_BLOQUEIO.search(str(texto)))


_SIMBOLO = re.compile(r"[A-Z0-9]{2,10}\.SA")


def _classificar(linhas: list[str], lote: list[str]) -> tuple[set[str], set[str]]:
    """Separa, dentro do que o yfinance reclamou, quem foi barrado de quem não existe.

    O yfinance agrupa os símbolos por mensagem de erro, uma linha por motivo.
    Ler linha a linha é o que permite repescar só os bloqueados: mandar de
    volta os inexistentes junto seria repetir o desperdício que atrai o
    bloqueio.
    """
    pedidos = set(lote)
    bloqueados, mortos = set(), set()
    for linha in linhas:
        achados = set(_SIMBOLO.findall(linha)) & pedidos
        if not achados:
            continue
        (bloqueados if _bloqueado(linha) else mortos).update(achados)
    return bloqueados, mortos - bloqueados


class _EscutaYF(logging.Handler):
    """Guarda o que o yfinance reclama durante um lote.

    Isto existe porque o `yf.download` NÃO levanta exceção quando o Yahoo
    bloqueia: ele registra "Failed downloads" no logger dele e devolve um
    DataFrame vazio. Sem ler esse log, um bloqueio fica indistinguível de um
    ticker que não existe — e era por isso que a espera longa nunca era
    aplicada: o código só olhava para exceções, que não vinham.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.linhas: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.linhas.append(record.getMessage())
        except Exception:                                   # noqa: BLE001
            pass

    @property
    def texto(self) -> str:
        return " ".join(self.linhas)


@contextmanager
def _escutando_yfinance():
    h = _EscutaYF()
    lg = logging.getLogger("yfinance")
    lg.addHandler(h)
    try:
        yield h
    finally:
        lg.removeHandler(h)


def _simbolos(bloco: pd.DataFrame | None) -> set[str]:
    """Quais tickers realmente vieram no bloco."""
    if bloco is None or bloco.empty or not isinstance(bloco.columns, pd.MultiIndex):
        return set()
    n0 = set(map(str, bloco.columns.get_level_values(0)))
    n1 = set(map(str, bloco.columns.get_level_values(1)))
    return n1 if any(s.endswith(SUFIXO_B3) for s in n1) else n0


def _baixar_lote(tickers: list[str], inicio, fim, tentativas: int = 4):
    """Um lote. Devolve (dados, bloqueados, inexistentes).

    `bloqueados` são os símbolos que o Yahoo barrou: podem existir e vale
    tentar de novo. `inexistentes` são as combinações de sufixo que a B3 nunca
    negociou; repetir não inventa cotação, então saem da fila de vez.

    Atenção ao caso misto: o lote pode voltar com dados E com bloqueio. Foi o
    que apareceu em produção — 49 dos 50 falharam, 25 por não existirem e 16
    por bloqueio, e o único que respondeu fazia o lote parecer bem-sucedido.
    Os 16 sumiriam calados. Por isso devolvemos `bloqueado` mesmo com dados.
    """
    yf = _yf()
    for n in range(tentativas):
        try:
            with _escutando_yfinance() as escuta:
                raw = yf.download(tickers, start=str(inicio), end=str(fim),
                                  auto_adjust=False, progress=False,
                                  group_by="column", threads=False)
            bloqueados, mortos = _classificar(escuta.linhas, tickers)
            if raw is not None and not raw.empty:
                return raw, bloqueados, mortos
            barrado = bool(bloqueados) or _bloqueado(escuta.texto)
        except Exception as exc:                            # noqa: BLE001
            barrado = _bloqueado(exc)
            bloqueados = set(tickers) if barrado else set()
            mortos = set()
            log.warning("Lote falhou: %s", str(exc)[:160])

        if not barrado:
            log.info("Lote sem cotação e sem bloqueio: %d símbolos inexistentes.",
                     len(tickers))
            return None, set(), mortos or set(tickers)

        espera = ESPERA_BLOQUEIO[min(n, len(ESPERA_BLOQUEIO) - 1)]
        if n == tentativas - 1:
            break
        log.warning("Yahoo bloqueou (tentativa %d/%d). Esperando %.0fs.",
                    n + 1, tentativas, espera)
        time.sleep(espera)
    return None, set(tickers), set()


def baixar_historico(tickers: list[str], inicio: str | date, fim: str | date,
                     *, usar_cache: bool = True, progresso=None
                     ) -> dict[str, pd.DataFrame]:
    """Devolve {'preco': ajustado, 'fechamento': bruto, 'volume': em ações}.

    Baixa em lotes de 150 símbolos. Um lote que falhe não derruba os demais —
    os tickers dele simplesmente ficam de fora, e isso aparece no diagnóstico.
    """
    tickers = sorted(set(tickers))
    if not tickers:
        vazio = pd.DataFrame()
        return {"preco": vazio, "fechamento": vazio, "volume": vazio}

    arq = _cache(f"px{VERSAO_CACHE}_{_chave(tuple(tickers), inicio, fim)}.parquet")
    if usar_cache and arq.exists():
        raw = pd.read_parquet(arq)
        raw.columns = pd.MultiIndex.from_tuples(
            [tuple(c.split("|", 1)) for c in raw.columns])
    else:
        mortos = _carregar_inexistentes() if usar_cache else set()
        vivos = [t for t in tickers if t not in mortos]
        if mortos:
            log.info("Pulando %d símbolos já conhecidos como inexistentes.",
                     len(tickers) - len(vivos))

        estado = {"partes": [], "mortos": set(), "repescar": set(),
                  "pausa": PAUSA_ENTRE_LOTES}

        def processar(lote: list[str], rotulo: str, primeiro: bool) -> None:
            # Cache por lote: uma rodada interrompida (ou barrada no meio)
            # não joga fora o que já baixou. A seguinte continua de onde parou.
            arq_lote = _cache(f"lt{VERSAO_CACHE}_{_chave(tuple(lote), inicio, fim)}.parquet")
            if usar_cache and arq_lote.exists():
                bloco = pd.read_parquet(arq_lote)
                bloco.columns = pd.MultiIndex.from_tuples(
                    [tuple(c.split("|", 1)) for c in bloco.columns])
                estado["partes"].append(bloco)
                return

            if not primeiro:
                time.sleep(estado["pausa"])
            # Uma tentativa só: quem for barrado volta na próxima rodada, não
            # aqui. Esperar 9 minutos parado dentro de cada lote era o que
            # estourava o relógio antes de a varredura chegar ao fim.
            bloco, bloqueados, mortos = _baixar_lote(lote, inicio, fim, tentativas=1)
            barrado = bool(bloqueados)
            estado["mortos"].update(mortos)

            if barrado:
                # Vai com mais calma: insistir no mesmo ritmo dentro de um
                # bloqueio é o que mantém o bloqueio.
                estado["pausa"] = min(estado["pausa"] * 2, PAUSA_MAXIMA)

            if bloco is None:
                if barrado:
                    log.warning("%s barrado; %d símbolos vão para a próxima "
                                "rodada.", rotulo, len(bloqueados))
                    estado["repescar"].update(bloqueados)
                return

            if not isinstance(bloco.columns, pd.MultiIndex):
                bloco.columns = pd.MultiIndex.from_product([bloco.columns, [lote[0]]])
            estado["partes"].append(bloco)

            if barrado:
                faltando = bloqueados - _simbolos(bloco)
                if faltando:
                    log.warning("%s: %d símbolos perdidos por bloqueio, "
                                "vão para a repescagem.", rotulo, len(faltando))
                    estado["repescar"].update(faltando)
            elif usar_cache:
                # Só vale cachear o lote que veio inteiro; um lote mutilado por
                # bloqueio congelaria a perda para todas as rodadas seguintes.
                plano = bloco.copy()
                plano.columns = ["|".join(map(str, c)) for c in plano.columns]
                plano.to_parquet(arq_lote)
                estado["pausa"] = max(PAUSA_ENTRE_LOTES, estado["pausa"] * 0.8)

        # Varre tudo depressa e só depois volta para os barrados, em ondas.
        # O bloqueio do Yahoo é intermitente: esperar entre as ondas dá tempo
        # de a janela dele reabrir, enquanto esperar dentro do lote apenas
        # gasta o relógio sem que o resto do universo avance.
        pendentes, gasto = list(vivos), 0.0
        for rodada in range(1 + RODADAS_DE_REPESCAGEM):
            if not pendentes:
                break
            if rodada:
                espera = ESPERA_ENTRE_RODADAS[min(rodada - 1,
                                                  len(ESPERA_ENTRE_RODADAS) - 1)]
                if gasto + espera > ORCAMENTO_ESPERA_S:
                    log.warning("Orçamento de espera esgotado; %d símbolos "
                                "ficam sem cotação.", len(pendentes))
                    break
                log.warning("Rodada %d: %d símbolos barrados. Esperando %.0f min.",
                            rodada, len(pendentes), espera / 60)
                time.sleep(espera)
                gasto += espera

            estado["repescar"] = set()
            lotes = [pendentes[i:i + TAMANHO_LOTE]
                     for i in range(0, len(pendentes), TAMANHO_LOTE)]
            nome = "Lote" if not rodada else f"Repescagem {rodada}"
            for i, lote in enumerate(lotes):
                if progresso:
                    progresso(f"Cotações: {nome.lower()} {i+1} de {len(lotes)}...", None)
                processar(lote, f"{nome} {i+1} de {len(lotes)}", primeiro=(i == 0))
            pendentes = sorted(estado["repescar"])

        partes = estado["partes"]
        _gravar_inexistentes(estado["mortos"])

        if pendentes:
            # A base é o universo que existe de verdade, não os ~2.000 chutes:
            # perder 300 papéis reais não pode passar por "15% de 2.000".
            reais = max(len(vivos) - len(estado["mortos"]), 1)
            fracao = len(pendentes) / reais
            log.warning("%d de %d símbolos existentes ficaram sem cotação por "
                        "bloqueio (%.0f%%).", len(pendentes), reais, 100 * fracao)
            if fracao > FRACAO_MAXIMA_PERDIDA:
                raise BloqueioYahoo(
                    f"O Yahoo barrou {len(pendentes)} de {reais} papéis "
                    f"({100*fracao:.0f}%) e não liberou nas repescagens. Prefiro "
                    "parar a entregar um histórico furado: o que já baixou ficou "
                    "em cache, rode de novo mais tarde e ele continua daqui.")
        if not partes:
            vazio = pd.DataFrame()
            return {"preco": vazio, "fechamento": vazio, "volume": vazio}

        raw = pd.concat(partes, axis=1).sort_index()
        raw = raw.loc[:, ~raw.columns.duplicated()]
        if usar_cache:
            flat = raw.copy()
            flat.columns = ["|".join(map(str, c)) for c in flat.columns]
            flat.to_parquet(arq)

    campo_aj = "Adj Close" if "Adj Close" in set(
        raw.columns.get_level_values(0) if isinstance(raw.columns, pd.MultiIndex)
        else raw.columns) else "Close"

    return {
        "preco": _achatar(raw, campo_aj, tickers),
        "fechamento": _achatar(raw, "Close", tickers),
        "volume": _achatar(raw, "Volume", tickers),
    }


def liquidez_media_diaria(fechamento: pd.DataFrame, volume: pd.DataFrame,
                          janela: int = 63) -> pd.Series:
    """Volume financeiro médio (R$/dia) dos últimos `janela` pregões."""
    if fechamento.empty or volume.empty:
        return pd.Series(dtype=float)
    fin = (fechamento * volume).tail(janela)
    return fin.mean(skipna=True)


def tickers_validos(precos: pd.DataFrame, min_pregoes: int = 120,
                    cobertura_minima: float = 0.8) -> list[str]:
    """Descarta papéis com histórico curto demais para estimar covariância.

    O script original usava `prices.T.dropna().T`, que exclui qualquer ativo
    com um único dia faltante — inclusive por feriado ou leilão.
    """
    if precos.empty:
        return []
    validos = precos.notna().sum()
    n = len(precos)
    ok = (validos >= min_pregoes) & (validos >= cobertura_minima * n)
    return list(precos.columns[ok])


def retornos(precos: pd.DataFrame, *, log_ret: bool = False) -> pd.DataFrame:
    px = precos.ffill()
    r = np.log(px).diff() if log_ret else px.pct_change()
    return r.dropna(how="all").fillna(0.0)


# ---------------------------------------------------------------------------
# Valor de mercado
# ---------------------------------------------------------------------------
def acoes_em_circulacao(tickers: list[str], *, usar_cache: bool = True) -> pd.Series:
    """Número de ações por ticker (Yahoo). Cacheado por dia."""
    arq = _cache(f"shares_{date.today():%Y%m%d}.parquet")
    if usar_cache and arq.exists():
        s = pd.read_parquet(arq)["ACOES"]
        faltando = [t for t in tickers if t not in s.index]
        if not faltando:
            return s.reindex(tickers)
    else:
        s = pd.Series(dtype=float)
        faltando = tickers

    yf = _yf()
    novos, falhas_seguidas = {}, 0
    for i, t in enumerate(faltando):
        if i:
            time.sleep(0.35)                 # uma requisição por empresa: vá devagar
        try:
            fi = yf.Ticker(t).fast_info
            n = fi.get("shares") or fi.get("sharesOutstanding")
            mc = fi.get("market_cap") or fi.get("marketCap")
            px = fi.get("last_price") or fi.get("lastPrice")
            if not n and mc and px:
                n = mc / px
            novos[t] = float(n) if n else np.nan
            falhas_seguidas = 0
        except Exception as exc:                            # noqa: BLE001
            log.debug("sem ações em circulação para %s: %s", t, exc)
            novos[t] = np.nan
            falhas_seguidas += 1
            if _bloqueado(exc):
                log.warning("Yahoo limitou as requisições; pausando %.0fs",
                            PAUSA_APOS_BLOQUEIO)
                time.sleep(PAUSA_APOS_BLOQUEIO)
                falhas_seguidas = 0
            elif falhas_seguidas >= 25:
                log.warning("25 falhas seguidas no nº de ações; desistindo das "
                            "%d restantes.", len(faltando) - i - 1)
                break

    obtidos = sum(1 for v in novos.values() if v == v and v)
    log.info("nº de ações pelo Yahoo: %d de %d consultados", obtidos, len(faltando))

    s = pd.concat([s, pd.Series(novos)]) if len(s) else pd.Series(novos)
    s = s[~s.index.duplicated(keep="last")]
    if usar_cache:
        s.rename("ACOES").to_frame().to_parquet(arq)
    return s.reindex(tickers)


def acoes_historicas(ticker: str, data_ref: pd.Timestamp) -> float:
    """Nº de ações vigente numa data passada (para backtest sem viés)."""
    yf = _yf()
    try:
        serie = yf.Ticker(ticker).get_shares_full(
            start=str((data_ref - timedelta(days=400)).date()),
            end=str(data_ref.date()))
        if serie is not None and len(serie):
            return float(serie.iloc[-1])
    except Exception:                                       # noqa: BLE001
        pass
    return float("nan")
