"""A143: list_recent_sync_requests must not starve on a fixed 200-row scan
or build reports with per-request (N+1) target queries."""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from mail_core.mail.application.sync_requests import list_recent_sync_requests
from mail_core.mail.storage.models import SyncRequest, SyncRequestTarget

_DDL = [
    """
    CREATE TABLE sync_requests (
        id CHAR(36) PRIMARY KEY,
        client_request_id VARCHAR(64) NOT NULL UNIQUE,
        mode VARCHAR(32) NOT NULL,
        "trigger" VARCHAR(32) NOT NULL,
        state VARCHAR(32) NOT NULL DEFAULT 'queued',
        scope JSON NOT NULL DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        finished_at DATETIME
    )
    """,
    """
    CREATE TABLE sync_request_targets (
        id CHAR(36) PRIMARY KEY,
        request_id CHAR(36) NOT NULL,
        account_id CHAR(36),
        folder_id CHAR(36),
        target_key VARCHAR(255) NOT NULL,
        requested_generation CHAR(36) NOT NULL,
        state VARCHAR(32) NOT NULL DEFAULT 'queued',
        error_code VARCHAR(64),
        safe_error VARCHAR(500),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        finished_at DATETIME
    )
    """,
]
_BASE = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

def _make_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    return engine

def _seed(session, *, scope, created_at, state="queued", targets=0):
    rid = uuid.uuid4()
    session.add(SyncRequest(id=rid, client_request_id=f"a143-{uuid.uuid4().hex}", mode="delta", trigger="manual", state=state, scope=scope, created_at=created_at))
    for i in range(targets):
        session.add(SyncRequestTarget(id=uuid.uuid4(), request_id=rid, account_id=None, folder_id=None, target_key=f"k{i}", requested_generation=uuid.uuid4(), state="complete" if i == 0 else "queued", created_at=created_at))
    return rid

def test_matching_requests_not_starved_by_200_newer_unrelated():
    engine = _make_engine()
    Session = sessionmaker(bind=engine)
    account_id = uuid.uuid4()
    other = uuid.uuid4()
    with Session() as session:
        matching = [_seed(session, scope={"account_id": str(account_id)}, created_at=_BASE + timedelta(minutes=i)) for i in range(3)]
        for i in range(250):
            _seed(session, scope={"account_id": str(other)}, created_at=_BASE + timedelta(hours=2, minutes=i))
        session.commit()
    with Session() as session:
        reports = list_recent_sync_requests(session, account_id=account_id)
    assert {r.id for r in reports} == {str(m) for m in matching}

def test_reports_batch_load_targets_single_query():
    engine = _make_engine()
    Session = sessionmaker(bind=engine)
    account_id = uuid.uuid4()
    with Session() as session:
        ids = [_seed(session, scope={"account_id": str(account_id)}, created_at=_BASE + timedelta(minutes=i), targets=2) for i in range(5)]
        session.commit()
    target_selects = []
    def _count(conn, cursor, statement, parameters, context, executemany):
        if "sync_request_targets" in statement and statement.lstrip().upper().startswith("SELECT"):
            target_selects.append(statement)
    event.listen(engine, "before_cursor_execute", _count)
    try:
        with Session() as session:
            reports = list_recent_sync_requests(session, account_id=account_id)
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert {r.id for r in reports} == {str(i) for i in ids}
    assert all(r.target_count == 2 and r.completed_count == 1 and r.queued_count == 1 for r in reports)
    assert len(target_selects) == 1, f"expected 1 batched target query, got {len(target_selects)}"

def test_global_query_still_scope_exact_under_batch_scan():
    engine = _make_engine()
    Session = sessionmaker(bind=engine)
    account_id = uuid.uuid4()
    with Session() as session:
        global_id = _seed(session, scope={"all": True}, created_at=_BASE)
        _seed(session, scope={"account_id": str(account_id)}, created_at=_BASE + timedelta(minutes=1))
        session.commit()
    with Session() as session:
        reports = list_recent_sync_requests(session)
    assert {r.id for r in reports} == {str(global_id)}
