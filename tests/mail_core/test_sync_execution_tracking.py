"""Package C (R06/R08): sync-request execution tracking and full-scan lifecycle.

PostgreSQL-backed: these tests drive the real ``handle_job`` / ``complete_job``
/ ``fail_job`` paths so request reports must reach terminal states with
correct counts — the review's repro was a completed WorkerJob whose request
report stayed ``queued`` forever.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.application.sync_requests import create_sync_request, get_sync_request_report
from mail_core.mail.domain.enums import JobStatus, JobType
from mail_core.mail.storage.models import (
    Account,
    Folder,
    OutboxEvent,
    SyncCheckpoint,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.providers.base import DeltaPage, MetadataPage, RemoteFolder
from mail_core.sync.checkpoints import ScanGenerationMismatch, commit_checkpoint
from mail_core.sync.engine import sync_folder_metadata
from mail_core.sync.jobs import claim_jobs, enqueue_job, fail_job
from mail_core.sync.leases import acquire_lease
from mail_core.worker.handlers import handle_job

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

WORKER = "w-pkg-c"


def _seed_account_folder(*, full_scan_complete: bool = True, cursor: dict | None = None):
    Session = get_session_factory()
    with Session() as session:
        account = Account(
            email=f"pkgc-{uuid.uuid4().hex[:8]}@example.com",
            provider="imap",
            sync_enabled=True,
        )
        session.add(account)
        session.flush()
        folder = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        session.add(
            SyncCheckpoint(
                account_id=account.id,
                folder_id=folder.id,
                cursor=cursor if cursor is not None else {"uid_next": 500},
                uidvalidity=7,
                full_scan_complete=full_scan_complete,
            )
        )
        session.commit()
        return account.id, folder.id


def _create_delta_request(account_id, folder_id, client_id: str | None = None):
    Session = get_session_factory()
    with Session() as session:
        req, created = create_sync_request(
            session,
            client_request_id=client_id or f"pkgc-{uuid.uuid4().hex}",
            mode="delta",
            trigger="manual",
            scope={"account_id": str(account_id), "folder_id": str(folder_id)},
            account_id=account_id,
            folder_id=folder_id,
        )
        session.commit()
        assert created
        return req.id


def _report(request_id):
    Session = get_session_factory()
    with Session() as session:
        return get_sync_request_report(session, request_id)


def _claim_one(job_type: str | None = None, account_id: uuid.UUID | None = None) -> uuid.UUID:
    Session = get_session_factory()
    with Session() as session:
        jobs = claim_jobs(
            session,
            worker_id=WORKER,
            limit=1,
            job_types=[job_type] if job_type else None,
            account_id=account_id,
        )
        assert jobs, "expected a claimable job"
        job_id = jobs[0].id
        session.commit()
        return job_id


def _run_job(job_id) -> bool:
    Session = get_session_factory()
    with Session() as session:
        job = session.get(WorkerJob, job_id)
        assert job is not None
        with patch("mail_core.worker.handlers.get_credential_store", return_value=object()):
            ok = handle_job(session, job, worker_id=WORKER)
        session.commit()
        return ok


class _DeltaProvider:
    def delta_changes(self, _remote_id, _cursor):
        return DeltaPage(changes=[], next_cursor={"uid_next": 501}, exhausted=True)


def _delta_patches(provider=None):
    return patch("mail_core.sync.delta.build_provider", return_value=provider or _DeltaProvider())


def test_request_reaches_complete_after_real_handle_and_complete_job():
    """R06 repro: job done must move the request report to complete."""
    account_id, folder_id = _seed_account_folder()
    request_id = _create_delta_request(account_id, folder_id)

    report = _report(request_id)
    assert report.state == "queued"
    assert report.queued_count == 1

    job_id = _claim_one(JobType.SYNC_FOLDER_DELTA.value, account_id)
    # Claim marks the bound target running.
    assert _report(request_id).running_count == 1

    with _delta_patches():
        assert _run_job(job_id) is True

    report = _report(request_id)
    assert report.state == "complete"
    assert report.completed_count == 1
    assert report.queued_count == 0
    assert report.finished_at is not None

    Session = get_session_factory()
    with Session() as session:
        events = list(
            session.scalars(
                select(OutboxEvent).where(OutboxEvent.event_type == "sync.request_updated")
            ).all()
        )
        assert any(e.payload.get("request_id") == str(request_id) and e.payload.get("state") == "complete" for e in events)


def test_shared_pending_job_is_observed_by_two_requests():
    account_id, folder_id = _seed_account_folder()
    first = _create_delta_request(account_id, folder_id)
    second = _create_delta_request(account_id, folder_id)

    Session = get_session_factory()
    with Session() as session:
        bindings = list(session.scalars(select(SyncRequestTargetJob)).all())
        mine = [
            b
            for b in bindings
            if b.target_id
            in {
                t.id
                for t in session.scalars(
                    select(SyncRequestTarget).where(SyncRequestTarget.request_id.in_([first, second]))
                ).all()
            }
        ]
        assert len(mine) == 2
        # Both requests observe the same deduplicated execution generation.
        assert mine[0].execution_generation == mine[1].execution_generation
        assert mine[0].job_id == mine[1].job_id

    job_id = _claim_one(JobType.SYNC_FOLDER_DELTA.value, account_id)
    with _delta_patches():
        assert _run_job(job_id) is True

    assert _report(first).state == "complete"
    assert _report(second).state == "complete"


def test_claimed_job_request_binds_successor_not_running_execution():
    account_id, folder_id = _seed_account_folder()
    first = _create_delta_request(account_id, folder_id)
    job_id = _claim_one(JobType.SYNC_FOLDER_DELTA.value, account_id)

    # Second request arrives while the job is CLAIMED.
    second = _create_delta_request(account_id, folder_id)

    Session = get_session_factory()
    with Session() as session:
        running_job = session.get(WorkerJob, job_id)
        successor_generation = (running_job.payload.get("_queue_next") or {}).get("execution_generation")
        assert successor_generation, "claimed job must pre-allocate a successor generation once"
        target = session.scalar(
            select(SyncRequestTarget).where(SyncRequestTarget.request_id == second)
        )
        assert target.requested_generation == uuid.UUID(successor_generation)
        assert target.requested_generation != running_job.execution_generation
        binding = session.scalar(
            select(SyncRequestTargetJob).where(SyncRequestTargetJob.target_id == target.id)
        )
        assert binding.execution_generation == target.requested_generation
        assert binding.job_id is None  # successor not created yet

    with _delta_patches():
        assert _run_job(job_id) is True

    # Old execution completing must NOT complete the successor-bound request.
    assert _report(first).state == "complete"
    second_report = _report(second)
    assert second_report.state in ("queued", "running")
    assert second_report.completed_count == 0

    Session = get_session_factory()
    with Session() as session:
        successor = session.scalar(
            select(WorkerJob).where(
                WorkerJob.execution_generation == uuid.UUID(successor_generation)
            )
        )
        assert successor is not None and successor.status == JobStatus.PENDING.value
        binding = session.scalar(
            select(SyncRequestTargetJob).where(
                SyncRequestTargetJob.execution_generation == successor.execution_generation
            )
        )
        assert binding.job_id == successor.id
        successor_id = successor.id

    claimed_successor = _claim_one(JobType.SYNC_FOLDER_DELTA.value, account_id)
    assert claimed_successor == successor_id
    with _delta_patches():
        assert _run_job(claimed_successor) is True
    assert _report(second).state == "complete"
    assert _report(second).completed_count == 1


def test_retriable_failure_keeps_target_open_terminal_failure_fails_request():
    account_id, folder_id = _seed_account_folder()
    request_id = _create_delta_request(account_id, folder_id)

    job_id = _claim_one(JobType.SYNC_FOLDER_DELTA.value, account_id)
    Session = get_session_factory()
    with Session() as session:
        job = session.get(WorkerJob, job_id)
        fail_job(session, job, "transient boom", worker_id=WORKER, max_attempts=5)
        session.commit()
    report = _report(request_id)
    assert report.state in ("queued", "running")
    assert report.failed_count == 0

    job_id = _claim_one(JobType.SYNC_FOLDER_DELTA.value, account_id)
    with Session() as session:
        job = session.get(WorkerJob, job_id)
        fail_job(session, job, "final boom", worker_id=WORKER, max_attempts=1)
        session.commit()
    report = _report(request_id)
    assert report.state == "failed"
    assert report.failed_count == 1
    assert report.errors and report.errors[0].code == "job_failed"


def test_delta_without_baseline_fails_with_baseline_required():
    account_id, folder_id = _seed_account_folder(full_scan_complete=False, cursor={})
    # Remove the checkpoint entirely: no baseline and no initialization scan.
    Session = get_session_factory()
    with Session() as session:
        cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
        session.delete(cp)
        session.commit()

    request_id = _create_delta_request(account_id, folder_id)
    job_id = _claim_one(JobType.SYNC_FOLDER_DELTA.value, account_id)
    # No provider is built on this path; handle_job must still settle.
    assert _run_job(job_id) is True

    report = _report(request_id)
    assert report.state == "failed"
    assert report.errors and report.errors[0].code == "baseline_required"


def test_delta_binds_inflight_initialization_scan():
    account_id, folder_id = _seed_account_folder(full_scan_complete=False, cursor={})
    Session = get_session_factory()
    with Session() as session:
        cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
        session.delete(cp)
        session.commit()
        enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_METADATA.value,
            account_id=account_id,
            payload={"folder_id": str(folder_id)},
            priority=50,
            dedupe_key=f"metadata:{account_id}:{folder_id}",
        )
        session.commit()

    request_id = _create_delta_request(account_id, folder_id)
    delta_job_id = _claim_one(JobType.SYNC_FOLDER_DELTA.value, account_id)
    assert _run_job(delta_job_id) is True
    # Delta was skipped onto the initialization scan: request still open.
    assert _report(request_id).state in ("queued", "running")
    assert _report(request_id).failed_count == 0

    metadata_job_id = _claim_one(JobType.SYNC_FOLDER_METADATA.value, account_id)

    class _MetaProvider:
        def fetch_metadata_page(self, _remote_id, _cursor):
            return MetadataPage(items=[], next_cursor={"uid_next": 2}, exhausted=True)

    with patch("mail_core.sync.engine.build_provider", return_value=_MetaProvider()):
        assert _run_job(metadata_job_id) is True
    assert _report(request_id).state == "complete"


class _FullProvider:
    def __init__(self):
        self.metadata_cursors: list[dict] = []
        self.reconciled = False

    def list_folders(self):
        return [RemoteFolder(remote_id="INBOX", name="INBOX", role="inbox")]

    def fetch_metadata_page(self, _remote_id, cursor):
        self.metadata_cursors.append(dict(cursor))
        return MetadataPage(items=[], next_cursor={"uid_next": 2}, exhausted=True)

    def reconcile(self, _remote_id, _local_ids):
        self.reconciled = True
        return []


def test_full_scan_resets_cursor_and_completes_only_after_reconcile():
    """R08 repro: preexisting uid_next=500 + full_scan_complete=True must not
    leak into a full request — the provider starts from the reset cursor."""
    account_id, folder_id = _seed_account_folder(full_scan_complete=True, cursor={"uid_next": 500})
    provider = _FullProvider()

    Session = get_session_factory()
    with Session() as session:
        req, _ = create_sync_request(
            session,
            client_request_id=f"pkgc-full-{uuid.uuid4().hex}",
            mode="full",
            trigger="manual",
            scope={"account_id": str(account_id)},
            account_id=account_id,
        )
        session.commit()
        request_id = req.id
        target = session.scalar(select(SyncRequestTarget).where(SyncRequestTarget.request_id == request_id))
        root_generation = target.requested_generation

    discovery_id = _claim_one(JobType.SYNC_ACCOUNT_FOLDERS.value, account_id)
    with patch("mail_core.sync.engine.build_provider", return_value=provider):
        assert _run_job(discovery_id) is True
    # Discovery completing does not complete the request: metadata is bound.
    assert _report(request_id).state in ("queued", "running")
    assert _report(request_id).completed_count == 0

    metadata_id = _claim_one(JobType.SYNC_FOLDER_METADATA.value, account_id)
    with (
        patch("mail_core.sync.engine.build_provider", return_value=provider),
        patch("mail_core.sync.reconcile.build_provider", return_value=provider),
    ):
        assert _run_job(metadata_id) is True
    assert provider.metadata_cursors, "metadata provider was not called"
    assert provider.metadata_cursors[0] == {}, "full scan must start from the reset cursor, not uid_next=500"

    with Session() as session:
        cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
        assert cp.scan_generation == root_generation
        assert cp.full_scan_complete is True
    # Reconcile is queued after metadata success; request still open.
    assert _report(request_id).state in ("queued", "running")

    reconcile_id = _claim_one(JobType.RECONCILE_FOLDER.value, account_id)
    with patch("mail_core.sync.reconcile.build_provider", return_value=provider):
        assert _run_job(reconcile_id) is True
    assert provider.reconciled is True
    report = _report(request_id)
    assert report.state == "complete"
    assert report.completed_count == 1


def test_full_scan_same_generation_retry_continues_cursor_and_old_generation_is_rejected():
    account_id, folder_id = _seed_account_folder(full_scan_complete=True, cursor={"uid_next": 500})
    gen1, gen2 = uuid.uuid4(), uuid.uuid4()
    seen: list[dict] = []

    class _PagingProvider:
        def fetch_metadata_page(self, _remote_id, cursor):
            seen.append(dict(cursor))
            if not cursor:
                return MetadataPage(items=[], next_cursor={"uid_next": 10}, exhausted=False)
            return MetadataPage(items=[], next_cursor={"uid_next": 20}, exhausted=True)

    with patch("mail_core.sync.engine.build_provider", return_value=_PagingProvider()):
        result = sync_folder_metadata(
            account_id, folder_id, worker_id=WORKER, store=object(),
            full=True, scan_generation=gen1, max_pages=1,
        )
        assert result["status"] == "ok"
        # Same generation retry continues from the stored cursor (no reset).
        result = sync_folder_metadata(
            account_id, folder_id, worker_id=WORKER, store=object(),
            full=True, scan_generation=gen1, max_pages=1,
        )
        assert result["status"] == "ok"
        # A new generation resets again.
        result = sync_folder_metadata(
            account_id, folder_id, worker_id=WORKER, store=object(),
            full=True, scan_generation=gen2, max_pages=1,
        )
        assert result["status"] == "ok"
    assert seen[0] == {}  # gen1 first entry: reset from uid_next=500
    assert seen[1] == {"uid_next": 10}  # gen1 retry: continues
    assert seen[2] == {}  # gen2 first entry: reset again

    Session = get_session_factory()
    with Session() as session:
        cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
        assert cp.scan_generation == gen2
        lease = acquire_lease(session, account_id=account_id, owner_id=WORKER)
        with pytest.raises(ScanGenerationMismatch):
            commit_checkpoint(
                session,
                account_id=account_id,
                folder_id=folder_id,
                fencing_token=lease.fencing_token,
                cursor={"uid_next": 999},
                scan_generation=gen1,
            )
        session.rollback()


def test_failed_metadata_folder_gets_no_reconcile():
    account_id, folder_id = _seed_account_folder(full_scan_complete=False, cursor={})

    class _BoomProvider:
        def fetch_metadata_page(self, _remote_id, _cursor):
            raise RuntimeError("provider exploded")

    with patch("mail_core.sync.engine.build_provider", return_value=_BoomProvider()):
        with pytest.raises(RuntimeError):
            sync_folder_metadata(
                account_id, folder_id, worker_id=WORKER, store=object(),
                full=True, scan_generation=uuid.uuid4(),
            )

    Session = get_session_factory()
    with Session() as session:
        reconcile_jobs = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == account_id,
                    WorkerJob.job_type == JobType.RECONCILE_FOLDER.value,
                )
            ).all()
        )
        assert reconcile_jobs == []
        cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
        assert cp.full_scan_complete is False


def test_reaper_converges_binding_whose_job_vanished():
    account_id, folder_id = _seed_account_folder()
    request_id = _create_delta_request(account_id, folder_id)

    Session = get_session_factory()
    with Session() as session:
        target = session.scalar(
            select(SyncRequestTarget).where(SyncRequestTarget.request_id == request_id)
        )
        binding = session.scalar(
            select(SyncRequestTargetJob).where(SyncRequestTargetJob.target_id == target.id)
        )
        job = session.get(WorkerJob, binding.job_id)
        session.delete(job)  # FK SET NULL leaves the binding orphaned
        session.commit()

    from mail_core.sync.execution import converge_orphaned_bindings

    with Session() as session:
        changed = converge_orphaned_bindings(session)
        session.commit()
    assert changed >= 1
    report = _report(request_id)
    assert report.state == "failed"
    assert report.errors and report.errors[0].code == "execution_lost"


def test_account_deletion_fails_open_targets():
    account_id, folder_id = _seed_account_folder()
    request_id = _create_delta_request(account_id, folder_id)

    from mail_core.accounts.service import delete_account

    Session = get_session_factory()
    with Session() as session:
        delete_account(session, account_id)
        session.commit()

    report = _report(request_id)
    assert report.state == "failed"
    assert report.errors and report.errors[0].code == "account_deleted"
