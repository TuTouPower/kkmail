"""Shared loopback TLS, HTTP/HTTPS proxy, SOCKS5, and image servers for outbound tests."""

from __future__ import annotations

import base64
import datetime
import http.server
import ipaddress
import selectors
import socket
import ssl
import struct
import threading
from pathlib import Path
from typing import Any, cast

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

VALID_1X1_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
    b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def write_self_signed_cert(tmp_path: Path, dns_names: list[str], prefix: str = "server") -> tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, dns_names[0])])
    now = datetime.datetime.now(datetime.timezone.utc)
    san_entries: list[x509.GeneralName] = []
    for entry in dns_names:
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(entry)))
        except ValueError:
            san_entries.append(x509.DNSName(entry))
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=7))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / f"{prefix}.crt"
    key_path = tmp_path / f"{prefix}.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def client_ssl_context(ca_files: list[Path]) -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    for path in ca_files:
        ctx.load_verify_locations(cafile=str(path))
    ctx.check_hostname = True
    return ctx


def _forward_chunk(src: socket.socket, dst: socket.socket) -> bool:
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


def relay_sockets(a: socket.socket, b: socket.socket) -> None:
    sel = selectors.DefaultSelector()
    a.setblocking(False)
    b.setblocking(False)
    sel.register(a, selectors.EVENT_READ, b)
    sel.register(b, selectors.EVENT_READ, a)
    try:
        while True:
            for key, _ in sel.select(timeout=1.0):
                if not _forward_chunk(cast(socket.socket, key.fileobj), cast(socket.socket, key.data)):
                    return
    except OSError:
        pass
    finally:
        sel.close()
        for sock in (a, b):
            try:
                sock.close()
            except OSError:
                pass


class LoopbackHttpConnectProxy:
    """Loopback HTTP/HTTPS CONNECT proxy recording authority & optionally wrapping outer TLS."""

    def __init__(
        self,
        upstream_host: str,
        upstream_port: int,
        *,
        expected_auth: tuple[str, str] | None = None,
        forced_status: int | None = None,
        tls_cert_key: tuple[Path, Path] | None = None,
    ) -> None:
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.expected_auth = expected_auth
        self.forced_status = forced_status
        self.requests: list[str] = []
        self._tls_ctx: ssl.SSLContext | None = None
        if tls_cert_key is not None:
            self._tls_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self._tls_ctx.load_cert_chain(str(tls_cert_key[0]), str(tls_cert_key[1]))
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self.port = self._sock.getsockname()[1]
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> LoopbackHttpConnectProxy:
        self._thread.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self._stop = True
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, raw_client: socket.socket) -> None:
        client: socket.socket = raw_client
        buf = bytearray()
        try:
            if self._tls_ctx is not None:
                client = self._tls_ctx.wrap_socket(raw_client, server_side=True)
            while b"\r\n\r\n" not in buf:
                chunk = client.recv(1024)
                if not chunk:
                    client.close()
                    return
                buf.extend(chunk)
            lines = buf.decode("latin-1").split("\r\n")
            first_parts = lines[0].split(" ")
            self.requests.append(first_parts[1] if len(first_parts) >= 2 else "")

            if self.forced_status is not None:
                client.sendall(f"HTTP/1.1 {self.forced_status} Err\r\nContent-Length: 0\r\n\r\n".encode("ascii"))
                client.close()
                return

            if self.expected_auth is not None:
                expected_tok = base64.b64encode(
                    f"{self.expected_auth[0]}:{self.expected_auth[1]}".encode("utf-8")
                ).decode("ascii")
                auth_header = next(
                    (ln.split(":", 1)[1].strip() for ln in lines[1:] if ln.lower().startswith("proxy-authorization:")),
                    "",
                )
                if auth_header != f"Basic {expected_tok}":
                    client.sendall(b"HTTP/1.1 407 Proxy Auth Required\r\nProxy-Authenticate: Basic\r\n\r\n")
                    client.close()
                    return

            upstream = socket.create_connection((self.upstream_host, self.upstream_port), timeout=5.0)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            leftover = bytes(buf.split(b"\r\n\r\n", 1)[1])
            if leftover:
                upstream.sendall(leftover)
            relay_sockets(client, upstream)
        except OSError:
            try:
                client.close()
            except OSError:
                pass


class LoopbackSocks5Proxy:
    """Real loopback SOCKS5/SOCKS5h proxy recording ATYP & target address."""

    def __init__(self, upstream_host: str, upstream_port: int, *, expected_auth: tuple[str, str] | None = None) -> None:
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port
        self.expected_auth = expected_auth
        self.connects: list[tuple[int, str, int]] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self.port = self._sock.getsockname()[1]
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> LoopbackSocks5Proxy:
        self._thread.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self._stop = True
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _recv_exact(self, conn: socket.socket, n: int) -> bytes:
        data = bytearray()
        while len(data) < n:
            chunk = conn.recv(n - len(data))
            if not chunk:
                raise EOFError
            data.extend(chunk)
        return bytes(data)

    def _handle_client(self, client: socket.socket) -> None:
        try:
            ver, nmethods = self._recv_exact(client, 2)
            assert ver == 5
            methods = self._recv_exact(client, nmethods)
            if self.expected_auth is not None:
                if 2 not in methods:
                    client.sendall(b"\x05\xff"); client.close(); return
                client.sendall(b"\x05\x02")
                _sub = self._recv_exact(client, 1)
                user = self._recv_exact(client, self._recv_exact(client, 1)[0]).decode("utf-8")
                pw = self._recv_exact(client, self._recv_exact(client, 1)[0]).decode("utf-8")
                if (user, pw) != self.expected_auth:
                    client.sendall(b"\x01\x01"); client.close(); return
                client.sendall(b"\x01\x00")
            else:
                client.sendall(b"\x05\x00")

            ver, cmd, _rsv, atyp = self._recv_exact(client, 4)
            assert ver == 5 and cmd == 1
            if atyp == 1:
                dest = socket.inet_ntop(socket.AF_INET, self._recv_exact(client, 4))
            elif atyp == 3:
                dest = self._recv_exact(client, self._recv_exact(client, 1)[0]).decode("ascii")
            elif atyp == 4:
                dest = socket.inet_ntop(socket.AF_INET6, self._recv_exact(client, 16))
            else:
                client.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00"); client.close(); return
            dest_port = struct.unpack("!H", self._recv_exact(client, 2))[0]
            self.connects.append((atyp, dest, dest_port))
            upstream = socket.create_connection((self.upstream_host, self.upstream_port), timeout=5.0)
            client.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01" + struct.pack("!H", self.upstream_port))
            relay_sockets(client, upstream)
        except Exception:
            try:
                client.close()
            except OSError:
                pass


class LoopbackTlsImapServer:
    """Minimal real TLS IMAP server recording SNI and supporting LIST & IDLE."""

    def __init__(self, cert_path: Path, key_path: Path, *, folder_name: str = "INBOX") -> None:
        self.sni_seen: list[str | None] = []
        self.folder_name = folder_name
        self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._ctx.load_cert_chain(str(cert_path), str(key_path))
        self._ctx.sni_callback = lambda _s, name, _c: self.sni_seen.append(name)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self.port = self._sock.getsockname()[1]
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> LoopbackTlsImapServer:
        self._thread.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self._stop = True
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)

    def _serve(self) -> None:
        while not self._stop:
            try:
                raw_conn, _ = self._sock.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_conn, args=(raw_conn,), daemon=True).start()

    def _handle_conn(self, raw_conn: socket.socket) -> None:
        try:
            conn = self._ctx.wrap_socket(raw_conn, server_side=True)
            conn.sendall(b"* OK [CAPABILITY IMAP4rev1 IDLE ID] Test IMAP Ready\r\n")
            reader = conn.makefile("r", encoding="latin-1", newline="\r\n")
            for line in reader:
                stripped = line.rstrip("\r\n")
                if not stripped:
                    continue
                parts = stripped.split(" ", 2)
                tag = parts[0]
                cmd = parts[1].upper() if len(parts) > 1 else ""
                if cmd == "CAPABILITY":
                    conn.sendall(b"* CAPABILITY IMAP4rev1 IDLE ID\r\n" + f"{tag} OK CAPABILITY completed\r\n".encode("ascii"))
                elif cmd == "LIST":
                    conn.sendall(
                        f'* LIST (\\HasNoChildren) "/" "{self.folder_name}"\r\n{tag} OK LIST completed\r\n'.encode("ascii")
                    )
                elif cmd in ("EXAMINE", "SELECT"):
                    conn.sendall(b"* 1 EXISTS\r\n" + f"{tag} OK [READ-ONLY] SELECT completed\r\n".encode("ascii"))
                elif cmd == "IDLE":
                    conn.sendall(b"+ idling\r\n* 2 EXISTS\r\n")
                    if reader.readline():
                        conn.sendall(f"{tag} OK IDLE completed\r\n".encode("ascii"))
                elif cmd == "LOGOUT":
                    conn.sendall(b"* BYE closing\r\n" + f"{tag} OK LOGOUT completed\r\n".encode("ascii"))
                    break
                else:
                    conn.sendall(f"{tag} OK completed\r\n".encode("ascii"))
            conn.close()
        except Exception:
            try:
                raw_conn.close()
            except OSError:
                pass


class LoopbackHttpsServer:
    """Minimal HTTPS JSON + PNG image server for testing urllib & remote_image_proxy."""

    def __init__(self, cert_path: Path | None, key_path: Path | None) -> None:
        self.sni_seen: list[str | None] = []
        self.requests: list[str] = []
        outer = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                outer.requests.append(self.path)
                if self.path.endswith(".png"):
                    payload, ctype = VALID_1X1_PNG, "image/png"
                else:
                    payload, ctype = b'{"ok": true, "via": "proxy"}', "application/json"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):  # noqa: N802
                outer.requests.append(self.path)
                _ = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = b'{"access_token": "tok-123", "expires_in": 3600}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: Any) -> None:
                return

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        if cert_path is not None and key_path is not None:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(str(cert_path), str(key_path))
            ctx.sni_callback = lambda _s, name, _c: outer.sni_seen.append(name)
            self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> LoopbackHttpsServer:
        self._thread.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=2.0)


class SilentAcceptServer:
    """TCP listener that accepts connections and never responds (stalls TLS handshake)."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(16)
        self.port = self._sock.getsockname()[1]
        self.accepted: list[socket.socket] = []
        self._stop = False
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def __enter__(self) -> SilentAcceptServer:
        self._thread.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self._stop = True
        try:
            self._sock.close()
        except OSError:
            pass
        for conn in self.accepted:
            try:
                conn.close()
            except OSError:
                pass
        self._thread.join(timeout=2.0)

    def _serve(self) -> None:
        while not self._stop:
            try:
                conn, _ = self._sock.accept()
                self.accepted.append(conn)
            except OSError:
                break
