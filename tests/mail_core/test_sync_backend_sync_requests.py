"""Adoption fixes for scoped sync requests (S3/S4/S5).

All DB-backed tests run against the real PostgreSQL schema built by
Alembic; JSONB scope pushdown, UUID foreign keys and the session factory
are the production ones. No hand-written DDL reproduces production tables.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import event, select

from mail_core.db.session import get_engine, get_session_factory
import mail_core.mail.application.sync_requests as sr
from mail_core.mail.application.sync_requests import (
    create_sync_request,
    list_recent_sync_requests,
    resolve_sync_targets,
)
from mail_core.mail.storage.models import (
    Account,
    Folder,
    SyncCheckpoint,
    SyncRequest,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


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


def _select_count():
    engine = get_engine()
    seen: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append(f"{statement} {parameters!r}")

    event.listen(engine, "before_cursor_execute", before)
    return seen, lambda: event.remove(engine, "before_cursor_execute", before)


def test_s3_delta_resolution_uses_constant_number_of_queries():
    Session = get_session_factory()
    counts = {}
    # The real schema is shared for the whole test (per-test TRUNCATE only),
    # so grow the dataset incrementally instead of rebuilding a fresh DB.
    seeded = 0
    for n in (1, 6):
        _seed_accounts(Session, n - seeded)
        seeded = n
        with Session() as session:
            seen, cleanup = _select_count()
            try:
                targets = resolve_sync_targets(session, mode="delta")
            finally:
                cleanup()
            counts[n] = len(seen)
        assert len(targets) == n
        assert all(t.folder_role == "inbox" for t in targets)
    assert counts[6] == counts[1], counts


def test_s3_delta_resolution_falls_back_without_baseline():
    Session = get_session_factory()
    _seed_accounts(Session, 3, baseline=False)
    with Session() as session:
        targets = resolve_sync_targets(session, mode="delta")
    assert len(targets) == 3
    assert all(t.folder_id is None and t.folder_role is None for t in targets)


def test_s4_role_inbox_request_derives_no_background_request():
    Session = get_session_factory()
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
    Session = get_session_factory()
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
    Session = get_session_factory()
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
            seen, cleanup = _select_count()
            try:
                reports = list_recent_sync_requests(session, account_id=aid)
            finally:
                cleanup()
    assert str(bg) not in _ids(reports)
    assert any("background" in sql for sql in seen)
