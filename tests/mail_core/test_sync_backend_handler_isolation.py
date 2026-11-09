"""Adoption fixes for the sync backend review (background isolation).

Covers:
- P1-4: a background ``SYNC_ACCOUNT_FOLDERS`` failure must never write the
  account ``sync_status=FAILED`` (spec mail_sync_and_storage.md §15.3).
- P2-D1: dead host-security imports removed from providers.factory.
- P2-S1: background folder discovery must not enqueue the inbox folder.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from mail_core.mail.domain.enums import JobType, SyncStatus
from mail_core.mail.storage.models import WorkerJob
from mail_core.worker import handlers
from mail_core.worker.handlers import _evaluate_result, _is_background_sync


def _job(*, background: bool) -> WorkerJob:
    payload: dict = {"request_id": str(uuid.uuid4())}
    if background:
        payload["background"] = True
    job = WorkerJob(
        job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
        account_id=uuid.uuid4(),
        status="claimed",
        payload=payload,
    )
    job.id = uuid.uuid4()
    job.locked_by = "w-fix"
    return job


def _terminal_job(*, background: bool) -> WorkerJob:
    from mail_core.sync.jobs import _max_attempts

    job = _job(background=background)
    job.failure_attempts = _max_attempts() - 1
    return job


def test_is_background_sync_reads_payload_marker():
    assert _is_background_sync(_job(background=True)) is True
    assert _is_background_sync(_job(background=False)) is False
    assert _is_background_sync(WorkerJob(payload=None)) is False
    assert _is_background_sync(WorkerJob(payload={"background": False})) is False


@pytest.mark.parametrize("status", ["provider_error", "rate_limited"])
def test_foreground_failure_marks_account_failed(status):
    job = _job(background=False)
    session = MagicMock()
    with (
        patch.object(handlers, "update_account_sync_status") as mark,
        patch.object(handlers, "complete_job"),
        patch.object(handlers, "fail_job"),
    ):
        _evaluate_result(session, job, {"status": status, "error": "boom"}, worker_id="w-fix")
    mark.assert_called_once()
    assert mark.call_args.args[2] is SyncStatus.FAILED


@pytest.mark.parametrize("status", ["provider_error", "rate_limited"])
def test_background_failure_does_not_mark_account_failed(status):
    job = _job(background=True)
    session = MagicMock()
    with (
        patch.object(handlers, "update_account_sync_status") as mark,
        patch.object(handlers, "complete_job"),
        patch.object(handlers, "fail_job"),
    ):
        _evaluate_result(session, job, {"status": status, "error": "boom"}, worker_id="w-fix")
    mark.assert_not_called()


def test_handle_job_passes_background_flag_to_engine():
    job = _job(background=True)
    session = MagicMock()
    session.get.return_value = MagicMock(sync_enabled=True)
    with (
        patch("mail_core.sync.engine.sync_account_folders", return_value={"status": "ok"}) as engine,
        patch.object(handlers, "get_credential_store"),
        patch.object(handlers, "complete_job"),
        patch.object(handlers, "_recover_account_sync_status"),
    ):
        ok = handlers.handle_job(session, job, worker_id="w-fix")
    assert ok is True
    assert engine.call_args.kwargs["background"] is True


def test_handle_job_foreground_does_not_pass_background_flag():
    job = _job(background=False)
    session = MagicMock()
    session.get.return_value = MagicMock(sync_enabled=True)
    with (
        patch("mail_core.sync.engine.sync_account_folders", return_value={"status": "ok"}) as engine,
        patch.object(handlers, "get_credential_store"),
        patch.object(handlers, "complete_job"),
        patch.object(handlers, "_recover_account_sync_status"),
    ):
        handlers.handle_job(session, job, worker_id="w-fix")
    assert engine.call_args.kwargs["background"] is False


def test_foreground_terminal_failure_marks_account_failed():
    job = _terminal_job(background=False)
    session = MagicMock()
    session.in_transaction.return_value = True
    session.get.return_value = MagicMock(sync_enabled=True)
    with (
        patch("mail_core.sync.engine.sync_account_folders", side_effect=RuntimeError("outage")),
        patch.object(handlers, "update_account_sync_status") as mark,
        patch.object(handlers, "fail_job"),
    ):
        ok = handlers.handle_job(session, job, worker_id="w-fix")
    assert ok is False
    mark.assert_called_once()


def test_background_terminal_failure_does_not_mark_account_failed():
    job = _terminal_job(background=True)
    session = MagicMock()
    session.in_transaction.return_value = True
    session.get.return_value = MagicMock(sync_enabled=True)
    with (
        patch("mail_core.sync.engine.sync_account_folders", side_effect=RuntimeError("outage")),
        patch.object(handlers, "update_account_sync_status") as mark,
        patch.object(handlers, "fail_job"),
    ):
        ok = handlers.handle_job(session, job, worker_id="w-fix")
    assert ok is False
    mark.assert_not_called()


def test_factory_does_not_import_dead_host_security_helpers():
    import mail_core.providers.factory as factory

    for name in ("is_private_host", "is_restricted_ip", "private_hosts_allowed"):
        assert not hasattr(factory, name)
    for name in ("is_loopback_host", "reject_microsoft_imap", "validate_imap_host"):
        assert hasattr(factory, name)


def test_background_discovery_skips_inbox_only():
    from mail_core.sync.engine import _should_enqueue_discovered_folder

    assert _should_enqueue_discovered_folder("inbox", background=False) is True
    assert _should_enqueue_discovered_folder("inbox", background=True) is False
    assert _should_enqueue_discovered_folder("sent", background=False) is True
    assert _should_enqueue_discovered_folder("sent", background=True) is True
    assert _should_enqueue_discovered_folder(None, background=True) is True
