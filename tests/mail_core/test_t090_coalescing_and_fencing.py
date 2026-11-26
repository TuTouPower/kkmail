"""Coalescing lineage, FencingMismatch, real IdleWatcher/Archive flows, and foreground health tests (t090)."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

import mail_core.blobs.archive as archive_mod
import mail_core.sync.delta as delta_mod
from mail_core.db.session import get_session_factory
from mail_core.mail.application.sync_requests import create_sync_request
from mail_core.mail.domain.enums import (
    ConnectivityState,
    CredentialState,
    ExecutionOrigin,
    JobStatus,
    JobType,
    FolderRemoteState,
)
from mail_core.mail.storage.models import (
    Account,
    AccountSyncLease,
    Folder,
    Message,
    MessageArchiveState,
    MessageLocation,
    SyncCheckpoint,
    WorkerJob,
)
from mail_core.providers.base import DeltaPage
from mail_core.sync.context import sync_request_payload
from mail_core.sync.idle_watcher import IdleWatcherConfig, IdleWatcherManager
from mail_core.sync.jobs import claim_jobs, complete_job, enqueue_job
from mail_core.worker.handlers import handle_job

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_account(session, *, full_scan: bool = True) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    acc = Account(
        id=uuid.uuid4(),
        email=f"t090-cf-{uuid.uuid4().hex[:8]}@example.test",
        provider="imap",
        credential_ref="ref-t090-cf",
        sync_enabled=True,
        connectivity_state=ConnectivityState.CONNECTED.value,
        credential_state=CredentialState.VALID.value,
        config={},
    )
    session.add(acc)
    session.flush()
    inbox = Folder(
        id=uuid.uuid4(),
        account_id=acc.id,
        remote_id="INBOX",
        name="INBOX",
        role="inbox",
        kind="container",
        remote_state=FolderRemoteState.ACTIVE.value,
    )
    sent = Folder(
        id=uuid.uuid4(),
        account_id=acc.id,
        remote_id="SENT",
        name="SENT",
        role="sent",
        kind="container",
        remote_state=FolderRemoteState.ACTIVE.value,
    )
    session.add_all([inbox, sent])
    session.flush()
    for folder in (inbox, sent):
        session.add(
            SyncCheckpoint(
                account_id=acc.id,
                folder_id=folder.id,
                cursor={"modseq": 1},
                full_scan_complete=full_scan,
            )
        )
    session.flush()
    return acc.id, inbox.id, sent.id


def _execute_job_with_timeout(Session, job_id: uuid.UUID, *, worker_id: str = "w-t090-cf") -> bool:
    now = datetime.now(timezone.utc)
    with Session() as session:
        job = session.get(WorkerJob, job_id)
        assert job is not None
        job.status = JobStatus.CLAIMED.value
        job.locked_by = worker_id
        job.run_after = now
        job.attempts = (job.attempts or 0) + 1
        session.commit()
    with Session() as session:
        job = session.get(WorkerJob, job_id)
        assert job is not None
        with patch("mail_core.worker.handlers.get_credential_store", return_value=object()):
            ok = handle_job(session, job, worker_id=worker_id)
        session.commit()
        return ok


def test_t090_coalescing_preserves_foreground_lineage_and_strips_settled_origin():
    """AC-001/AC-002: fg+bg coalescing preserves fg lineage; bg->fg and complete_job strip stale lineage."""
    Session = get_session_factory()
    with Session() as session:
        aid1, inbox1, _ = _seed_account(session)
        aid2, _, sent2 = _seed_account(session)
        req_fg = uuid.uuid4()
        req_bg = uuid.uuid4()
        parent_bg = uuid.uuid4()

        # Pending fg + incoming bg: keeps foreground origin and fg lineage keys
        enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.FOREGROUND,
            account_id=aid1,
            payload=sync_request_payload(req_fg, folder_id=str(inbox1), full=True, scan_generation=2),
            priority=50,
            dedupe_key=f"delta:{aid1}:{inbox1}",
        )
        coalesced_fg = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND,
            account_id=aid1,
            payload={"folder_id": str(inbox1)},
            priority=60,
            dedupe_key=f"delta:{aid1}:{inbox1}",
        )
        assert coalesced_fg.execution_origin == ExecutionOrigin.FOREGROUND.value
        assert coalesced_fg.payload["request_id"] == str(req_fg)
        assert coalesced_fg.payload["full"] is True
        assert coalesced_fg.payload["scan_generation"] == 2
        assert "background" not in coalesced_fg.payload

        # Pending bg + incoming fg without request_id: promotes to fg and strips stale bg lineage
        enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND,
            account_id=aid2,
            payload={
                "folder_id": str(sent2),
                "request_id": str(req_bg),
                "parent_request_id": str(parent_bg),
                "full": True,
                "scan_generation": 1,
            },
            priority=60,
            dedupe_key=f"delta:{aid2}:{sent2}",
        )
        promoted = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.FOREGROUND,
            account_id=aid2,
            payload={"folder_id": str(sent2)},
            priority=40,
            dedupe_key=f"delta:{aid2}:{sent2}",
        )
        assert promoted.execution_origin == ExecutionOrigin.FOREGROUND.value
        for stale_key in ("request_id", "parent_request_id", "full", "scan_generation"):
            assert stale_key not in promoted.payload

        # Claimed fg + queued bg -> complete_job successor drops settled fg lineage
        claimed_fg = claim_jobs(session, worker_id="w-coalesce", limit=1, account_id=aid1)[0]
        assert claimed_fg.id == coalesced_fg.id
        enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND,
            account_id=aid1,
            payload={"folder_id": str(inbox1)},
            priority=60,
            dedupe_key=f"delta:{aid1}:{inbox1}",
        )
        successor_bg = complete_job(session, claimed_fg, worker_id="w-coalesce")
        assert successor_bg is not None
        assert successor_bg.execution_origin == ExecutionOrigin.BACKGROUND.value
        for stale_key in ("request_id", "parent_request_id", "full", "scan_generation"):
            assert stale_key not in successor_bg.payload

        # Same-origin fg->fg queued next preserves incoming request_id
        req_fg2 = uuid.uuid4()
        claimed_promo = claim_jobs(session, worker_id="w-coalesce", limit=1, account_id=aid2)[0]
        assert claimed_promo.id == promoted.id
        enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.FOREGROUND,
            account_id=aid2,
            payload=sync_request_payload(req_fg2, folder_id=str(sent2)),
            priority=40,
            dedupe_key=f"delta:{aid2}:{sent2}",
        )
        successor_fg = complete_job(session, claimed_promo, worker_id="w-coalesce")
        assert successor_fg is not None
        assert successor_fg.execution_origin == ExecutionOrigin.FOREGROUND.value
        assert successor_fg.payload.get("request_id") == str(req_fg2)
        session.commit()


def test_t090_delta_fencing_mismatch_both_branches_preserve_background(monkeypatch):
    """AC-003/AC-004: Both FencingMismatch branches in sync_folder_delta keep background isolation."""
    Session = get_session_factory()
    with Session() as session:
        aid_a, inbox_a, _ = _seed_account(session)
        aid_b, inbox_b, _ = _seed_account(session)
        session.commit()

    def _bump_fencing(target_account_id: uuid.UUID) -> None:
        with Session() as s_lease:
            lease = s_lease.get(AccountSyncLease, target_account_id)
            assert lease is not None
            lease.fencing_token = int(lease.fencing_token) + 1
            s_lease.commit()

    # Branch A: fencing stolen before apply_delta_page
    class _StealOnDeltaProvider:
        def delta_changes(self, _rid, _cur):
            _bump_fencing(aid_a)
            return DeltaPage(changes=[], next_cursor={"modseq": 2}, exhausted=True)

    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _StealOnDeltaProvider())
    res_a = delta_mod.sync_folder_delta(
        aid_a, inbox_a, worker_id="w-fence-a", execution_origin=ExecutionOrigin.BACKGROUND
    )
    assert res_a["status"] == "fencing_mismatch"

    # Branch B: fencing stolen after apply_delta_page, caught by final assert_fencing
    orig_apply = delta_mod.apply_delta_page

    class _CleanDeltaProvider:
        def delta_changes(self, _rid, _cur):
            return DeltaPage(changes=[], next_cursor={"modseq": 3}, exhausted=True)

    def _apply_then_steal(session, *, account_id, folder_id, fencing_token, page):
        applied = orig_apply(
            session,
            account_id=account_id,
            folder_id=folder_id,
            fencing_token=fencing_token,
            page=page,
        )
        session.commit()
        _bump_fencing(account_id)
        return applied

    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _CleanDeltaProvider())
    monkeypatch.setattr(delta_mod, "apply_delta_page", _apply_then_steal)
    res_b = delta_mod.sync_folder_delta(
        aid_b, inbox_b, worker_id="w-fence-b", execution_origin=ExecutionOrigin.BACKGROUND
    )
    assert res_b["status"] == "fencing_mismatch"

    class _TimeoutProvider:
        def delta_changes(self, _rid, _cur):
            raise TimeoutError("proxy handshake reset")

    monkeypatch.setattr(delta_mod, "apply_delta_page", orig_apply)
    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _TimeoutProvider())
    for aid, inbox_id in ((aid_a, inbox_a), (aid_b, inbox_b)):
        with Session() as session:
            lease = session.get(AccountSyncLease, aid)
            if lease is not None:
                lease.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            followup = session.scalar(
                select(WorkerJob).where(WorkerJob.dedupe_key == f"delta:{aid}:{inbox_id}")
            )
            assert followup is not None
            assert followup.execution_origin == ExecutionOrigin.BACKGROUND.value
            followup_id = followup.id
            session.commit()
        assert _execute_job_with_timeout(Session, followup_id) is False
        with Session() as session:
            acc = session.get(Account, aid)
            assert acc.connectivity_state == ConnectivityState.CONNECTED.value
            assert acc.credential_state == CredentialState.VALID.value


def test_t090_idle_watcher_real_lifecycle_enqueues_background(monkeypatch):
    """AC-002/AC-004: Real IdleWatcherManager start()/stop() catch-up and changed wake tag background."""
    Session = get_session_factory()
    with Session() as session:
        aid, inbox_id, _ = _seed_account(session)
        session.commit()

    changed_sent = threading.Event()
    catchup_seen = threading.Event()
    calls = {"count": 0}

    class _FakeIdleSession:
        def wait_for_change(self, *, timeout_s: float, stop_event: threading.Event) -> str:
            calls["count"] += 1
            if calls["count"] == 1:
                catchup_seen.wait(timeout=3.0)
                changed_sent.set()
                return "changed"
            stop_event.wait(timeout=3.0)
            return "stopped"

        def close(self) -> None:
            return None

    manager = IdleWatcherManager(
        Session,
        idle_session_factory=lambda _acc, _fld: _FakeIdleSession(),
        config=IdleWatcherConfig(enabled=True, reconcile_interval_s=0.05, max_duration_s=5.0),
    )
    manager.start()
    try:
        dedupe = f"delta:{aid}:{inbox_id}"
        deadline = datetime.now(timezone.utc) + timedelta(seconds=5)
        while datetime.now(timezone.utc) < deadline:
            with Session() as session:
                job = session.scalar(select(WorkerJob).where(WorkerJob.dedupe_key == dedupe))
                if job is not None:
                    assert job.execution_origin == ExecutionOrigin.BACKGROUND.value
                    session.delete(job)
                    session.commit()
                    catchup_seen.set()
                    break
            threading.Event().wait(0.02)
        assert catchup_seen.is_set()
        assert changed_sent.wait(timeout=5.0)
        wakeup_job_id = None
        deadline = datetime.now(timezone.utc) + timedelta(seconds=5)
        while datetime.now(timezone.utc) < deadline:
            with Session() as session:
                job = session.scalar(select(WorkerJob).where(WorkerJob.dedupe_key == dedupe))
                if job is not None:
                    assert job.execution_origin == ExecutionOrigin.BACKGROUND.value
                    assert "background" not in (job.payload or {})
                    wakeup_job_id = job.id
                    break
            threading.Event().wait(0.02)
        assert wakeup_job_id is not None
    finally:
        manager.stop()

    class _TimeoutProvider:
        def delta_changes(self, _rid, _cur):
            raise TimeoutError("idle delta timeout")

    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _TimeoutProvider())
    assert _execute_job_with_timeout(Session, wakeup_job_id) is False
    with Session() as session:
        acc = session.get(Account, aid)
        assert acc.connectivity_state == ConnectivityState.CONNECTED.value
        assert acc.credential_state == CredentialState.VALID.value


def test_t090_routine_archive_batch_self_continuation_enqueues_background(monkeypatch, tmp_path):
    """AC-002/AC-003: Routine archive batch (without message_id) self-continues as background."""
    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path / "blobs"))
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        aid, inbox_id, _ = _seed_account(session)
        msg = Message(
            id=uuid.uuid4(),
            account_id=aid,
            remote_id="uid-arch-1",
            subject="routine archive",
            from_address="a@example.test",
            sort_time=now,
        )
        session.add(msg)
        session.flush()
        session.add(MessageArchiveState(message_id=msg.id, state="metadata_synced"))
        session.add(MessageLocation(message_id=msg.id, folder_id=inbox_id, uid=1))
        session.commit()

    class _MimeProvider:
        def fetch_mime(self, _remote_id: str) -> bytes:
            return b"From: a@example.test\r\nSubject: Routine\r\n\r\nhello world\r\n"

    monkeypatch.setattr(archive_mod, "build_provider", lambda *a, **k: _MimeProvider())
    res = archive_mod.run_archive_batch(
        account_id=aid,
        worker_id="w-arch-routine",
        store=object(),
        payload={"batch_size": 1},
    )
    assert res["status"] == "ok" and res["completed"] == 1
    with Session() as session:
        next_batch = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == aid,
                WorkerJob.job_type == JobType.ARCHIVE_MIME_BATCH.value,
            )
        )
        assert next_batch is not None
        assert next_batch.execution_origin == ExecutionOrigin.BACKGROUND.value


def test_t090_foreground_sync_request_failure_escalates_connectivity(monkeypatch):
    """AC-004: Explicit foreground SyncRequest delta transport failures escalate degraded -> unreachable."""
    Session = get_session_factory()
    with Session() as session:
        aid, inbox_id, _ = _seed_account(session)
        req, created = create_sync_request(
            session,
            client_request_id=f"fg-health-{uuid.uuid4().hex}",
            mode="delta",
            trigger="manual",
            scope={"account_id": str(aid)},
            account_id=aid,
            folder_id=inbox_id,
        )
        assert created
        job = session.scalar(select(WorkerJob).where(WorkerJob.dedupe_key == f"delta:{aid}:{inbox_id}"))
        assert job is not None
        assert job.execution_origin == ExecutionOrigin.FOREGROUND.value
        assert job.payload["request_id"] == str(req.id)
        jid = job.id
        session.commit()

    class _TimeoutProvider:
        def delta_changes(self, _rid, _cur):
            raise TimeoutError("smtp/imap proxy timeout")

    current_now = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("mail_core.accounts.health._now", lambda: current_now)
    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _TimeoutProvider())

    assert _execute_job_with_timeout(Session, jid) is False
    with Session() as session:
        assert session.get(Account, aid).connectivity_state == ConnectivityState.DEGRADED.value

    for step in range(1, 5):
        current_now = datetime(2026, 11, 25, 12, 0, 0, tzinfo=timezone.utc) + timedelta(
            seconds=76 * step
        )
        assert _execute_job_with_timeout(Session, jid) is False

    with Session() as session:
        acc = session.get(Account, aid)
        assert acc.connectivity_state == ConnectivityState.UNREACHABLE.value
        assert acc.credential_state == CredentialState.VALID.value
