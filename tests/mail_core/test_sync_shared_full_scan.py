"""DEFECT 4: two full requests sharing one deduplicated discovery job.

``create_sync_request`` enqueues the folder-discovery job under dedupe key
``sync:{account_id}``; a second full request for the same account arriving
while that job is PENDING dedupes onto the same job and both requests'
targets bind its execution generation. The job payload, however, carries a
SINGLE ``request_id`` (the second request's, after the pending-payload
merge). ``engine.sync_account_folders`` bound the metadata phase jobs only
for that payload request, and ``sync_folder_metadata`` bound the reconcile
job the same way. The other sharing request therefore held only the
discovery-generation binding: when the discovery job settled, its target
aggregated to complete and the request flipped to ``complete`` at the end
of folder discovery, while the metadata/reconcile work it depended on was
still queued.

These tests drive the real chain on a SQLite engine --
``create_sync_request`` (x2, sharing) -> ``claim_jobs`` ->
``sync_account_folders`` -> ``complete_job`` -> ``claim_jobs`` ->
``sync_folder_metadata`` -> ``complete_job`` -> ``claim_jobs`` (reconcile)
-> ``complete_job`` -- following ``test_sync_execution_lock_order.py`` /
``test_sync_successor_binding_backfill.py``: SQLite strips ``FOR UPDATE``
and cannot execute the PostgreSQL advisory generation lock or
``pg_notify``, so ``lock_generation`` and ``try_notify_outbox`` are
patched out; neither is the invariant under test. The PostgreSQL version
of the single-request lifecycle lives in
``test_sync_execution_tracking.py::test_full_scan_resets_cursor_and_completes_only_after_reconcile``
(skipped in unit mode: no ``MAIL_CORE_DATABASE_URL`` in this sandbox).

No existing test is modified by this file.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from mail_core.sync import jobs as jobs_mod

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from mail_core.mail.application.sync_requests import create_sync_request, get_sync_request_report
from mail_core.mail.domain.enums import JobType
from mail_core.mail.storage.models import (
    Account,
    Folder,
    FolderStats,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.providers.base import MetadataPage, RemoteFolder
from mail_core.sync import engine as engine_mod
from mail_core.sync import execution as execution_mod
from mail_core.sync.jobs import claim_jobs, complete_job

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
    CREATE TABLE folders (
        id CHAR(36) PRIMARY KEY,
        account_id CHAR(36) NOT NULL,
        remote_id VARCHAR(512) NOT NULL,
        name VARCHAR(512) NOT NULL,
        role VARCHAR(32) NOT NULL DEFAULT 'other',
        parent_remote_id VARCHAR(512),
        sync_status VARCHAR(32) NOT NULL DEFAULT 'idle',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE folder_stats (
        folder_id CHAR(36) PRIMARY KEY,
        total_count INTEGER NOT NULL DEFAULT 0,
        unread_count INTEGER,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
    """
    CREATE TABLE account_sync_leases (
        account_id CHAR(36) PRIMARY KEY,
        owner_id VARCHAR(128) NOT NULL,
        lease_expires_at DATETIME NOT NULL,
        heartbeat_at DATETIME NOT NULL,
        fencing_token INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE sync_runs (
        id CHAR(36) PRIMARY KEY,
        account_id CHAR(36) NOT NULL,
        folder_id CHAR(36),
        phase VARCHAR(64) NOT NULL,
        status VARCHAR(32) NOT NULL,
        stats JSON NOT NULL DEFAULT '{}',
        error TEXT,
        fencing_token INTEGER,
        started_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        finished_at DATETIME
    )
    """,
    """
    CREATE TABLE sync_checkpoints (
        account_id CHAR(36) NOT NULL,
        folder_id CHAR(36) NOT NULL,
        cursor JSON NOT NULL DEFAULT '{}',
        uidvalidity BIGINT,
        modseq BIGINT,
        history_id VARCHAR(128),
        delta_link TEXT,
        full_scan_complete BOOLEAN NOT NULL DEFAULT 0,
        scan_generation CHAR(36),
        fencing_token INTEGER,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (account_id, folder_id)
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
_WORKER = "w-defect4"


class _Provider:
    """One selectable INBOX; metadata exhausts in a single empty page."""

    def list_folders(self):
        return [RemoteFolder(remote_id="INBOX", name="INBOX", role="inbox")]

    def fetch_metadata_page(self, _remote_id, _cursor):
        return MetadataPage(items=[], next_cursor={"uid_next": 2}, exhausted=True)


def _make_session_factory():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    return sessionmaker(bind=engine)


def _seed_account(Session) -> uuid.UUID:
    account_id = uuid.uuid4()
    with Session() as session:
        session.add(
            Account(
                id=account_id,
                email=f"defect4-{uuid.uuid4().hex[:8]}@example.com",
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
    return account_id


class _NaiveUTCDateTime(datetime):
    """datetime whose now() is naive UTC.

    SQLite strips tzinfo when storing ``DateTime(timezone=True)`` values,
    so a re-read ``WorkerJob.run_after`` is naive and the pending-job
    payload merge in ``enqueue_job`` would compare it against an aware
    ``datetime.now(timezone.utc)`` (PostgreSQL returns aware values; this
    is a harness-only artifact). Making the jobs module produce naive UTC
    during request creation keeps the comparison consistent without
    touching the sharing semantics under test.
    """

    @classmethod
    def now(cls, tz=None):  # noqa: D102 - test harness shim
        return datetime.now(timezone.utc).replace(tzinfo=None)


def _create_two_full_requests(Session, account_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    ids = []
    with patch.object(jobs_mod, "datetime", _NaiveUTCDateTime):
        with Session() as session:
            for _ in range(2):
                req, created = create_sync_request(
                    session,
                    client_request_id=f"defect4-{uuid.uuid4().hex}",
                    mode="full",
                    trigger="manual",
                    scope={"account_id": str(account_id)},
                    account_id=account_id,
                )
                assert created
                ids.append(req.id)
            session.commit()
    return ids[0], ids[1]


def _report(Session, request_id: uuid.UUID):
    with Session() as session:
        return get_sync_request_report(session, request_id)


def _claim_one(Session, job_type: str, account_id: uuid.UUID) -> tuple[uuid.UUID, dict]:
    with Session() as session:
        jobs = claim_jobs(
            session,
            worker_id=_WORKER,
            limit=1,
            job_types=[job_type],
            account_id=account_id,
        )
        assert jobs, f"expected a claimable {job_type} job"
        job_id, payload = jobs[0].id, dict(jobs[0].payload or {})
        session.commit()
        return job_id, payload


def _complete(Session, job_id: uuid.UUID) -> None:
    with Session() as session:
        job = session.get(WorkerJob, job_id)
        assert job is not None
        with patch.object(execution_mod, "lock_generation", lambda _s, _g: None):
            complete_job(session, job, worker_id=_WORKER)
        session.commit()


def _uuid_or_none(value) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value else None


def test_shared_full_requests_complete_only_after_metadata_and_reconcile():
    Session = _make_session_factory()
    account_id = _seed_account(Session)
    first_id, second_id = _create_two_full_requests(Session, account_id)

    # Precondition: both requests share ONE pending discovery job and hold
    # bindings at the same execution generation; the payload carries only
    # the second (last-merged) request's id.
    with Session() as session:
        discovery_jobs = list(
            session.scalars(
                select(WorkerJob).where(WorkerJob.job_type == JobType.SYNC_ACCOUNT_FOLDERS.value)
            ).all()
        )
        assert len(discovery_jobs) == 1
        assert discovery_jobs[0].payload.get("request_id") == str(second_id)
        targets = list(
            session.scalars(
                select(SyncRequestTarget).where(
                    SyncRequestTarget.request_id.in_([first_id, second_id])
                )
            ).all()
        )
        assert len(targets) == 2
        bindings = list(
            session.scalars(
                select(SyncRequestTargetJob).where(
                    SyncRequestTargetJob.target_id.in_([t.id for t in targets])
                )
            ).all()
        )
        assert len(bindings) == 2
        assert bindings[0].execution_generation == bindings[1].execution_generation

    provider = _Provider()
    with (
        patch.object(engine_mod, "_session_factory", lambda: Session),
        patch.object(engine_mod, "build_provider", lambda *_a, **_k: provider),
        patch("mail_core.sync.metadata.try_notify_outbox", lambda _s: None),
    ):
        # --- Discovery phase -------------------------------------------------
        discovery_id, payload = _claim_one(Session, JobType.SYNC_ACCOUNT_FOLDERS.value, account_id)
        result = engine_mod.sync_account_folders(
            account_id,
            worker_id=_WORKER,
            store=object(),
            full=bool(payload.get("full")),
            scan_generation=_uuid_or_none(payload.get("scan_generation")),
            request_id=_uuid_or_none(payload.get("request_id")),
        )
        assert result["status"] == "ok"
        _complete(Session, discovery_id)

        # (1) Discovery settling must complete NEITHER request: both depend
        # on the metadata phase jobs created during discovery. On the old
        # code the non-payload (first) request flips to complete here.
        for request_id in (first_id, second_id):
            report = _report(Session, request_id)
            assert report.state in ("queued", "running"), (
                f"request {request_id} completed at end of discovery"
            )
            assert report.completed_count == 0
            assert report.finished_at is None

        with Session() as session:
            folder = session.scalar(select(Folder).where(Folder.account_id == account_id))
            assert folder is not None
            folder_id = folder.id
            # Pre-seed folder stats so the empty metadata page does not
            # trigger a stats recompute (which needs the message tables).
            session.add(FolderStats(folder_id=folder_id, total_count=0, unread_count=0, updated_at=_NOW))
            session.commit()

        # --- Metadata phase --------------------------------------------------
        metadata_id, payload = _claim_one(Session, JobType.SYNC_FOLDER_METADATA.value, account_id)
        result = engine_mod.sync_folder_metadata(
            account_id,
            folder_id,
            worker_id=_WORKER,
            store=object(),
            full=bool(payload.get("full")),
            scan_generation=_uuid_or_none(payload.get("scan_generation")),
            request_id=_uuid_or_none(payload.get("request_id")),
        )
        assert result["status"] == "ok"
        assert result["exhausted"] is True
        _complete(Session, metadata_id)

        # Reconcile was queued at metadata exhaustion; both requests still
        # hold its open binding, so neither is complete yet.
        for request_id in (first_id, second_id):
            report = _report(Session, request_id)
            assert report.state in ("queued", "running")
            assert report.completed_count == 0

        # --- Reconcile phase ---------------------------------------------------
        reconcile_id, _payload = _claim_one(Session, JobType.RECONCILE_FOLDER.value, account_id)
        _complete(Session, reconcile_id)

    # (2) With metadata + reconcile bindings settled complete, BOTH
    # requests aggregate to complete.
    for request_id in (first_id, second_id):
        report = _report(Session, request_id)
        assert report.state == "complete"
        assert report.completed_count == 1
        assert report.finished_at is not None
