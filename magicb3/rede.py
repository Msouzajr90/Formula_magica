"""Camada de rede: sessão HTTP com repetição, e diagnóstico de IPv4/IPv6.

Existe por causa de um problema real encontrado em produção: o servidor
`dados.cvm.gov.br` respondia normalmente do Brasil, mas devolvia
`[Errno 101] Network is unreachable` a partir dos servidores do GitHub Actions.

Duas causas possíveis, com tratamentos diferentes:

  1. O endereço resolve para IPv6 e a máquina não tem rota IPv6. Nesse caso
     `forcar_ipv4()` resolve — é a primeira coisa a tentar, porque é grátis.

  2. O servidor bloqueia faixas de IP estrangeiras ou de datacenter. Nesse
     caso nada feito no cliente resolve: é preciso baixar de uma máquina no
     Brasil. `diagnosticar()` distingue os dois casos.
"""
from __future__ import annotations

import logging
import socket
import ssl

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger(__name__)

_ipv4_forcado = False


def forcar_ipv4() -> None:
    """Faz toda a biblioteca requests resolver apenas endereços IPv4.

    Idempotente. Chamada automaticamente pelos módulos que acessam a CVM.
    """
    global _ipv4_forcado
    if _ipv4_forcado:
        return
    try:
        import urllib3.util.connection as u3
        u3.allowed_gai_family = lambda: socket.AF_INET
        _ipv4_forcado = True
        log.info("Resolução de nomes restrita a IPv4.")
    except Exception as exc:                                   # noqa: BLE001
        log.warning("Não foi possível forçar IPv4: %s", exc)


def sessao(tentativas: int = 4, backoff: float = 2.0) -> requests.Session:
    """Sessão HTTP que repete em erro de rede e em 5xx, com espera crescente."""
    from urllib3.util.retry import Retry

    forcar_ipv4()
    s = requests.Session()
    politica = Retry(
        total=tentativas, connect=tentativas, read=tentativas,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    adaptador = HTTPAdapter(max_retries=politica, pool_maxsize=8)
    s.mount("https://", adaptador)
    s.mount("http://", adaptador)
    s.headers.update({
        # Alguns servidores públicos brasileiros recusam requisições sem
        # User-Agent de navegador.
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/126.0 Safari/537.36"),
        "Accept": "*/*",
        "Accept-Language": "pt-BR,pt;q=0.9",
    })
    return s


# ---------------------------------------------------------------------------
# Diagnóstico
# ---------------------------------------------------------------------------
def _tentar(familia: int, host: str, porta: int, timeout: float) -> tuple[bool, str]:
    try:
        infos = socket.getaddrinfo(host, porta, familia, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return False, f"sem registro DNS ({exc})"
    if not infos:
        return False, "sem registro DNS"

    ultimo = ""
    for *_, endereco in infos:
        sock = None
        try:
            # criar o socket já falha se a máquina não suporta a família
            sock = socket.socket(familia, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(endereco)
            return True, f"conectou em {endereco[0]}"
        except OSError as exc:
            ultimo = f"{endereco[0]}: {exc.__class__.__name__} {exc}"
        finally:
            if sock is not None:
                sock.close()
    return False, ultimo


def diagnosticar(host: str = "dados.cvm.gov.br", porta: int = 443,
                 timeout: float = 15.0) -> dict:
    """Testa IPv4 e IPv6 separadamente e diz qual é o problema."""
    ok4, det4 = _tentar(socket.AF_INET, host, porta, timeout)
    ok6, det6 = _tentar(socket.AF_INET6, host, porta, timeout)

    if ok4:
        veredito = "IPv4 funciona"
        causa = ("Se a aplicação falhava antes, era o IPv6 sendo tentado "
                 "primeiro. Forçar IPv4 resolve.")
    elif ok6:
        veredito = "só IPv6 funciona"
        causa = "Situação incomum; não force IPv4 nesta máquina."
    else:
        veredito = "nenhum dos dois conecta"
        causa = ("O servidor não é alcançável desta máquina. A causa mais "
                 "provável é bloqueio de IPs estrangeiros ou de datacenter — "
                 "comum em sites públicos brasileiros. Nesse caso é preciso "
                 "baixar de uma máquina no Brasil.")

    # Confirma se o TLS completa, não só o TCP
    tls = ""
    if ok4:
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((host, porta), timeout=timeout) as c:
                with ctx.wrap_socket(c, server_hostname=host) as t:
                    tls = f"TLS ok ({t.version()})"
        except Exception as exc:                               # noqa: BLE001
            tls = f"TCP conectou mas o TLS falhou: {exc}"

    return {"host": host, "ipv4": ok4, "ipv4_detalhe": det4,
            "ipv6": ok6, "ipv6_detalhe": det6, "tls": tls,
            "veredito": veredito, "causa": causa}


def relatorio(host: str = "dados.cvm.gov.br") -> str:
    d = diagnosticar(host)
    linhas = [
        f"host        : {d['host']}",
        f"IPv4        : {'OK' if d['ipv4'] else 'FALHA'} — {d['ipv4_detalhe']}",
        f"IPv6        : {'OK' if d['ipv6'] else 'FALHA'} — {d['ipv6_detalhe']}",
    ]
    if d["tls"]:
        linhas.append(f"TLS         : {d['tls']}")
    linhas += [f"veredito    : {d['veredito']}", f"o que fazer : {d['causa']}"]
    return "\n".join(linhas)
