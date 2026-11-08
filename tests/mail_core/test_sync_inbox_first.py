"""t074: account-level sync claims the inbox folder's jobs first.

Account discovery enqueues the inbox (``role="inbox"``) delta at priority
55 (siblings 60) and the inbox metadata at 45 (siblings 50) — strictly
smaller numeric priority is the only ordering guarantee, because every
child job of one discovery transaction shares the same ``created_at``.
Delta/metadata requeues (lease conflict, rate limit, capacity, provider
error, fencing loss, unexhausted paging) must keep the original job's
priority instead of falling back to the type default; the metadata
cursor-invalid rebuild keeps its explicit 40.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.application.sync_requests import create_sync_request, get_sync_request_report
from mail_core.mail.domain.enums import JobStatus, JobType
from mail_core.mail.storage.models import (
    Account,
    AccountSyncLease,
    Folder,
    Message,
    SyncCheckpoint,
    SyncRequestTarget,
    WorkerJob,
)
from mail_core.providers.base import DeltaPage, RemoteFolder, RemoteMessageMeta
from mail_core.providers.connection_slots import ProviderCapacityUnavailable
from mail_core.providers.http import CursorInvalidError, RateLimitedError
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.sync.delta import sync_folder_delta
from mail_core.sync.engine import sync_account_folders, sync_folder_metadata
from mail_core.sync.jobs import claim_jobs, enqueue_job
from mail_core.sync.leases import acquire_lease, release_lease
from mail_core.worker.handlers import handle_job
import mail_core.sync.delta as delta_mod
import mail_core.sync.engine as engine_mod

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

WORKER = "w-t074"
_NOW = datetime(2026, 11, 4, 14, 0, 0, tzinfo=timezone.utc)

# Inbox is deliberately LAST in provider order: priority numbers, not
# discovery iteration order, must produce the inbox-first schedule.
_REMOTE_FOLDERS = [
    RemoteFolder("Archive", "Archive", "archive"),
    RemoteFolder("Sent", "Sent", "sent"),
    RemoteFolder("INBOX", "INBOX", "inbox"),
]


def _seed_account(*, baselines: bool, remote_folders=_REMOTE_FOLDERS):
    Session = get_session_factory()
    with Session() as session:
        account = Account(
            email=f"t074-{uuid.uuid4().hex[:8]}@example.com",
            provider="imap",
            sync_enabled=True,
        )
        session.add(account)
        session.flush()
        folders = {}
        for rf in remote_folders:
            folder = Folder(
                account_id=account.id,
                remote_id=rf.remote_id,
                name=rf.name,
                role=rf.role,
            )
            session.add(folder)
            session.flush()
            folders[rf.remote_id] = folder.id
            if baselines:
                session.add(
                    SyncCheckpoint(
                        account_id=account.id,
                        folder_id=folder.id,
                        cursor={"modseq": 0},
                        full_scan_complete=True,
                    )
                )
        session.commit()
        return account.id, folders


def _provider(**kwargs) -> MemoryProvider:
    return MemoryProvider(folders=list(_REMOTE_FOLDERS), **kwargs)


def _jobs_by_folder(account_id, job_type: str) -> dict[uuid.UUID, WorkerJob]:
    Session = get_session_factory()
    with Session() as session:
        jobs = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == account_id,
                    WorkerJob.job_type == job_type,
                )
            )
        )
        return {uuid.UUID(str(j.payload["folder_id"])): j for j in jobs}


def _pending_job(account_id, job_type: str, folder_id) -> WorkerJob:
    Session = get_session_factory()
    with Session() as session:
        job = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == account_id,
                WorkerJob.job_type == job_type,
                WorkerJob.status == JobStatus.PENDING.value,
                WorkerJob.dedupe_key.endswith(f":{folder_id}"),
            )
        )
        assert job is not None, f"expected a pending {job_type} job for folder {folder_id}"
        return job


def _hold_lease(account_id) -> None:
    Session = get_session_factory()
    with Session() as session:
        acquire_lease(session, account_id=account_id, owner_id="lease-holder", ttl=timedelta(minutes=5))
        session.commit()


def _claim_one(account_id, job_type: str | None = None) -> uuid.UUID:
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


# ---------------------------------------------------------------------------
# AC-001 / AC-002: discovery enqueue priorities
# ---------------------------------------------------------------------------


def test_discovery_delta_inbox_priority_strictly_smaller_and_claimed_first(monkeypatch):
    account_id, folders = _seed_account(baselines=True)
    provider = _provider()
    provider.append_message(
        "INBOX",
        RemoteMessageMeta("new-1", "Fresh", "a@b.c", "A", _NOW, False, False, uid=99),
    )
    monkeypatch.setattr(engine_mod, "build_provider", lambda *_a, **_k: provider)
    monkeypatch.setattr(delta_mod, "build_provider", lambda *_a, **_k: provider)

    assert sync_account_folders(account_id, worker_id="w", store=object())["status"] == "ok"

    by_folder = _jobs_by_folder(account_id, JobType.SYNC_FOLDER_DELTA.value)
    assert set(by_folder) == set(folders.values())
    inbox_priority = by_folder[folders["INBOX"]].priority
    sibling_priorities = [j.priority for fid, j in by_folder.items() if fid != folders["INBOX"]]
    assert inbox_priority == 55
    assert sibling_priorities == [60, 60]
    assert inbox_priority < min(sibling_priorities)

    # The inbox delta is claimed first, completes first, and its new mail
    # is already in the message table while siblings are still pending.
    job_id = _claim_one(account_id, JobType.SYNC_FOLDER_DELTA.value)
    Session = get_session_factory()
    with Session() as session:
        claimed = session.get(WorkerJob, job_id)
        assert uuid.UUID(str(claimed.payload["folder_id"])) == folders["INBOX"]
    assert _run_job(job_id) is True

    by_folder = _jobs_by_folder(account_id, JobType.SYNC_FOLDER_DELTA.value)
    assert by_folder[folders["INBOX"]].status == JobStatus.DONE.value
    assert all(
        j.status == JobStatus.PENDING.value
        for fid, j in by_folder.items()
        if fid != folders["INBOX"]
    )
    with Session() as session:
        remotes = set(
            session.scalars(
                select(Message.remote_id).where(Message.account_id == account_id)
            ).all()
        )
    assert "new-1" in remotes


def test_discovery_metadata_inbox_priority_strictly_smaller_and_claimed_first(monkeypatch):
    account_id, folders = _seed_account(baselines=False)
    provider = _provider()
    monkeypatch.setattr(engine_mod, "build_provider", lambda *_a, **_k: provider)
    assert sync_account_folders(account_id, worker_id="w", store=object())["status"] == "ok"

    by_folder = _jobs_by_folder(account_id, JobType.SYNC_FOLDER_METADATA.value)
    assert set(by_folder) == set(folders.values())
    assert by_folder[folders["INBOX"]].priority == 45
    assert [j.priority for fid, j in by_folder.items() if fid != folders["INBOX"]] == [50, 50]

    # The inbox baseline is claimed first and completes first.
    job_id = _claim_one(account_id, JobType.SYNC_FOLDER_METADATA.value)
    Session = get_session_factory()
    with Session() as session:
        claimed = session.get(WorkerJob, job_id)
        assert uuid.UUID(str(claimed.payload["folder_id"])) == folders["INBOX"]
    assert _run_job(job_id) is True

    by_folder = _jobs_by_folder(account_id, JobType.SYNC_FOLDER_METADATA.value)
    assert by_folder[folders["INBOX"]].status == JobStatus.DONE.value
    assert all(
        j.status == JobStatus.PENDING.value
        for fid, j in by_folder.items()
        if fid != folders["INBOX"]
    )


def test_metadata_pagination_continuation_keeps_inbox_priority():
    account_id, folders = _seed_account(baselines=False)
    provider = _provider(page_size=1)
    for remote_id in ("INBOX", "Archive"):
        provider.seed(
            remote_id,
            [
                RemoteMessageMeta(f"{remote_id}-1", "One", "a@b.c", "A", _NOW, False, False, uid=1),
                RemoteMessageMeta(f"{remote_id}-2", "Two", "a@b.c", "A", _NOW, False, False, uid=2),
            ],
        )
    with patch.object(engine_mod, "build_provider", lambda *_a, **_k: provider):
        result = sync_folder_metadata(
            account_id, folders["INBOX"], worker_id="w", store=object(), max_pages=1, priority=45
        )
        assert result["status"] == "ok"
        assert result["exhausted"] is False
        result_default = sync_folder_metadata(
            account_id, folders["Archive"], worker_id="w", store=object(), max_pages=1
        )
        assert result_default["exhausted"] is False

    assert _pending_job(account_id, JobType.SYNC_FOLDER_METADATA.value, folders["INBOX"]).priority == 45
    assert _pending_job(account_id, JobType.SYNC_FOLDER_METADATA.value, folders["Archive"]).priority == 50


# ---------------------------------------------------------------------------
# AC-003: delta requeues keep the original priority
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("priority", [55, 75, 20])
def test_delta_lease_busy_requeue_keeps_priority(priority):
    account_id, folders = _seed_account(baselines=True)
    _hold_lease(account_id)
    result = sync_folder_delta(
        account_id, folders["INBOX"], worker_id="w", store=object(), priority=priority
    )
    assert result["status"] == "lease_busy"
    assert _pending_job(account_id, JobType.SYNC_FOLDER_DELTA.value, folders["INBOX"]).priority == priority


def test_delta_lease_busy_requeue_default_priority():
    account_id, folders = _seed_account(baselines=True)
    _hold_lease(account_id)
    result = sync_folder_delta(account_id, folders["INBOX"], worker_id="w", store=object())
    assert result["status"] == "lease_busy"
    assert _pending_job(account_id, JobType.SYNC_FOLDER_DELTA.value, folders["INBOX"]).priority == 60


def test_delta_rate_limited_requeue_keeps_priority(monkeypatch):
    account_id, folders = _seed_account(baselines=True)

    class LimitedProvider:
        def delta_changes(self, _remote_id, _cursor):
            raise RateLimitedError("slow down", retry_after_seconds=30)

    monkeypatch.setattr(delta_mod, "build_provider", lambda *_a, **_k: LimitedProvider())
    result = sync_folder_delta(
        account_id, folders["INBOX"], worker_id="w", store=object(), priority=55
    )
    assert result["status"] == "rate_limited"
    assert _pending_job(account_id, JobType.SYNC_FOLDER_DELTA.value, folders["INBOX"]).priority == 55


def test_delta_capacity_requeue_keeps_priority(monkeypatch):
    account_id, folders = _seed_account(baselines=True)

    class SaturatedProvider:
        def delta_changes(self, _remote_id, _cursor):
            raise ProviderCapacityUnavailable("connection budget saturated")

    monkeypatch.setattr(delta_mod, "build_provider", lambda *_a, **_k: SaturatedProvider())
    result = sync_folder_delta(
        account_id, folders["INBOX"], worker_id="w", store=object(), priority=55
    )
    assert result["status"] == "capacity_unavailable"
    assert _pending_job(account_id, JobType.SYNC_FOLDER_DELTA.value, folders["INBOX"]).priority == 55


def test_delta_provider_error_requeue_keeps_priority(monkeypatch):
    account_id, folders = _seed_account(baselines=True)

    class BrokenProvider:
        def delta_changes(self, _remote_id, _cursor):
            raise RuntimeError("synthetic provider outage")

    monkeypatch.setattr(delta_mod, "build_provider", lambda *_a, **_k: BrokenProvider())
    result = sync_folder_delta(
        account_id, folders["INBOX"], worker_id="w", store=object(), priority=55
    )
    assert result["status"] == "provider_error"
    assert _pending_job(account_id, JobType.SYNC_FOLDER_DELTA.value, folders["INBOX"]).priority == 55


def test_delta_fencing_reschedule_keeps_priority(monkeypatch):
    account_id, folders = _seed_account(baselines=True)

    class LeaseStealingProvider:
        def delta_changes(self, _remote_id, _cursor):
            Session = get_session_factory()
            with Session() as session:
                row = session.get(AccountSyncLease, account_id)
                assert row is not None
                row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
                session.flush()
                acquire_lease(
                    session, account_id=account_id, owner_id="thief", ttl=timedelta(minutes=5)
                )
                session.commit()
            return DeltaPage(changes=[], next_cursor={"modseq": 1}, exhausted=True)

    monkeypatch.setattr(delta_mod, "build_provider", lambda *_a, **_k: LeaseStealingProvider())
    result = sync_folder_delta(
        account_id, folders["INBOX"], worker_id="w", store=object(), priority=55
    )
    assert result["status"] == "fencing_mismatch"
    assert _pending_job(account_id, JobType.SYNC_FOLDER_DELTA.value, folders["INBOX"]).priority == 55


def test_delta_unexhausted_continuation_keeps_priority(monkeypatch):
    account_id, folders = _seed_account(baselines=True)
    provider = _provider(page_size=1)
    for uid in (1, 2):
        provider.append_message(
            "INBOX",
            RemoteMessageMeta(f"m-{uid}", f"M{uid}", "a@b.c", "A", _NOW, False, False, uid=uid),
        )
    monkeypatch.setattr(delta_mod, "build_provider", lambda *_a, **_k: provider)
    result = sync_folder_delta(
        account_id, folders["INBOX"], worker_id="w", store=object(), max_pages=1, priority=55
    )
    assert result["status"] == "ok"
    assert result["exhausted"] is False
    assert _pending_job(account_id, JobType.SYNC_FOLDER_DELTA.value, folders["INBOX"]).priority == 55


# ---------------------------------------------------------------------------
# AC-003: metadata requeues keep the original priority; rebuild stays 40
# ---------------------------------------------------------------------------


def test_metadata_lease_busy_requeue_keeps_priority():
    account_id, folders = _seed_account(baselines=False)
    _hold_lease(account_id)
    result = sync_folder_metadata(
        account_id, folders["INBOX"], worker_id="w", store=object(), priority=45
    )
    assert result["status"] == "lease_busy"
    assert _pending_job(account_id, JobType.SYNC_FOLDER_METADATA.value, folders["INBOX"]).priority == 45


def test_metadata_lease_busy_requeue_default_priority():
    account_id, folders = _seed_account(baselines=False)
    _hold_lease(account_id)
    result = sync_folder_metadata(account_id, folders["INBOX"], worker_id="w", store=object())
    assert result["status"] == "lease_busy"
    assert _pending_job(account_id, JobType.SYNC_FOLDER_METADATA.value, folders["INBOX"]).priority == 50


def test_metadata_rate_limited_requeue_keeps_priority(monkeypatch):
    account_id, folders = _seed_account(baselines=False)

    class LimitedProvider:
        def fetch_metadata_page(self, _remote_id, _cursor):
            raise RateLimitedError("slow down", retry_after_seconds=30)

    monkeypatch.setattr(engine_mod, "build_provider", lambda *_a, **_k: LimitedProvider())
    result = sync_folder_metadata(
        account_id, folders["INBOX"], worker_id="w", store=object(), priority=45
    )
    assert result["status"] == "rate_limited"
    assert _pending_job(account_id, JobType.SYNC_FOLDER_METADATA.value, folders["INBOX"]).priority == 45


def test_metadata_capacity_requeue_keeps_priority(monkeypatch):
    account_id, folders = _seed_account(baselines=False)

    class SaturatedProvider:
        def fetch_metadata_page(self, _remote_id, _cursor):
            raise ProviderCapacityUnavailable("connection budget saturated")

    monkeypatch.setattr(engine_mod, "build_provider", lambda *_a, **_k: SaturatedProvider())
    result = sync_folder_metadata(
        account_id, folders["INBOX"], worker_id="w", store=object(), priority=45
    )
    assert result["status"] == "capacity_unavailable"
    assert _pending_job(account_id, JobType.SYNC_FOLDER_METADATA.value, folders["INBOX"]).priority == 45


def test_metadata_cursor_invalid_rebuild_stays_40(monkeypatch):
    account_id, folders = _seed_account(baselines=False)

    class InvalidCursorProvider:
        def fetch_metadata_page(self, _remote_id, _cursor):
            raise CursorInvalidError("cursor expired")

    monkeypatch.setattr(engine_mod, "build_provider", lambda *_a, **_k: InvalidCursorProvider())
    result = sync_folder_metadata(
        account_id, folders["INBOX"], worker_id="w", store=object(), priority=45
    )
    assert result["status"] == "cursor_invalid"
    rebuild = _pending_job(account_id, JobType.SYNC_FOLDER_METADATA.value, folders["INBOX"])
    assert rebuild.priority == 40
    assert rebuild.payload.get("reason") == "cursor_invalid"


# ---------------------------------------------------------------------------
# AC-003 via the worker: the handler passes the claimed job's priority
# ---------------------------------------------------------------------------


def _seed_claimed_job(account_id, folder_id, *, job_type: str, priority: int) -> uuid.UUID:
    Session = get_session_factory()
    prefix = "delta" if job_type == JobType.SYNC_FOLDER_DELTA.value else "metadata"
    with Session() as session:
        job = WorkerJob(
            job_type=job_type,
            account_id=account_id,
            payload={"folder_id": str(folder_id)},
            priority=priority,
            status=JobStatus.CLAIMED.value,
            locked_by=WORKER,
            attempts=1,
            dedupe_key=f"{prefix}:{account_id}:{folder_id}",
        )
        session.add(job)
        session.commit()
        return job.id


def test_claimed_delta_job_lease_busy_successor_keeps_priority():
    account_id, folders = _seed_account(baselines=True)
    job_id = _seed_claimed_job(
        account_id, folders["INBOX"], job_type=JobType.SYNC_FOLDER_DELTA.value, priority=75
    )
    _hold_lease(account_id)
    assert _run_job(job_id) is True

    Session = get_session_factory()
    with Session() as session:
        assert session.get(WorkerJob, job_id).status == JobStatus.DONE.value
    successor = _pending_job(account_id, JobType.SYNC_FOLDER_DELTA.value, folders["INBOX"])
    assert successor.priority == 75


def test_claimed_metadata_job_lease_busy_successor_keeps_priority():
    account_id, folders = _seed_account(baselines=False)
    job_id = _seed_claimed_job(
        account_id, folders["INBOX"], job_type=JobType.SYNC_FOLDER_METADATA.value, priority=55
    )
    _hold_lease(account_id)
    assert _run_job(job_id) is True

    Session = get_session_factory()
    with Session() as session:
        assert session.get(WorkerJob, job_id).status == JobStatus.DONE.value
    successor = _pending_job(account_id, JobType.SYNC_FOLDER_METADATA.value, folders["INBOX"])
    assert successor.priority == 55


# ---------------------------------------------------------------------------
# Adoption A21: Inbox sync settles independently, background syncs siblings
# ---------------------------------------------------------------------------
# Note on removed test:
# test_request_settles_only_after_all_folder_deltas was removed because its semantics
# required the primary manual refresh request to wait for all sibling folder deltas
# before reaching a terminal state. Under Adoption A21, manual inbox sync is decoupled
# from background full discovery, achieving an independent terminal state upon inbox delta completion.


def test_a21_inbox_settles_independently_and_background_syncs_siblings(monkeypatch):
    account_id, folders = _seed_account(baselines=True)
    provider = _provider()
    monkeypatch.setattr(engine_mod, "build_provider", lambda *_a, **_k: provider)
    monkeypatch.setattr(delta_mod, "build_provider", lambda *_a, **_k: provider)

    Session = get_session_factory()
    with Session() as session:
        req, created = create_sync_request(
            session,
            client_request_id=f"a21-{uuid.uuid4().hex}",
            mode="delta",
            trigger="manual",
            scope={"account_id": str(account_id)},
            account_id=account_id,
            folder_id=None,
        )
        session.commit()
        assert created
        request_id = req.id

    # 1. Under A21, the primary request targets the known inbox folder directly (priority 20)
    # and a separate background request targets full discovery (priority 60).
    with Session() as session:
        report = get_sync_request_report(session, request_id)
        assert report is not None
        assert report.state == "queued"
        assert report.inbox_ready is False
        assert report.background_request_id is not None
        assert report.background_state == "queued"
        bg_req_id = uuid.UUID(report.background_request_id)

    # 2. Worker claims inbox delta first (priority 20 < 60)
    inbox_job_id = _claim_one(account_id, JobType.SYNC_FOLDER_DELTA.value)
    with Session() as session:
        claimed = session.get(WorkerJob, inbox_job_id)
        assert uuid.UUID(str(claimed.payload["folder_id"])) == folders["INBOX"]
        assert claimed.priority == 20
    assert _run_job(inbox_job_id) is True

    # 3. Upon inbox delta completion, primary request enters terminal complete state immediately!
    with Session() as session:
        report = get_sync_request_report(session, request_id)
        assert report is not None
        assert report.state == "complete"
        assert report.finished_at is not None
        assert report.inbox_ready is True
        # Background sync is still queued / running
        assert report.background_state in ("queued", "running")

    # 4. Now background folder discovery job runs independently
    discovery_job_id = _claim_one(account_id, JobType.SYNC_ACCOUNT_FOLDERS.value)
    assert _run_job(discovery_job_id) is True

    # Sibling folders run their deltas until all phase jobs complete
    while True:
        try:
            job_id = _claim_one(account_id, JobType.SYNC_FOLDER_DELTA.value)
            assert _run_job(job_id) is True
        except AssertionError:
            break

    # 5. Background sync request now finishes and settles to complete
    with Session() as session:
        report = get_sync_request_report(session, request_id)
        assert report is not None
        assert report.state == "complete"
        assert report.background_state == "complete"

        bg_report = get_sync_request_report(session, bg_req_id)
        assert bg_report is not None
        assert bg_report.state == "complete"


def test_a21_background_folder_failure_is_isolated_from_inbox(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_JOB_MAX_ATTEMPTS", "1")
    account_id, folders = _seed_account(baselines=True)
    provider = _provider()
    monkeypatch.setattr(engine_mod, "build_provider", lambda *_a, **_k: provider)
    monkeypatch.setattr(delta_mod, "build_provider", lambda *_a, **_k: provider)

    Session = get_session_factory()
    with Session() as session:
        req, created = create_sync_request(
            session,
            client_request_id=f"a21-fail-{uuid.uuid4().hex}",
            mode="delta",
            trigger="manual",
            scope={"account_id": str(account_id)},
            account_id=account_id,
            folder_id=None,
        )
        session.commit()
        assert created
        request_id = req.id

    # Settle inbox delta successfully
    inbox_job_id = _claim_one(account_id, JobType.SYNC_FOLDER_DELTA.value)
    assert _run_job(inbox_job_id) is True

    with Session() as session:
        report = get_sync_request_report(session, request_id)
        assert report.state == "complete"

    # Background discovery runs
    discovery_job_id = _claim_one(account_id, JobType.SYNC_ACCOUNT_FOLDERS.value)
    assert _run_job(discovery_job_id) is True

    # Make provider fail for sibling deltas
    monkeypatch.setattr(
        delta_mod,
        "sync_folder_delta",
        lambda *args, **kwargs: {"status": "error", "error": "sibling_failed"},
    )
    while True:
        try:
            sibling_job_id = _claim_one(account_id, JobType.SYNC_FOLDER_DELTA.value)
            _run_job(sibling_job_id)
        except AssertionError:
            break

    # Primary request remains complete (error isolation)
    with Session() as session:
        report = get_sync_request_report(session, request_id)
        assert report.state == "complete"
        assert report.inbox_ready is True
        assert report.background_state == "failed"


# ---------------------------------------------------------------------------
# AC-005: no inbox folder -> existing priorities and behaviour
# ---------------------------------------------------------------------------


def test_no_inbox_account_keeps_existing_priorities():
    remote_folders = [
        RemoteFolder("Archive", "Archive", "archive"),
        RemoteFolder("Sent", "Sent", "sent"),
    ]
    account_id, folders = _seed_account(baselines=True, remote_folders=remote_folders)
    provider = MemoryProvider(folders=list(remote_folders))
    with patch.object(engine_mod, "build_provider", lambda *_a, **_k: provider):
        assert sync_account_folders(account_id, worker_id="w", store=object())["status"] == "ok"

    by_folder = _jobs_by_folder(account_id, JobType.SYNC_FOLDER_DELTA.value)
    assert {j.priority for j in by_folder.values()} == {60}

    account2_id, folders2 = _seed_account(baselines=False, remote_folders=remote_folders)
    with patch.object(engine_mod, "build_provider", lambda *_a, **_k: provider):
        assert sync_account_folders(account2_id, worker_id="w", store=object())["status"] == "ok"
    by_folder2 = _jobs_by_folder(account2_id, JobType.SYNC_FOLDER_METADATA.value)
    assert {j.priority for j in by_folder2.values()} == {50}

    # Sync still completes normally for an inbox-less account.
    with patch.object(delta_mod, "build_provider", lambda *_a, **_k: provider):
        result = sync_folder_delta(account_id, folders["Archive"], worker_id="w", store=object())
    assert result["status"] == "ok"


def test_requeued_inbox_delta_claimed_before_sibling():
    # AC-003 tail: after a lease-conflict requeue, the inbox successor
    # (55) is claimed before a pending sibling delta (60) once the
    # account is free again.
    account_id, folders = _seed_account(baselines=True)
    _hold_lease(account_id)
    result = sync_folder_delta(
        account_id, folders["INBOX"], worker_id="w", store=object(), priority=55
    )
    assert result["status"] == "lease_busy"

    Session = get_session_factory()
    with Session() as session:
        enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            account_id=account_id,
            payload={"folder_id": str(folders["Archive"])},
            priority=60,
            dedupe_key=f"delta:{account_id}:{folders['Archive']}",
        )
        lease = session.get(AccountSyncLease, account_id)
        assert lease is not None
        release_lease(
            session,
            account_id=account_id,
            owner_id="lease-holder",
            fencing_token=lease.fencing_token,
        )
        # Simulate the lease-busy retry delay (5s) having elapsed.
        successor = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == account_id,
                WorkerJob.status == JobStatus.PENDING.value,
                WorkerJob.dedupe_key.endswith(f":{folders['INBOX']}"),
            )
        )
        assert successor is not None
        successor.run_after = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    job_id = _claim_one(account_id, JobType.SYNC_FOLDER_DELTA.value)
    with Session() as session:
        claimed = session.get(WorkerJob, job_id)
        assert uuid.UUID(str(claimed.payload["folder_id"])) == folders["INBOX"]
        assert claimed.priority == 55


def test_a21_new_account_without_inbox_runs_discovery(monkeypatch):
    # For a new account or an account with no selectable inbox,
    # manual refresh follows the required discovery flow directly.
    account_id, folders = _seed_account(baselines=False, remote_folders=[])
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    monkeypatch.setattr(engine_mod, "build_provider", lambda *_a, **_k: provider)

    Session = get_session_factory()
    with Session() as session:
        req, created = create_sync_request(
            session,
            client_request_id=f"a21-new-{uuid.uuid4().hex}",
            mode="delta",
            trigger="manual",
            scope={"account_id": str(account_id)},
            account_id=account_id,
            folder_id=None,
        )
        session.commit()
        assert created
        request_id = req.id

    with Session() as session:
        report = get_sync_request_report(session, request_id)
        assert report is not None
        assert report.state == "queued"
        # No background decoupled request created because this request itself does discovery
        assert report.background_request_id is None

    # Claim and run discovery job
    discovery_job_id = _claim_one(account_id, JobType.SYNC_ACCOUNT_FOLDERS.value)
    assert _run_job(discovery_job_id) is True

    # Now the inbox has been discovered and its initial metadata job enqueued
    metadata_job_id = _claim_one(account_id, JobType.SYNC_FOLDER_METADATA.value)
    assert _run_job(metadata_job_id) is True

    with Session() as session:
        report = get_sync_request_report(session, request_id)
        assert report is not None
        assert report.state == "complete"
        assert report.inbox_ready is True


def test_inbox_without_completed_baseline_falls_back_to_discovery(monkeypatch):
    # When an inbox folder exists in DB but baseline is not completed
    # (full_scan_complete is False), delta mode falls back to account discovery
    # instead of locking directly onto inbox delta (which would fail with baseline_required).
    remote_folders = [RemoteFolder("INBOX", "INBOX", "inbox")]
    account_id, folders = _seed_account(baselines=False, remote_folders=remote_folders)
    Session = get_session_factory()
    with Session() as session:
        session.add(
            SyncCheckpoint(
                account_id=account_id,
                folder_id=folders["INBOX"],
                cursor={"modseq": 0},
                full_scan_complete=False,
            )
        )
        session.commit()

    provider = MemoryProvider(folders=list(remote_folders))
    monkeypatch.setattr(engine_mod, "build_provider", lambda *_a, **_k: provider)

    with Session() as session:
        req, created = create_sync_request(
            session,
            client_request_id=f"t3-major-{uuid.uuid4().hex}",
            mode="delta",
            trigger="manual",
            scope={"account_id": str(account_id)},
            account_id=account_id,
            folder_id=None,
        )
        session.commit()
        assert created
        request_id = req.id

    with Session() as session:
        report = get_sync_request_report(session, request_id)
        assert report is not None
        assert report.state == "queued"
        assert report.background_request_id is None
        req_targets = list(
            session.scalars(
                select(SyncRequestTarget).where(SyncRequestTarget.request_id == request_id)
            ).all()
        )
        assert len(req_targets) == 1
        assert req_targets[0].folder_id is None
        assert req_targets[0].target_key == f"account:{account_id}:folder:all:role:all"

    # Claim and run discovery job
    discovery_job_id = _claim_one(account_id, JobType.SYNC_ACCOUNT_FOLDERS.value)
    assert _run_job(discovery_job_id) is True

    # Initial metadata scan completes baseline for the inbox
    metadata_job_id = _claim_one(account_id, JobType.SYNC_FOLDER_METADATA.value)
    assert _run_job(metadata_job_id) is True

    with Session() as session:
        report = get_sync_request_report(session, request_id)
        assert report is not None
        assert report.state == "complete"
        assert report.inbox_ready is True
        cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folders["INBOX"]})
        assert cp is not None
        assert cp.full_scan_complete is True
