"""imaplib adapters routed through the unified outbound dialer."""

from __future__ import annotations

import imaplib
import ssl
import sys
from typing import Any, Callable

from mail_core.net.bulkhead import EndpointBulkhead
from mail_core.net.dialer import (
    ConnectorFn,
    DEFAULT_CONNECT_TIMEOUT_S,
    DEFAULT_IO_TIMEOUT_S,
    DEFAULT_PER_ATTEMPT_TIMEOUT_S,
    ResolverFn,
    dial_stream,
)
from mail_core.net.policy import OutboundSecurityPolicy
from mail_core.net.proxy import ProxyConfig


class DialedIMAP4(imaplib.IMAP4):
    """Plaintext IMAP4 client opening sockets via ``mail_core.net.dial_stream``."""

    def __init__(
        self,
        host: str = "",
        port: int = imaplib.IMAP4_PORT,
        *,
        timeout: float | None = DEFAULT_IO_TIMEOUT_S,
        connect_timeout: float | None = None,
        per_attempt_timeout: float | None = None,
        proxy: ProxyConfig | None = None,
        security_policy: OutboundSecurityPolicy | None = None,
        bulkhead: EndpointBulkhead | None = ...,  # type: ignore[assignment]
        resolver: ResolverFn | None = None,
        connector: ConnectorFn | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._dial_options: dict[str, Any] = {
            "connect_timeout": float(connect_timeout) if connect_timeout is not None else None,
            "per_attempt_timeout": float(per_attempt_timeout) if per_attempt_timeout is not None else None,
            "proxy": proxy,
            "security_policy": security_policy,
            "bulkhead": bulkhead,
            "resolver": resolver,
            "connector": connector,
            "clock": clock,
        }
        super().__init__(host, port, timeout)

    def _create_socket(self, timeout: float | None) -> Any:
        if timeout is not None and not timeout:
            raise ValueError("Non-blocking socket (timeout=0) is not supported")
        if not self.host:
            raise ValueError("IMAP host is required")
        sys.audit("imaplib.open", self, self.host, self.port)
        return dial_stream(
            self.host,
            int(self.port),
            tls=False,
            io_timeout=timeout,
            **self._dial_options,
        )


class DialedIMAP4_SSL(imaplib.IMAP4_SSL):
    """TLS IMAP4 client performing connect/proxy/TLS via ``dial_stream``."""

    def __init__(
        self,
        host: str = "",
        port: int = imaplib.IMAP4_SSL_PORT,
        *,
        ssl_context: ssl.SSLContext | None = None,
        timeout: float | None = DEFAULT_IO_TIMEOUT_S,
        connect_timeout: float | None = None,
        per_attempt_timeout: float | None = None,
        proxy: ProxyConfig | None = None,
        security_policy: OutboundSecurityPolicy | None = None,
        bulkhead: EndpointBulkhead | None = ...,  # type: ignore[assignment]
        resolver: ResolverFn | None = None,
        connector: ConnectorFn | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._dial_options: dict[str, Any] = {
            "connect_timeout": float(connect_timeout) if connect_timeout is not None else None,
            "per_attempt_timeout": float(per_attempt_timeout) if per_attempt_timeout is not None else None,
            "proxy": proxy,
            "security_policy": security_policy,
            "bulkhead": bulkhead,
            "resolver": resolver,
            "connector": connector,
            "clock": clock,
        }
        super().__init__(host, port, ssl_context=ssl_context, timeout=timeout)

    def _create_socket(self, timeout: float | None) -> Any:
        if timeout is not None and not timeout:
            raise ValueError("Non-blocking socket (timeout=0) is not supported")
        if not self.host:
            raise ValueError("IMAP host is required")
        sys.audit("imaplib.open", self, self.host, self.port)
        return dial_stream(
            self.host,
            int(self.port),
            tls=True,
            ssl_context=self.ssl_context,
            io_timeout=timeout,
            **self._dial_options,
        )
