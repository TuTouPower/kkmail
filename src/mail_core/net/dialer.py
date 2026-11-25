"""Unified outbound TCP, Pin-IP SSRF, dual-stack fallback, TLS & proxy dialer."""

from __future__ import annotations

import errno
import ipaddress
import os
import socket
import ssl
import time
from typing import Any, Callable, Mapping, Sequence

from mail_core.net.bulkhead import EndpointBulkhead, EndpointKey, default_bulkhead
from mail_core.net.policy import NetworkSecurityError, OutboundSecurityPolicy
from mail_core.net.proxy import ProxyConfig
from mail_core.net.tunnel import (
    ProxyTunnelError,
    bridge_tls_socket,
    handshake_http_connect,
    handshake_socks5,
)

DEFAULT_CONNECT_TIMEOUT_S = 10.0
DEFAULT_PER_ATTEMPT_TIMEOUT_S = 5.0
DEFAULT_IO_TIMEOUT_S = 60.0

_LOCAL_ROUTING_ERRNOS: frozenset[int] = frozenset(
    code
    for code in (
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
        errno.EAFNOSUPPORT,
        errno.EPROTONOSUPPORT,
        errno.EADDRNOTAVAIL,
    )
    if code
)

ResolverFn = Callable[[str, int, int, int], list[Any]]
ConnectorFn = Callable[[tuple[str, int], float], Any]


def _read_positive_float_env(name: str, default: float, env: Mapping[str, str] | None = None) -> float:
    source = os.environ if env is None else env
    raw = (source.get(name) or "").strip()
    if not raw:
        return default
    val = float(raw)
    if val <= 0:
        raise ValueError(f"{name} must be > 0, got {val!r}")
    return val


def default_connect_timeout_s(env: Mapping[str, str] | None = None) -> float:
    return _read_positive_float_env("MAIL_CORE_CONNECT_TIMEOUT_S", DEFAULT_CONNECT_TIMEOUT_S, env)


def default_per_attempt_timeout_s(env: Mapping[str, str] | None = None) -> float:
    return _read_positive_float_env("MAIL_CORE_CONNECT_ATTEMPT_TIMEOUT_S", DEFAULT_PER_ATTEMPT_TIMEOUT_S, env)


def _default_connector(address: tuple[str, int], timeout: float) -> socket.socket:
    return socket.create_connection(address, timeout=timeout)


def _error_priority(exc: BaseException) -> int:
    """Rank dial errors so remote Timeouts beat local IPv6 ENETUNREACH noise."""
    if isinstance(exc, TimeoutError):
        return 4
    if isinstance(exc, OSError) and exc.errno == errno.ETIMEDOUT:
        return 4
    if isinstance(exc, (ProxyTunnelError, ssl.SSLError, ConnectionRefusedError, ConnectionResetError)):
        return 3
    if isinstance(exc, OSError) and exc.errno in _LOCAL_ROUTING_ERRNOS:
        return 1
    if isinstance(exc, OSError):
        return 2
    return 0


def _resolve_ips(host: str, port: int, resolver: ResolverFn) -> list[str]:
    clean = host.strip().strip("[]")
    try:
        ipaddress.ip_address(clean)
        return [clean]
    except ValueError:
        pass
    infos = resolver(clean, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    ips: list[str] = []
    seen: set[str] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        ip_str = str(sockaddr[0])
        if ip_str not in seen:
            seen.add(ip_str)
            ips.append(ip_str)
    if not ips:
        raise OSError(f"no IP addresses resolved for host {host!r}")
    return ips


def connect_ips_with_fallback(
    ips: Sequence[str],
    port: int,
    *,
    total_timeout: float,
    per_attempt_timeout: float = DEFAULT_PER_ATTEMPT_TIMEOUT_S,
    connector: ConnectorFn | None = None,
    clock: Callable[[], float] | None = None,
) -> Any:
    """Dial pre-resolved IPs IPv4-first within a bounded shared budget.

    Preserves remote ``TimeoutError`` / peer rejections instead of overwriting
    them with trailing local routing errors such as IPv6 ``ENETUNREACH``.
    """
    if not ips:
        raise OSError("no IP addresses available to connect")
    dial = connector or _default_connector
    mono = clock or time.monotonic
    ordered = sorted(ips, key=lambda ip: 1 if ":" in ip else 0)
    deadline = mono() + float(total_timeout)

    best_error: BaseException | None = None
    best_priority = -1
    secondary_errors: list[str] = []

    for ip in ordered:
        remaining = deadline - mono()
        if remaining <= 0:
            timeout_exc = TimeoutError(f"connect budget ({total_timeout:.2f}s) exhausted before dialing {ip}")
            if _error_priority(timeout_exc) > best_priority:
                best_priority = 4
                best_error = timeout_exc
            break
        attempt_timeout = min(float(per_attempt_timeout), remaining)
        try:
            return dial((ip, int(port)), attempt_timeout)
        except Exception as exc:
            prio = _error_priority(exc)
            if prio > best_priority:
                if best_error is not None:
                    secondary_errors.append(f"{type(best_error).__name__}({getattr(best_error, 'errno', None)})")
                best_priority = prio
                best_error = exc
            else:
                secondary_errors.append(f"{ip}: {type(exc).__name__}({getattr(exc, 'errno', None)})")

    assert best_error is not None
    if secondary_errors and hasattr(best_error, "add_note"):
        best_error.add_note("secondary dial failures: " + "; ".join(secondary_errors[:4]))
    raise best_error


def wrap_tls_socket(
    sock: Any,
    *,
    server_hostname: str,
    ssl_context: ssl.SSLContext | None = None,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> Any:
    """Perform TLS handshake within the connect budget while setting target SNI."""
    if deadline is not None:
        remaining = deadline - clock()
        if remaining <= 0:
            try:
                sock.close()
            except Exception:
                pass
            raise TimeoutError(f"TLS handshake budget exhausted for {server_hostname!r}")
        if hasattr(sock, "settimeout"):
            sock.settimeout(remaining)
    ctx = ssl_context if ssl_context is not None else ssl.create_default_context()
    clean_sni = server_hostname.strip().strip("[]")
    try:
        return ctx.wrap_socket(sock, server_hostname=clean_sni)
    except BaseException:
        try:
            sock.close()
        except Exception:
            pass
        raise


def _prepare_target_plan(
    target_host: str,
    target_port: int,
    proxy: ProxyConfig | None,
    policy: OutboundSecurityPolicy,
    resolve: ResolverFn,
) -> tuple[list[str] | None, str | None]:
    if proxy is None:
        raw_ips = _resolve_ips(target_host, int(target_port), resolve)
        return policy.validate_resolved_ips(raw_ips, host=target_host), None

    clean_target = policy.validate_target_for_proxy(target_host)
    if proxy.scheme != "socks5":
        return None, None
    try:
        ipaddress.ip_address(clean_target)
        return None, clean_target
    except ValueError:
        raw_ips = _resolve_ips(clean_target, int(target_port), resolve)
        validated = policy.validate_resolved_ips(raw_ips, host=clean_target)
        ordered = sorted(validated, key=lambda ip: 1 if ":" in ip else 0)
        return None, ordered[0]


def _dial_via_proxy(
    *,
    proxy: ProxyConfig,
    target_host: str,
    target_port: int,
    socks5_target_ip: str | None,
    tls_for_target: bool,
    connect_timeout: float,
    per_attempt_timeout: float,
    deadline: float,
    resolve: ResolverFn,
    connector: ConnectorFn | None,
    clock: Callable[[], float],
) -> Any:
    # Trusted operator proxy endpoints may reside on loopback/private networks.
    proxy_ips = _resolve_ips(proxy.host, proxy.port, resolve)
    sock = connect_ips_with_fallback(
        proxy_ips,
        proxy.port,
        total_timeout=connect_timeout,
        per_attempt_timeout=per_attempt_timeout,
        connector=connector,
        clock=clock,
    )
    try:
        if proxy.scheme == "https":
            sock = wrap_tls_socket(
                sock,
                server_hostname=proxy.host,
                ssl_context=None,
                deadline=deadline,
                clock=clock,
            )
        if proxy.scheme in ("http", "https"):
            handshake_http_connect(
                sock,
                target_host=target_host,
                target_port=int(target_port),
                proxy=proxy,
                deadline=deadline,
                clock=clock,
            )
            # An outer SSLSocket must be bridged to a fresh OS socket before inner
            # wrap_socket runs; direct wrap_socket detaches the outer OpenSSL fd.
            if proxy.scheme == "https" and tls_for_target and isinstance(sock, ssl.SSLSocket):
                sock = bridge_tls_socket(sock)
        else:
            handshake_socks5(
                sock,
                target_host=target_host,
                target_port=int(target_port),
                target_ip=socks5_target_ip,
                proxy=proxy,
                deadline=deadline,
                clock=clock,
            )
    except BaseException:
        try:
            sock.close()
        except Exception:
            pass
        raise
    return sock


def _record_dial_failure(
    bulkhead: EndpointBulkhead | None,
    endpoint_key: EndpointKey,
    exc: BaseException,
) -> None:
    if bulkhead is None:
        return
    is_proxy_auth_reject = isinstance(exc, ProxyTunnelError) and exc.status == 407
    is_cert_verify = isinstance(exc, ssl.SSLCertVerificationError)
    is_transport_failure = (
        isinstance(exc, (TimeoutError, ConnectionError, OSError))
        and not isinstance(exc, NetworkSecurityError)
        and not is_proxy_auth_reject
        and not is_cert_verify
    )
    if is_transport_failure:
        bulkhead.record_transport_failure(endpoint_key)
    else:
        bulkhead.release_probe_without_outcome(endpoint_key)


def _close_quietly(sock: Any) -> None:
    if sock is not None:
        try:
            sock.close()
        except Exception:
            pass


def _open_configured_socket(
    *,
    target_host: str,
    target_port: int,
    proxy: ProxyConfig | None,
    direct_safe_ips: list[str] | None,
    socks5_target_ip: str | None,
    tls: bool,
    ssl_context: ssl.SSLContext | None,
    connect_timeout: float,
    per_attempt_timeout: float,
    io_timeout: float | None,
    deadline: float,
    resolve: ResolverFn,
    connector: ConnectorFn | None,
    clock: Callable[[], float],
) -> Any:
    sock: Any = None
    try:
        if proxy is None:
            assert direct_safe_ips is not None
            sock = connect_ips_with_fallback(
                direct_safe_ips,
                target_port,
                total_timeout=connect_timeout,
                per_attempt_timeout=per_attempt_timeout,
                connector=connector,
                clock=clock,
            )
        else:
            sock = _dial_via_proxy(
                proxy=proxy,
                target_host=target_host,
                target_port=target_port,
                socks5_target_ip=socks5_target_ip,
                tls_for_target=tls,
                connect_timeout=connect_timeout,
                per_attempt_timeout=per_attempt_timeout,
                deadline=deadline,
                resolve=resolve,
                connector=connector,
                clock=clock,
            )
        if tls:
            sock = wrap_tls_socket(
                sock,
                server_hostname=target_host,
                ssl_context=ssl_context,
                deadline=deadline,
                clock=clock,
            )
        if hasattr(sock, "settimeout"):
            sock.settimeout(None if io_timeout is None else float(io_timeout))
        return sock
    except BaseException:
        _close_quietly(sock)
        raise


def dial_stream(
    target_host: str,
    target_port: int,
    *,
    tls: bool = False,
    ssl_context: ssl.SSLContext | None = None,
    proxy: ProxyConfig | None = None,
    security_policy: OutboundSecurityPolicy | None = None,
    connect_timeout: float | None = None,
    per_attempt_timeout: float | None = None,
    io_timeout: float | None = DEFAULT_IO_TIMEOUT_S,
    bulkhead: EndpointBulkhead | None = ...,  # type: ignore[assignment]
    resolver: ResolverFn | None = None,
    connector: ConnectorFn | None = None,
    clock: Callable[[], float] | None = None,
) -> Any:
    """Dial an outbound TCP(+TLS) stream directly (Pin-IP) or via HTTP/SOCKS5 proxy."""
    policy = security_policy or OutboundSecurityPolicy.from_env()
    resolve = resolver or socket.getaddrinfo
    mono = clock or time.monotonic
    resolved_connect_timeout = (
        float(connect_timeout) if connect_timeout is not None else default_connect_timeout_s()
    )
    resolved_per_attempt = (
        float(per_attempt_timeout)
        if per_attempt_timeout is not None
        else default_per_attempt_timeout_s()
    )
    active_bulkhead: EndpointBulkhead | None = default_bulkhead() if bulkhead is ... else bulkhead
    endpoint_key: EndpointKey = (
        proxy.safe_key() if proxy is not None else "direct",
        target_host.strip().lower(),
        int(target_port),
    )

    direct_safe_ips, socks5_target_ip = _prepare_target_plan(
        target_host, int(target_port), proxy, policy, resolve
    )
    if active_bulkhead is not None:
        active_bulkhead.before_dial(endpoint_key)

    deadline = mono() + resolved_connect_timeout
    try:
        sock = _open_configured_socket(
            target_host=target_host,
            target_port=int(target_port),
            proxy=proxy,
            direct_safe_ips=direct_safe_ips,
            socks5_target_ip=socks5_target_ip,
            tls=tls,
            ssl_context=ssl_context,
            connect_timeout=resolved_connect_timeout,
            per_attempt_timeout=resolved_per_attempt,
            io_timeout=io_timeout,
            deadline=deadline,
            resolve=resolve,
            connector=connector,
            clock=mono,
        )
    except BaseException as exc:
        _record_dial_failure(active_bulkhead, endpoint_key, exc)
        raise

    if active_bulkhead is not None:
        active_bulkhead.record_success(endpoint_key)
    return sock
