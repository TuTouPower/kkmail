"""Worker outbox_dispatch_wake must NOTIFY, not mark_dispatched."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobStatus, JobType, OutboxEventType
from mail_core.mail.storage.models import OutboxEvent, WorkerJob
from mail_core.sync.jobs import claim_jobs, enqueue_job
from mail_core.worker.handlers import handle_job

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_outbox_wake_notifies_without_marking_dispatched():
    Session = get_session_factory()
    with Session() as session:
        row = OutboxEvent(event_type=OutboxEventType.SYNC_PROGRESS.value, payload={"wake": True})
        session.add(row)
        job = enqueue_job(session, job_type=JobType.OUTBOX_DISPATCH_WAKE.value, payload={})
        session.commit()
        eid, jid = int(row.id), job.id

    with Session() as session:
        jobs = claim_jobs(session, worker_id="wake-test", limit=1, job_types=[JobType.OUTBOX_DISPATCH_WAKE.value])
        assert len(jobs) == 1
        assert jobs[0].id == jid
        with patch("mail_core.realtime.notify.try_notify_outbox") as notify:
            with patch("mail_core.realtime.dispatcher.get_dispatcher") as gd:
                handle_job(session, jobs[0])
                session.commit()
                notify.assert_called_once()
                gd.assert_not_called()

    with Session() as session:
        row = session.get(OutboxEvent, eid)
        assert row is not None
        # REPLACED (migration 0026 contract): this block previously
        # asserted ``row.dispatched_at is None``. The dispatched_at column
        # was dropped by 20261026_0026 and OutboxEvent no longer carries
        # any dispatch marker (pinned by
        # test_outbox_retention_unit.test_outbox_model_dropped_dispatched_at_and_old_consumption_index);
        # consumers advance their own watermarks instead. Under the new
        # contract "the wake does not mark dispatched" means the wake
        # leaves the event row itself untouched -- still present with its
        # payload unchanged -- on top of the notify-once / dispatcher-
        # never-called assertions above.
        assert row.payload == {"wake": True}
        job = session.get(WorkerJob, jid)
        assert job is not None
        assert job.status == JobStatus.DONE.value
