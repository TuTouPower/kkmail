"""Stdlib HTTP/HTTPS opener adapter unified with outbound proxy policy and dial_stream."""

from __future__ import annotations

import http.client
import socket
import ssl
import urllib.error
import urllib.request
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from mail_core.net.bulkhead import EndpointBulkhead, EndpointCircuitOpenError
from mail_core.net.dialer import (
    DEFAULT_CONNECT_TIMEOUT_S,
    DEFAULT_IO_TIMEOUT_S,
    DEFAULT_PER_ATTEMPT_TIMEOUT_S,
    dial_stream,
)
from mail_core.net.policy import OutboundSecurityPolicy
from mail_core.net.proxy import ProxyConfig, env_would_proxy_url, resolve_outbound_proxy, validate_proxy_mode


class _DialedHTTPConnection(http.client.HTTPConnection):
    def __init__(
        self,
        host: str,
        port: int | None = None,
        timeout: float | None = DEFAULT_IO_TIMEOUT_S,
        *,
        dial_proxy: ProxyConfig | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_S,
        per_attempt_timeout: float = DEFAULT_PER_ATTEMPT_TIMEOUT_S,
        security_policy: OutboundSecurityPolicy | None = None,
        bulkhead: EndpointBulkhead | None = ...,  # type: ignore[assignment]
        ssl_context: ssl.SSLContext | None = None,
        use_tls: bool = False,
    ) -> None:
        resolved_timeout = (
            DEFAULT_IO_TIMEOUT_S
            if timeout is socket._GLOBAL_DEFAULT_TIMEOUT
            else timeout
        )
        super().__init__(host, port=port, timeout=resolved_timeout)
        self._dial_proxy = dial_proxy
        self._connect_timeout = float(connect_timeout)
        self._per_attempt_timeout = float(per_attempt_timeout)
        self._security_policy = security_policy
        self._bulkhead = bulkhead
        self._ssl_context = ssl_context
        self._use_tls = use_tls

    def connect(self) -> None:
        target_port = int(self.port or (443 if self._use_tls else 80))
        self.sock = dial_stream(
            self.host,
            target_port,
            tls=self._use_tls,
            ssl_context=self._ssl_context,
            proxy=self._dial_proxy,
            security_policy=self._security_policy,
            connect_timeout=self._connect_timeout,
            per_attempt_timeout=self._per_attempt_timeout,
            io_timeout=self.timeout,
            bulkhead=self._bulkhead,
        )


class _DialedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, *, opener_kwargs: dict[str, Any]) -> None:
        super().__init__()
        self._opener_kwargs = opener_kwargs

    def http_open(self, req: urllib.request.Request) -> Any:
        def _factory(host: str, **kwargs: Any) -> _DialedHTTPConnection:
            return _DialedHTTPConnection(
                host,
                timeout=kwargs.get("timeout", DEFAULT_IO_TIMEOUT_S),
                use_tls=False,
                **self._opener_kwargs,
            )

        return self.do_open(_factory, req)


class _DialedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(
        self,
        *,
        opener_kwargs: dict[str, Any],
        context: ssl.SSLContext | None = None,
    ) -> None:
        super().__init__(context=context)
        self._opener_kwargs = opener_kwargs
        self._ssl_context = context

    def https_open(self, req: urllib.request.Request) -> Any:
        def _factory(host: str, **kwargs: Any) -> _DialedHTTPConnection:
            return _DialedHTTPConnection(
                host,
                timeout=kwargs.get("timeout", DEFAULT_IO_TIMEOUT_S),
                use_tls=True,
                ssl_context=self._ssl_context,
                **self._opener_kwargs,
            )

        return self.do_open(_factory, req)


_STDLIB_URLOPEN = urllib.request.urlopen


def _should_use_custom_dial_opener(
    scheme: str,
    host: str,
    port: int,
    proxy: ProxyConfig | None,
    *,
    env: Mapping[str, str] | None,
    urlopen_fn: Callable[..., Any] | None,
) -> bool:
    if urlopen_fn is not None or urllib.request.urlopen is not _STDLIB_URLOPEN:
        return False
    if proxy is None:
        # Use custom direct opener when OS proxy env vars would otherwise hijack a
        # NO_PROXY / MAIL_CORE_NO_PROXY / direct-override target.
        return env_would_proxy_url(host, port, protocol=scheme, env=env)
    # Route all proxied traffic (http CONNECT, https tunnel, socks5, socks5h)
    # through dial_stream for bounded connect budgets, bulkhead isolation, and
    # unified TLS context handling.
    return True


def urlopen_outbound(
    req: urllib.request.Request,
    *,
    timeout: float = DEFAULT_IO_TIMEOUT_S,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT_S,
    per_attempt_timeout: float = DEFAULT_PER_ATTEMPT_TIMEOUT_S,
    explicit_proxy: str | None = None,
    explicit_no_proxy: str | None = None,
    proxy_mode: str | None = None,
    security_policy: OutboundSecurityPolicy | None = None,
    bulkhead: EndpointBulkhead | None = ...,  # type: ignore[assignment]
    ssl_context: ssl.SSLContext | None = None,
    env: Mapping[str, str] | None = None,
    _urlopen_fn: Callable[..., Any] | None = None,
) -> Any:
    """Execute ``urllib.request.Request`` honoring unified proxy & NO_PROXY policy.

    Handles SOCKS5/SOCKS5h, authenticated HTTP/HTTPS proxies, HTTPS proxy tunnels,
    and direct Pin-IP overrides via ``dial_stream`` while keeping standard
    ``urllib.request.urlopen`` compatibility for plain HTTP/direct unit tests.
    """
    parts = urlsplit(req.full_url)
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    port = parts.port or (443 if scheme == "https" else 80)

    proxy = resolve_outbound_proxy(
        host,
        port,
        explicit_proxy=explicit_proxy,
        explicit_no_proxy=explicit_no_proxy,
        proxy_mode=proxy_mode,
        protocol=scheme,
        env=env,
    )

    if _should_use_custom_dial_opener(
        scheme, host, port, proxy, env=env, urlopen_fn=_urlopen_fn
    ):
        # Empty ProxyHandler disables urllib's implicit env/system proxy resolution so
        # all proxying / NO_PROXY suppression runs purely through dial_stream.
        opener_kwargs: dict[str, Any] = {
            "dial_proxy": proxy,
            "connect_timeout": connect_timeout,
            "per_attempt_timeout": per_attempt_timeout,
            "security_policy": security_policy,
            "bulkhead": bulkhead,
        }
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _DialedHTTPHandler(opener_kwargs=opener_kwargs),
            _DialedHTTPSHandler(opener_kwargs=opener_kwargs, context=ssl_context),
        )
        try:
            return opener.open(req, timeout=timeout)
        except EndpointCircuitOpenError:
            raise
        except OSError as exc:
            if isinstance(exc, urllib.error.URLError):
                raise
            raise urllib.error.URLError(exc) from exc

    if _urlopen_fn is None and urllib.request.urlopen is _STDLIB_URLOPEN and validate_proxy_mode(proxy_mode) == "direct":
        # Prevent macOS _scproxy or OS proxy settings when caller requested direct mode.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(req, timeout=timeout)

    urlopen = _urlopen_fn or urllib.request.urlopen
    return urlopen(req, timeout=timeout)
