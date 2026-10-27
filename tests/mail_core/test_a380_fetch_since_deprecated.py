"""A380: fetch_since is a v1 legacy id-ordered replay API that bypasses the
v2 publication order. It must be marked deprecated, warn on use, and have
no production callers (production replay uses fetch_published_since)."""
import re
import warnings
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from mail_core.mail.storage.models import OutboxEvent
from mail_core.realtime.outbox import fetch_since

ROOT = Path(__file__).resolve().parents[2]


def test_no_production_callers_of_fetch_since():
    offenders = []
    for path in (ROOT / "src" / "mail_core").rglob("*.py"):
        if path.name == "outbox.py" and "realtime" in path.parts:
            continue
        if path.name == "__init__.py" and "realtime" in path.parts:
            continue  # legacy re-export, retained only for compat
        if re.search(r"\bfetch_since\b", path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_fetch_since_is_marked_deprecated():
    assert fetch_since.__doc__ is not None
    assert "deprecat" in fetch_since.__doc__.lower()
    assert "fetch_published_since" in fetch_since.__doc__


def _session_factory():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type VARCHAR(64) NOT NULL, account_id CHAR(36),
                payload JSON NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                publication_seq BIGINT, published_at DATETIME)
            """))
    return sessionmaker(bind=engine)


def test_fetch_since_warns_deprecation_but_still_works():
    Session = _session_factory()
    with Session() as session:
        row = OutboxEvent(event_type="sync.progress", payload={})
        session.add(row)
        session.commit()
        row_id = row.id
    with Session() as session:
        with pytest.warns(DeprecationWarning, match="fetch_since"):
            rows = fetch_since(session, last_event_id=row_id - 1, limit=10)
        assert [r.id for r in rows] == [row_id]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            assert fetch_since(session, last_event_id=row_id, limit=10) == []
