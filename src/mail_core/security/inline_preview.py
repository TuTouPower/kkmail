"""Signed URL generation and validation for inline image attachments (t066)."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from mail_core.security.auth import require_secret_key

_INLINE_IMAGE_SALT = "kkmail/inline-image-preview/v1"
INLINE_IMAGE_TOKEN_MAX_AGE_SECONDS = 900  # 15 minutes

# Allowed bitmap MIME types for inline preview. SVG is explicitly excluded for XSS defense-in-depth.
SUPPORTED_INLINE_IMAGE_MIMES = frozenset({
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
})


def is_supported_inline_image_mime(mime: str | None) -> bool:
    if not mime:
        return False
    return mime.strip().lower() in SUPPORTED_INLINE_IMAGE_MIMES


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        require_secret_key(),
        salt=_INLINE_IMAGE_SALT,
        signer_kwargs={"digest_method": hashlib.sha256},
    )


def sign_inline_image_preview_token(attachment_id: str | uuid.UUID) -> str:
    payload = {
        "ver": 1,
        "purp": "inline-image-preview",
        "att_id": str(attachment_id),
    }
    return _serializer().dumps(payload)


def verify_inline_image_preview_token(
    attachment_id: str | uuid.UUID,
    token: str,
    max_age: int = INLINE_IMAGE_TOKEN_MAX_AGE_SECONDS,
) -> bool:
    if not token or not token.strip():
        return False
    try:
        data: dict[str, Any] = _serializer().loads(token.strip(), max_age=max_age)
        return (
            data.get("ver") == 1
            and data.get("purp") == "inline-image-preview"
            and data.get("att_id") == str(attachment_id)
        )
    except (BadSignature, SignatureExpired, Exception):
        return False


def build_inline_image_preview_url(attachment_id: str | uuid.UUID) -> str:
    token = sign_inline_image_preview_token(attachment_id)
    return f"/api/mail/attachments/{attachment_id}/preview?token={token}"
