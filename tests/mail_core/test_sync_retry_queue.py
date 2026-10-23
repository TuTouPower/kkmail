from __future__ import annotations

import os
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobStatus, JobType
from mail_core.mail.storage.models import Account, Folder, SyncCheckpoint, WorkerJob
from mail_core.providers.http import CursorInvalidError
from mail_core.sync.delta import sync_folder_delta
from mail_core.sync.engine import sync_folder_metadata
from mail_core.sync.leases import acquire_lease
from mail_core.worker.handlers import _evaluate_result, handle_job
import mail_core.sync.delta as delta_mod
import mail_core.sync.engine as engine_mod
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
            dedupe_key=f"delta:{folder_id}",
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
        assert successors[0].payload.get("reason") == "cursor_invalid"
