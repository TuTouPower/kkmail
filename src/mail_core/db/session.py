"""SQLAlchemy engine/session helpers for mail-core."""

from __future__ import annotations

import os
import threading

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mail_core.db.events import install_session_wake_hooks

install_session_wake_hooks(Session)

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_engine_lock = threading.Lock()


class DatabaseConfigError(RuntimeError):
    """MAIL_CORE_DATABASE_URL missing — no built-in credential default."""


def database_url() -> str:
    url = (os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip()
    if not url:
        raise DatabaseConfigError("MAIL_CORE_DATABASE_URL is required")
    return url


def _pool_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise DatabaseConfigError(
            f"{name} must be an integer >= {minimum} (got {raw!r})"
        ) from exc
    if value < minimum:
        raise DatabaseConfigError(
            f"{name} must be an integer >= {minimum} (got {value})"
        )
    return value


def _pool_timeout() -> float:
    import math

    name = "MAIL_CORE_DB_POOL_TIMEOUT"
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return 30.0
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise DatabaseConfigError(
            f"{name} must be a finite number > 0 (got {raw!r})"
        ) from exc
    if not math.isfinite(value) or value <= 0:
        raise DatabaseConfigError(
            f"{name} must be a finite number > 0 (got {value})"
        )
    return value


def _pool_kwargs() -> dict:
    return {
        "pool_pre_ping": True,
        "pool_size": _pool_int("MAIL_CORE_DB_POOL_SIZE", 10, minimum=1),
        "max_overflow": _pool_int("MAIL_CORE_DB_MAX_OVERFLOW", 10, minimum=0),
        "pool_timeout": _pool_timeout(),
        "pool_recycle": _pool_int("MAIL_CORE_DB_POOL_RECYCLE", 1800, minimum=0),
    }


def _get_engine_locked(resolved: str) -> Engine:
    global _engine, _SessionLocal
    # Compare unmasked URLs (str(engine.url) masks the password and never matches).
    if _engine is None or _engine.url.render_as_string(hide_password=False) != resolved:
        if _engine is not None:
            _engine.dispose()
        _engine = create_engine(resolved, future=True, **_pool_kwargs())
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_engine(url: str | None = None) -> Engine:
    resolved = url or database_url()
    with _engine_lock:
        return _get_engine_locked(resolved)


def get_session_factory(url: str | None = None) -> sessionmaker[Session]:
    global _SessionLocal
    resolved = url or database_url()
    with _engine_lock:
        _get_engine_locked(resolved)
        assert _SessionLocal is not None
        return _SessionLocal
