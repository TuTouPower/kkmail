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

These tests drive the real chain on PostgreSQL:
``create_sync_request`` (x2, sharing) -> ``claim_jobs`` ->
``sync_account_folders`` -> ``complete_job`` -> ``claim_jobs`` ->
``sync_folder_metadata`` -> ``complete_job`` -> ``claim_jobs`` (reconcile)
-> ``complete_job``.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
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
from mail_core.sync.jobs import claim_jobs, complete_job

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
_WORKER = "w-defect4"


class _Provider:
    """One selectable INBOX; metadata exhausts in a single empty page."""

    def list_folders(self):
        return [RemoteFolder(remote_id="INBOX", name="INBOX", role="inbox")]

    def fetch_metadata_page(self, _remote_id, _cursor):
        return MetadataPage(items=[], next_cursor={"uid_next": 2}, exhausted=True)


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


def _create_two_full_requests(Session, account_id: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    ids = []
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
        complete_job(session, job, worker_id=_WORKER)
        session.commit()


def _uuid_or_none(value) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value else None


def test_shared_full_requests_complete_only_after_metadata_and_reconcile():
    Session = get_session_factory()
    account_id = _seed_account(Session)
    first_id, second_id = _create_two_full_requests(Session, account_id)

    # Precondition: both requests share ONE pending discovery job and hold
    # bindings at the same execution generation; the payload carries only
    # the second (last-merged) request's id.
    with Session() as session:
        discovery_jobs = list(
            session.scalars(
                select(WorkerJob).where(WorkerJob.job_type == JobType.SYNC_ACCOUNT_FOLDERS.value, WorkerJob.account_id == account_id)
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
    with patch.object(engine_mod, "build_provider", lambda *_a, **_k: provider):
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
            if session.get(FolderStats, folder_id) is None:
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
