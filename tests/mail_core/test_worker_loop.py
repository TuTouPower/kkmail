import os
import threading
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from mail_core.worker import main as worker_main

pytestmark_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_worker_stops_on_flag():
    def run():
        worker_main.run(poll_interval_s=0.05)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(0.12)
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

    with patch("mail_core.realtime.notify.try_notify_outbox"):
        handled = worker_main._tick("test-worker-iso")
    assert handled >= 2

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
        n = worker_main._tick("w-fail-count")
    assert n == 0
