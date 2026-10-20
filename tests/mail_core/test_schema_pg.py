"""Requires MAIL_CORE_DATABASE_URL pointing at Postgres (CI / local compose)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect, select, text

from mail_core.db.session import get_engine, get_session_factory
from mail_core.mail.storage import Account, AccountSyncLease, MessageArchiveState, OutboxEvent, WorkerJob

REQUIRED = [
    "accounts",
    "folders",
    "messages",
    "message_locations",
    "message_bodies",
    "message_blobs",
    "message_blob_links",
    "attachments",
    "threads",
    "thread_messages",
    "sync_checkpoints",
    "sync_runs",
    "remote_operations",
    "folder_stats",
    "account_sync_leases",
    "outbox",
    "message_archive_state",
    "worker_jobs",
]


pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_all_tables_exist():
    engine = get_engine()
    names = set(inspect(engine).get_table_names())
    missing = [t for t in REQUIRED if t not in names]
    assert missing == [], missing


def test_insert_account_lease_outbox_archive():
    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"t-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        session.add(
            AccountSyncLease(
                account_id=acc.id,
                owner_id="worker-test",
                lease_expires_at=datetime.now(timezone.utc),
                heartbeat_at=datetime.now(timezone.utc),
                fencing_token=1,
            )
        )
        session.add(OutboxEvent(event_type="sync.progress", account_id=acc.id, payload={"phase": "metadata"}))
        # message + archive state
        from mail_core.mail.storage import Message

        msg = Message(
            account_id=acc.id,
            remote_id="r1",
            subject="hi",
            from_address="a@b.c",
            sort_time=datetime.now(timezone.utc),
        )
        session.add(msg)
        session.flush()
        session.add(MessageArchiveState(message_id=msg.id, state="metadata_synced"))
        session.add(WorkerJob(job_type="sync_account_folders", account_id=acc.id, payload={}))
        session.commit()

        leases = session.scalars(select(AccountSyncLease).where(AccountSyncLease.account_id == acc.id)).all()
        assert len(leases) == 1
        assert leases[0].fencing_token == 1
        assert session.scalar(text("select count(*) from outbox")) >= 1
