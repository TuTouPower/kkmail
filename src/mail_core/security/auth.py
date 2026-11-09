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

import hashlib
import json
import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from mail_core.security.redact import safe_error

log = logging.getLogger("mail_core.security.auth")

SESSION_COOKIE_NAME = "kkmail_mc_session"
CSRF_HEADER_NAMES = ("X-CSRF-Token", "X-CSRFToken")
_SESSION_SALT = "kkmail-mail-core-session-v1"

_password_hash: bytes | None = None
_api_keys: frozenset[str] | None = None
_session_epoch: int = 1
_DEFAULT_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30
_MAX_SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 365
_session_max_age_seconds: int | None = None


class AuthConfigError(RuntimeError):
    pass


class _NoLoginCredentialsConfigured(AuthConfigError):
    """No login credential is configured at all.

    Distinct from infrastructure failures (e.g. the credential database is
    unreachable): verify_password maps only this case to ``False`` and lets
    every other AuthConfigError propagate so callers can answer 500 instead
    of disguising an outage as a wrong password.
    """


# Single source of truth for the password size contract: bcrypt consumes at
# most 72 bytes of input. How an over-long input behaves is bcrypt-version
# dependent — bcrypt 5.0.0 raises ValueError from hashpw/checkpw, while
# older/truncating builds silently used only the first 72 bytes (letting
# distinct passwords sharing a 72-byte prefix verify against each other).
# Nothing here may rely on either behaviour: producers reject over-long
# passwords via bcrypt_password_bytes, verify_password rejects them
# explicitly, and the API schemas enforce the same byte budget.
MAX_PASSWORD_BYTES = 72
_BCRYPT_MAX_PASSWORD_BYTES = MAX_PASSWORD_BYTES


def bcrypt_password_bytes(password: str) -> bytes:
    encoded = password.encode("utf-8")
    if len(encoded) > _BCRYPT_MAX_PASSWORD_BYTES:
        raise AuthConfigError("password must not exceed 72 bytes when encoded as UTF-8")
    return encoded


def _fsync_dir(dir_path: Path) -> None:
    try:
        dir_fd = os.open(dir_path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        try:
            os.close(dir_fd)
        except OSError:
            pass


def _write_password_hash_file(path: Path, password_hash: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp.{secrets.token_hex(8)}")
    fd = None
    try:
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        else:
            os.chmod(tmp_path, 0o600)
        with open(fd, "wb", closefd=True) as output:
            fd = None
            output.write(password_hash)
            output.flush()
            os.fsync(output.fileno())
        os.replace(tmp_path, path)
        _fsync_dir(path.parent)
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise


@dataclass(frozen=True, slots=True)
class AuthPrincipal:
    via: Literal["session", "api_key"]
    csrf_token: str | None = None
    api_key_digest: str | None = field(default=None, repr=False)
    session_epoch: int | None = None


def reset_auth_caches() -> None:
    """Test helper: clear cached password hash, API keys, session epoch, and max age."""
    global _password_hash, _api_keys, _session_epoch, _session_max_age_seconds
    _password_hash = None
    _api_keys = None
    _session_epoch = 1
    _session_max_age_seconds = None


def require_secret_key() -> str:
    key = (os.environ.get("MAIL_CORE_SECRET_KEY") or "").strip()
    if not key:
        raise AuthConfigError(
            "MAIL_CORE_SECRET_KEY is required to sign mail-core sessions"
        )
    return key


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(require_secret_key(), salt=_SESSION_SALT)


def _parse_session_max_age() -> int:
    raw = os.environ.get("MAIL_CORE_SESSION_MAX_AGE") or str(_DEFAULT_SESSION_MAX_AGE_SECONDS)
    try:
        value = int(raw)
    except ValueError as exc:
        raise AuthConfigError("MAIL_CORE_SESSION_MAX_AGE must be an integer number of seconds") from exc
    if not 0 < value <= _MAX_SESSION_MAX_AGE_SECONDS:
        raise AuthConfigError(
            "MAIL_CORE_SESSION_MAX_AGE must be between 1 and "
            f"{_MAX_SESSION_MAX_AGE_SECONDS} seconds (365 days)"
        )
    return value


def session_max_age() -> int:
    global _session_max_age_seconds
    if _session_max_age_seconds is None:
        _session_max_age_seconds = _parse_session_max_age()
    return _session_max_age_seconds


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


def cookie_samesite(request: Any = None) -> str:
    raw = (os.environ.get("MAIL_CORE_COOKIE_SAMESITE") or "lax").strip().lower()
    if raw not in ("lax", "strict", "none"):
        return "lax"
    if raw == "none" and not cookie_secure(request):
        # Browsers reject SameSite=None cookies without the Secure attribute,
        # and over plain HTTP it would also expose the session cross-site.
        log.warning(
            "MAIL_CORE_COOKIE_SAMESITE=none requires a secure cookie; "
            "falling back to samesite=lax"
        )
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
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise AuthConfigError("MAIL_CORE_API_KEYS must be valid JSON (a list of strings)") from exc
        if not isinstance(data, list):
            raise AuthConfigError("MAIL_CORE_API_KEYS JSON must be a list of strings")
        for item in data:
            if not isinstance(item, str) or not item.strip():
                raise AuthConfigError("MAIL_CORE_API_KEYS JSON must be a list of non-empty strings")
        _api_keys = frozenset(data)
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
        log.error(
            "database query for auth credentials failed (error type=%s)",
            type(exc).__name__,
        )
        log.debug("database query for auth credentials failed: %s", safe_error(exc))
        raise AuthConfigError("failed to query authentication credentials from database") from exc


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
        from mail_core.realtime.notify import try_notify_session_revocation

        Session = get_session_factory()
        with Session() as session:
            # Row lock: the epoch increment below is a read-modify-write and
            # must serialize against invalidate_all_sessions(), otherwise a
            # concurrent logout/login interleave loses one increment and a
            # pre-change session stays valid after the password change (R02).
            cred = session.get(AuthCredential, "default", with_for_update=True)
            if cred is None:
                new_epoch = _session_epoch + (1 if increment_epoch else 0)
                cred = AuthCredential(id="default", login_password_hash=hash_str, session_epoch=new_epoch)
                session.add(cred)
            else:
                cred.login_password_hash = hash_str
                if increment_epoch:
                    cred.session_epoch = (getattr(cred, "session_epoch", None) or 1) + 1
            if increment_epoch:
                try_notify_session_revocation(session, int(cred.session_epoch))
            session.commit()
            if increment_epoch and cred is not None:
                _close_local_session_streams(current_epoch=int(cred.session_epoch))
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
        raise _NoLoginCredentialsConfigured("Set MAIL_CORE_LOGIN_PASSWORD_HASH (bcrypt) or MAIL_CORE_LOGIN_PASSWORD for mail-core login")

    _password_hash = bcrypt.hashpw(bcrypt_password_bytes(plain), bcrypt.gensalt())
    if not _persist_db_password_hash(_password_hash.decode("utf-8")):
        raise AuthConfigError("failed to persist bootstrap password hash to database")
    if path_raw:
        try:
            _write_password_hash_file(Path(path_raw), _password_hash)
        except Exception as exc:
            log.warning("could not write password hash path: %s", exc)
    return _password_hash


def verify_password(password: str) -> bool:
    """Return True iff ``password`` matches the stored login credential.

    Returns False when no credential is configured at all. Any other
    AuthConfigError (e.g. the credential database query failed) propagates
    so the login route can answer 500 rather than counting an outage as a
    failed login attempt.
    """
    if not password:
        return False
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        # Explicit rejection: do not delegate this to bcrypt, whose
        # over-long-input behaviour varies by version (see MAX_PASSWORD_BYTES).
        return False
    try:
        stored = get_login_password_hash()
    except _NoLoginCredentialsConfigured:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored)
    except (ValueError, TypeError):
        return False


def validate_auth_config() -> None:
    """Fail-fast at process start."""
    require_secret_key()
    session_max_age()
    cookie_samesite()  # surface the SameSite=None/Secure combination at startup
    get_login_password_hash()
    load_api_keys()  # validate JSON if present


def get_session_epoch() -> int:
    """Fetch the authoritative session epoch from database, or in-memory epoch if DB not configured.

    Raises:
        AuthConfigError: If database is configured but record is missing or query fails (fail-closed).
    """
    if not (os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip():
        return _session_epoch

    try:
        from mail_core.db.session import get_session_factory
        from mail_core.mail.storage.models import AuthCredential

        Session = get_session_factory()
        with Session() as session:
            cred = session.get(AuthCredential, "default")
            if cred is None or getattr(cred, "session_epoch", None) is None:
                raise AuthConfigError("auth credential record missing in database")
            return int(cred.session_epoch)
    except AuthConfigError:
        raise
    except Exception as exc:
        log.error(
            "could not fetch session epoch from database (error type=%s)",
            type(exc).__name__,
        )
        log.debug("could not fetch session epoch from database: %s", safe_error(exc))
        raise AuthConfigError("could not fetch session epoch from database") from exc


def _close_local_session_streams(*, current_epoch: int | None = None) -> None:
    try:
        from mail_core.realtime.dispatcher import get_dispatcher

        get_dispatcher().close_session_streams(current_epoch=current_epoch)
    except Exception as exc:
        log.warning(
            "could not close local SSE streams after session invalidation (error type=%s)",
            type(exc).__name__,
        )


def invalidate_all_sessions() -> None:
    """Invalidate all active sessions by incrementing the session epoch in database and memory.

    Raises:
        AuthConfigError: If database is configured but update fails.
    """
    global _session_epoch
    if not (os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip():
        _session_epoch += 1
        _close_local_session_streams(current_epoch=_session_epoch)
        return
    try:
        from mail_core.db.session import get_session_factory
        from mail_core.mail.storage.models import AuthCredential
        from mail_core.realtime.notify import try_notify_session_revocation

        Session = get_session_factory()
        with Session() as session:
            # Row lock: serialize against _persist_db_password_hash()'s
            # epoch increment so concurrent increments never lose one (R02).
            cred = session.get(AuthCredential, "default", with_for_update=True)
            if cred is None:
                cred = AuthCredential(
                    id="default",
                    login_password_hash="",
                    session_epoch=_session_epoch + 1,
                )
                session.add(cred)
            else:
                cred.session_epoch = (getattr(cred, "session_epoch", None) or 1) + 1
            try_notify_session_revocation(session, int(cred.session_epoch))
            session.commit()
            new_epoch = int(cred.session_epoch)
        _close_local_session_streams(current_epoch=new_epoch)
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


def digest_api_key(token: str) -> str:
    """Return a non-reversible fingerprint for binding API-key-owned state."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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

    global _password_hash, _session_epoch
    if not verify_password(current):
        raise AuthConfigError("current password incorrect")
    if len(new) < 8:
        raise AuthConfigError("new password must be at least 8 characters")
    hashed = bcrypt.hashpw(bcrypt_password_bytes(new), bcrypt.gensalt())
    hashed_str = hashed.decode("utf-8")

    has_db = bool((os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip())

    # Persist directly into database atomically (password + incremented epoch)
    if not _persist_db_password_hash(hashed_str, increment_epoch=True):
        raise AuthConfigError("failed to persist password to database")

    # If without DB, increment epoch in memory
    if not has_db:
        _session_epoch += 1
        _close_local_session_streams(current_epoch=_session_epoch)

    # Refresh in-memory cache only after DB commit succeeded
    _password_hash = hashed
    path_raw = (os.environ.get("MAIL_CORE_PASSWORD_HASH_PATH") or "").strip()
    if path_raw:
        try:
            _write_password_hash_file(Path(path_raw), hashed)
        except Exception as exc:
            log.warning("could not write password hash to %s: %s", path_raw, exc)
