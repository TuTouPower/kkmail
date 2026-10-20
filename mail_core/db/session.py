"""SQLAlchemy engine/session helpers for mail-core."""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


class DatabaseConfigError(RuntimeError):
    """MAIL_CORE_DATABASE_URL missing — no built-in credential default."""


def database_url() -> str:
    url = (os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip()
    if not url:
        raise DatabaseConfigError("MAIL_CORE_DATABASE_URL is required")
    return url


def _pool_kwargs() -> dict:
    return {
        "pool_pre_ping": True,
        "pool_size": int(os.environ.get("MAIL_CORE_DB_POOL_SIZE") or 10),
        "max_overflow": int(os.environ.get("MAIL_CORE_DB_MAX_OVERFLOW") or 10),
        "pool_timeout": float(os.environ.get("MAIL_CORE_DB_POOL_TIMEOUT") or 30),
        "pool_recycle": int(os.environ.get("MAIL_CORE_DB_POOL_RECYCLE") or 1800),
    }


def get_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    resolved = url or database_url()
    # Compare unmasked URLs (str(engine.url) masks the password and never matches).
    if _engine is None or _engine.url.render_as_string(hide_password=False) != resolved:
        if _engine is not None:
            _engine.dispose()
        _engine = create_engine(resolved, future=True, **_pool_kwargs())
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_session_factory(url: str | None = None) -> sessionmaker[Session]:
    get_engine(url)
    assert _SessionLocal is not None
    return _SessionLocal


def session_scope(url: str | None = None) -> Generator[Session, None, None]:
    factory = get_session_factory(url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
