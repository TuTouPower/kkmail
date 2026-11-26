"""HTTP/HTTPS CONNECT, SOCKS5/SOCKS5h, and TLS-in-TLS proxy tunnel helpers."""

from __future__ import annotations

import base64
import ipaddress
import selectors
import socket
import ssl
import struct
import threading
import time
from typing import Callable

from mail_core.net.policy import validate_hostname_syntax
from mail_core.net.proxy import ProxyConfig

_MAX_HTTP_CONNECT_HEADER_BYTES = 16 * 1024

_SOCKS5_ERRORS = {
    0x01: "general SOCKS server failure",
    0x02: "connection not allowed by ruleset",
    0x03: "network unreachable",
    0x04: "host unreachable",
    0x05: "connection refused",
    0x06: "TTL expired",
    0x07: "command not supported",
    0x08: "address type not supported",
}


class ProxyTunnelError(ConnectionError):
    """Raised when a proxy rejects or corrupts tunnel establishment."""

    failure_phase = "proxy_connect"

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        socks_reply: int | None = None,
        proxy_key: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.socks_reply = socks_reply
        self.proxy_key = proxy_key


def _set_remaining_timeout(
    sock: socket.socket,
    deadline: float,
    clock: Callable[[], float],
    phase: str,
) -> None:
    remaining = deadline - clock()
    if remaining <= 0:
        raise TimeoutError(f"{phase} timed out")
    sock.settimeout(remaining)


def _recv_exact(
    sock: socket.socket,
    size: int,
    *,
    deadline: float,
    clock: Callable[[], float],
    phase: str,
) -> bytes:
    buf = bytearray()
    while len(buf) < size:
        _set_remaining_timeout(sock, deadline, clock, phase)
        chunk = sock.recv(size - len(buf))
        if not chunk:
            raise ProxyTunnelError(f"proxy closed connection during {phase}")
        buf.extend(chunk)
    return bytes(buf)


def _build_connect_request(target_host: str, target_port: int, proxy: ProxyConfig) -> bytes:
    clean_host = validate_hostname_syntax(target_host)
    if not (1 <= int(target_port) <= 65535):
        raise ValueError(f"invalid target port: {target_port}")
    host_header = f"[{clean_host}]" if ":" in clean_host else clean_host.encode("idna").decode("ascii")
    authority = f"{host_header}:{int(target_port)}"
    lines = [f"CONNECT {authority} HTTP/1.1", f"Host: {authority}"]
    if proxy.username is not None or proxy.password is not None:
        raw_user = proxy.username or ""
        raw_pass = proxy.password or ""
        if any(ch in ("\r", "\n", "\x00") for ch in raw_user + raw_pass):
            raise ProxyTunnelError("proxy credentials contain invalid control characters", proxy_key=proxy.safe_key())
        token = base64.b64encode(f"{raw_user}:{raw_pass}".encode("utf-8")).decode("ascii")
        lines.append(f"Proxy-Authorization: Basic {token}")
    lines.append("Proxy-Connection: Keep-Alive")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")


def _read_connect_status(
    sock: socket.socket,
    *,
    proxy: ProxyConfig,
    deadline: float,
    clock: Callable[[], float],
) -> int:
    # Read 1 byte at a time so zero post-header TLS/IMAP bytes are consumed.
    header_buf = bytearray()
    while not header_buf.endswith(b"\r\n\r\n"):
        if len(header_buf) >= _MAX_HTTP_CONNECT_HEADER_BYTES:
            raise ProxyTunnelError("HTTP CONNECT response header exceeded limit", proxy_key=proxy.safe_key())
        _set_remaining_timeout(sock, deadline, clock, "HTTP CONNECT response")
        byte = sock.recv(1)
        if not byte:
            raise ProxyTunnelError("proxy closed connection during HTTP CONNECT response", proxy_key=proxy.safe_key())
        header_buf.extend(byte)
    status_line = header_buf.split(b"\r\n", 1)[0].decode("latin-1", errors="replace").strip()
    parts = status_line.split(" ", 2)
    if len(parts) < 2 or not parts[0].upper().startswith("HTTP/") or not parts[1].isdigit():
        raise ProxyTunnelError(f"malformed HTTP CONNECT status line from {proxy.safe_key()}", proxy_key=proxy.safe_key())
    return int(parts[1])


def handshake_http_connect(
    sock: socket.socket,
    *,
    target_host: str,
    target_port: int,
    proxy: ProxyConfig,
    deadline: float,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Establish an HTTP/HTTPS CONNECT tunnel through ``proxy`` to ``target_host:target_port``."""
    payload = _build_connect_request(target_host, target_port, proxy)
    _set_remaining_timeout(sock, deadline, clock, "HTTP CONNECT send")
    sock.sendall(payload)
    status = _read_connect_status(sock, proxy=proxy, deadline=deadline, clock=clock)
    if status == 407:
        raise ProxyTunnelError(
            f"HTTP proxy authentication required/rejected (407) by {proxy.safe_key()}",
            status=407,
            proxy_key=proxy.safe_key(),
        )
    if not (200 <= status < 300):
        raise ProxyTunnelError(
            f"HTTP CONNECT rejected with status {status} by {proxy.safe_key()}",
            status=status,
            proxy_key=proxy.safe_key(),
        )


def _encode_socks5_target(target_host: str, target_ip: str | None) -> bytes:
    """Encode SOCKS5 address family + payload (IPv4, IPv6, or IDNA domain)."""
    if target_ip is not None:
        ip_obj = ipaddress.ip_address(target_ip)
        return (b"\x01" if ip_obj.version == 4 else b"\x04") + ip_obj.packed
    clean_host = validate_hostname_syntax(target_host)
    try:
        literal_ip = ipaddress.ip_address(clean_host)
    except ValueError:
        domain_bytes = clean_host.encode("idna")
        if not domain_bytes or len(domain_bytes) > 255:
            raise ProxyTunnelError(f"target domain length invalid for SOCKS5: {clean_host!r}")
        return bytes([0x03, len(domain_bytes)]) + domain_bytes
    return (b"\x01" if literal_ip.version == 4 else b"\x04") + literal_ip.packed


def _socks5_negotiate_auth(
    sock: socket.socket,
    *,
    proxy: ProxyConfig,
    deadline: float,
    clock: Callable[[], float],
) -> None:
    has_auth = proxy.username is not None or proxy.password is not None
    greeting = b"\x05\x02\x00\x02" if has_auth else b"\x05\x01\x00"
    _set_remaining_timeout(sock, deadline, clock, "SOCKS5 greeting")
    sock.sendall(greeting)

    ver, method = _recv_exact(sock, 2, deadline=deadline, clock=clock, phase="SOCKS5 method")
    if ver != 0x05:
        raise ProxyTunnelError(f"unexpected SOCKS version {ver!r} from {proxy.safe_key()}", proxy_key=proxy.safe_key())
    if method == 0xFF:
        raise ProxyTunnelError(
            f"SOCKS5 proxy {proxy.safe_key()} rejected offered authentication methods",
            proxy_key=proxy.safe_key(),
        )
    if method == 0x00:
        return
    if method != 0x02:
        raise ProxyTunnelError(
            f"unsupported SOCKS5 auth method {method!r} selected by {proxy.safe_key()}",
            proxy_key=proxy.safe_key(),
        )

    user_bytes = (proxy.username or "").encode("utf-8")
    pass_bytes = (proxy.password or "").encode("utf-8")
    if not (1 <= len(user_bytes) <= 255) or len(pass_bytes) > 255:
        raise ProxyTunnelError("SOCKS5 username/password length invalid", proxy_key=proxy.safe_key())
    auth_req = bytes([0x01, len(user_bytes)]) + user_bytes + bytes([len(pass_bytes)]) + pass_bytes
    _set_remaining_timeout(sock, deadline, clock, "SOCKS5 auth")
    sock.sendall(auth_req)
    sub_ver, auth_status = _recv_exact(sock, 2, deadline=deadline, clock=clock, phase="SOCKS5 auth reply")
    if sub_ver != 0x01 or auth_status != 0x00:
        raise ProxyTunnelError(
            f"SOCKS5 authentication failed on {proxy.safe_key()}",
            status=407,
            proxy_key=proxy.safe_key(),
        )


def _socks5_drain_bound_addr(
    sock: socket.socket,
    *,
    atyp: int,
    proxy: ProxyConfig,
    deadline: float,
    clock: Callable[[], float],
) -> None:
    if atyp == 0x01:
        _recv_exact(sock, 6, deadline=deadline, clock=clock, phase="SOCKS5 BND IPv4")
    elif atyp == 0x04:
        _recv_exact(sock, 18, deadline=deadline, clock=clock, phase="SOCKS5 BND IPv6")
    elif atyp == 0x03:
        domain_len = _recv_exact(sock, 1, deadline=deadline, clock=clock, phase="SOCKS5 BND domain len")[0]
        _recv_exact(sock, domain_len + 2, deadline=deadline, clock=clock, phase="SOCKS5 BND domain")
    else:
        raise ProxyTunnelError(f"unknown SOCKS5 ATYP {atyp!r}", proxy_key=proxy.safe_key())


def handshake_socks5(
    sock: socket.socket,
    *,
    target_host: str,
    target_port: int,
    target_ip: str | None,
    proxy: ProxyConfig,
    deadline: float,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Establish a SOCKS5 / SOCKS5h CONNECT stream tunnel through ``proxy``."""
    if not (1 <= int(target_port) <= 65535):
        raise ValueError(f"invalid target port: {target_port}")
    _socks5_negotiate_auth(sock, proxy=proxy, deadline=deadline, clock=clock)

    addr_payload = _encode_socks5_target(target_host, target_ip)
    req = b"\x05\x01\x00" + addr_payload + struct.pack("!H", int(target_port))
    _set_remaining_timeout(sock, deadline, clock, "SOCKS5 CONNECT")
    sock.sendall(req)

    rep_ver, rep, _rsv, atyp = _recv_exact(
        sock, 4, deadline=deadline, clock=clock, phase="SOCKS5 CONNECT reply"
    )
    if rep_ver != 0x05:
        raise ProxyTunnelError(f"unexpected SOCKS5 reply version {rep_ver!r}", proxy_key=proxy.safe_key())
    _socks5_drain_bound_addr(sock, atyp=atyp, proxy=proxy, deadline=deadline, clock=clock)
    if rep != 0x00:
        detail = _SOCKS5_ERRORS.get(rep, f"error code {rep:#x}")
        raise ProxyTunnelError(
            f"SOCKS5 CONNECT failed ({detail}) via {proxy.safe_key()}",
            socks_reply=rep,
            proxy_key=proxy.safe_key(),
        )


def _forward_readable(src: socket.socket, dst: socket.socket) -> bool:
    """Copy available bytes (including OpenSSL pending buffer) from ``src`` to ``dst``.

    Returns False on clean EOF so the bridge tears down cleanly.
    """
    while True:
        try:
            chunk = src.recv(16384)
        except (ssl.SSLWantReadError, BlockingIOError):
            return True
        if not chunk:
            return False
        dst.setblocking(True)
        try:
            dst.sendall(chunk)
        finally:
            dst.setblocking(False)
        if not (isinstance(src, ssl.SSLSocket) and src.pending() > 0):
            return True


def bridge_tls_socket(outer_ssl_sock: ssl.SSLSocket) -> socket.socket:
    """Bridge an outer TLS proxy socket over a local socketpair for inner TLS wrapping.

    CPython's ``SSLContext.wrap_socket`` detaches the underlying raw fd and
    would strip the outer HTTPS proxy TLS session if called directly on
    ``outer_ssl_sock``. Exposing an OS ``socketpair`` endpoint lets the inner
    ``SSLSocket`` retain full ``fileno``/``makefile``/``settimeout``/``shutdown``
    semantics while a single pump thread owns all I/O on ``outer_ssl_sock``.
    """
    app_sock, peer_sock = socket.socketpair()

    def _pump() -> None:
        sel = selectors.DefaultSelector()
        outer_ssl_sock.setblocking(False)
        peer_sock.setblocking(False)
        sel.register(outer_ssl_sock, selectors.EVENT_READ, peer_sock)
        sel.register(peer_sock, selectors.EVENT_READ, outer_ssl_sock)
        try:
            while True:
                for key, _ in sel.select(timeout=1.0):
                    src = key.fileobj
                    dst = key.data
                    if not _forward_readable(src, dst):  # type: ignore[arg-type]
                        return
        except OSError:
            pass
        finally:
            for item in (sel, outer_ssl_sock, peer_sock):
                try:
                    item.close()
                except OSError:
                    pass

    threading.Thread(target=_pump, name="tls-tunnel-bridge", daemon=True).start()
    return app_sock
