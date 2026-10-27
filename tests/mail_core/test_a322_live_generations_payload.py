"""A322: _live_execution_generations must not read whole payloads.

Old code selected the full ``WorkerJob.payload`` JSON of every
PENDING/CLAIMED job and parsed ``_queue_next`` in Python — payloads can
carry large detail text, and converge_orphaned_bindings pays this on
every patrol. The fix extracts only
``_queue_next.execution_generation`` in SQL via a JSON path expression.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from mail_core.mail.storage.models import WorkerJob
from mail_core.sync.execution import _live_execution_generations

_DDL = """
CREATE TABLE worker_jobs (
    id CHAR(36) PRIMARY KEY,
    execution_generation CHAR(36) NOT NULL,
    job_type VARCHAR(64) NOT NULL,
    account_id CHAR(36),
    dedupe_key VARCHAR(128),
    payload JSON NOT NULL DEFAULT '{}',
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 100,
    run_after DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    failure_attempts INTEGER NOT NULL DEFAULT 0,
    locked_by VARCHAR(128),
    locked_at DATETIME,
    last_error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)
"""

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


def test_live_generations_includes_own_and_successor_only_from_live_jobs():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(_DDL))
    Session = sessionmaker(bind=engine)

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
    # 2 own generations from live jobs (claimed + 2 pending = 3) + 1 successor
    assert len(live) == 4


def test_live_generations_query_does_not_select_full_payload():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(_DDL))
    Session = sessionmaker(bind=engine)
    successor = uuid.uuid4()
    _seed(
        Session,
        status="pending",
        payload={"_queue_next": {"execution_generation": str(successor)}, "detail": "y" * 1000},
    )

    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    with Session() as session:
        live = _live_execution_generations(session)
    assert successor in live

    # No statement may select the whole payload column.
    for stmt in statements:
        assert not re.search(r"SELECT\s+worker_jobs\.payload\s+FROM", stmt), stmt
    # And the successor lookup must use a JSON path extraction in SQL.
    assert any(
        ("payload[" in stmt) or ("->>" in stmt) or ("json_extract" in stmt.lower())
        for stmt in statements
    ), statements
