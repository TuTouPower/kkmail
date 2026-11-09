"""Adoption fixes for scoped sync requests (S3/S4/S5).

All tests run against an in-memory SQLite engine with hand-written DDL
(same pattern as test_sync_requests_paused_folder.py / test_sync_requests_scope_exact.py),
so no PostgreSQL runtime is required.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

import mail_core.mail.application.sync_requests as sr
from mail_core.mail.application.sync_requests import (
    create_sync_request,
    list_recent_sync_requests,
    resolve_sync_targets,
)
from mail_core.mail.storage.models import (
    Account,
    Base,
    Folder,
    SyncCheckpoint,
    SyncRequest,
)

_ACCOUNTS_DDL = """
CREATE TABLE accounts (
    id CHAR(36) PRIMARY KEY,
    email VARCHAR(320) NOT NULL UNIQUE,
    provider VARCHAR(32) NOT NULL,
    display_name VARCHAR(255),
    credential_ref VARCHAR(512),
    group_id CHAR(36),
    master_order INTEGER,
    group_order INTEGER,
    sync_enabled BOOLEAN NOT NULL DEFAULT 1,
    sync_status VARCHAR(32) NOT NULL DEFAULT 'idle',
    config TEXT NOT NULL DEFAULT '{}',
    recipient_addresses TEXT NOT NULL DEFAULT '[]',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_CHECKPOINTS_DDL = """
CREATE TABLE sync_checkpoints (
    account_id CHAR(36) NOT NULL,
    folder_id CHAR(36) NOT NULL,
    cursor TEXT NOT NULL DEFAULT '{}',
    uidvalidity BIGINT,
    modseq BIGINT,
    history_id VARCHAR(128),
    delta_link TEXT,
    full_scan_complete BOOLEAN NOT NULL DEFAULT 0,
    scan_generation CHAR(36),
    fencing_token BIGINT NOT NULL DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PRIMARY KEY (account_id, folder_id)
)
"""

_SYNC_REQUESTS_DDL = """
CREATE TABLE sync_requests (
    id CHAR(36) PRIMARY KEY,
    client_request_id VARCHAR(64) NOT NULL UNIQUE,
    mode VARCHAR(32) NOT NULL,
    "trigger" VARCHAR(32) NOT NULL,
    state VARCHAR(32) NOT NULL DEFAULT 'queued',
    scope JSON NOT NULL DEFAULT '{}',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME
)
"""

_SYNC_TARGETS_DDL = """
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
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME
)
"""

_DDL = [_ACCOUNTS_DDL, _CHECKPOINTS_DDL, _SYNC_REQUESTS_DDL, _SYNC_TARGETS_DDL]


def _make_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    Base.metadata.create_all(engine, tables=[Folder.__table__])
    return engine


def _seed_accounts(Session, n: int, *, baseline: bool = True):
    ids = []
    with Session() as session:
        for i in range(n):
            aid = uuid.uuid4()
            fid = uuid.uuid4()
            session.add(
                Account(id=aid, email=f"s3-{i}-{uuid.uuid4().hex[:6]}@example.test",
                        provider="imap", sync_enabled=True)
            )
            session.add(
                Folder(id=fid, account_id=aid, remote_id="INBOX", name="INBOX",
                       role="inbox", sync_status="idle")
            )
            session.flush()
            if baseline:
                session.add(
                    SyncCheckpoint(account_id=aid, folder_id=fid, cursor={"modseq": 0},
                                   full_scan_complete=True)
                )
            ids.append((aid, fid))
        session.commit()
    return ids


def _select_count(engine):
    seen: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(f"{statement} {parameters!r}")

    event.listen(engine, "before_cursor_execute", before)
    return seen, lambda: event.remove(engine, "before_cursor_execute", before)


def test_s3_delta_resolution_uses_constant_number_of_queries():
    counts = {}
    for n in (1, 6):
        engine = _make_engine()
        Session = sessionmaker(bind=engine)
        _seed_accounts(Session, n)
        with Session() as session:
            seen, cleanup = _select_count(engine)
            try:
                targets = resolve_sync_targets(session, mode="delta")
            finally:
                cleanup()
            counts[n] = len(seen)
        assert len(targets) == n
        assert all(t.folder_role == "inbox" for t in targets)
    assert counts[6] == counts[1], counts


def test_s3_delta_resolution_falls_back_without_baseline():
    engine = _make_engine()
    Session = sessionmaker(bind=engine)
    _seed_accounts(Session, 3, baseline=False)
    with Session() as session:
        targets = resolve_sync_targets(session, mode="delta")
    assert len(targets) == 3
    assert all(t.folder_id is None and t.folder_role is None for t in targets)


def test_s4_role_inbox_request_derives_no_background_request():
    engine = _make_engine()
    Session = sessionmaker(bind=engine)
    aid, _fid = _seed_accounts(Session, 1)[0]
    with (
        patch.object(sr, "enqueue_job", return_value=MagicMock()),
        patch.object(sr, "binding_generation_for", return_value=(uuid.uuid4(), MagicMock())),
        patch.object(sr, "bind_target"),
    ):
        with Session() as session:
            create_sync_request(
                session,
                client_request_id="s4-role-inbox",
                mode="delta",
                trigger="navigation",
                scope={"folder_role": "inbox"},
                folder_role="inbox",
            )
            session.commit()
    with Session() as session:
        bg_rows = list(
            session.scalars(
                select(SyncRequest).where(SyncRequest.scope["background"].as_boolean().is_(True))
            ).all()
        )
    assert bg_rows == []


def test_s4_global_delta_request_derives_background_via_scope():
    """Replaces the marker-based test. The payload ``background`` key is gone
    (zero-compat burden): the derived discovery job now carries only
    ``request_id`` pointing at the request whose scope holds the flag."""
    engine = _make_engine()
    Session = sessionmaker(bind=engine)
    _seed_accounts(Session, 1)
    with (
        patch.object(sr, "enqueue_job", return_value=MagicMock()) as enq,
        patch.object(sr, "binding_generation_for", return_value=(uuid.uuid4(), MagicMock())),
        patch.object(sr, "bind_target"),
    ):
        with Session() as session:
            create_sync_request(
                session,
                client_request_id="s4-global-delta",
                mode="delta",
                trigger="manual",
                scope={},
            )
            session.commit()
    with Session() as session:
        bg_rows = list(
            session.scalars(
                select(SyncRequest).where(SyncRequest.scope["background"].as_boolean().is_(True))
            ).all()
        )
        assert len(bg_rows) == 1
        bg_id = bg_rows[0].id
    bg_calls = [
        c for c in enq.call_args_list
        if c.kwargs.get("job_type") == "sync_account_folders"
        and c.kwargs.get("payload", {}).get("request_id") == str(bg_id)
    ]
    assert len(bg_calls) == 1
    assert "background" not in bg_calls[0].kwargs["payload"]


def _seed_request(Session, *, scope: dict, state: str) -> uuid.UUID:
    rid = uuid.uuid4()
    with Session() as session:
        session.add(
            SyncRequest(
                id=rid,
                client_request_id=f"s5-{uuid.uuid4().hex}",
                mode="delta",
                trigger="manual",
                state=state,
                scope=scope,
                created_at=datetime(2026, 11, 4, tzinfo=timezone.utc),
            )
        )
        session.commit()
    return rid


def _ids(reports) -> set[str]:
    return {r.id for r in reports}


def test_s5_background_filter_is_pushed_into_sql():
    engine = _make_engine()
    Session = sessionmaker(bind=engine)
    aid = uuid.uuid4()
    fg = _seed_request(Session, scope={"account_id": str(aid), "folder_role": "inbox"}, state="queued")
    bg = _seed_request(
        Session,
        scope={"account_id": str(aid), "background": True, "parent_request_id": str(uuid.uuid4())},
        state="queued",
    )
    bg_false = _seed_request(Session, scope={"account_id": str(aid), "background": False}, state="running")

    with Session() as session:
        reports = list_recent_sync_requests(session, account_id=aid)
        assert _ids(reports) == {str(fg), str(bg_false)}

    with patch.object(sr, "_scope_matches", return_value=True):
        with Session() as session:
            seen, cleanup = _select_count(engine)
            try:
                reports = list_recent_sync_requests(session, account_id=aid)
            finally:
                cleanup()
    assert str(bg) not in _ids(reports)
    assert any("background" in sql for sql in seen)
