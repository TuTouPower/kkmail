"""Security and network transport layer for remote image proxy (t068).

Implements strict SSRF protection, DNS rebinding mitigation, safe bitmap magic number
detection, stateless URL token signing, and bounded streaming for remote images.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import socket
import urllib.parse
import uuid
from typing import Any, Iterator

import httpcore
import httpcore._backends.sync
import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from mail_core.security.auth import require_secret_key

_REMOTE_IMAGE_SALT = "kkmail/remote-image-proxy/v1"
REMOTE_IMAGE_TOKEN_MAX_AGE_SECONDS = 900  # 15 minutes
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MiB limit
CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 3
MAX_URL_LENGTH = 2048

# Safe bitmap image MIME types allowed through the proxy.
# SVG is strictly excluded for XSS defense-in-depth.
SUPPORTED_IMAGE_MIMES = frozenset({
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
})

# Extra reserved networks to block for SSRF defense
_EXTRA_BLOCKED_NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),     # CGNAT
    ipaddress.ip_network("198.18.0.0/15"),    # Benchmark tests
    ipaddress.ip_network("192.0.0.0/24"),     # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),     # TEST-NET-1
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),   # TEST-NET-3
    ipaddress.ip_network("169.254.169.254/32"),  # Cloud metadata IP
)


class SSRFSecurityError(ValueError):
    """Raised when an address or URL violates SSRF safety rules."""


class RemoteImageSizeLimitError(ValueError):
    """Raised when a remote image exceeds the maximum allowed size (10 MiB)."""


class UnsupportedImageFormatError(ValueError):
    """Raised when a remote payload is not a verified safe bitmap image format."""


class RemoteImageFetchError(RuntimeError):
    """Raised when fetching a remote image encounters a transport or protocol error."""


def _get_allowed_cidrs() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    env_val = os.environ.get("MAIL_CORE_PROXY_ALLOW_CIDRS", "").strip()
    if not env_val:
        return []
    cidrs = []
    for item in env_val.split(","):
        raw = item.strip()
        if raw:
            try:
                cidrs.append(ipaddress.ip_network(raw, strict=False))
            except ValueError:
                pass
    return cidrs


def is_safe_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if an IP is a public, non-reserved, non-loopback, non-private IP."""
    # Check configured allowlist overrides first (useful in controlled test environments)
    allowed_cidrs = _get_allowed_cidrs()
    for cidr in allowed_cidrs:
        if ip_obj in cidr:
            return True

    # Handle IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
    if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped:
        ip_obj = ip_obj.ipv4_mapped

    if ip_obj.is_loopback:
        return False
    if ip_obj.is_private:
        return False
    if ip_obj.is_link_local:
        return False
    if ip_obj.is_multicast:
        return False
    if ip_obj.is_reserved:
        return False
    if ip_obj.is_unspecified:
        return False

    for net in _EXTRA_BLOCKED_NETWORKS:
        if ip_obj.version == net.version and ip_obj in net:
            return False

    return True


def validate_remote_url(raw_url: str) -> urllib.parse.SplitResult:
    """Validate remote URL for scheme, ports, credentials and length."""
    if not raw_url or not isinstance(raw_url, str):
        raise SSRFSecurityError("URL is required")

    trimmed = raw_url.strip()
    if len(trimmed) > MAX_URL_LENGTH:
        raise SSRFSecurityError(f"URL exceeds max length of {MAX_URL_LENGTH}")

    parts = urllib.parse.urlsplit(trimmed)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise SSRFSecurityError(f"Unsupported URL scheme: {parts.scheme!r}")

    if parts.username or parts.password:
        raise SSRFSecurityError("URL userinfo credentials are not allowed")

    if not parts.hostname:
        raise SSRFSecurityError("URL host is missing")

    port = parts.port
    if port is not None:
        if scheme == "http" and port != 80:
            raise SSRFSecurityError(f"Non-standard HTTP port {port} is not allowed")
        if scheme == "https" and port != 443:
            raise SSRFSecurityError(f"Non-standard HTTPS port {port} is not allowed")

    return parts


class SSRFSafeSyncBackend(httpcore.SyncBackend):
    """Custom network backend that enforces strict SSRF DNS resolution and pinning.

    Prevents DNS rebinding by connecting directly to the validated IP while preserving
    TLS SNI verification for HTTPS.
    """

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> httpcore.NetworkStream:
        # Check if host is already a literal IP
        try:
            literal_ip = ipaddress.ip_address(host)
            if not is_safe_ip(literal_ip):
                raise SSRFSecurityError(f"SSRF blocked target IP: {host}")
            target_ip_str = host
        except ValueError:
            # Resolve DNS
            try:
                addr_infos = socket.getaddrinfo(
                    host,
                    port,
                    family=socket.AF_UNSPEC,
                    type=socket.SOCK_STREAM,
                )
            except socket.gaierror as exc:
                raise SSRFSecurityError(f"DNS resolution failed for {host}: {exc}") from exc

            if not addr_infos:
                raise SSRFSecurityError(f"No IP addresses resolved for {host}")

            # Verify every resolved address; reject immediately if any resolved IP is dangerous
            safe_ips: list[str] = []
            for info in addr_infos:
                ip_str = info[4][0]
                try:
                    ip_obj = ipaddress.ip_address(ip_str)
                except ValueError:
                    raise SSRFSecurityError(f"Invalid resolved IP: {ip_str}")
                if not is_safe_ip(ip_obj):
                    raise SSRFSecurityError(f"SSRF blocked resolved IP: {ip_str} for host {host}")
                safe_ips.append(ip_str)

            target_ip_str = safe_ips[0]

        address = (target_ip_str, port)
        source_address = None if local_address is None else (local_address, 0)

        exc_map = {
            socket.timeout: httpcore.ConnectTimeout,
            OSError: httpcore.ConnectError,
        }

        with httpcore._backends.sync.map_exceptions(exc_map):
            sock = socket.create_connection(
                address,
                timeout,
                source_address=source_address,
            )
            if socket_options:
                for option in socket_options:
                    sock.setsockopt(*option)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        return httpcore._backends.sync.SyncStream(sock)


class SSRFSafeTransport(httpx.HTTPTransport):
    """HTTPTransport configured with SSRFSafeSyncBackend."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._pool = httpcore.ConnectionPool(
            ssl_context=self._pool._ssl_context,
            network_backend=SSRFSafeSyncBackend(),
        )


def detect_safe_image_mime(header: bytes) -> str | None:
    """Inspect magic numbers of payload header and return safe MIME or None.

    Supports PNG, JPEG, GIF, WebP. Rejects SVG and non-bitmap formats.
    """
    if len(header) < 12:
        return None

    # PNG: \x89PNG\r\n\x1a\n
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    # JPEG: \xff\xd8\xff
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"

    # GIF: GIF87a or GIF89a
    if header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return "image/gif"

    # WebP: starts with RIFF and has WEBP at offset 8..12
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"

    return None


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        require_secret_key(),
        salt=_REMOTE_IMAGE_SALT,
        signer_kwargs={"digest_method": hashlib.sha256},
    )


def sign_remote_image_proxy_token(
    message_id: str | uuid.UUID,
    target_url: str,
) -> str:
    """Generate stateless tamper-proof token binding message_id and target_url."""
    payload = {
        "ver": 1,
        "purp": "remote-image",
        "msg_id": str(message_id),
        "url": target_url.strip(),
    }
    return _serializer().dumps(payload)


def verify_remote_image_proxy_token(
    message_id: str | uuid.UUID,
    target_url: str,
    token: str,
    max_age: int = REMOTE_IMAGE_TOKEN_MAX_AGE_SECONDS,
) -> bool:
    """Verify that the token was signed with the secret key and binds to message_id and url."""
    if not token or not token.strip():
        return False
    try:
        data: dict[str, Any] = _serializer().loads(token.strip(), max_age=max_age)
        return (
            data.get("ver") == 1
            and data.get("purp") == "remote-image"
            and data.get("msg_id") == str(message_id)
            and data.get("url") == target_url.strip()
        )
    except (BadSignature, SignatureExpired, Exception):
        return False


def build_remote_image_proxy_url(
    message_id: str | uuid.UUID,
    target_url: str,
) -> str:
    """Construct full internal proxy endpoint URL with signed token."""
    token = sign_remote_image_proxy_token(message_id, target_url)
    encoded_url = urllib.parse.quote(target_url, safe="")
    return f"/api/mail/messages/{message_id}/remote-images?url={encoded_url}&token={token}"


import re

_IMG_SRC_RE = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["'](https?://[^"'>\s]+)["']""", re.IGNORECASE)
_BG_URL_RE = re.compile(r"""url\s*\(\s*["']?(https?://[^"')>\s]+)["']?\s*\)""", re.IGNORECASE)


def extract_remote_image_urls(html: str | None, max_urls: int = 200) -> list[str]:
    """Scan HTML body for http(s) image URLs from img[src] and background-image styles."""
    if not html or not isinstance(html, str):
        return []
    found: set[str] = set()
    order: list[str] = []

    for match in _IMG_SRC_RE.finditer(html):
        url = match.group(1).strip()
        if url and url not in found and len(url) <= MAX_URL_LENGTH:
            found.add(url)
            order.append(url)
            if len(order) >= max_urls:
                return order

    for match in _BG_URL_RE.finditer(html):
        url = match.group(1).strip()
        if url and url not in found and len(url) <= MAX_URL_LENGTH:
            found.add(url)
            order.append(url)
            if len(order) >= max_urls:
                return order

    return order


def fetch_safe_remote_image(
    target_url: str,
    transport: httpx.HTTPTransport | None = None,
) -> tuple[str, Iterator[bytes]]:
    """Fetch remote image through SSRF-protected transport with manual redirect checks.

    Returns (mime_type, byte_stream_iterator).
    Raises SSRFSecurityError, RemoteImageSizeLimitError, UnsupportedImageFormatError,
    or RemoteImageFetchError.
    """
    current_url = target_url
    redirect_count = 0

    if transport is None:
        transport = SSRFSafeTransport()

    client = httpx.Client(
        transport=transport,
        follow_redirects=False,
        timeout=httpx.Timeout(READ_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS),
    )

    clean_headers = {
        "Accept": "image/png,image/jpeg,image/gif,image/webp,*/*;q=0.8",
        "User-Agent": "kkmail-image-proxy/1.0",
    }

    try:
        while True:
            validate_remote_url(current_url)

            response = client.send(
                client.build_request("GET", current_url, headers=clean_headers),
                stream=True,
            )

            # Handle redirects manually to enforce SSRF validation at every hop
            if response.status_code in (301, 302, 303, 307, 308):
                response.close()
                redirect_count += 1
                if redirect_count > MAX_REDIRECTS:
                    raise SSRFSecurityError(f"Too many redirects (exceeded max {MAX_REDIRECTS})")
                location = response.headers.get("Location")
                if not location:
                    raise RemoteImageFetchError("Redirect missing Location header")
                current_url = urllib.parse.urljoin(current_url, location)
                continue

            if response.status_code != 200:
                response.close()
                raise RemoteImageFetchError(f"Upstream HTTP error status={response.status_code}")

            # Stream body and check magic number on first chunk
            stream_iter = response.iter_bytes(chunk_size=16384)
            try:
                first_chunk = next(stream_iter)
            except StopIteration:
                response.close()
                raise UnsupportedImageFormatError("Empty response body")

            mime = detect_safe_image_mime(first_chunk)
            if not mime or mime not in SUPPORTED_IMAGE_MIMES:
                response.close()
                raise UnsupportedImageFormatError(
                    f"Unsupported or dangerous image format (detected: {mime!r})"
                )

            # Generator that yields chunks while enforcing the 10 MiB limit
            def _bounded_stream() -> Iterator[bytes]:
                total_bytes = len(first_chunk)
                if total_bytes > MAX_IMAGE_BYTES:
                    response.close()
                    client.close()
                    raise RemoteImageSizeLimitError(f"Image exceeds limit of {MAX_IMAGE_BYTES} bytes")
                yield first_chunk

                try:
                    for chunk in stream_iter:
                        total_bytes += len(chunk)
                        if total_bytes > MAX_IMAGE_BYTES:
                            response.close()
                            client.close()
                            raise RemoteImageSizeLimitError(
                                f"Image exceeds limit of {MAX_IMAGE_BYTES} bytes"
                            )
                        yield chunk
                finally:
                    response.close()
                    client.close()

            return mime, _bounded_stream()

    except Exception:
        client.close()
        raise
