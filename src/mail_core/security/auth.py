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
import logging
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

log = logging.getLogger("mail_core.security.auth")

SESSION_COOKIE_NAME = "kkmail_mc_session"
CSRF_HEADER_NAMES = ("X-CSRF-Token", "X-CSRFToken")
_SESSION_SALT = "kkmail-mail-core-session-v1"

_password_hash: bytes | None = None
_api_keys: frozenset[str] | None = None
_session_epoch: int = 1
_SESSION_EPOCH_CACHE_TTL_SECONDS = 5.0
_session_epoch_cache: tuple[int, float] | None = None
_session_epoch_generation = 0


class AuthConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    via: Literal["session", "api_key"]
    csrf_token: str | None = None


_session_epoch: int = 1


def reset_auth_caches() -> None:
    """Test helper: clear cached password hash / API keys / session epoch."""
    global _password_hash, _api_keys, _session_epoch, _session_epoch_cache
    global _session_epoch_generation
    _password_hash = None
    _api_keys = None
    _session_epoch = 1
    _session_epoch_cache = None
    _session_epoch_generation += 1


def _update_session_epoch_cache(epoch: int) -> None:
    """Publish a session epoch change made by this process."""
    global _session_epoch, _session_epoch_cache, _session_epoch_generation
    _session_epoch = epoch
    _session_epoch_generation += 1
    _session_epoch_cache = (epoch, time.monotonic())


def require_secret_key() -> str:
    key = (os.environ.get("MAIL_CORE_SECRET_KEY") or "").strip()
    if not key:
        raise AuthConfigError(
            "MAIL_CORE_SECRET_KEY is required to sign mail-core sessions"
        )
    return key


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(require_secret_key(), salt=_SESSION_SALT)


def session_max_age() -> int:
    return int(os.environ.get("MAIL_CORE_SESSION_MAX_AGE") or str(60 * 60 * 24 * 30))


def cookie_secure(request: Any = None) -> bool:
    env_val = os.environ.get("MAIL_CORE_COOKIE_SECURE")
    if env_val is not None and env_val.strip() != "":
        return env_val.strip().lower() in ("1", "true", "yes", "on")
    if request is not None:
        scope = getattr(request, "scope", None)
        if isinstance(scope, dict) and scope.get("scheme") == "https":
            return True
        try:
            if getattr(request.url, "scheme", "") == "https":
                return True
        except Exception:
            pass
    return False


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


def _fetch_db_credentials() -> tuple[str | None, int | None]:
    """Fetch password hash and session epoch from database.

    Returns:
        (login_password_hash, session_epoch)
        If database is reachable but no record exists yet, returns (None, None).
    Raises:
        AuthConfigError: If database is configured but query fails (fail-closed).
    """
    if not (os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip():
        return None, None
    try:
        from mail_core.db.session import get_session_factory
        from mail_core.mail.storage.models import AuthCredential

        Session = get_session_factory()
        with Session() as session:
            cred = session.get(AuthCredential, "default")
            if cred is not None and cred.login_password_hash:
                return cred.login_password_hash, getattr(cred, "session_epoch", None)
            return None, getattr(cred, "session_epoch", None) if cred is not None else None
    except Exception as exc:
        log.error("database query for auth credentials failed: %s", exc)
        raise AuthConfigError(f"failed to query authentication credentials from database: {exc}") from exc


def _fetch_db_password_hash() -> str | None:
    """Fetch password hash from database.

    Returns:
        The bcrypt password hash string, or None if database is reachable but no record exists.
    Raises:
        AuthConfigError: If database is configured but query fails (fail-closed).
    """
    hash_val, _ = _fetch_db_credentials()
    return hash_val


def _persist_db_password_hash(hash_str: str, increment_epoch: bool = False) -> bool:
    if not (os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip():
        return True
    try:
        from mail_core.db.session import get_session_factory
        from mail_core.mail.storage.models import AuthCredential

        Session = get_session_factory()
        with Session() as session:
            cred = session.get(AuthCredential, "default")
            if cred is None:
                new_epoch = _session_epoch + (1 if increment_epoch else 0)
                cred = AuthCredential(id="default", login_password_hash=hash_str, session_epoch=new_epoch)
                session.add(cred)
            else:
                cred.login_password_hash = hash_str
                if increment_epoch:
                    cred.session_epoch = (getattr(cred, "session_epoch", None) or 1) + 1
            session.commit()
            if increment_epoch and cred is not None:
                _update_session_epoch_cache(cred.session_epoch)
            return True
    except Exception as exc:
        log.warning("could not persist password hash to database: %s", exc)
        return False


def get_login_password_hash() -> bytes:
    global _password_hash

    has_db = bool((os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip())
    if has_db:
        # Priority 1: Query database (Decision Plan A: authoritative source)
        # _fetch_db_password_hash raises AuthConfigError on DB error (fail-closed)
        db_hash = _fetch_db_password_hash()
        if db_hash:
            _password_hash = db_hash.encode("utf-8")
            return _password_hash
        # db_hash is None means DB reachable but empty record (first boot)

    if _password_hash is not None and not has_db:
        return _password_hash

    # Priority 2: Bootstrap from environment on first boot
    hashed = (os.environ.get("MAIL_CORE_LOGIN_PASSWORD_HASH") or "").strip()
    if hashed:
        _password_hash = hashed.encode("utf-8")
        if not _persist_db_password_hash(hashed):
            raise AuthConfigError("failed to persist bootstrap password hash to database")
        return _password_hash

    path_raw = (os.environ.get("MAIL_CORE_PASSWORD_HASH_PATH") or "").strip()
    if path_raw:
        path = Path(path_raw)
        if path.is_file():
            stored_file_hash = path.read_bytes().strip()
            if stored_file_hash:
                _password_hash = stored_file_hash
                if not _persist_db_password_hash(_password_hash.decode("utf-8")):
                    raise AuthConfigError("failed to persist bootstrap password hash to database")
                return _password_hash

    plain = (os.environ.get("MAIL_CORE_LOGIN_PASSWORD") or "").strip()
    if not plain:
        raise AuthConfigError("Set MAIL_CORE_LOGIN_PASSWORD_HASH (bcrypt) or MAIL_CORE_LOGIN_PASSWORD for mail-core login")

    _password_hash = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt())
    if not _persist_db_password_hash(_password_hash.decode("utf-8")):
        raise AuthConfigError("failed to persist bootstrap password hash to database")
    if path_raw:
        try:
            path = Path(path_raw)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(_password_hash)
        except Exception as exc:
            log.warning("could not write password hash path: %s", exc)
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


def get_session_epoch() -> int:
    """Fetch the session epoch from a short-lived cache or the authoritative database.

    Raises:
        AuthConfigError: If database is configured but query fails (fail-closed).
    """
    global _session_epoch, _session_epoch_cache
    if not (os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip():
        return _session_epoch

    now = time.monotonic()
    cached = _session_epoch_cache
    if cached is not None and now - cached[1] < _SESSION_EPOCH_CACHE_TTL_SECONDS:
        return cached[0]
    generation = _session_epoch_generation

    try:
        from mail_core.db.session import get_session_factory
        from mail_core.mail.storage.models import AuthCredential

        Session = get_session_factory()
        with Session() as session:
            cred = session.get(AuthCredential, "default")
            if cred is None:
                cred = AuthCredential(
                    id="default",
                    login_password_hash="",
                    session_epoch=_session_epoch,
                )
                session.add(cred)
                session.commit()
                epoch = _session_epoch
            else:
                epoch = getattr(cred, "session_epoch", None)
            if epoch is None:
                epoch = _session_epoch
                cred.session_epoch = epoch
                session.commit()
            if generation != _session_epoch_generation:
                # A local password change or logout completed while this query ran.
                return _session_epoch
            _session_epoch = epoch
            _session_epoch_cache = (epoch, time.monotonic())
            return epoch
    except Exception as exc:
        log.error("could not fetch session epoch from database: %s", exc)
        raise AuthConfigError(f"could not fetch session epoch from database: {exc}") from exc


def invalidate_all_sessions() -> None:
    """Invalidate all active sessions by incrementing the session epoch in database and memory.

    Raises:
        AuthConfigError: If database is configured but update fails.
    """
    if not (os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip():
        _update_session_epoch_cache(_session_epoch + 1)
        return
    try:
        from mail_core.db.session import get_session_factory
        from mail_core.mail.storage.models import AuthCredential

        Session = get_session_factory()
        with Session() as session:
            cred = session.get(AuthCredential, "default")
            if cred is None:
                cred = AuthCredential(
                    id="default",
                    login_password_hash="",
                    session_epoch=_session_epoch + 1,
                )
                session.add(cred)
            else:
                cred.session_epoch = (getattr(cred, "session_epoch", None) or 1) + 1
            session.commit()
            _update_session_epoch_cache(cred.session_epoch)
    except Exception as exc:
        log.error("could not increment session epoch in database: %s", exc)
        raise AuthConfigError(f"could not increment session epoch in database: {exc}") from exc


def issue_session() -> tuple[str, str]:
    """Return (signed_cookie_value, csrf_token)."""
    csrf = secrets.token_urlsafe(32)
    epoch = get_session_epoch()
    token = _serializer().dumps({"v": 1, "csrf": csrf, "epoch": epoch})
    return token, csrf


def read_session(cookie_value: str) -> dict[str, Any] | None:
    try:
        data = _serializer().loads(cookie_value, max_age=session_max_age())
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("v") != 1:
        return None
    try:
        current_epoch = get_session_epoch()
    except AuthConfigError:
        log.warning("rejecting session: failed to read authoritative session epoch from database")
        return None
    if data.get("epoch") != current_epoch:
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
    """Verify current password and persist new bcrypt hash + session epoch atomically in one DB tx."""
    import bcrypt

    global _password_hash
    if not verify_password(current):
        raise AuthConfigError("current password incorrect")
    if len(new) < 8:
        raise AuthConfigError("new password must be at least 8 characters")
    hashed = bcrypt.hashpw(new.encode("utf-8"), bcrypt.gensalt())
    hashed_str = hashed.decode("utf-8")

    has_db = bool((os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip())

    # Persist directly into database atomically (password + incremented epoch)
    if not _persist_db_password_hash(hashed_str, increment_epoch=True):
        raise AuthConfigError("failed to persist password to database")

    # If without DB, increment epoch in memory
    if not has_db:
        _update_session_epoch_cache(_session_epoch + 1)

    # Refresh in-memory cache only after DB commit succeeded
    _password_hash = hashed
    path_raw = (os.environ.get("MAIL_CORE_PASSWORD_HASH_PATH") or "").strip()
    if path_raw:
        try:
            path = Path(path_raw)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(hashed)
        except Exception as exc:
            log.warning("could not write password hash to %s: %s", path_raw, exc)

    try:
        from mail_core.runtime.bootstrap import clear_initial_password

        clear_initial_password(os.environ.get("MAIL_CORE_DATA_DIR"))
    except Exception as exc:
        log.warning("could not clear initial password: %s", exc)
