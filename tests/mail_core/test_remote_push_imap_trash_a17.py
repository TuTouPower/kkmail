"""A17: IMAP trash fallback must run for real ImapProvider-shaped providers.

The old gate read ``getattr(provider, "name", "") == "imap"``; real
providers have no ``name`` attribute, so the fallback never ran and ops
kept the literal ``"Trash"`` folder. Resolving the folder must also not
poison the settlement CAS: the claimed ``desired_state`` snapshot is what
the CAS compares against, so a locally resolved trash folder that leaks
into that snapshot makes every push look "modified during push" and
loops forever.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from mail_core.db import session as db_session_mod
from mail_core.mail.domain.enums import RemoteOperationStatus
from mail_core.mail.storage.models import Account, Folder, RemoteOperation
from mail_core.providers.imap import ImapProvider
from mail_core.sync import remote_push as remote_push_mod

_DDL = [
    """
    CREATE TABLE accounts (
        id CHAR(36) PRIMARY KEY, email VARCHAR(320) NOT NULL,
        provider VARCHAR(32) NOT NULL, display_name VARCHAR(255),
        credential_ref VARCHAR(512), group_id CHAR(36),
        master_order INTEGER, group_order INTEGER,
        sync_enabled BOOLEAN NOT NULL DEFAULT 1,
        sync_status VARCHAR(32) NOT NULL DEFAULT 'idle',
        config JSON NOT NULL DEFAULT '{}',
        recipient_addresses JSON NOT NULL DEFAULT '[]',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE account_sync_leases (
        account_id CHAR(36) PRIMARY KEY, owner_id VARCHAR(128) NOT NULL,
        lease_expires_at DATETIME NOT NULL, heartbeat_at DATETIME NOT NULL,
        fencing_token INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE remote_operations (
        id CHAR(36) PRIMARY KEY, account_id CHAR(36) NOT NULL,
        entity_key VARCHAR(512) NOT NULL, op_type VARCHAR(64) NOT NULL,
        desired_state JSON NOT NULL DEFAULT '{}',
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT,
        next_attempt_at DATETIME, idempotency_key VARCHAR(128) UNIQUE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE worker_jobs (
        id CHAR(36) PRIMARY KEY, execution_generation CHAR(36) NOT NULL,
        job_type VARCHAR(64) NOT NULL, account_id CHAR(36),
        dedupe_key VARCHAR(128), payload JSON NOT NULL DEFAULT '{}',
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        priority INTEGER NOT NULL DEFAULT 100,
        run_after DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        failure_attempts INTEGER NOT NULL DEFAULT 0,
        locked_by VARCHAR(128), locked_at DATETIME, last_error TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE sync_requests (
        id CHAR(36) PRIMARY KEY, client_request_id VARCHAR(64) NOT NULL UNIQUE,
        mode VARCHAR(32) NOT NULL, "trigger" VARCHAR(32) NOT NULL,
        state VARCHAR(32) NOT NULL DEFAULT 'queued',
        scope JSON NOT NULL DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, finished_at DATETIME
    )
    """,
    """
    CREATE TABLE sync_request_targets (
        id CHAR(36) PRIMARY KEY, request_id CHAR(36) NOT NULL,
        account_id CHAR(36), folder_id CHAR(36),
        target_key VARCHAR(255) NOT NULL, requested_generation CHAR(36) NOT NULL,
        state VARCHAR(32) NOT NULL DEFAULT 'queued', error_code VARCHAR(64),
        safe_error VARCHAR(500),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, finished_at DATETIME
    )
    """,
    """
    CREATE TABLE sync_request_target_jobs (
        id CHAR(36) PRIMARY KEY, target_id CHAR(36) NOT NULL,
        execution_generation CHAR(36) NOT NULL, job_id CHAR(36),
        phase VARCHAR(64) NOT NULL DEFAULT 'sync', folder_id CHAR(36),
        status VARCHAR(32) NOT NULL DEFAULT 'queued', error_code VARCHAR(64),
        safe_error VARCHAR(500),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, finished_at DATETIME
    )
    """,
    """
    CREATE TABLE outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT, event_type VARCHAR(64) NOT NULL,
        account_id CHAR(36), payload JSON NOT NULL DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        publication_seq BIGINT, published_at DATETIME
    )
    """,
    """
    CREATE TABLE folders (
        id CHAR(36) PRIMARY KEY, account_id CHAR(36) NOT NULL,
        remote_id VARCHAR(512) NOT NULL, name VARCHAR(512) NOT NULL,
        role VARCHAR(32) NOT NULL DEFAULT 'other', parent_remote_id VARCHAR(512),
        sync_status VARCHAR(32) NOT NULL DEFAULT 'idle',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE messages (
        id CHAR(36) PRIMARY KEY, account_id CHAR(36) NOT NULL,
        remote_id VARCHAR(512), internet_message_id VARCHAR(998),
        thread_id CHAR(36), subject TEXT NOT NULL DEFAULT '',
        from_address VARCHAR(320) NOT NULL DEFAULT '', from_name VARCHAR(255),
        to_addresses JSON NOT NULL DEFAULT '[]', cc_addresses JSON NOT NULL DEFAULT '[]',
        sort_time DATETIME, is_read BOOLEAN, is_flagged BOOLEAN,
        has_attachments BOOLEAN, snippet TEXT, size_bytes BIGINT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
]

_NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)


def test_imap_trash_fallback_resolves_real_folder_and_settles_done():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    Session = sessionmaker(bind=engine)
    account_id = uuid.uuid4()
    op_id = uuid.uuid4()
    with Session() as session:
        session.add(
            Account(
                id=account_id, email="imap@example.test", provider="imap",
                credential_ref="ref", config={}, sync_enabled=True,
            )
        )
        session.add(
            Folder(
                id=uuid.uuid4(), account_id=account_id,
                remote_id="Papierkorb", name="Papierkorb", role="trash",
            )
        )
        session.add(
            RemoteOperation(
                id=op_id, account_id=account_id,
                entity_key="msg:msg-1:trash", op_type="trash",
                desired_state={
                    "remote_id": "msg-1", "folder_remote_id": "INBOX",
                    "trash_folder_remote_id": "Trash",
                },
                status=RemoteOperationStatus.PENDING.value,
                created_at=_NOW, updated_at=_NOW,
            )
        )
        session.commit()

    provider = ImapProvider(host="imap.example.test", port=993, username="u", password="p")
    assert not hasattr(provider, "name"), "real ImapProvider shape has no name attribute"
    seen: dict = {}

    def _apply(op_type, desired_state):
        seen["op_type"] = op_type
        seen["desired"] = dict(desired_state)
        return SimpleNamespace(success=True, error=None, remote_state={})

    provider.apply_remote_operation = _apply  # type: ignore[method-assign]

    # SQLite drops tzinfo on round-trip, which would make the settlement
    # CAS datetime comparison fail for an unrelated harness reason (on
    # PostgreSQL timestamptz the claimed instant compares equal). Strip
    # tzinfo from the claim timestamp so the instant is what is compared.
    original_mark = remote_push_mod.mark_remote_operation

    def _mark(session, op, **kwargs):
        applied = original_mark(session, op, **kwargs)
        if op.updated_at is not None and op.updated_at.tzinfo is not None:
            op.updated_at = op.updated_at.replace(tzinfo=None)
        return applied

    with (
        patch.object(db_session_mod, "get_session_factory", lambda: Session),
        patch.object(remote_push_mod, "build_provider", lambda *a, **k: provider),
        patch.object(remote_push_mod, "mark_remote_operation", _mark),
    ):
        result = remote_push_mod.push_remote_operations(account_id, worker_id="w-a17", store=object())

    assert result["status"] == "ok"
    assert result["pushed"] == 1, f"op must settle DONE, not loop back to PENDING: {result}"
    assert seen["desired"]["trash_folder_remote_id"] == "Papierkorb"
    with Session() as session:
        op = session.get(RemoteOperation, op_id)
        assert op is not None and op.status == RemoteOperationStatus.DONE.value
