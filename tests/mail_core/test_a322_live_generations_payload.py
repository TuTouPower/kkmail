"""A322: _live_execution_generations must not read whole payloads.

Old code selected the full ``WorkerJob.payload`` JSON of every
PENDING/CLAIMED job and parsed ``_queue_next`` in Python — payloads can
carry large detail text, and converge_orphaned_bindings pays this on
every patrol. The fix extracts only
``_queue_next.execution_generation`` in SQL via a JSON path expression.

These tests run against the real PostgreSQL schema built by Alembic: the
JSONB path extraction, UUID columns and the session factory come straight
from production infrastructure, with no hand-written DDL.
"""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import event

from mail_core.db.session import get_engine, get_session_factory
from mail_core.mail.storage.models import WorkerJob
from mail_core.sync.execution import _live_execution_generations

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)


def _seed(Session, *, status: str, payload: dict) -> uuid.UUID:
    generation = uuid.uuid4()
    with Session() as session:
        session.add(
            WorkerJob(
                id=uuid.uuid4(),
                execution_generation=generation,
                job_type="sync_folder_delta",
                payload=payload,
                status=status,
                run_after=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()
    return generation


def _capture_sql():
    engine = get_engine()
    statements: list[str] = []

    def _record(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    return statements, lambda: event.remove(engine, "before_cursor_execute", _record)


def test_live_generations_includes_own_and_successor_only_from_live_jobs():
    Session = get_session_factory()

    successor = uuid.uuid4()
    own = _seed(
        Session,
        status="claimed",
        payload={
            "_queue_next": {"execution_generation": str(successor)},
            "detail": "x" * 5000,
        },
    )
    _seed(Session, status="pending", payload={})
    _seed(Session, status="pending", payload={"_queue_next": {"execution_generation": "not-a-uuid"}})
    dead_successor = uuid.uuid4()
    _seed(
        Session,
        status="done",
        payload={"_queue_next": {"execution_generation": str(dead_successor)}},
    )

    with Session() as session:
        live = _live_execution_generations(session)

    assert own in live
    assert successor in live
    assert dead_successor not in live
    # 3 own generations from live jobs (claimed + 2 pending) + 1 successor
    assert len(live) == 4


def test_live_generations_query_does_not_select_full_payload():
    Session = get_session_factory()
    successor = uuid.uuid4()
    _seed(
        Session,
        status="pending",
        payload={"_queue_next": {"execution_generation": str(successor)}, "detail": "y" * 1000},
    )

    statements, stop_capture = _capture_sql()
    try:
        with Session() as session:
            live = _live_execution_generations(session)
    finally:
        stop_capture()
    assert successor in live

    # No statement may select the whole payload column.
    for stmt in statements:
        assert not re.search(r"SELECT\s+worker_jobs\.payload\s+FROM", stmt), stmt
    # The successor lookup must use a PostgreSQL JSONB path extraction in SQL.
    assert any("->>" in stmt or "->" in stmt for stmt in statements), statements
