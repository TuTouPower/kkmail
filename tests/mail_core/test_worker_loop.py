import os
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from mail_core.worker import main as worker_main

pytestmark_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


@pytest.mark.parametrize("raw", ["bad", "nan", "inf", "0", "-1"])
def test_positive_float_setting_warns_and_uses_default(monkeypatch, caplog, raw):
    monkeypatch.setenv("MAIL_CORE_WORKER_POLL_S", raw)

    with caplog.at_level("WARNING", logger="mail_core.worker"):
        value = worker_main._positive_float_setting("MAIL_CORE_WORKER_POLL_S", 2.0)

    assert value == 2.0
    assert "invalid numeric environment setting MAIL_CORE_WORKER_POLL_S" in caplog.text
    assert raw in caplog.text


def test_worker_stops_on_flag(monkeypatch):
    ticked = threading.Event()

    def fake_tick(_worker_id):
        ticked.set()
        return worker_main.TickResult(claimed=0, handled=0)

    monkeypatch.setattr(worker_main, "_reclaim_once", lambda: 0)
    monkeypatch.setattr(worker_main, "_tick", fake_tick)
    t = threading.Thread(target=lambda: worker_main.run(poll_interval_s=0.01), daemon=True)
    t.start()
    try:
        assert ticked.wait(timeout=2)
    finally:
        worker_main.request_stop()
        t.join(timeout=2)
    assert not t.is_alive()


def test_reclaim_once_calls_reclaim_stale_claims():
    with (
        patch("mail_core.db.session.get_session_factory") as gs,
        patch("mail_core.sync.jobs.reclaim_stale_claims", return_value=2) as rc,
    ):
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        gs.return_value = MagicMock(return_value=session)
        n = worker_main._reclaim_once()
        assert n == 2
        rc.assert_called_once()
        session.commit.assert_called()


def test_claim_heartbeat_refreshes_all_jobs_in_claimed_batch(monkeypatch):
    import uuid

    monkeypatch.setattr(worker_main, "_claim_heartbeat_interval_s", lambda: 0.01)
    heartbeat_calls = []
    all_refreshed = threading.Event()
    job_ids = [uuid.uuid4(), uuid.uuid4()]
    now = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)
    claim_times = {job_id: now for job_id in job_ids}
    claim_lock = threading.Lock()
    stop_event = threading.Event()

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def commit(self):
            pass

    def refresh(_session, *, job_id, worker_id, locked_at, now):
        heartbeat_calls.append((job_id, worker_id, locked_at))
        if len(heartbeat_calls) == 2:
            all_refreshed.set()
        return now

    with patch("mail_core.sync.jobs.heartbeat_job_claim", side_effect=refresh):
        thread = threading.Thread(
            target=worker_main._heartbeat_claims,
            args=(
                lambda: Session(),
                [(job_ids[0], "worker-1", now), (job_ids[1], "worker-1", now)],
                claim_times,
                claim_lock,
                stop_event,
            ),
            daemon=True,
        )
        thread.start()
        assert all_refreshed.wait(1)
        stop_event.set()
        thread.join(timeout=1)

    assert not thread.is_alive()
    assert [call[0] for call in heartbeat_calls] == job_ids
    assert all(claim_times[job_id] != now for job_id in job_ids)


def test_run_reclaims_on_a_separate_time_cadence(monkeypatch):
    clock = iter((0.0, 10.0, 60.0, 61.0))
    monkeypatch.setattr(worker_main, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda _seconds: None))
    monkeypatch.setattr(worker_main, "RECLAIM_INTERVAL_S", 60.0)
    monkeypatch.setattr("mail_core.blobs.crypto.load_keyring_from_env", lambda: {})
    reclaim = MagicMock()
    monkeypatch.setattr(worker_main, "_reclaim_once", reclaim)
    ticks = 0

    def tick(_worker_id):
        nonlocal ticks
        ticks += 1
        if ticks == 4:
            worker_main.request_stop()
        return worker_main.TickResult(claimed=worker_main.CLAIM_BATCH, handled=worker_main.CLAIM_BATCH)

    monkeypatch.setattr(worker_main, "_tick", tick)
    thread = threading.Thread(target=worker_main.run, kwargs={"poll_interval_s": 0.01}, daemon=True)
    thread.start()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert ticks == 4
    assert reclaim.call_count == 2


def test_run_uses_base_poll_after_claimed_jobs_fail(monkeypatch):
    delays = []

    def stop_after_sleep(delay):
        delays.append(delay)
        worker_main.request_stop()

    monkeypatch.setattr(
        worker_main,
        "time",
        SimpleNamespace(monotonic=lambda: 0.0, sleep=stop_after_sleep),
    )
    monkeypatch.setattr("mail_core.blobs.crypto.load_keyring_from_env", lambda: {})
    monkeypatch.setattr(worker_main, "_reclaim_once", lambda: 0)
    monkeypatch.setattr(
        worker_main,
        "_tick",
        lambda _worker_id: worker_main.TickResult(claimed=3, handled=0),
    )

    worker_main.run(poll_interval_s=2.0)

    assert delays == [2.0]


@pytestmark_db
def test_tick_reclaims_stale_and_isolates_job_sessions():
    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.enums import JobStatus, JobType
    from mail_core.mail.storage.models import WorkerJob
    from mail_core.sync.jobs import enqueue_job

    Session = get_session_factory()
    with Session() as session:
        stale = WorkerJob(
            job_type=JobType.OUTBOX_DISPATCH_WAKE.value,
            payload={},
            status=JobStatus.CLAIMED.value,
            locked_by="dead-worker",
            locked_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            attempts=1,
            priority=10,
            run_after=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
        session.add(stale)
        j1 = enqueue_job(session, job_type=JobType.OUTBOX_DISPATCH_WAKE.value, payload={}, priority=10)
        j2 = enqueue_job(session, job_type=JobType.OUTBOX_DISPATCH_WAKE.value, payload={}, priority=10)
        session.commit()
        stale_id, id1, id2 = stale.id, j1.id, j2.id

    worker_main._reclaim_once()
    with patch("mail_core.realtime.notify.try_notify_outbox"):
        result = worker_main._tick("test-worker-iso")
    assert result.claimed >= 2
    assert result.handled >= 2

    with Session() as session:
        stale_row = session.get(WorkerJob, stale_id)
        assert stale_row is not None
        # Stale claim must have been reclaimed (PENDING) or re-handled to DONE — never left
        # CLAIMED by the dead worker.
        assert stale_row.status in (JobStatus.PENDING.value, JobStatus.DONE.value)
        if stale_row.status == JobStatus.CLAIMED.value:
            raise AssertionError("stale job still CLAIMED after reclaim tick")
        if stale_row.locked_by == "dead-worker":
            raise AssertionError("stale job still locked by dead-worker")

        for jid in (id1, id2):
            row = session.get(WorkerJob, jid)
            assert row is not None
            # Fresh pending wake jobs must actually be handled to DONE (not a tautology).
            assert row.status == JobStatus.DONE.value, (jid, row.status, row.last_error)
            assert row.locked_by == "test-worker-iso" or row.locked_by is None


@pytestmark_db
def test_sync_failure_recovers_after_retry_without_hiding_other_errors():
    import uuid

    from datetime import datetime, timezone

    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.enums import JobStatus, JobType
    from mail_core.mail.storage.models import Account, WorkerJob
    from mail_core.worker.handlers import handle_job

    Session = get_session_factory()
    account_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    with Session() as session:
        account = Account(email=f"self-heal-{account_id.hex[:10]}@example.test", provider="imap")
        session.add(account)
        session.flush()
        account_id = account.id
        failed_job = WorkerJob(
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            account_id=account_id,
            payload={"folder_id": str(folder_id)},
            status=JobStatus.CLAIMED.value,
            locked_by="worker-failed",
            attempts=1,
        )
        successful_job = WorkerJob(
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            account_id=account_id,
            payload={"folder_id": str(folder_id)},
            status=JobStatus.CLAIMED.value,
            locked_by="worker-success",
            attempts=1,
        )
        session.add_all([failed_job, successful_job])
        session.commit()
        failed_job_id, successful_job_id = failed_job.id, successful_job.id

    with Session() as session:
        job = session.get(WorkerJob, failed_job_id)
        assert job is not None
        with patch(
            "mail_core.sync.delta.sync_folder_delta",
            side_effect=RuntimeError("temporary provider outage"),
        ):
            assert handle_job(session, job, worker_id="worker-failed") is False
        session.commit()
        account = session.get(Account, account_id)
        assert account is not None
        assert account.sync_status == "failed"
        assert (account.config or {}).get("last_sync_error")
        assert session.get(WorkerJob, failed_job_id).status == JobStatus.PENDING.value

    with Session() as session:
        job = session.get(WorkerJob, successful_job_id)
        assert job is not None
        with patch("mail_core.sync.delta.sync_folder_delta", return_value={"status": "ok"}):
            assert handle_job(session, job, worker_id="worker-success") is True
        session.commit()
        account = session.get(Account, account_id)
        assert account is not None
        assert account.sync_status == "failed"
        assert (account.config or {}).get("last_sync_error")

    with Session() as session:
        retry = session.get(WorkerJob, failed_job_id)
        assert retry is not None
        retry.status = JobStatus.CLAIMED.value
        retry.locked_by = "worker-retry"
        retry.locked_at = datetime.now(timezone.utc)
        retry.attempts = 2
        session.commit()
        with patch("mail_core.sync.delta.sync_folder_delta", return_value={"status": "ok"}):
            assert handle_job(session, retry, worker_id="worker-retry") is True
        session.commit()
        account = session.get(Account, account_id)
        assert account is not None
        assert account.sync_status == "idle"
        assert "last_sync_error" not in (account.config or {})

        account.sync_status = "auth_failed"
        account.sync_enabled = False
        auth_job = WorkerJob(
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            account_id=account_id,
            payload={"folder_id": str(folder_id)},
            status=JobStatus.CLAIMED.value,
            locked_by="worker-auth",
            attempts=1,
        )
        session.add(auth_job)
        session.commit()
        assert handle_job(session, auth_job, worker_id="worker-auth") is True
        session.commit()
        account = session.get(Account, account_id)
        assert account is not None
        assert account.sync_status == "auth_failed"


@pytestmark_db
def test_auxiliary_archive_failure_does_not_mark_account_sync_failed():
    import uuid

    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.enums import JobStatus, JobType
    from mail_core.mail.storage.models import Account, WorkerJob
    from mail_core.worker.handlers import handle_job

    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"archive-status-{uuid.uuid4().hex[:10]}@example.test", provider="imap")
        session.add(account)
        session.flush()
        job = WorkerJob(
            job_type=JobType.ARCHIVE_MIME_BATCH.value,
            account_id=account.id,
            payload={},
            status=JobStatus.CLAIMED.value,
            locked_by="worker-archive",
            attempts=1,
        )
        session.add(job)
        session.commit()
        account_id = account.id

        with patch(
            "mail_core.blobs.archive.run_archive_batch",
            side_effect=RuntimeError("archive disk failure"),
        ):
            assert handle_job(session, job, worker_id="worker-archive") is False
        session.commit()
        account = session.get(Account, account_id)
        assert account is not None
        assert account.sync_status == "idle"


def test_tick_failed_job_not_counted_as_handled():
    """handle_job False (fail_job path) must not increment handled / skew backoff."""
    import uuid

    from mail_core.mail.storage.models import WorkerJob

    job = WorkerJob(job_type="no_such_type_xyz", payload={})
    job.id = uuid.uuid4()

    class _S:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *_a, **_k):
            return job

        def in_transaction(self):
            return True

        def commit(self):
            return None

        def rollback(self):
            return None

    with (
        patch("mail_core.worker.main._reclaim_once", return_value=0),
        patch("mail_core.db.session.get_session_factory", return_value=lambda: _S()),
        patch("mail_core.sync.jobs.claim_jobs", return_value=[job]),
        patch("mail_core.worker.handlers.handle_job", return_value=False),
    ):
        result = worker_main._tick("w-fail-count")
    assert result.claimed == 1
    assert result.handled == 0


def test_handle_job_sanitizes_error_in_update_account_sync_status():
    import uuid
    from mail_core.mail.domain.enums import JobType, SyncStatus
    from mail_core.mail.storage.models import Account, WorkerJob
    from mail_core.worker.handlers import handle_job

    account_id = uuid.uuid4()
    job = WorkerJob(
        account_id=account_id,
        job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
        status="claimed",
        payload={"account_id": str(account_id)},
    )
    job.id = uuid.uuid4()

    mock_account = MagicMock(spec=Account)
    mock_account.sync_enabled = True

    session = MagicMock()
    session.in_transaction.return_value = True
    session.get.return_value = mock_account

    sensitive_exc = ValueError("connection failed: postgresql://user:my_secret_password@host/db?token=ya29.secret")

    with (
        patch("mail_core.sync.engine.sync_account_folders", side_effect=sensitive_exc),
        patch("mail_core.worker.handlers.update_account_sync_status") as mock_update_status,
        patch("mail_core.worker.handlers.fail_job"),
    ):
        ok = handle_job(session, job, worker_id="test-worker")
        assert ok is False
        mock_update_status.assert_called_once()
        call_kwargs = mock_update_status.call_args[1]
        assert (
            call_kwargs.get("status") is SyncStatus.FAILED
            or mock_update_status.call_args[0][2] is SyncStatus.FAILED
        )
        passed_error = call_kwargs.get("error", "")
        assert "my_secret_password" not in passed_error
        assert "[REDACTED]" in passed_error


def test_handle_job_resolves_credential_store_inside_job_error_boundary():
    import uuid

    from mail_core.mail.domain.enums import JobType
    from mail_core.mail.storage.models import WorkerJob
    from mail_core.worker.handlers import handle_job

    job = WorkerJob(
        account_id=uuid.uuid4(),
        job_type=JobType.REMOTE_OPERATION_PUSH.value,
        status="claimed",
        payload={},
    )
    job.id = uuid.uuid4()
    session = MagicMock()

    with (
        patch("mail_core.worker.handlers.get_credential_store", side_effect=RuntimeError("store unavailable")),
        patch("mail_core.worker.handlers.fail_job") as mock_fail_job,
    ):
        assert handle_job(session, job, worker_id="test-worker") is False

    mock_fail_job.assert_called_once()


def test_handle_job_skips_credential_store_for_outbox_wake():
    import uuid

    from mail_core.mail.domain.enums import JobType
    from mail_core.mail.storage.models import WorkerJob
    from mail_core.worker.handlers import handle_job

    job = WorkerJob(job_type=JobType.OUTBOX_DISPATCH_WAKE.value, status="claimed", payload={})
    job.id = uuid.uuid4()
    session = MagicMock()

    with (
        patch("mail_core.worker.handlers.get_credential_store", side_effect=AssertionError("not needed")),
        patch("mail_core.realtime.notify.try_notify_outbox"),
        patch("mail_core.worker.handlers.complete_job"),
    ):
        assert handle_job(session, job, worker_id="test-worker") is True


def test_worker_result_log_summary_keeps_only_safe_fields():
    from mail_core.worker.handlers import _result_log_summary

    result = {
        "status": "provider_error",
        "upserted": 4,
        "pages": 2,
        "duration_seconds": 1.25,
        "error": "password=private-secret",
        "email": "person@example.com",
        "payload": {"token": "private-token"},
    }

    assert _result_log_summary(result) == {
        "status": "provider_error",
        "upserted": 4,
        "pages": 2,
        "duration_seconds": 1.25,
    }


def test_evaluate_result_retains_business_payload_for_followup():
    """AC-005: Worker _evaluate_result must retain business payload and strip _followup_* fields."""
    import uuid
    from mail_core.mail.domain.enums import JobType
    from mail_core.mail.storage.models import WorkerJob
    from mail_core.worker.handlers import _evaluate_result

    job = WorkerJob(
        job_type=JobType.SYNC_FOLDER_DELTA.value,
        account_id=uuid.uuid4(),
        status="claimed",
        payload={
            "folder_id": "f-12345",
            "account_id": "acc-999",
            "_followup_needed": True,
            "_followup_run_after": "2026-10-23T10:00:00+00:00",
        },
        priority=5,
        dedupe_key="dedupe-123",
    )
    job.id = uuid.uuid4()

    session = MagicMock()
    with (
        patch("mail_core.worker.handlers.complete_job"),
        patch("mail_core.sync.jobs.enqueue_job") as mock_enqueue,
    ):
        ok = _evaluate_result(session, job, {"status": "ok", "has_more": True}, worker_id="test-worker")
        assert ok is True
        mock_enqueue.assert_called_once()
        _, kwargs = mock_enqueue.call_args
        assert kwargs["payload"] == {"folder_id": "f-12345", "account_id": "acc-999"}
        assert kwargs["run_after"] == datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)
        assert "_followup_needed" not in kwargs["payload"]
        assert "_followup_run_after" not in kwargs["payload"]


def test_evaluate_result_logs_unparseable_followup_run_after():
    """Malformed scheduling metadata is visible without logging its contents."""
    import uuid
    from mail_core.mail.domain.enums import JobType
    from mail_core.mail.storage.models import WorkerJob
    from mail_core.worker.handlers import _evaluate_result

    job = WorkerJob(
        job_type=JobType.SYNC_FOLDER_DELTA.value,
        account_id=uuid.uuid4(),
        status="claimed",
        payload={"_followup_needed": True, "_followup_run_after": "not-a-date"},
        priority=5,
        dedupe_key="dedupe-invalid-time",
    )
    job.id = uuid.uuid4()
    session = MagicMock()

    with (
        patch("mail_core.worker.handlers.complete_job"),
        patch("mail_core.sync.jobs.enqueue_job") as mock_enqueue,
        patch("mail_core.worker.handlers.log.warning") as warning,
    ):
        ok = _evaluate_result(session, job, {"status": "ok"}, worker_id="test-worker")

    assert ok is True
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.kwargs["run_after"] is None
    warning.assert_called_once()
    warning_message = " ".join(str(arg) for arg in warning.call_args.args)
    assert "unparseable _followup_run_after" in warning_message
    assert "not-a-date" not in warning_message
