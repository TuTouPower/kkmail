"""Full-scan reuse must cover the metadata phase, not only discovery.

``_inflight_full_root_generation`` only looked at the folder-discovery
job (``sync:{account_id}``). Once discovery completes, that job is DONE
while the scan continues in per-folder metadata jobs
(``metadata:{account_id}:{folder_id}``, payload carrying the root
``scan_generation``). A full request issued in that window found no
in-flight generation, allocated a NEW root generation and forced a
second full scan with a cursor reset, instead of observing the scan
already in progress.

Pinned here on SQLite (hand DDL, following
test_sync_shared_full_scan.py): after discovery is DONE and a metadata
job is still PENDING, a second full request reuses the in-flight root
generation; once the metadata job is DONE too, the helper reports no
in-flight generation. No existing test is modified by this file.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from mail_core.mail.application.sync_requests import (
    _inflight_full_root_generation,
    create_sync_request,
)
from mail_core.mail.domain.enums import JobStatus, JobType
from mail_core.mail.storage.models import Account, SyncRequestTarget, WorkerJob

_DDL = [
    """
    CREATE TABLE accounts (
        id CHAR(36) PRIMARY KEY,
        email VARCHAR(320) NOT NULL,
        provider VARCHAR(32) NOT NULL,
        display_name VARCHAR(255),
        credential_ref VARCHAR(512),
        group_id CHAR(36),
        master_order INTEGER,
        group_order INTEGER,
        sync_enabled BOOLEAN NOT NULL DEFAULT 1,
        sync_status VARCHAR(32) NOT NULL DEFAULT 'idle',
        config JSON NOT NULL DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
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
    """
    CREATE TABLE sync_request_target_jobs (
        id CHAR(36) PRIMARY KEY,
        target_id CHAR(36) NOT NULL,
        execution_generation CHAR(36) NOT NULL,
        job_id CHAR(36),
        phase VARCHAR(64) NOT NULL DEFAULT 'sync',
        folder_id CHAR(36),
        status VARCHAR(32) NOT NULL DEFAULT 'queued',
        error_code VARCHAR(64),
        safe_error VARCHAR(500),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        finished_at DATETIME
    )
    """,
    """
    CREATE TABLE outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type VARCHAR(64) NOT NULL,
        account_id CHAR(36),
        payload JSON NOT NULL DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        publication_seq BIGINT,
        published_at DATETIME
    )
    """,
    """
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
    """,
]

_NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


def _make_session_factory():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    return sessionmaker(bind=engine)


def _create_full_request(Session, account_id: uuid.UUID) -> uuid.UUID:
    with Session() as session:
        req, created = create_sync_request(
            session,
            client_request_id=f"meta-reuse-{uuid.uuid4().hex}",
            mode="full",
            trigger="manual",
            scope={"account_id": str(account_id)},
            account_id=account_id,
        )
        assert created
        session.commit()
        return req.id


def _requested_generation(Session, request_id: uuid.UUID) -> uuid.UUID:
    with Session() as session:
        target = session.scalar(
            select(SyncRequestTarget).where(SyncRequestTarget.request_id == request_id)
        )
        assert target is not None
        return target.requested_generation


def test_full_request_reuses_root_generation_while_metadata_in_flight():
    Session = _make_session_factory()
    account_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    with Session() as session:
        session.add(
            Account(
                id=account_id,
                email=f"meta-reuse-{uuid.uuid4().hex[:8]}@example.com",
                provider="imap",
                credential_ref=None,
                sync_enabled=True,
                sync_status="idle",
                config={},
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()

    first_id = _create_full_request(Session, account_id)
    root_generation = _requested_generation(Session, first_id)

    # Discovery completes; the scan continues in a per-folder metadata
    # job carrying the root generation (the engine's enqueue shape).
    with Session() as session:
        discovery = session.scalar(
            select(WorkerJob).where(WorkerJob.dedupe_key == f"sync:{account_id}")
        )
        assert discovery is not None
        discovery.status = JobStatus.DONE.value
        session.add(
            WorkerJob(
                id=uuid.uuid4(),
                execution_generation=uuid.uuid4(),
                job_type=JobType.SYNC_FOLDER_METADATA.value,
                account_id=account_id,
                dedupe_key=f"metadata:{account_id}:{folder_id}",
                payload={
                    "folder_id": str(folder_id),
                    "full": True,
                    "scan_generation": str(root_generation),
                    "request_id": str(first_id),
                },
                status=JobStatus.PENDING.value,
                run_after=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()

    with Session() as session:
        assert _inflight_full_root_generation(session, account_id) == root_generation

    second_id = _create_full_request(Session, account_id)
    assert _requested_generation(Session, second_id) == root_generation, (
        "second full request allocated a new root generation although the "
        "first scan's metadata phase is still in flight"
    )

    # Once the metadata job AND the second request's own discovery job
    # are done too, nothing is in flight anymore.
    with Session() as session:
        for job in session.scalars(select(WorkerJob)).all():
            job.status = JobStatus.DONE.value
        session.commit()
    with Session() as session:
        assert _inflight_full_root_generation(session, account_id) is None
