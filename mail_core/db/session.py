"""SQLAlchemy engine/session helpers for mail-core."""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://kkmail:kkmail@127.0.0.1:5433/kkmail_mail"

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def database_url() -> str:
    return os.environ.get("MAIL_CORE_DATABASE_URL", DEFAULT_DATABASE_URL)


def get_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    resolved = url or database_url()
    if _engine is None or str(_engine.url) != resolved:
        _engine = create_engine(resolved, pool_pre_ping=True, future=True)
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
