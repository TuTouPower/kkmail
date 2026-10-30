"""Tests for inline preview signed URL token generation and validation (t066)."""

from __future__ import annotations

import os
import uuid
import pytest

from mail_core.security.inline_preview import (
    INLINE_IMAGE_TOKEN_MAX_AGE_SECONDS,
    SUPPORTED_INLINE_IMAGE_MIMES,
    build_inline_image_preview_url,
    is_supported_inline_image_mime,
    sign_inline_image_preview_token,
    verify_inline_image_preview_token,
)


def test_supported_inline_image_mimes():
    assert is_supported_inline_image_mime("image/png")
    assert is_supported_inline_image_mime("image/jpeg")
    assert is_supported_inline_image_mime("image/gif")
    assert is_supported_inline_image_mime("image/webp")
    assert is_supported_inline_image_mime("IMAGE/PNG ")  # case & whitespace insensitive

    # SVG is explicitly excluded for XSS defense-in-depth
    assert not is_supported_inline_image_mime("image/svg+xml")
    assert not is_supported_inline_image_mime("text/html")
    assert not is_supported_inline_image_mime("application/pdf")
    assert not is_supported_inline_image_mime(None)
    assert not is_supported_inline_image_mime("")


def test_sign_and_verify_token_roundtrip(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_SECRET_KEY", "test-secret-key-for-inline-preview-t066-secure-random")
    att_id = str(uuid.uuid4())

    token = sign_inline_image_preview_token(att_id)
    assert token and isinstance(token, str)

    # Valid token
    assert verify_inline_image_preview_token(att_id, token)

    # UUID object instead of str
    assert verify_inline_image_preview_token(uuid.UUID(att_id), token)


def test_verify_rejects_tampered_or_mismatched(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_SECRET_KEY", "test-secret-key-for-inline-preview-t066-secure-random")
    att_id = str(uuid.uuid4())
    other_att_id = str(uuid.uuid4())

    token = sign_inline_image_preview_token(att_id)

    # Different attachment ID
    assert not verify_inline_image_preview_token(other_att_id, token)

    # Tampered token string
    assert not verify_inline_image_preview_token(att_id, token + "x")
    assert not verify_inline_image_preview_token(att_id, "invalid.token.here")
    assert not verify_inline_image_preview_token(att_id, "")


def test_verify_rejects_expired_token(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_SECRET_KEY", "test-secret-key-for-inline-preview-t066-secure-random")
    att_id = str(uuid.uuid4())
    token = sign_inline_image_preview_token(att_id)

    # Using max_age=-1 forces expiration
    assert not verify_inline_image_preview_token(att_id, token, max_age=-1)


def test_build_preview_url(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_SECRET_KEY", "test-secret-key-for-inline-preview-t066-secure-random")
    att_id = str(uuid.uuid4())
    url = build_inline_image_preview_url(att_id)

    assert url.startswith(f"/api/mail/attachments/{att_id}/preview?token=")
    token = url.split("?token=")[1]
    assert verify_inline_image_preview_token(att_id, token)


def test_image_magic_verification():
    from mail_core.api.mail import _is_valid_image_magic

    # PNG
    assert _is_valid_image_magic(b"\x89PNG\r\n\x1a\n\x00\x00", "image/png")
    # JPEG
    assert _is_valid_image_magic(b"\xff\xd8\xff\xe0\x00\x10JFIF", "image/jpeg")
    # GIF
    assert _is_valid_image_magic(b"GIF89a\x01\x00", "image/gif")
    assert _is_valid_image_magic(b"GIF87a\x01\x00", "image/gif")
    # WebP
    assert _is_valid_image_magic(b"RIFF\x18\x00\x00\x00WEBPVP8 ", "image/webp")

    # Mismatched or active content
    assert not _is_valid_image_magic(b"<svg xmlns='http://www.w3.org/2000/svg'>", "image/png")
    assert not _is_valid_image_magic(b"<html><script>alert(1)</script>", "image/jpeg")
    assert not _is_valid_image_magic(b"\x89PNG\r\n\x1a\n", "image/jpeg")  # PNG bytes claiming to be JPEG
    assert not _is_valid_image_magic(b"", "image/png")
    assert not _is_valid_image_magic(None, "image/png")
