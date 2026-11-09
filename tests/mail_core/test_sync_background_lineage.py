"""Real-chain coverage for background sync lineage (spec §15.2/§15.3).

Background isolation is derived from ``SyncRequest.scope["background"]`` via
the ``request_id`` carried by every derived/requeued account-sync job, never
from a payload marker. These tests run the real create/discovery/handler chain
against the real PostgreSQL schema built by Alembic; the advisory generation
lock is stubbed so the single-process lineage chain does not depend on
cross-worker coordination.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import select

import mail_core.sync.delta as delta_mod
import mail_core.sync.engine as engine_mod
import mail_core.sync.execution as execution_mod
from mail_core.db.session import get_session_factory
from mail_core.mail.application.sync_requests import (
    create_sync_request,
    get_sync_request_report,
)
from mail_core.sync.context import (
    account_sync_failure_status,
    is_permanent_auth_error,
    resolve_sync_context,
    sync_context_payload,
)
from mail_core.mail.domain.enums import JobStatus, JobType, SyncStatus
from mail_core.mail.storage.models import (
    Account,
    Folder,
    SyncCheckpoint,
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.providers.base import RemoteFolder
from mail_core.providers.http import PermanentAuthError, RateLimitedError
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.worker.handlers import handle_job

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)
_WORKER = "w-lineage"
_REMOTE_FOLDERS = [
    RemoteFolder("INBOX", "INBOX", "inbox"),
    RemoteFolder("SENT", "SENT", "sent"),
    RemoteFolder("ARCHIVE", "ARCHIVE", "archive"),
]


def _make_session(monkeypatch):
    Session = get_session_factory()
    monkeypatch.setattr(execution_mod, "lock_generation", lambda session, generation: None)
    return Session


def _seed_account(Session, *, baselines=True):
    aid = uuid.uuid4()
    folders = {}
    with Session() as session:
        session.add(
            Account(
                id=aid,
                email=f"lin-{aid.hex[:8]}@example.test",
                provider="imap",
                sync_enabled=True,
            )
        )
        for rf in _REMOTE_FOLDERS:
            fid = uuid.uuid4()
            session.add(
                Folder(
                    id=fid,
                    account_id=aid,
                    remote_id=rf.remote_id,
                    name=rf.name,
                    role=rf.role,
                    sync_status=SyncStatus.IDLE.value,
                )
            )
            session.add(
                SyncCheckpoint(
                    account_id=aid,
                    folder_id=fid,
                    cursor={"modseq": 0},
                    full_scan_complete=baselines,
                )
            )
            folders[rf.role] = fid
        session.commit()
    return aid, folders


def _create_request(Session, aid):
    with Session() as session:
        req, created = create_sync_request(
            session,
            client_request_id=f"lin-{uuid.uuid4().hex}",
            mode="delta",
            trigger="manual",
            scope={"account_id": str(aid)},
            account_id=aid,
            folder_id=None,
        )
        session.commit()
        assert created
        report = get_sync_request_report(session, req.id)
        assert report is not None
        assert report.background_request_id is not None
        return req.id, uuid.UUID(report.background_request_id)


def _job_id(Session, aid, job_type, *, request_id=None, dedupe_suffix=None):
    with Session() as session:
        stmt = select(WorkerJob.id).where(
            WorkerJob.account_id == aid,
            WorkerJob.job_type == job_type,
        )
        rows = list(session.scalars(stmt))
        for jid in rows:
            job = session.get(WorkerJob, jid)
            if request_id is not None and job.payload.get("request_id") != str(request_id):
                continue
            if dedupe_suffix is not None and not str(job.dedupe_key or "").endswith(dedupe_suffix):
                continue
            return jid
    raise AssertionError(f"no {job_type} job for {aid}")


def _claim(Session, job_id):
    with Session() as session:
        job = session.get(WorkerJob, job_id)
        job.status = JobStatus.CLAIMED.value
        job.locked_by = _WORKER
        job.attempts = 1
        session.commit()


def _run(Session, job_id):
    with Session() as session:
        job = session.get(WorkerJob, job_id)
        with patch("mail_core.worker.handlers.get_credential_store", return_value=object()):
            ok = handle_job(session, job, worker_id=_WORKER)
        session.commit()
        return ok


def _prepare(monkeypatch, *, baselines=True, manual_background=False):
    Session = _make_session(monkeypatch)
    aid, folders = _seed_account(Session, baselines=baselines)
    if manual_background:
        bg_id = uuid.uuid4()
        with Session() as session:
            session.add(
                SyncRequest(
                    id=bg_id,
                    client_request_id=f"bg-{uuid.uuid4().hex}",
                    mode="delta",
                    trigger="manual",
                    state="queued",
                    scope={"background": True, "parent_request_id": str(uuid.uuid4())},
                    created_at=_NOW,
                )
            )
            job = WorkerJob(
                job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
                account_id=aid,
                payload={"request_id": str(bg_id)},
                priority=60,
                status=JobStatus.PENDING.value,
                dedupe_key=f"sync:{aid}",
            )
            session.add(job)
            session.commit()
            discovery_id = job.id
    else:
        _main_id, bg_id = _create_request(Session, aid)
        discovery_id = _job_id(Session, aid, JobType.SYNC_ACCOUNT_FOLDERS.value, request_id=bg_id)
    monkeypatch.setattr(
        engine_mod, "build_provider", lambda *a, **k: MemoryProvider(folders=list(_REMOTE_FOLDERS))
    )
    _claim(Session, discovery_id)
    assert _run(Session, discovery_id) is True
    return Session, aid, folders, bg_id


def _seed_foreground_request(Session, aid, folder_id, job_type):
    rid = uuid.uuid4()
    with Session() as session:
        session.add(
            SyncRequest(
                id=rid,
                client_request_id=f"fg-{uuid.uuid4().hex}",
                mode="delta",
                trigger="manual",
                state="queued",
                scope={"account_id": str(aid)},
                created_at=_NOW,
            )
        )
        job = WorkerJob(
            job_type=job_type,
            account_id=aid,
            payload={"folder_id": str(folder_id), "request_id": str(rid)},
            priority=60,
            status=JobStatus.CLAIMED.value,
            locked_by=_WORKER,
            attempts=1,
            dedupe_key=f"fg:{aid}:{folder_id}",
        )
        session.add(job)
        session.commit()
        return rid, job.id


class _BrokenDeltaProvider:
    def delta_changes(self, remote_id, cursor):
        raise RuntimeError("sibling provider outage")


class _RateLimitedDeltaProvider:
    def delta_changes(self, remote_id, cursor):
        raise RateLimitedError("slow down", retry_after_seconds=30)


class _RateLimitedMetadataProvider:
    def fetch_metadata_page(self, remote_id, cursor):
        raise RateLimitedError("slow down", retry_after_seconds=30)


def test_resolve_sync_context_uses_scope_and_fails_closed(monkeypatch):
    Session = _make_session(monkeypatch)
    fg_id, bg_id, unknown = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with Session() as session:
        session.add(
            SyncRequest(
                id=fg_id,
                client_request_id="fg",
                mode="delta",
                trigger="manual",
                state="queued",
                scope={"account_id": "x"},
                created_at=_NOW,
            )
        )
        session.add(
            SyncRequest(
                id=bg_id,
                client_request_id="bg",
                mode="delta",
                trigger="manual",
                state="queued",
                scope={"background": True, "parent_request_id": str(fg_id)},
                created_at=_NOW,
            )
        )
        session.commit()
        assert resolve_sync_context(session, SimpleNamespace(payload={"request_id": str(bg_id)})) == (
            True,
            bg_id,
        )
        assert resolve_sync_context(session, SimpleNamespace(payload={"request_id": str(fg_id)})) == (
            False,
            fg_id,
        )
        assert resolve_sync_context(session, SimpleNamespace(payload={"request_id": str(unknown)})) == (
            False,
            unknown,
        )
        assert resolve_sync_context(session, SimpleNamespace(payload={"parent_request_id": str(bg_id)})) == (
            True,
            bg_id,
        )
        assert resolve_sync_context(session, SimpleNamespace(payload={})) == (False, None)
        assert resolve_sync_context(session, SimpleNamespace(payload=None)) == (False, None)


def test_sync_context_payload_carries_lineage_without_marker():
    rid = uuid.uuid4()
    payload = sync_context_payload(rid, folder_id="f", full=True, scan_generation=None)
    assert payload == {"folder_id": "f", "full": True, "request_id": str(rid)}
    assert "background" not in payload
    assert sync_context_payload(None, folder_id="f") == {"folder_id": "f"}


def test_failure_status_classification_is_centralized():
    assert is_permanent_auth_error(PermanentAuthError("bad credentials")) is True
    assert is_permanent_auth_error({"status": "auth_failed"}) is True
    assert is_permanent_auth_error({"error_code": "auth_failed"}) is True
    assert is_permanent_auth_error(RuntimeError("transient")) is False
    assert account_sync_failure_status(result=PermanentAuthError("bad"), is_background=True) is SyncStatus.AUTH_FAILED
    assert account_sync_failure_status(result={"status": "auth_failed"}, is_background=True) is SyncStatus.AUTH_FAILED
    assert account_sync_failure_status(result={"status": "rate_limited"}, is_background=True) is None
    assert account_sync_failure_status(result={"status": "provider_error"}, is_background=True) is None
    assert account_sync_failure_status(result={"status": "rate_limited"}, is_background=False) is SyncStatus.FAILED
    assert account_sync_failure_status(result=RuntimeError("x"), is_background=False) is SyncStatus.FAILED


def test_background_discovery_delta_children_carry_lineage(monkeypatch):
    Session, aid, folders, bg_id = _prepare(monkeypatch, baselines=True)
    with Session() as session:
        discovery = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == aid,
                WorkerJob.job_type == JobType.SYNC_ACCOUNT_FOLDERS.value,
            )
        )
        assert discovery is not None
        assert discovery.payload == {"request_id": str(bg_id)}
        assert "background" not in discovery.payload
        deltas = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == aid,
                    WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
                )
            )
        )
        children = [j for j in deltas if j.payload.get("request_id") == str(bg_id)]
        assert len(children) == 2
        assert all("background" not in j.payload for j in children)
        child_folders = {uuid.UUID(str(j.payload["folder_id"])) for j in children}
        assert folders["inbox"] not in child_folders
        assert child_folders == {folders["sent"], folders["archive"]}
        assert session.get(Account, aid).sync_status == SyncStatus.IDLE.value


def test_background_discovery_metadata_children_carry_lineage(monkeypatch):
    Session, aid, folders, bg_id = _prepare(monkeypatch, baselines=False, manual_background=True)
    with Session() as session:
        metas = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == aid,
                    WorkerJob.job_type == JobType.SYNC_FOLDER_METADATA.value,
                )
            )
        )
        children = [j for j in metas if j.payload.get("request_id") == str(bg_id)]
        assert len(children) == 2
        assert all("background" not in j.payload for j in children)
        assert session.get(Account, aid).sync_status == SyncStatus.IDLE.value


def test_background_child_provider_error_does_not_fail_account(monkeypatch):
    Session, aid, folders, bg_id = _prepare(monkeypatch, baselines=True)
    child_id = _job_id(Session, aid, JobType.SYNC_FOLDER_DELTA.value, request_id=bg_id, dedupe_suffix=str(folders["sent"]))
    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _BrokenDeltaProvider())
    _claim(Session, child_id)
    assert _run(Session, child_id) is True
    with Session() as session:
        assert session.get(Account, aid).sync_status == SyncStatus.IDLE.value
        requeued = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == aid,
                    WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
                )
            )
        )
        assert any(j.payload.get("reason") == "provider_error" and j.payload.get("request_id") == str(bg_id) for j in requeued)


def test_background_child_rate_limited_does_not_fail_account(monkeypatch):
    Session, aid, folders, bg_id = _prepare(monkeypatch, baselines=True)
    child_id = _job_id(Session, aid, JobType.SYNC_FOLDER_DELTA.value, request_id=bg_id, dedupe_suffix=str(folders["sent"]))
    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _RateLimitedDeltaProvider())
    _claim(Session, child_id)
    assert _run(Session, child_id) is True
    with Session() as session:
        assert session.get(Account, aid).sync_status == SyncStatus.IDLE.value
        requeued = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == aid,
                    WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
                )
            )
        )
        assert any(j.payload.get("request_id") == str(bg_id) for j in requeued)


def test_background_metadata_child_rate_limited_does_not_fail_account(monkeypatch):
    Session, aid, folders, bg_id = _prepare(monkeypatch, baselines=False, manual_background=True)
    child_id = _job_id(Session, aid, JobType.SYNC_FOLDER_METADATA.value, request_id=bg_id, dedupe_suffix=str(folders["sent"]))
    monkeypatch.setattr(engine_mod, "build_provider", lambda *a, **k: _RateLimitedMetadataProvider())
    _claim(Session, child_id)
    assert _run(Session, child_id) is True
    with Session() as session:
        assert session.get(Account, aid).sync_status == SyncStatus.IDLE.value
        requeued = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == aid,
                    WorkerJob.job_type == JobType.SYNC_FOLDER_METADATA.value,
                )
            )
        )
        assert any(j.payload.get("request_id") == str(bg_id) for j in requeued)


def test_background_child_permanent_auth_marks_auth_failed_and_disables(monkeypatch):
    Session, aid, folders, bg_id = _prepare(monkeypatch, baselines=True)
    child_id = _job_id(Session, aid, JobType.SYNC_FOLDER_DELTA.value, request_id=bg_id, dedupe_suffix=str(folders["sent"]))

    def _auth_provider(*a, **k):
        raise PermanentAuthError("credentials rejected permanently")

    monkeypatch.setattr(delta_mod, "build_provider", _auth_provider)
    _claim(Session, child_id)
    assert _run(Session, child_id) is False
    with Session() as session:
        acc = session.get(Account, aid)
        assert acc.sync_status == SyncStatus.AUTH_FAILED.value
        assert acc.sync_enabled is False


def test_foreground_child_provider_error_marks_account_failed(monkeypatch):
    Session = _make_session(monkeypatch)
    aid, folders = _seed_account(Session, baselines=True)
    _rid, job_id = _seed_foreground_request(Session, aid, folders["sent"], JobType.SYNC_FOLDER_DELTA.value)
    monkeypatch.setattr(engine_mod, "build_provider", lambda *a, **k: MemoryProvider(folders=list(_REMOTE_FOLDERS)))
    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _BrokenDeltaProvider())
    assert _run(Session, job_id) is True
    with Session() as session:
        acc = session.get(Account, aid)
        assert acc.sync_status == SyncStatus.FAILED.value


def test_background_success_does_not_recover_failed_account(monkeypatch):
    Session = _make_session(monkeypatch)
    aid, folders = _seed_account(Session, baselines=True)
    _main_id, bg_id = _create_request(Session, aid)
    with Session() as session:
        session.get(Account, aid).sync_status = SyncStatus.FAILED.value
        session.commit()
    monkeypatch.setattr(
        engine_mod, "build_provider", lambda *a, **k: MemoryProvider(folders=list(_REMOTE_FOLDERS))
    )
    discovery_id = _job_id(Session, aid, JobType.SYNC_ACCOUNT_FOLDERS.value, request_id=bg_id)
    _claim(Session, discovery_id)
    assert _run(Session, discovery_id) is True
    with Session() as session:
        assert session.get(Account, aid).sync_status == SyncStatus.FAILED.value


def test_foreground_success_recovers_failed_account(monkeypatch):
    Session = _make_session(monkeypatch)
    aid, folders = _seed_account(Session, baselines=True)
    fg_id = uuid.uuid4()
    with Session() as session:
        session.add(
            SyncRequest(
                id=fg_id,
                client_request_id=f"fg-{uuid.uuid4().hex}",
                mode="delta",
                trigger="manual",
                state="queued",
                scope={"account_id": str(aid)},
                created_at=_NOW,
            )
        )
        acc = session.get(Account, aid)
        acc.sync_status = SyncStatus.FAILED.value
        job = WorkerJob(
            job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
            account_id=aid,
            payload={"request_id": str(fg_id)},
            priority=60,
            status=JobStatus.CLAIMED.value,
            locked_by=_WORKER,
            attempts=1,
            dedupe_key=f"sync:{aid}",
        )
        session.add(job)
        session.commit()
        job_id = job.id
    monkeypatch.setattr(
        engine_mod, "build_provider", lambda *a, **k: MemoryProvider(folders=list(_REMOTE_FOLDERS))
    )
    assert _run(Session, job_id) is True
    with Session() as session:
        assert session.get(Account, aid).sync_status == SyncStatus.IDLE.value
