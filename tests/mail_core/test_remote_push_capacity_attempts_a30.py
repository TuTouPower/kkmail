"""A30: capacity deferral must not consume a remote op's attempt budget.

Claiming an op marks it IN_PROGRESS, which increments ``attempts``. The
capacity branch resets the op to PENDING so it can be retried when the
connection budget frees up, but it used to keep the incremented count:
five purely capacity-driven rounds exhausted
``DEFAULT_MAX_REMOTE_OP_ATTEMPTS`` and the next real failure became
terminal even though no delivery had ever been attempted.

Note on baseline failure #7
(``test_remote_push_capacity_coalesced.py``): its failure is unrelated
to A30 -- its hand-written accounts DDL lacks the ``recipient_addresses``
column added to the Account model, so seeding the account already
raises ``sqlite3.OperationalError`` before any push logic runs. This
file carries the corrected column in its own DDL and leaves that test
untouched.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from mail_core.db import session as db_session_mod
from mail_core.mail.domain.enums import JobStatus, JobType, RemoteOperationStatus
from mail_core.mail.storage.models import Account, RemoteOperation, WorkerJob
from mail_core.providers.connection_slots import ProviderCapacityUnavailable
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
]

_NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
_WORKER = "w-a30"


class _CapacityProvider:
    def apply_remote_operation(self, _op_type, _desired_state):
        raise ProviderCapacityUnavailable("connection budget saturated")


def test_capacity_deferral_rounds_do_not_consume_attempts():
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
                id=account_id, email="push@example.test", provider="memory",
                credential_ref="ref", config={}, sync_enabled=True,
            )
        )
        session.add(
            WorkerJob(
                id=uuid.uuid4(), execution_generation=uuid.uuid4(),
                job_type=JobType.REMOTE_OPERATION_PUSH.value,
                account_id=account_id, payload={}, status=JobStatus.CLAIMED.value,
                locked_by=_WORKER, locked_at=_NOW,
                dedupe_key=f"remote-op-push:{account_id}",
                run_after=_NOW, created_at=_NOW, updated_at=_NOW,
            )
        )
        session.add(
            RemoteOperation(
                id=op_id, account_id=account_id, entity_key="msg:msg-1:read",
                op_type="mark_read",
                desired_state={"remote_id": "msg-1", "is_read": True},
                status=RemoteOperationStatus.PENDING.value, attempts=0,
                created_at=_NOW, updated_at=_NOW,
            )
        )
        session.commit()

    with (
        patch.object(db_session_mod, "get_session_factory", lambda: Session),
        patch.object(remote_push_mod, "build_provider", lambda *a, **k: _CapacityProvider()),
    ):
        for round_no in range(1, 6):
            result = remote_push_mod.push_remote_operations(account_id, worker_id=_WORKER, store=object())
            assert result["status"] == "capacity_unavailable"
            with Session() as session:
                op = session.get(RemoteOperation, op_id)
                assert op is not None
                assert op.status == RemoteOperationStatus.PENDING.value
                assert op.attempts == 0, (
                    f"round {round_no}: pure capacity waiting consumed an attempt "
                    f"(attempts={op.attempts})"
                )
                # Make the op due again for the next simulated round.
                op.next_attempt_at = None
                session.commit()
