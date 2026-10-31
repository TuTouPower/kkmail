"""Security and network transport layer for remote image proxy (t068).

Implements strict SSRF protection, DNS rebinding mitigation, safe bitmap magic number
detection, stateless URL token signing, and bounded streaming for remote images.
Implemented strictly using Python standard libraries (http.client, socket, ssl).
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import os
import re
import socket
import ssl
import urllib.parse
import uuid
from html.parser import HTMLParser
from typing import Any, Callable, Iterator

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from mail_core.security.auth import require_secret_key

_REMOTE_IMAGE_SALT = "kkmail/remote-image-proxy/v1"
REMOTE_IMAGE_TOKEN_MAX_AGE_SECONDS = 900  # 15 minutes
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MiB limit
MAX_SVG_BYTES = 64 * 1024  # SVGs are scanned in full; larger ones are rejected
CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 3
MAX_URL_LENGTH = 2048

# Safe image MIME types allowed through the proxy. SVG is allowed only after a
# static safety scan (no scripts, event handlers or external references).
SUPPORTED_IMAGE_MIMES = frozenset({
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/svg+xml",
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

_CSS_URL_RE = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""", re.IGNORECASE)

# Defense-in-depth for proxied SVG: <img> context already disables scripts, but a
# proxied URL can also be opened directly, so reject active or externally
# referencing content instead of relying on the response CSP alone.
_DANGEROUS_SVG_PATTERNS = (
    b"<script",
    b"<foreignobject",
    b"<iframe",
    b"<embed",
    b"<object",
    b"javascript:",
    b"onload=",
    b"onerror=",
    b"onclick=",
    b"onmouseover=",
)
_EXTERNAL_SVG_REF_RE = re.compile(
    rb"""(?:href|src)\s*=\s*["']\s*(?:https?:)?//""",
    re.IGNORECASE,
)


class SSRFSecurityError(ValueError):
    """Raised when an address or URL violates SSRF safety rules."""


class RemoteImageSizeLimitError(ValueError):
    """Raised when a remote image exceeds the maximum allowed size (10 MiB)."""


class RemoteImageTimeoutError(TimeoutError):
    """Raised when connecting to or reading from upstream times out."""


class UnsupportedImageFormatError(ValueError):
    """Raised when a remote payload is not a verified safe image format."""


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


def detect_safe_image_mime(header: bytes) -> str | None:
    """Inspect payload header and return a safe image MIME or None.

    Supports PNG, JPEG, GIF, WebP and statically safe SVG. SVG content itself is
    validated separately by :func:`validate_svg_payload`.
    """
    head = header.lstrip(b"\xef\xbb\xbf").lstrip()
    lowered = head[:1024].lower()
    if lowered.startswith(b"<svg") or (lowered.startswith(b"<?xml") and b"<svg" in lowered):
        return "image/svg+xml"

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


def validate_svg_payload(payload: bytes) -> None:
    """Reject SVG documents containing active content or external references."""
    if len(payload) > MAX_SVG_BYTES:
        raise UnsupportedImageFormatError(
            f"SVG exceeds the static scan limit of {MAX_SVG_BYTES} bytes"
        )
    lowered = payload.lower()
    for pattern in _DANGEROUS_SVG_PATTERNS:
        if pattern in lowered:
            raise UnsupportedImageFormatError("SVG contains active content")
    if _EXTERNAL_SVG_REF_RE.search(payload):
        raise UnsupportedImageFormatError("SVG references external resources")


def normalize_remote_image_url(raw: str | None) -> str | None:
    """Normalize an attribute value into a comparable absolute http(s) URL.

    Applies the same semantics the browser DOM uses: attribute values are entity
    decoded by the HTML parser; protocol-relative URLs get an explicit https scheme.
    """
    if not raw:
        return None
    url = raw.strip()
    if not url:
        return None
    if url.startswith("//"):
        url = "https:" + url
    lowered = url.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        return None
    if len(url) > MAX_URL_LENGTH:
        return None
    return url


class _RemoteImageURLParser(HTMLParser):
    """Extract remote image URLs with HTML5 attribute semantics."""

    def __init__(self, max_urls: int) -> None:
        super().__init__(convert_charrefs=True)
        self.max_urls = max_urls
        self.urls: list[str] = []
        self._seen: set[str] = set()
        self._done = False

    def _add(self, raw: str | None) -> None:
        if self._done:
            return
        url = normalize_remote_image_url(raw)
        if not url or url in self._seen:
            return
        self._seen.add(url)
        self.urls.append(url)
        if len(self.urls) >= self.max_urls:
            self._done = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return
        is_img = tag.lower() == "img"
        for name, value in attrs:
            if name.lower() == "style" and value:
                for match in _CSS_URL_RE.finditer(value):
                    self._add(match.group(1))
        if is_img:
            for name, value in attrs:
                if name.lower() == "src":
                    self._add(value)
                    break

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)


def extract_remote_image_urls(html: str | None, max_urls: int = 200) -> list[str]:
    """Scan HTML for remote image URLs from img[src] and inline style url(...)."""
    if not html or not isinstance(html, str):
        return []
    parser = _RemoteImageURLParser(max_urls)
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return parser.urls
    return parser.urls



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


def _connect_with_fallback(
    safe_ips: list[str],
    port: int,
    timeout: float,
    connector: Callable[[tuple[str, int], float], Any] | None = None,
) -> Any:
    """Connect to the first reachable safe IP, preferring IPv4 to avoid dead IPv6."""
    connect = connector or (lambda address, seconds: socket.create_connection(address, timeout=seconds))
    ordered = sorted(safe_ips, key=lambda ip: 1 if ":" in ip else 0)
    saw_timeout = False
    last_error: BaseException | None = None
    for ip in ordered:
        try:
            return connect((ip, port), timeout)
        except TimeoutError as exc:
            saw_timeout = True
            last_error = exc
        except OSError as exc:
            last_error = exc
    if saw_timeout:
        raise RemoteImageTimeoutError("Connection timed out for all resolved addresses") from last_error
    raise RemoteImageFetchError("All resolved addresses are unreachable") from last_error



def fetch_safe_remote_image(
    target_url: str,
    mock_opener: Any = None,
) -> tuple[str, Iterator[bytes]]:
    """Fetch remote image through standard library socket/http.client with strict SSRF defense.

    Directly connects to resolved safe IP to prevent DNS rebinding while preserving SNI.
    Enforces manual redirect inspection, max 10 MiB limit, and bitmap magic number verification.
    """
    if mock_opener is not None:
        return mock_opener(target_url)

    current_url = target_url
    redirect_count = 0

    while True:
        parts = validate_remote_url(current_url)
        host = parts.hostname
        assert host is not None
        scheme = parts.scheme.lower()
        port = parts.port or (443 if scheme == "https" else 80)

        # 1. Resolve host and inspect every resolved IP for SSRF
        try:
            addr_infos = socket.getaddrinfo(
                host,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as exc:
            raise RemoteImageFetchError("DNS resolution failed") from exc

        if not addr_infos:
            raise RemoteImageFetchError("No IP resolved for host")

        safe_ips: list[str] = []
        for info in addr_infos:
            ip_str = info[4][0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
            except ValueError:
                raise SSRFSecurityError(f"Invalid resolved IP: {ip_str}")
            if not is_safe_ip(ip_obj):
                raise SSRFSecurityError(f"SSRF blocked IP {ip_str} for host {host}")
            safe_ips.append(ip_str)

        # 2. Connect to a validated IP (prevents DNS rebinding); fall back across
        #    all resolved addresses because IPv6 may be unreachable in containers.
        try:
            raw_sock = _connect_with_fallback(safe_ips, port, CONNECT_TIMEOUT_SECONDS)
            raw_sock.settimeout(READ_TIMEOUT_SECONDS)
        except RemoteImageTimeoutError:
            raise
        except RemoteImageFetchError:
            raise
        except Exception as exc:
            raise RemoteImageFetchError("Connection failed") from exc

        # 3. TLS handshake if HTTPS
        if scheme == "https":
            ssl_ctx = ssl.create_default_context()
            try:
                conn_sock = ssl_ctx.wrap_socket(raw_sock, server_hostname=host)
            except TimeoutError as exc:
                raw_sock.close()
                raise RemoteImageTimeoutError("TLS handshake timed out") from exc
            except Exception as exc:
                raw_sock.close()
                raise RemoteImageFetchError("TLS handshake failed") from exc
        else:
            conn_sock = raw_sock

        conn = http.client.HTTPConnection(host, port, timeout=READ_TIMEOUT_SECONDS)
        conn.sock = conn_sock

        req_path = parts.path or "/"
        if parts.query:
            req_path += "?" + parts.query

        headers = {
            "Host": host if (port in (80, 443)) else f"{host}:{port}",
            "Accept": "image/png,image/jpeg,image/gif,image/webp,image/svg+xml,*/*;q=0.8",
            "User-Agent": "kkmail-image-proxy/1.0",
            "Connection": "close",
        }

        try:
            conn.request("GET", req_path, headers=headers)
            resp = conn.getresponse()
        except TimeoutError as exc:
            conn.close()
            raise RemoteImageTimeoutError("Upstream request timed out") from exc
        except Exception as exc:
            conn.close()
            raise RemoteImageFetchError("Upstream request failed") from exc

        # Handle redirects manually to enforce SSRF validation at every hop
        if resp.status in (301, 302, 303, 307, 308):
            location = resp.getheader("Location")
            conn.close()
            redirect_count += 1
            if redirect_count > MAX_REDIRECTS:
                raise SSRFSecurityError(f"Too many redirects (exceeded max {MAX_REDIRECTS})")
            if not location:
                raise RemoteImageFetchError("Redirect missing Location header")
            current_url = urllib.parse.urljoin(current_url, location)
            continue

        if resp.status != 200:
            conn.close()
            raise RemoteImageFetchError(f"Upstream HTTP error status={resp.status}")

        try:
            first_chunk = resp.read(16384)
        except TimeoutError as exc:
            conn.close()
            raise RemoteImageTimeoutError("Upstream response read timed out") from exc
        except Exception as exc:
            conn.close()
            raise RemoteImageFetchError("Upstream response read failed") from exc

        if not first_chunk:
            conn.close()
            raise UnsupportedImageFormatError("Empty response body")

        mime = detect_safe_image_mime(first_chunk)
        if not mime or mime not in SUPPORTED_IMAGE_MIMES:
            conn.close()
            raise UnsupportedImageFormatError(
                f"Unsupported or dangerous image format (detected: {mime!r})"
            )

        if mime == "image/svg+xml":
            # SVGs are small; read the whole document so the static safety scan
            # sees every element, then hand the verified bytes to the caller.
            chunks = [first_chunk]
            total = len(first_chunk)
            try:
                while total <= MAX_SVG_BYTES:
                    chunk = resp.read(16384)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
            except TimeoutError as exc:
                conn.close()
                raise RemoteImageTimeoutError("Upstream response read timed out") from exc
            except Exception as exc:
                conn.close()
                raise RemoteImageFetchError("Upstream response read failed") from exc
            finally:
                conn.close()
            payload = b"".join(chunks)
            validate_svg_payload(payload)
            return mime, iter([payload])

        def _bounded_stream() -> Iterator[bytes]:
            total_bytes = len(first_chunk)
            if total_bytes > MAX_IMAGE_BYTES:
                conn.close()
                raise RemoteImageSizeLimitError(f"Image exceeds limit of {MAX_IMAGE_BYTES} bytes")
            yield first_chunk

            try:
                while True:
                    chunk = resp.read(16384)
                    if not chunk:
                        break
                    total_bytes += len(chunk)
                    if total_bytes > MAX_IMAGE_BYTES:
                        conn.close()
                        raise RemoteImageSizeLimitError(
                            f"Image exceeds limit of {MAX_IMAGE_BYTES} bytes"
                        )
                    yield chunk
            except TimeoutError as exc:
                raise RemoteImageTimeoutError("Upstream response read timed out") from exc
            finally:
                conn.close()

        return mime, _bounded_stream()
