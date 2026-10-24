from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobStatus, JobType
from mail_core.mail.application.queries import list_folder_stats_for_account
from mail_core.mail.storage.models import Account, Folder, Message, MessageLocation, SyncCheckpoint, WorkerJob
from mail_core.providers.base import RemoteFolder
from mail_core.providers.http import CursorInvalidError
from mail_core.sync.delta import sync_folder_delta
from mail_core.sync.engine import sync_account_folders, sync_folder_metadata
from mail_core.sync.leases import acquire_lease
from mail_core.worker.handlers import _evaluate_result, handle_job
import mail_core.sync.delta as delta_mod
import mail_core.sync.engine as engine_mod
import mail_core.sync.reconcile as reconcile_mod
import mail_core.worker.handlers as handlers_mod

pytestmark_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_evaluate_result_completes_job_when_retry_is_already_scheduled():
    job = WorkerJob(
        job_type=JobType.SYNC_FOLDER_DELTA.value,
        account_id=uuid.uuid4(),
        payload={"folder_id": str(uuid.uuid4())},
        status=JobStatus.CLAIMED.value,
        locked_by="retry-worker",
    )
    job.id = uuid.uuid4()
    session = MagicMock()

    with (
        patch("mail_core.worker.handlers.complete_job") as complete,
        patch("mail_core.worker.handlers.fail_job") as fail,
    ):
        result = _evaluate_result(
            session,
            job,
            {"status": "provider_error", "error": "RuntimeError", "followup_scheduled": True},
            "retry-worker",
        )

    assert result is True
    complete.assert_called_once_with(session, job, worker_id="retry-worker")
    fail.assert_not_called()


def test_evaluate_result_still_fails_without_a_scheduled_followup():
    job = WorkerJob(
        job_type=JobType.SYNC_FOLDER_DELTA.value,
        payload={"folder_id": str(uuid.uuid4())},
        status=JobStatus.CLAIMED.value,
        locked_by="retry-worker",
    )
    job.id = uuid.uuid4()
    session = MagicMock()

    with (
        patch("mail_core.worker.handlers.complete_job") as complete,
        patch("mail_core.worker.handlers.fail_job") as fail,
    ):
        result = _evaluate_result(session, job, {"status": "unexpected_error"}, "retry-worker")

    assert result is False
    complete.assert_not_called()
    fail.assert_called_once()


def _seed_folder(*, full_scan_complete: bool) -> tuple[uuid.UUID, uuid.UUID]:
    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"retry-{uuid.uuid4().hex}@example.test", provider="imap")
        session.add(account)
        session.flush()
        folder = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        session.add(
            SyncCheckpoint(
                account_id=account.id,
                folder_id=folder.id,
                full_scan_complete=full_scan_complete,
                cursor={"uid_next": 2},
            )
        )
        session.commit()
        return account.id, folder.id


@pytestmark_db
def test_delta_provider_error_completes_claim_and_leaves_one_pending_retry(monkeypatch):
    Session = get_session_factory()
    account_id, folder_id = _seed_folder(full_scan_complete=True)
    with Session() as session:
        job = WorkerJob(
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            account_id=account_id,
            payload={"folder_id": str(folder_id), "_followup_needed": True},
            status=JobStatus.CLAIMED.value,
            locked_by="retry-worker",
            attempts=1,
            dedupe_key=f"delta:{account_id}:{folder_id}",
        )
        session.add(job)
        session.commit()
        job_id = job.id

    class FailingDeltaProvider:
        def delta_changes(self, _remote_id, _cursor):
            raise RuntimeError("synthetic provider outage")

    monkeypatch.setattr(delta_mod, "build_provider", lambda _account, _store=None: FailingDeltaProvider())
    observed_results = []
    original_evaluate_result = _evaluate_result

    def capture_result(session, job, result, worker_id):
        observed_results.append(dict(result))
        return original_evaluate_result(session, job, result, worker_id)

    monkeypatch.setattr(handlers_mod, "_evaluate_result", capture_result)
    with Session() as session:
        job = session.get(WorkerJob, job_id)
        assert job is not None
        with patch("mail_core.worker.handlers.get_credential_store", return_value=object()):
            assert handle_job(session, job, worker_id="retry-worker") is True
        session.commit()

    assert observed_results[0]["followup_scheduled"] is True
    with Session() as session:
        jobs = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == account_id,
                    WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
                )
            )
        )
        pending = [row for row in jobs if row.status == JobStatus.PENDING.value]
        assert len(pending) == 1
        assert pending[0].dedupe_key == f"delta:{account_id}:{folder_id}"
        assert pending[0].last_error is None
        assert session.get(WorkerJob, job_id).status == JobStatus.DONE.value
        account = session.get(Account, account_id)
        assert account is not None
        assert account.sync_status == "failed"
        assert (account.config or {}).get("last_sync_error")
        assert "synthetic provider outage" not in str((account.config or {}).get("last_sync_error"))


@pytestmark_db
def test_delta_and_metadata_lease_busy_results_mark_existing_retries():
    Session = get_session_factory()
    account_id, folder_id = _seed_folder(full_scan_complete=True)
    with Session() as session:
        acquire_lease(session, account_id=account_id, owner_id="lease-holder", ttl=timedelta(minutes=5))
        session.commit()

    store = object()
    delta_result = sync_folder_delta(account_id, folder_id, worker_id="delta-worker", store=store)
    metadata_result = sync_folder_metadata(account_id, folder_id, worker_id="metadata-worker", store=store)

    assert delta_result["status"] == "lease_busy"
    assert delta_result["followup_scheduled"] is True
    assert metadata_result["status"] == "lease_busy"
    assert metadata_result["followup_scheduled"] is True
    with Session() as session:
        jobs = session.scalars(
            select(WorkerJob).where(
                WorkerJob.account_id == account_id,
                WorkerJob.status == JobStatus.PENDING.value,
            )
        ).all()
        assert {job.dedupe_key for job in jobs} == {
            f"delta:{account_id}:{folder_id}",
            f"metadata:{account_id}:{folder_id}",
        }


@pytestmark_db
@pytest.mark.parametrize(
    ("job_type", "key_prefix"),
    [
        (JobType.SYNC_FOLDER_DELTA.value, "delta"),
        (JobType.SYNC_FOLDER_METADATA.value, "metadata"),
    ],
)
def test_claimed_sync_job_coalesces_lease_busy_followup(job_type, key_prefix):
    Session = get_session_factory()
    account_id, folder_id = _seed_folder(full_scan_complete=True)
    worker_id = f"{key_prefix}-worker"
    dedupe_key = f"{key_prefix}:{account_id}:{folder_id}"
    with Session() as session:
        acquire_lease(session, account_id=account_id, owner_id="lease-holder", ttl=timedelta(minutes=5))
        job = WorkerJob(
            job_type=job_type,
            account_id=account_id,
            payload={"folder_id": str(folder_id)},
            status=JobStatus.CLAIMED.value,
            locked_by=worker_id,
            attempts=1,
            dedupe_key=dedupe_key,
        )
        session.add(job)
        session.commit()
        job_id = job.id

    with Session() as session:
        job = session.get(WorkerJob, job_id)
        assert job is not None
        with patch("mail_core.worker.handlers.get_credential_store", return_value=object()):
            assert handle_job(session, job, worker_id=worker_id) is True
        session.commit()

    with Session() as session:
        followups = session.scalars(
            select(WorkerJob).where(
                WorkerJob.account_id == account_id,
                WorkerJob.dedupe_key == dedupe_key,
                WorkerJob.status == JobStatus.PENDING.value,
            )
        ).all()
        assert len(followups) == 1
        assert followups[0].run_after >= datetime.now(timezone.utc) + timedelta(seconds=4)


@pytestmark_db
@pytest.mark.parametrize(
    ("sync_path", "exhausted", "expected_type", "key_prefix"),
    [
        ("metadata", False, JobType.SYNC_FOLDER_METADATA.value, "metadata"),
        ("delta", False, JobType.SYNC_FOLDER_DELTA.value, "delta"),
        ("metadata", True, JobType.SYNC_FOLDER_DELTA.value, "delta"),
    ],
)
def test_page_followups_use_job_type_dedupe_key(monkeypatch, sync_path, exhausted, expected_type, key_prefix):
    from mail_core.providers.base import DeltaPage, MetadataPage

    Session = get_session_factory()
    account_id, folder_id = _seed_folder(full_scan_complete=sync_path == "delta")

    class PartialProvider:
        def fetch_metadata_page(self, _remote_id, _cursor):
            return MetadataPage(items=[], next_cursor={"uid_next": 2}, exhausted=exhausted)

        def delta_changes(self, _remote_id, _cursor):
            if exhausted:
                raise AssertionError("delta path case must remain non-exhausted")
            return DeltaPage(changes=[], next_cursor={"historyId": "2"}, exhausted=False)

    provider = PartialProvider()
    monkeypatch.setattr(engine_mod, "build_provider", lambda _account, _store=None: provider)
    monkeypatch.setattr(delta_mod, "build_provider", lambda _account, _store=None: provider)
    if sync_path == "metadata":
        result = sync_folder_metadata(account_id, folder_id, worker_id="page-followup", store=object(), max_pages=1)
    else:
        result = sync_folder_delta(account_id, folder_id, worker_id="page-followup", store=object(), max_pages=1)
    assert result["status"] == "ok"
    assert result["exhausted"] is exhausted

    dedupe_key = f"{key_prefix}:{account_id}:{folder_id}"
    with Session() as session:
        followups = session.scalars(
            select(WorkerJob).where(
                WorkerJob.account_id == account_id,
                WorkerJob.job_type == expected_type,
                WorkerJob.dedupe_key == dedupe_key,
                WorkerJob.status == JobStatus.PENDING.value,
            )
        ).all()
        assert len(followups) == 1


@pytestmark_db
def test_delta_cursor_invalid_marks_metadata_rebuild_as_scheduled(monkeypatch):
    Session = get_session_factory()
    account_id, folder_id = _seed_folder(full_scan_complete=True)

    class InvalidCursorProvider:
        def delta_changes(self, _remote_id, _cursor):
            raise CursorInvalidError("cursor expired")

    monkeypatch.setattr(delta_mod, "build_provider", lambda _account, _store=None: InvalidCursorProvider())
    result = sync_folder_delta(account_id, folder_id, worker_id="delta-worker", store=object())

    assert result["status"] == "cursor_invalid"
    assert result["followup_scheduled"] is True
    with Session() as session:
        successor = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == account_id,
                WorkerJob.job_type == JobType.SYNC_FOLDER_METADATA.value,
                WorkerJob.status == JobStatus.PENDING.value,
            )
        )
        assert successor is not None
        assert successor.dedupe_key == f"metadata:{account_id}:{folder_id}"
        assert successor.payload.get("reason") == "cursor_invalid"


@pytestmark_db
def test_metadata_cursor_invalid_marks_rebuild_as_scheduled(monkeypatch):
    Session = get_session_factory()
    account_id, folder_id = _seed_folder(full_scan_complete=False)

    class InvalidCursorProvider:
        def fetch_metadata_page(self, _remote_id, _cursor):
            raise CursorInvalidError("cursor expired")

    monkeypatch.setattr(engine_mod, "build_provider", lambda _account, _store=None: InvalidCursorProvider())
    result = sync_folder_metadata(account_id, folder_id, worker_id="metadata-worker", store=object())

    assert result["status"] == "cursor_invalid"
    assert result["followup_scheduled"] is True
    with Session() as session:
        successors = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == account_id,
                    WorkerJob.job_type == JobType.SYNC_FOLDER_METADATA.value,
                    WorkerJob.status == JobStatus.PENDING.value,
                )
            )
        )
        assert len(successors) == 1
        assert successors[0].dedupe_key == f"metadata:{account_id}:{folder_id}"
        assert successors[0].payload.get("reason") == "cursor_invalid"


@pytestmark_db
def test_noselect_folder_discovery_preserves_parent_and_skips_metadata_job(monkeypatch):
    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"noselect-{uuid.uuid4().hex}@example.test", provider="imap")
        session.add(account)
        session.flush()
        parent = Folder(
            account_id=account.id,
            remote_id="Other",
            name="其他文件夹",
            role="other",
            sync_status="idle",
        )
        message = Message(account_id=account.id, remote_id="preserved-message", subject="keep")
        session.add_all([parent, message])
        session.flush()
        session.add(MessageLocation(message_id=message.id, folder_id=parent.id, uid=1))
        checkpoint = SyncCheckpoint(
            account_id=account.id,
            folder_id=parent.id,
            cursor={"uid_next": 7},
            uidvalidity=42,
            full_scan_complete=True,
        )
        session.add(checkpoint)
        old_jobs = {
            job_type: WorkerJob(
                job_type=job_type.value,
                account_id=account.id,
                payload={"folder_id": str(parent.id)},
                status=JobStatus.CLAIMED.value,
                locked_by="worker-noselect",
                attempts=1,
            )
            for job_type in (
                JobType.SYNC_FOLDER_METADATA,
                JobType.SYNC_FOLDER_DELTA,
                JobType.RECONCILE_FOLDER,
            )
        }
        session.add_all(old_jobs.values())
        session.commit()
        account_id, parent_id, message_id = account.id, parent.id, message.id
        old_job_ids = {job_type: job.id for job_type, job in old_jobs.items()}

    class CatalogProvider:
        def list_folders(self):
            return [RemoteFolder("INBOX", "INBOX", "inbox")]

        def list_folder_catalog(self):
            return [
                RemoteFolder("INBOX", "INBOX", "inbox"),
                RemoteFolder("Other", "其他文件夹", "other", selectable=False),
                RemoteFolder("Other/QQ邮件订阅", "QQ邮件订阅", "other", parent_remote_id="Other"),
            ]

    monkeypatch.setattr(engine_mod, "build_provider", lambda _account, _store=None: CatalogProvider())
    def unexpected_provider(*_args, **_kwargs):
        raise AssertionError("non-selectable folder must not call a provider")

    monkeypatch.setattr(delta_mod, "build_provider", unexpected_provider)
    monkeypatch.setattr(reconcile_mod, "build_provider", unexpected_provider)
    result = sync_account_folders(account_id, worker_id="worker-noselect", store=object())
    assert result["status"] == "ok"

    with Session() as session:
        parent = session.get(Folder, parent_id)
        assert parent is not None
        assert parent.sync_status == "paused"
        assert session.get(Message, message_id) is not None
        assert session.scalar(
            select(MessageLocation.id).where(
                MessageLocation.folder_id == parent_id,
                MessageLocation.message_id == message_id,
            )
        ) is not None
        checkpoint = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": parent_id})
        assert checkpoint is not None
        assert checkpoint.cursor == {"uid_next": 7}
        assert checkpoint.uidvalidity == 42
        assert checkpoint.full_scan_complete is True
        child = session.scalar(select(Folder).where(Folder.remote_id == "Other/QQ邮件订阅"))
        assert child is not None
        assert child.parent_remote_id == "Other"
        parent_stats = next(
            row for row in list_folder_stats_for_account(session, account_id)
            if row["folder_id"] == str(parent_id)
        )
        assert parent_stats["sync_status"] == "paused"
        assert parent_stats["total_count"] is None
        assert parent_stats["unread_count"] is None
        child_jobs = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == account_id,
                    WorkerJob.job_type == JobType.SYNC_FOLDER_METADATA.value,
                    WorkerJob.payload["folder_id"].astext == str(child.id),
                )
            )
        )
        assert len(child_jobs) == 1
        assert child_jobs[0].status == JobStatus.PENDING.value
        for job_type, job_id in old_job_ids.items():
            old_job = session.get(WorkerJob, job_id)
            assert old_job is not None
            parent_jobs = list(
                session.scalars(
                    select(WorkerJob).where(
                        WorkerJob.account_id == account_id,
                        WorkerJob.job_type == job_type.value,
                        WorkerJob.payload["folder_id"].astext == str(parent_id),
                    )
                )
            )
            assert [job.id for job in parent_jobs] == [job_id]
            with patch("mail_core.worker.handlers.get_credential_store", return_value=object()):
                assert handle_job(session, old_job, worker_id="worker-noselect") is True
            session.commit()

    with Session() as session:
        for job_id in old_job_ids.values():
            completed = session.get(WorkerJob, job_id)
            assert completed is not None
            assert completed.status == JobStatus.DONE.value
            assert completed.attempts == 1
        checkpoint = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": parent_id})
        assert checkpoint is not None
        assert checkpoint.cursor == {"uid_next": 7}
        assert checkpoint.uidvalidity == 42
        assert checkpoint.full_scan_complete is True


@pytestmark_db
def test_folder_discovery_pauses_missing_remote_and_deduplicates_metadata_job(monkeypatch):
    from mail_core.mail.storage.models import OutboxEvent

    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"folders-{uuid.uuid4().hex}@example.test", provider="imap")
        session.add(account)
        session.flush()
        missing = Folder(
            account_id=account.id,
            remote_id="Deleted/Remote",
            name="Old folder",
            role="other",
            sync_status="idle",
        )
        message = Message(account_id=account.id, remote_id="kept-message", subject="Keep")
        session.add_all([missing, message])
        session.flush()
        session.add_all(
            [
                MessageLocation(message_id=message.id, folder_id=missing.id, uid=9),
                SyncCheckpoint(
                    account_id=account.id,
                    folder_id=missing.id,
                    cursor={"uid_next": 10},
                    full_scan_complete=True,
                ),
            ]
        )
        session.commit()
        account_id, missing_id, message_id = account.id, missing.id, message.id

    class ListingProvider:
        def list_folders(self):
            return [RemoteFolder("INBOX", "INBOX", "inbox")]

    monkeypatch.setattr(engine_mod, "build_provider", lambda _account, _store=None: ListingProvider())
    sync_account_folders(account_id, worker_id="folders-test", store=object())
    sync_account_folders(account_id, worker_id="folders-test", store=object())

    with Session() as session:
        missing = session.get(Folder, missing_id)
        assert missing is not None and missing.sync_status == "paused"
        assert session.get(Message, message_id) is not None
        assert session.scalar(
            select(MessageLocation.id).where(
                MessageLocation.folder_id == missing_id,
                MessageLocation.message_id == message_id,
            )
        ) is not None
        checkpoint = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": missing_id})
        assert checkpoint is not None and checkpoint.cursor == {"uid_next": 10}
        events = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.account_id == account_id,
                OutboxEvent.event_type == "folder.stats_updated",
                OutboxEvent.payload["folder_id"].astext == str(missing_id),
            )
        ).all()
        assert len(events) == 1
        assert session.scalar(
            select(WorkerJob.id).where(
                WorkerJob.account_id == account_id,
                WorkerJob.job_type == JobType.SYNC_FOLDER_METADATA.value,
                WorkerJob.payload["folder_id"].astext == str(missing_id),
            )
        ) is None

        inbox = session.scalar(select(Folder).where(Folder.account_id == account_id, Folder.remote_id == "INBOX"))
        assert inbox is not None
        jobs = session.scalars(
            select(WorkerJob).where(
                WorkerJob.account_id == account_id,
                WorkerJob.job_type == JobType.SYNC_FOLDER_METADATA.value,
                WorkerJob.dedupe_key == f"metadata:{account_id}:{inbox.id}",
            )
        ).all()
        assert len(jobs) == 1
