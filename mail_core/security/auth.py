"""mail-core authentication: Cookie session + Bearer API keys + CSRF.

Env contract:
  MAIL_CORE_SECRET_KEY or SECRET_KEY   — required; signs session cookies
  MAIL_CORE_LOGIN_PASSWORD_HASH        — preferred bcrypt hash ($2b$...)
  MAIL_CORE_LOGIN_PASSWORD             — plaintext alternative (hashed at load)
  MAIL_CORE_PASSWORD_HASH_PATH         — optional file to persist hash after first boot
  MAIL_CORE_API_KEYS                   — comma-separated or JSON list of Bearer keys
  MAIL_CORE_SESSION_MAX_AGE            — seconds (default 30 days)
  MAIL_CORE_COOKIE_SECURE              — 1/true for Secure cookie (HTTPS)
  MAIL_CORE_COOKIE_SAMESITE            — lax|strict|none (default lax)
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SESSION_COOKIE_NAME = "kkmail_mc_session"
CSRF_HEADER_NAMES = ("X-CSRF-Token", "X-CSRFToken")
_SESSION_SALT = "kkmail-mail-core-session-v1"

_password_hash: bytes | None = None
_api_keys: frozenset[str] | None = None


class AuthConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    via: Literal["session", "api_key"]
    csrf_token: str | None = None


def reset_auth_caches() -> None:
    """Test helper: clear cached password hash / API keys."""
    global _password_hash, _api_keys
    _password_hash = None
    _api_keys = None


def require_secret_key() -> str:
    key = (os.environ.get("MAIL_CORE_SECRET_KEY") or os.environ.get("SECRET_KEY") or "").strip()
    if not key:
        raise AuthConfigError(
            "MAIL_CORE_SECRET_KEY or SECRET_KEY is required to sign mail-core sessions"
        )
    return key


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(require_secret_key(), salt=_SESSION_SALT)


def session_max_age() -> int:
    return int(os.environ.get("MAIL_CORE_SESSION_MAX_AGE") or str(60 * 60 * 24 * 30))


def cookie_secure() -> bool:
    return (os.environ.get("MAIL_CORE_COOKIE_SECURE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def cookie_samesite() -> str:
    raw = (os.environ.get("MAIL_CORE_COOKIE_SAMESITE") or "lax").strip().lower()
    if raw not in ("lax", "strict", "none"):
        return "lax"
    return raw


def load_api_keys() -> frozenset[str]:
    global _api_keys
    if _api_keys is not None:
        return _api_keys
    raw = (os.environ.get("MAIL_CORE_API_KEYS") or "").strip()
    if not raw:
        _api_keys = frozenset()
        return _api_keys
    if raw.startswith("["):
        data = json.loads(raw)
        if not isinstance(data, list):
            raise AuthConfigError("MAIL_CORE_API_KEYS JSON must be a list of strings")
        _api_keys = frozenset(str(x) for x in data if str(x).strip())
    else:
        _api_keys = frozenset(k.strip() for k in raw.split(",") if k.strip())
    return _api_keys


def get_login_password_hash() -> bytes:
    global _password_hash
    if _password_hash is not None:
        return _password_hash

    hashed = (os.environ.get("MAIL_CORE_LOGIN_PASSWORD_HASH") or "").strip()
    if hashed:
        _password_hash = hashed.encode("utf-8")
        return _password_hash

    path_raw = (os.environ.get("MAIL_CORE_PASSWORD_HASH_PATH") or "").strip()
    if path_raw:
        path = Path(path_raw)
        if path.is_file():
            _password_hash = path.read_bytes().strip()
            if _password_hash:
                return _password_hash

    plain = (os.environ.get("MAIL_CORE_LOGIN_PASSWORD") or "").strip()
    if not plain:
        raise AuthConfigError("Set MAIL_CORE_LOGIN_PASSWORD_HASH (bcrypt) or MAIL_CORE_LOGIN_PASSWORD for mail-core login")

    _password_hash = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt())
    if path_raw:
        path = Path(path_raw)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_password_hash)
    return _password_hash


def verify_password(password: str) -> bool:
    if not password:
        return False
    try:
        stored = get_login_password_hash()
    except AuthConfigError:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored)
    except (ValueError, TypeError):
        return False


def validate_auth_config() -> None:
    """Fail-fast at process start."""
    require_secret_key()
    get_login_password_hash()
    load_api_keys()  # validate JSON if present


def issue_session() -> tuple[str, str]:
    """Return (signed_cookie_value, csrf_token)."""
    csrf = secrets.token_urlsafe(32)
    token = _serializer().dumps({"v": 1, "csrf": csrf})
    return token, csrf


def read_session(cookie_value: str) -> dict[str, Any] | None:
    try:
        data = _serializer().loads(cookie_value, max_age=session_max_age())
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("v") != 1:
        return None
    csrf = data.get("csrf")
    if not isinstance(csrf, str) or not csrf:
        return None
    return data


def api_key_matches(token: str) -> bool:
    keys = load_api_keys()
    if not token or not keys:
        return False
    for key in keys:
        if secrets.compare_digest(token, key):
            return True
    return False


def extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def csrf_header_value(headers: Any) -> str | None:
    for name in CSRF_HEADER_NAMES:
        val = headers.get(name)
        if val:
            return val
    return None


def change_login_password(*, current: str, new: str) -> None:
    """Verify current password and replace the cached bcrypt hash (and optional file)."""
    import bcrypt

    global _password_hash
    if not verify_password(current):
        raise AuthConfigError("current password incorrect")
    if len(new) < 8:
        raise AuthConfigError("new password must be at least 8 characters")
    hashed = bcrypt.hashpw(new.encode("utf-8"), bcrypt.gensalt())
    _password_hash = hashed
    path_raw = (os.environ.get("MAIL_CORE_PASSWORD_HASH_PATH") or "").strip()
    if path_raw:
        path = Path(path_raw)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(hashed)
    from mail_core.runtime.bootstrap import clear_initial_password

    clear_initial_password(os.environ.get("MAIL_CORE_DATA_DIR"))
