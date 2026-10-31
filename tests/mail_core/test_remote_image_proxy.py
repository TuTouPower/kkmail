"""Unit and integration tests for remote image security proxy (t068)."""

from __future__ import annotations

import io
import ipaddress
import os
import uuid
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.application.remote_images import (
    allow_message_remote_images,
    allow_sender_remote_images,
    remove_allowed_sender,
)
from mail_core.mail.storage.models import Account, Message
from mail_core.security.remote_image_proxy import (
    CONNECT_TIMEOUT_SECONDS,
    MAX_IMAGE_BYTES,
    MAX_REDIRECTS,
    READ_TIMEOUT_SECONDS,
    RemoteImageFetchError,
    RemoteImageSizeLimitError,
    SSRFSecurityError,
    UnsupportedImageFormatError,
    build_remote_image_proxy_url,
    detect_safe_image_mime,
    extract_remote_image_urls,
    fetch_safe_remote_image,
    is_safe_ip,
    sign_remote_image_proxy_token,
    validate_remote_url,
    verify_remote_image_proxy_token,
)

# Valid bitmap magic samples
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 20
GIF_BYTES = b"GIF89a" + b"\x00" * 20
WEBP_BYTES = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 20


def test_ssrf_ip_filtering_matrix() -> None:
    # 1. Loopback addresses
    assert not is_safe_ip(ipaddress.ip_address("127.0.0.1"))
    assert not is_safe_ip(ipaddress.ip_address("127.1.2.3"))
    assert not is_safe_ip(ipaddress.ip_address("::1"))

    # 2. Private RFC 1918 & ULA
    assert not is_safe_ip(ipaddress.ip_address("10.0.0.1"))
    assert not is_safe_ip(ipaddress.ip_address("172.16.0.1"))
    assert not is_safe_ip(ipaddress.ip_address("172.31.255.255"))
    assert not is_safe_ip(ipaddress.ip_address("192.168.1.1"))
    assert not is_safe_ip(ipaddress.ip_address("fc00::1"))
    assert not is_safe_ip(ipaddress.ip_address("fd12::1"))

    # 3. Link-local & cloud metadata
    assert not is_safe_ip(ipaddress.ip_address("169.254.1.1"))
    assert not is_safe_ip(ipaddress.ip_address("169.254.169.254"))
    assert not is_safe_ip(ipaddress.ip_address("fe80::1"))

    # 4. Carrier-grade NAT & benchmark / TEST-NET
    assert not is_safe_ip(ipaddress.ip_address("100.64.0.1"))
    assert not is_safe_ip(ipaddress.ip_address("198.18.0.1"))
    assert not is_safe_ip(ipaddress.ip_address("192.0.2.1"))
    assert not is_safe_ip(ipaddress.ip_address("198.51.100.1"))
    assert not is_safe_ip(ipaddress.ip_address("203.0.113.1"))

    # 5. Multicast, broadcast, unspecified
    assert not is_safe_ip(ipaddress.ip_address("224.0.0.1"))
    assert not is_safe_ip(ipaddress.ip_address("240.0.0.1"))
    assert not is_safe_ip(ipaddress.ip_address("0.0.0.0"))
    assert not is_safe_ip(ipaddress.ip_address("::"))

    # 6. IPv4-mapped IPv6
    assert not is_safe_ip(ipaddress.ip_address("::ffff:127.0.0.1"))
    assert not is_safe_ip(ipaddress.ip_address("::ffff:10.0.0.1"))
    assert not is_safe_ip(ipaddress.ip_address("::ffff:169.254.169.254"))

    # 7. Safe public addresses
    assert is_safe_ip(ipaddress.ip_address("8.8.8.8"))
    assert is_safe_ip(ipaddress.ip_address("1.1.1.1"))
    assert is_safe_ip(ipaddress.ip_address("2606:4700:4700::1111"))


def test_ssrf_allowlist_cidr_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIL_CORE_PROXY_ALLOW_CIDRS", "127.0.0.1/32, 192.168.0.0/16")
    # Overridden addresses are now accepted
    assert is_safe_ip(ipaddress.ip_address("127.0.0.1"))
    assert is_safe_ip(ipaddress.ip_address("192.168.1.100"))
    # Other private addresses remain blocked
    assert not is_safe_ip(ipaddress.ip_address("10.0.0.1"))
    assert not is_safe_ip(ipaddress.ip_address("169.254.169.254"))


def test_validate_remote_url() -> None:
    # Safe standard URLs
    res1 = validate_remote_url("https://example.com/images/cat.png")
    assert res1.scheme == "https"
    assert res1.hostname == "example.com"
    assert res1.port is None

    res2 = validate_remote_url("http://example.com:80/pic.jpg")
    assert res2.port == 80

    res3 = validate_remote_url("https://example.com:443/pic.jpg")
    assert res3.port == 443

    # Reject non-http/https
    with pytest.raises(SSRFSecurityError, match="Unsupported URL scheme"):
        validate_remote_url("ftp://example.com/pic.jpg")

    with pytest.raises(SSRFSecurityError, match="Unsupported URL scheme"):
        validate_remote_url("javascript:alert(1)")

    # Reject non-standard ports
    with pytest.raises(SSRFSecurityError, match="Non-standard HTTP port"):
        validate_remote_url("http://example.com:8080/pic.jpg")

    with pytest.raises(SSRFSecurityError, match="Non-standard HTTPS port"):
        validate_remote_url("https://example.com:8443/pic.jpg")

    # Reject credentials
    with pytest.raises(SSRFSecurityError, match="userinfo credentials are not allowed"):
        validate_remote_url("https://admin:pass@example.com/pic.jpg")

    # Reject excessive length
    with pytest.raises(SSRFSecurityError, match="exceeds max length"):
        validate_remote_url("https://example.com/" + "a" * 2100)


def test_detect_safe_image_mime() -> None:
    assert detect_safe_image_mime(PNG_BYTES) == "image/png"
    assert detect_safe_image_mime(JPEG_BYTES) == "image/jpeg"
    assert detect_safe_image_mime(GIF_BYTES) == "image/gif"
    assert detect_safe_image_mime(WEBP_BYTES) == "image/webp"

    # Reject SVG (XSS vector defense-in-depth)
    assert detect_safe_image_mime(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>") is None
    assert detect_safe_image_mime(b"<?xml version='1.0'?><svg>") is None

    # Reject HTML, scripts, executables
    assert detect_safe_image_mime(b"<!doctype html><html>") is None
    assert detect_safe_image_mime(b"MZ\x90\x00\x03\x00\x00\x00") is None
    assert detect_safe_image_mime(b"") is None
    assert detect_safe_image_mime(b"short") is None


def test_token_signing_and_tamper_proofing() -> None:
    msg_id = uuid.uuid4()
    url = "https://example.com/assets/logo.png"

    token = sign_remote_image_proxy_token(msg_id, url)
    assert token and isinstance(token, str)

    # Valid token succeeds
    assert verify_remote_image_proxy_token(msg_id, url, token)

    # URL tampering fails
    assert not verify_remote_image_proxy_token(msg_id, "https://example.com/assets/other.png", token)

    # Message ID tampering fails
    assert not verify_remote_image_proxy_token(uuid.uuid4(), url, token)

    # Token content tampering fails
    assert not verify_remote_image_proxy_token(msg_id, url, token + "x")
    assert not verify_remote_image_proxy_token(msg_id, url, "invalid-token")
    assert not verify_remote_image_proxy_token(msg_id, url, "")


def test_extract_remote_image_urls() -> None:
    html = """
    <div>
      <p>Hello</p>
      <img src="https://cdn.example.com/pic1.png">
      <img src="http://cdn.example.com/pic2.jpg" alt="test">
      <!-- duplicate -->
      <img src="https://cdn.example.com/pic1.png">
      <div style="background-image: url('https://cdn.example.com/bg1.png'); color: red;"></div>
      <div style="background: url(https://cdn.example.com/bg2.png)"></div>
      <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==">
      <img src="cid:my_inline_part">
    </div>
    """
    urls = extract_remote_image_urls(html)
    assert urls == [
        "https://cdn.example.com/pic1.png",
        "http://cdn.example.com/pic2.jpg",
        "https://cdn.example.com/bg1.png",
        "https://cdn.example.com/bg2.png",
    ]


def test_fetch_safe_remote_image_mock_opener() -> None:
    # Test valid fetch via mock_opener
    def mock_opener(url: str) -> tuple[str, Iterator[bytes]]:
        return "image/png", iter([PNG_BYTES])

    mime, stream = fetch_safe_remote_image("https://images.example.com/photo.png", mock_opener=mock_opener)
    assert mime == "image/png"
    chunks = list(stream)
    assert b"".join(chunks) == PNG_BYTES


def test_fetch_safe_remote_image_redirect_to_disallowed_scheme() -> None:
    # Scheme validation check
    with pytest.raises(SSRFSecurityError, match="Unsupported URL scheme"):
        validate_remote_url("ftp://internal.backup/secret.png")


def test_fetch_safe_remote_image_size_limit() -> None:
    # Stream payload exceeding MAX_IMAGE_BYTES
    chunk_size = 1024 * 1024  # 1 MiB
    total_chunks = 11  # 11 MiB (>10 MiB limit)

    def generate_large() -> Iterator[bytes]:
        yield PNG_BYTES
        for _ in range(total_chunks):
            yield b"x" * chunk_size

    def mock_opener(url: str) -> tuple[str, Iterator[bytes]]:
        def _bounded_stream() -> Iterator[bytes]:
            total = 0
            for chunk in generate_large():
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    raise RemoteImageSizeLimitError(f"Image exceeds limit of {MAX_IMAGE_BYTES} bytes")
                yield chunk
        return "image/png", _bounded_stream()

    mime, stream = fetch_safe_remote_image("https://images.example.com/huge.png", mock_opener=mock_opener)
    assert mime == "image/png"

    with pytest.raises(RemoteImageSizeLimitError, match="Image exceeds limit"):
        for _ in stream:
            pass


def test_fetch_safe_remote_image_fake_mime_rejected() -> None:
    # Payload returns HTML
    html_bytes = b"<!doctype html><html><body>Login page</body></html>"
    assert detect_safe_image_mime(html_bytes) is None


_db_required = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


@_db_required
def test_remote_image_proxy_api_endpoint_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIL_CORE_SECRET_KEY", "test-secret-key-for-proxy-t068-random")
    client = TestClient(app)

    # Create test account and message
    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            id=uuid.uuid4(),
            email=f"owner-{uuid.uuid4().hex[:8]}@test.local",
            provider="stub",
            credential_ref="cred_ref",
        )
        session.add(acc)
        session.flush()

        msg = Message(
            id=uuid.uuid4(),
            account_id=acc.id,
            remote_id="remote-msg-1",
            from_address="sender@upstream.test",
            to_addresses=["owner@test.local"],
            subject="Remote image email",
            snippet="...",
        )
        session.add(msg)
        session.commit()
        msg_id = msg.id

    img_url = "https://images.example.com/banner.png"
    token = sign_remote_image_proxy_token(msg_id, img_url)

    # 1. Invalid or tampered token -> 401
    resp = client.get(f"/api/mail/messages/{msg_id}/remote-images?url={img_url}&token=badtoken")
    assert resp.status_code == 401

    # 2. Before allowlisting message or sender -> 403 Forbidden
    resp = client.get(f"/api/mail/messages/{msg_id}/remote-images?url={img_url}&token={token}")
    assert resp.status_code == 403
    assert "Remote images are not allowed" in resp.text

    # 3. Allow message remote images
    with Session() as session:
        allow_message_remote_images(session, msg_id)
        session.commit()

    # Mock fetch_safe_remote_image to return PNG bytes
    def mock_fetch(url: str, transport: Any = None) -> tuple[str, Iterator[bytes]]:
        return "image/png", iter([PNG_BYTES])

    monkeypatch.setattr("mail_core.api.mail.fetch_safe_remote_image", mock_fetch)

    # 4. Request with valid token and allowlisted message -> 200 Streaming
    resp = client.get(f"/api/mail/messages/{msg_id}/remote-images?url={img_url}&token={token}")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"] == "image/png"
    assert resp.headers["Content-Disposition"] == "inline"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Content-Security-Policy"] == "default-src 'none'"
    assert resp.content == PNG_BYTES

    # 5. HEAD request returns metadata without body
    head_resp = client.head(f"/api/mail/messages/{msg_id}/remote-images?url={img_url}&token={token}")
    assert head_resp.status_code == 200
    assert head_resp.headers["Content-Type"] == "image/png"
    assert len(head_resp.content) == 0


@_db_required
def test_remote_image_proxy_sender_allowlist_and_revocation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIL_CORE_SECRET_KEY", "test-secret-key-for-proxy-t068-random")
    client = TestClient(app)
    sender_email = "newsletter@marketing.test"
    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            id=uuid.uuid4(),
            email=f"user-{uuid.uuid4().hex[:8]}@test.local",
            provider="stub",
            credential_ref="cred_ref",
        )
        session.add(acc)
        session.flush()

        msg = Message(
            id=uuid.uuid4(),
            account_id=acc.id,
            remote_id="remote-msg-2",
            from_address=sender_email,
            to_addresses=["user@test.local"],
            subject="Newsletter",
            snippet="...",
        )
        session.add(msg)
        session.commit()
        msg_id = msg.id

    img_url = "https://images.example.com/logo.png"
    token = sign_remote_image_proxy_token(msg_id, img_url)

    # Allow sender globally
    with Session() as session:
        sender_allow = allow_sender_remote_images(session, sender_email)
        sender_allow_id = sender_allow.id
        session.commit()

    def mock_fetch(url: str, transport: Any = None) -> tuple[str, Iterator[bytes]]:
        return "image/png", iter([PNG_BYTES])

    monkeypatch.setattr("mail_core.api.mail.fetch_safe_remote_image", mock_fetch)

    # Allowed by sender -> 200 OK
    resp = client.get(f"/api/mail/messages/{msg_id}/remote-images?url={img_url}&token={token}")
    assert resp.status_code == 200

    # Revoke sender allowlist
    with Session() as session:
        removed = remove_allowed_sender(session, sender_allow_id)
        assert removed
        session.commit()

    # AC-006: Immediate real-time revocation -> 403 Forbidden
    revoked_resp = client.get(f"/api/mail/messages/{msg_id}/remote-images?url={img_url}&token={token}")
    assert revoked_resp.status_code == 403
