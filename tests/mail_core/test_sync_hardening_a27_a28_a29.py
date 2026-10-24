"""Tests for A27 (error redaction), A28 (rate limit & Retry-After), A29 (provider build error lease release)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.blobs.archive import run_archive_batch
from mail_core.db.session import get_session_factory
from mail_core.mail.application.remote_ops import enqueue_remote_operation
from mail_core.mail.domain.enums import ArchiveState, JobStatus, JobType, RemoteOperationStatus
from mail_core.mail.storage import Account, AccountSyncLease, Folder, Message, MessageArchiveState, RemoteOperation, WorkerJob
from mail_core.providers.base import RemoteFolder, RemoteMessageMeta
from mail_core.providers.http import CursorInvalidError, ProviderHttpError, RateLimitedError
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.security.redact import safe_provider_summary
from mail_core.sync import enqueue_job, push_remote_operations, sync_folder_delta, sync_folder_metadata
import mail_core.sync.delta as delta_mod
import mail_core.sync.engine as engine_mod
import mail_core.sync.remote_push as push_mod
from mail_core.sync.engine import sync_account_folders
from mail_core.worker.handlers import handle_job

_requires_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


# ---------------------------------------------------------------------------
# A27: Error redaction / safe summary
# ---------------------------------------------------------------------------


def test_safe_provider_summary_unit():
    # 1. ProviderHttpError with sensitive body and message
    err1 = ProviderHttpError(
        "HTTP 500: Database failed with token Bearer secret123",
        status=500,
        body={"error": "db_fail", "secret": "super_secret_token", "password": "p1"},
    )
    s1 = safe_provider_summary(err1)
    assert s1 == "ProviderHttpError status=500"
    assert "secret" not in s1
    assert "token" not in s1

    # 2. RateLimitedError with retry_after
    err2 = RateLimitedError(
        "Too many requests from client secret=xyz",
        retry_after_seconds=42.0,
        status=429,
        body="raw 429 page content with credentials",
    )
    s2 = safe_provider_summary(err2)
    assert s2 == "RateLimitedError status=429 retry_after=42.0"
    assert "secret" not in s2
    assert "raw" not in s2

    # 3. CursorInvalidError
    err3 = CursorInvalidError("sync cursor invalid: token expired", status=410)
    s3 = safe_provider_summary(err3)
    assert s3 == "CursorInvalidError status=410"
    assert "token" not in s3

    # 4. Standard Exception
    err4 = RuntimeError("Connection to postgresql://user:hunter2@db/test failed")
    s4 = safe_provider_summary(err4)
    assert s4 == "RuntimeError"
    assert "hunter2" not in s4

    # 5. String input with colon
    s5 = safe_provider_summary("ProviderHttpError status=500: leaked body content")
    assert s5 == "ProviderHttpError status=500"


@_requires_db
def test_a27_sync_folder_delta_sanitizes_errors(monkeypatch):
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed("INBOX", [RemoteMessageMeta("1", "One", "a@b.c", "A", now, False, False, uid=1)])

    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(session, email=f"a27-d-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
            session.commit()
            account_id = acc.id

        monkeypatch.setattr(engine_mod, "build_provider", lambda a, s=None: provider)
        monkeypatch.setattr(delta_mod, "build_provider", lambda a, s=None: provider)

        assert sync_account_folders(account_id, worker_id="w", store=store)["status"] == "ok"
        with Session() as session:
            folder_id = session.scalar(select(Folder.id).where(Folder.account_id == account_id))
        assert sync_folder_metadata(account_id, folder_id, worker_id="w", store=store)["exhausted"]

        # Simulate provider raising ProviderHttpError with sensitive body
        def boom(folder_remote_id, cursor):
            raise ProviderHttpError("Sensitive server crash: token=LEAKED_SECRET", status=500, body={"leak": "LEAKED_BODY"})

        provider.delta_changes = boom  # type: ignore[method-assign]
        res = sync_folder_delta(account_id, folder_id, worker_id="w", store=store)
        assert res["status"] == "provider_error"
        assert res["error"] == "ProviderHttpError status=500"
        assert "LEAKED" not in res["error"]

        # Check job payload written to database
        with Session() as session:
            job = session.scalar(
                select(WorkerJob)
                .where(WorkerJob.account_id == account_id)
                .where(WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value)
                .order_by(WorkerJob.created_at.desc())
                .limit(1)
            )
            assert job is not None
            assert job.payload.get("detail") == "ProviderHttpError status=500"
            assert "LEAKED" not in str(job.payload)
    finally:
        set_credential_store(None)


@_requires_db
def test_a27_sync_account_folders_sanitizes_last_sync_error(monkeypatch):
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(session, email=f"a27-acc-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
            session.commit()
            account_id = acc.id

        class FlakyFolders(MemoryProvider):
            def list_folders(self):
                raise ProviderHttpError("Failed folder listing: access_token=SECRET_TOKEN", status=502, body="SECRET_BODY")

        provider = FlakyFolders()
        monkeypatch.setattr(engine_mod, "build_provider", lambda a, s=None: provider)

        with pytest.raises(ProviderHttpError):
            sync_account_folders(account_id, worker_id="w", store=store)

        with Session() as session:
            acc = session.get(Account, account_id)
            last_err = (acc.config or {}).get("last_sync_error", "")
            assert last_err == "ProviderHttpError status=502"
            assert "SECRET" not in last_err
    finally:
        set_credential_store(None)


@_requires_db
def test_a27_remote_push_sanitizes_errors(monkeypatch):
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(session, email=f"a27-rp-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
            session.commit()
            account_id = acc.id

        class PushCrash(MemoryProvider):
            def apply_remote_operation(self, op_type, desired):
                raise ProviderHttpError("Failed remote op: client_secret=LEAK123", status=500, body="BODY_LEAK")

        provider = PushCrash(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
        monkeypatch.setattr(push_mod, "build_provider", lambda a, s=None: provider)

        with Session() as session:
            enqueue_remote_operation(
                session,
                account_id=account_id,
                entity_key="msg:1",
                op_type="mark_read",
                desired_state={"remote_id": "1", "folder_remote_id": "INBOX", "is_read": True},
            )
            session.commit()

        push_remote_operations(account_id, worker_id="w", store=store)

        with Session() as session:
            op = session.scalar(select(RemoteOperation).where(RemoteOperation.account_id == account_id).limit(1))
            assert op is not None
            err = op.last_error or op.error or ""
            assert err == "ProviderHttpError status=500"
            assert "LEAK" not in err
            assert "BODY" not in err
    finally:
        set_credential_store(None)


# ---------------------------------------------------------------------------
# A28: Rate limiting & Retry-After unification
# ---------------------------------------------------------------------------


@_requires_db
def test_a28_worker_handler_rate_limited_single_job(monkeypatch):
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed("INBOX", [RemoteMessageMeta("1", "One", "a@b.c", "A", now, False, False, uid=1)])

    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(session, email=f"a28-w-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
            session.commit()
            account_id = acc.id

        monkeypatch.setattr(engine_mod, "build_provider", lambda a, s=None: provider)
        monkeypatch.setattr(delta_mod, "build_provider", lambda a, s=None: provider)

        sync_account_folders(account_id, worker_id="w", store=store)
        with Session() as session:
            folder_id = session.scalar(select(Folder.id).where(Folder.account_id == account_id))
        sync_folder_metadata(account_id, folder_id, worker_id="w", store=store)

        # Clear any prior background jobs from metadata sync
        with Session() as session:
            for j in session.scalars(select(WorkerJob).where(WorkerJob.account_id == account_id)).all():
                session.delete(j)
            session.commit()

        # Enqueue a delta job
        with Session() as session:
            initial_job = enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                account_id=account_id,
                payload={"folder_id": str(folder_id)},
                priority=60,
            )
            initial_job.status = JobStatus.CLAIMED.value
            initial_job.locked_by = "test-worker"
            initial_job.locked_at = now
            session.commit()
            job_id = initial_job.id

        # Delta throws RateLimitedError(retry_after_seconds=120.0)
        def rate_limited(remote_id, cursor):
            raise RateLimitedError("Too many delta requests", retry_after_seconds=120.0)

        provider.delta_changes = rate_limited  # type: ignore[method-assign]

        with Session() as session:
            job = session.get(WorkerJob, job_id)
            res = handle_job(session, job, worker_id="test-worker")
            session.commit()
            assert res is True

        with Session() as session:
            # The original job must be marked DONE (not rescheduled with short backoff)
            orig = session.get(WorkerJob, job_id)
            assert orig.status == JobStatus.DONE.value

            # Exactly one successor job exists, with run_after >= now + 120s
            pending = list(
                session.scalars(
                    select(WorkerJob)
                    .where(WorkerJob.account_id == account_id)
                    .where(WorkerJob.status == JobStatus.PENDING.value)
                ).all()
            )
            assert len(pending) == 1
            successor = pending[0]
            assert successor.job_type == JobType.SYNC_FOLDER_DELTA.value
            assert successor.run_after >= now + timedelta(seconds=115)
    finally:
        set_credential_store(None)


@pytest.mark.parametrize(
    ("prior_attempts", "expected_status"),
    [
        (0, RemoteOperationStatus.PENDING.value),
        (4, RemoteOperationStatus.FAILED.value),
    ],
)
@_requires_db
def test_a28_remote_push_rate_limit_respects_retry_after_and_attempt_cap(
    monkeypatch, prior_attempts, expected_status
):
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(session, email=f"a28-rp-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
            session.commit()
            account_id = acc.id

        class RateLimitedPush(MemoryProvider):
            def apply_remote_operation(self, op_type, desired):
                raise RateLimitedError("Hit limit", retry_after_seconds=75.0)

        provider = RateLimitedPush(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
        monkeypatch.setattr(push_mod, "build_provider", lambda a, s=None: provider)

        now = datetime.now(timezone.utc)
        with Session() as session:
            op = enqueue_remote_operation(
                session,
                account_id=account_id,
                entity_key="msg:1",
                op_type="mark_read",
                desired_state={"remote_id": "1", "folder_remote_id": "INBOX", "is_read": True},
            )
            op.attempts = prior_attempts
            session.commit()
            op_id = op.id

        result = push_remote_operations(account_id, worker_id="w", store=store)

        with Session() as session:
            op = session.get(RemoteOperation, op_id)
            assert op is not None
            assert op.status == expected_status
            assert op.attempts == prior_attempts + 1
            assert "RateLimitedError" in (op.last_error or op.error or "")

            if expected_status == RemoteOperationStatus.PENDING.value:
                assert op.next_attempt_at >= now + timedelta(seconds=70)
                job = session.scalar(
                    select(WorkerJob)
                    .where(WorkerJob.account_id == account_id)
                    .where(WorkerJob.job_type == JobType.REMOTE_OPERATION_PUSH.value)
                    .order_by(WorkerJob.created_at.desc())
                    .limit(1)
                )
                assert job is not None
                assert job.run_after >= now + timedelta(seconds=70)
                assert result["failed"] == 0
            else:
                assert op.next_attempt_at is None
                assert result["failed"] == 1
    finally:
        set_credential_store(None)


# ---------------------------------------------------------------------------
# A29: Release lease/claim on build_provider failure
# ---------------------------------------------------------------------------


@_requires_db
def test_a29_sync_account_folders_releases_lease_on_build_provider_failure(monkeypatch):
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(session, email=f"a29-acc-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
            session.commit()
            account_id = acc.id

        def fail_build(account, store=None):
            raise ValueError("corrupted credentials during build")

        monkeypatch.setattr(engine_mod, "build_provider", fail_build)

        with pytest.raises(ValueError, match="corrupted credentials"):
            sync_account_folders(account_id, worker_id="worker-a29", store=store)

        with Session() as session:
            lease = session.get(AccountSyncLease, account_id)
            assert lease is not None
            # Lease must be expired/released
            assert lease.lease_expires_at <= datetime.now(timezone.utc) + timedelta(seconds=1)
    finally:
        set_credential_store(None)


@_requires_db
def test_a29_sync_folder_metadata_releases_lease_on_build_provider_failure(monkeypatch):
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(session, email=f"a29-m-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
            folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
            session.add(folder)
            session.commit()
            account_id, folder_id = acc.id, folder.id

        def fail_build(account, store=None):
            raise RuntimeError("provider init failed")

        monkeypatch.setattr(engine_mod, "build_provider", fail_build)

        with pytest.raises(RuntimeError, match="provider init failed"):
            sync_folder_metadata(account_id, folder_id, worker_id="worker-a29", store=store)

        with Session() as session:
            lease = session.get(AccountSyncLease, account_id)
            assert lease is not None
            assert lease.lease_expires_at <= datetime.now(timezone.utc) + timedelta(seconds=1)
    finally:
        set_credential_store(None)


@_requires_db
def test_a29_sync_folder_delta_releases_lease_on_build_provider_failure(monkeypatch):
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed("INBOX", [RemoteMessageMeta("1", "One", "a@b.c", "A", now, False, False, uid=1)])

    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(session, email=f"a29-d-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
            session.commit()
            account_id = acc.id

        monkeypatch.setattr(engine_mod, "build_provider", lambda a, s=None: provider)
        sync_account_folders(account_id, worker_id="w", store=store)
        with Session() as session:
            folder_id = session.scalar(select(Folder.id).where(Folder.account_id == account_id))
        sync_folder_metadata(account_id, folder_id, worker_id="w", store=store)

        def fail_build(account, store=None):
            raise RuntimeError("delta build failure")

        monkeypatch.setattr(delta_mod, "build_provider", fail_build)

        with pytest.raises(RuntimeError, match="delta build failure"):
            sync_folder_delta(account_id, folder_id, worker_id="worker-a29", store=store)

        with Session() as session:
            lease = session.get(AccountSyncLease, account_id)
            assert lease is not None
            assert lease.lease_expires_at <= datetime.now(timezone.utc) + timedelta(seconds=1)
    finally:
        set_credential_store(None)


@_requires_db
def test_a29_remote_push_releases_lease_on_build_provider_failure(monkeypatch):
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(session, email=f"a29-push-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
            session.commit()
            account_id = acc.id
            enqueue_remote_operation(
                session,
                account_id=account_id,
                entity_key="msg:1",
                op_type="mark_read",
                desired_state={"remote_id": "1", "folder_remote_id": "INBOX", "is_read": True},
            )
            session.commit()

        def fail_build(account, store=None):
            raise RuntimeError("push build failure")

        monkeypatch.setattr(push_mod, "build_provider", fail_build)

        with pytest.raises(RuntimeError, match="push build failure"):
            push_remote_operations(account_id, worker_id="worker-a29", store=store)

        with Session() as session:
            lease = session.get(AccountSyncLease, account_id)
            assert lease is not None
            assert lease.lease_expires_at <= datetime.now(timezone.utc) + timedelta(seconds=1)
    finally:
        set_credential_store(None)


@_requires_db
def test_a29_archive_batch_releases_lease_and_restores_claims_on_build_failure(monkeypatch):
    from unittest.mock import patch
    import mail_core.blobs.archive as archive_mod

    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)

    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(session, email=f"a29-arch-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
            session.commit()
            account_id = acc.id

            folder = Folder(account_id=account_id, remote_id="INBOX", name="INBOX", role="inbox")
            session.add(folder)
            session.flush()

            msg = Message(
                account_id=account_id,
                remote_id="msg-arch-1",
                subject="Test Archive",
                from_address="s@ex.com",
                snippet="hello",
                sort_time=now,
            )
            session.add(msg)
            session.flush()

            st = MessageArchiveState(
                message_id=msg.id,
                state=ArchiveState.METADATA_SYNCED.value,
                priority=100,
            )
            session.add(st)
            session.commit()
            msg_id = msg.id

        def fail_build(account, store=None):
            raise RuntimeError("archive provider build failed")

        monkeypatch.setattr(archive_mod, "build_provider", fail_build)

        with pytest.raises(RuntimeError, match="archive provider build failed"):
            run_archive_batch(account_id=account_id, worker_id="worker-arch", store=store, payload={"batch_size": 10})

        with Session() as session:
            # Lease must be expired/released
            lease = session.get(AccountSyncLease, account_id)
            if lease is not None:
                assert lease.lease_expires_at <= datetime.now(timezone.utc) + timedelta(seconds=1)

                # Claim must be restored to ARCHIVE_PENDING with claimed_by cleared
                st = session.get(MessageArchiveState, msg_id)
                assert st is not None
                assert st.state == ArchiveState.ARCHIVE_PENDING.value
                assert st.claimed_by is None
                assert "RuntimeError" in (st.last_error or "")
    finally:
        set_credential_store(None)
