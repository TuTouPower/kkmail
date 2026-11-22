"""T082: sync requests converge by real work, never by phantom generations.

The p083 repro: a request arriving while its deduplicated job is CLAIMED used
to bind a pre-allocated *successor generation* that could vanish, producing
``execution_lost`` / "The bound sync execution no longer exists" although the
mail was already stored. These tests pin the new contract: every link points
at a real job, successors migrate links, and failures carry readable text.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.application.sync_requests import create_sync_request, get_sync_request_report
from mail_core.mail.domain.enums import JobStatus, JobType
from mail_core.mail.storage.models import (
    Account,
    Folder,
    SyncCheckpoint,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.sync.jobs import claim_jobs, complete_job, fail_job

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

WORKER = "w-t082"


def _seed():
    Session = get_session_factory()
    with Session() as s:
        acc = Account(email=f"t082-{uuid.uuid4().hex[:8]}@example.com", provider="imap", sync_enabled=True)
        s.add(acc)
        s.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        s.add(folder)
        s.flush()
        s.add(SyncCheckpoint(account_id=acc.id, folder_id=folder.id, cursor={"uid_next": 500},
                             uidvalidity=7, full_scan_complete=True))
        s.commit()
        return acc.id, folder.id


def _request(account_id, folder_id, tag):
    Session = get_session_factory()
    with Session() as s:
        req, _ = create_sync_request(
            s,
            client_request_id=f"t082-{tag}-{uuid.uuid4().hex}",
            mode="delta",
            trigger="manual",
            scope={"account_id": str(account_id), "folder_id": str(folder_id)},
            account_id=account_id,
            folder_id=folder_id,
        )
        s.commit()
        return req.id


def _report(request_id):
    Session = get_session_factory()
    with Session() as s:
        return get_sync_request_report(s, request_id)


def _claim_delta(account_id):
    Session = get_session_factory()
    with Session() as s:
        jobs = claim_jobs(s, worker_id=WORKER, limit=1,
                          job_types=[JobType.SYNC_FOLDER_DELTA.value], account_id=account_id)
        assert jobs
        job_id = jobs[0].id
        s.commit()
        return job_id


def _complete_delta(job_id):
    """Claim a pending job if needed, then complete its pass."""
    Session = get_session_factory()
    with Session() as s:
        job = s.get(WorkerJob, job_id)
        if job.status == JobStatus.PENDING.value:
            claimed = claim_jobs(s, worker_id=WORKER, limit=1,
                                 job_types=[JobType.SYNC_FOLDER_DELTA.value], account_id=job.account_id)
            assert claimed and claimed[0].id == job_id
            job = s.get(WorkerJob, job_id)
        successor = complete_job(s, job, worker_id=WORKER, result={"status": "ok", "exhausted": True})
        s.commit()
        return successor.id if successor is not None else None


def test_every_target_link_points_at_a_real_job():
    """No link may point at a pre-allocated, not-yet-created successor."""
    account_id, folder_id = _seed()
    _request(account_id, folder_id, "first")
    _claim_delta(account_id)
    _request(account_id, folder_id, "second")  # arrives while the job is CLAIMED
    Session = get_session_factory()
    with Session() as s:
        links = list(s.scalars(select(SyncRequestTargetJob)).all())
        assert len(links) >= 2
        for link in links:
            assert link.job_id is not None, "no link may point at a phantom successor"
            assert s.get(WorkerJob, link.job_id) is not None, "every link must point at a real job"


def test_claimed_job_request_completes_after_successor_pass():
    """p083: second request during a CLAIMED job must complete, not execution_lost."""
    account_id, folder_id = _seed()
    first = _request(account_id, folder_id, "first")
    claimed_job = _claim_delta(account_id)
    second = _request(account_id, folder_id, "second")

    successor = _complete_delta(claimed_job)
    assert successor is not None, "a request waiting on a claimed job needs one more pass"
    # Original request settles on the finished pass.
    assert _report(first).state == "complete"
    # The waiting request must still be open until its own covering pass runs.
    assert _report(second).state in ("queued", "running")

    _complete_delta(successor)
    report = _report(second)
    assert report.state == "complete", report.errors
    assert all(error.code != "execution_lost" for error in report.errors)


def test_terminal_job_failure_has_readable_message_not_internal_jargon():
    account_id, folder_id = _seed()
    request_id = _request(account_id, folder_id, "fail")
    claimed_job = _claim_delta(account_id)
    Session = get_session_factory()
    with Session() as s:
        job = s.get(WorkerJob, claimed_job)
        fail_job(s, job, "provider exploded", worker_id=WORKER, max_attempts=1)
        s.commit()

    report = _report(request_id)
    assert report.state == "failed"
    codes = {error.code for error in report.errors}
    assert "execution_lost" not in codes
    for error in report.errors:
        assert error.safe_message
        assert "no longer exists" not in error.safe_message.lower()


def test_transient_failure_then_retry_completes_request():
    account_id, folder_id = _seed()
    request_id = _request(account_id, folder_id, "retry")
    job_id = _claim_delta(account_id)

    Session = get_session_factory()
    with Session() as s:
        job = s.get(WorkerJob, job_id)
        fail_job(s, job, "transient provider error", worker_id=WORKER, max_attempts=5)
        s.commit()
    assert _report(request_id).state in ("queued", "running")
    assert _report(request_id).failed_count == 0

    # Backoff is stamped; a later claim sees the same job row and completes it.
    from datetime import timedelta

    Session = get_session_factory()
    with Session() as s:
        due = datetime.now(timezone.utc) + timedelta(seconds=5)
        claimed = claim_jobs(
            s, worker_id=WORKER, limit=1,
            job_types=[JobType.SYNC_FOLDER_DELTA.value], account_id=account_id, now=due,
        )
        assert claimed and claimed[0].id == job_id
        job = s.get(WorkerJob, job_id)
        complete_job(s, job, worker_id=WORKER, result={"status": "ok", "exhausted": True})
        s.commit()

    report = _report(request_id)
    assert report.state == "complete", report.errors
