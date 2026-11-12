"""Full-scan reuse must cover the metadata phase, not only discovery.

``_inflight_full_root_generation`` only looked at the folder-discovery
job (``sync:{account_id}``). Once discovery completes, that job is DONE
while the scan continues in per-folder metadata jobs
(``metadata:{account_id}:{folder_id}``, payload carrying the root
``scan_generation``). A full request issued in that window found no
in-flight generation, allocated a NEW root generation and forced a
second full scan with a cursor reset, instead of observing the scan
already in progress.

Pinned here on PostgreSQL: after discovery is DONE and a metadata
job is still PENDING, a second full request reuses the in-flight root
generation; once the metadata job is DONE too, the helper reports no
in-flight generation.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.application.sync_requests import (
    _inflight_full_root_generation,
    create_sync_request,
)
from mail_core.mail.domain.enums import JobStatus, JobType
from mail_core.mail.storage.models import Account, SyncRequestTarget, WorkerJob

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


def _create_full_request(Session, account_id: uuid.UUID) -> uuid.UUID:
    with Session() as session:
        req, created = create_sync_request(
            session,
            client_request_id=f"meta-reuse-{uuid.uuid4().hex}",
            mode="full",
            trigger="manual",
            scope={"account_id": str(account_id)},
            account_id=account_id,
        )
        assert created
        session.commit()
        return req.id


def _requested_generation(Session, request_id: uuid.UUID) -> uuid.UUID:
    with Session() as session:
        target = session.scalar(
            select(SyncRequestTarget).where(SyncRequestTarget.request_id == request_id)
        )
        assert target is not None
        return target.requested_generation


def test_full_request_reuses_root_generation_while_metadata_in_flight():
    Session = get_session_factory()
    account_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    with Session() as session:
        session.add(
            Account(
                id=account_id,
                email=f"meta-reuse-{uuid.uuid4().hex[:8]}@example.com",
                provider="imap",
                credential_ref=None,
                sync_enabled=True,
                config={},
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()

    first_id = _create_full_request(Session, account_id)
    root_generation = _requested_generation(Session, first_id)

    # Discovery completes; the scan continues in a per-folder metadata
    # job carrying the root generation (the engine's enqueue shape).
    with Session() as session:
        discovery = session.scalar(
            select(WorkerJob).where(WorkerJob.dedupe_key == f"sync:{account_id}")
        )
        assert discovery is not None
        discovery.status = JobStatus.DONE.value
        session.add(
            WorkerJob(
                id=uuid.uuid4(),
                execution_generation=uuid.uuid4(),
                job_type=JobType.SYNC_FOLDER_METADATA.value,
                account_id=account_id,
                dedupe_key=f"metadata:{account_id}:{folder_id}",
                payload={
                    "folder_id": str(folder_id),
                    "full": True,
                    "scan_generation": str(root_generation),
                    "request_id": str(first_id),
                },
                status=JobStatus.PENDING.value,
                run_after=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()

    with Session() as session:
        assert _inflight_full_root_generation(session, account_id) == root_generation

    second_id = _create_full_request(Session, account_id)
    assert _requested_generation(Session, second_id) == root_generation, (
        "second full request allocated a new root generation although the "
        "first scan's metadata phase is still in flight"
    )

    # Once the metadata job AND the second request's own discovery job
    # are done too, nothing is in flight anymore.
    with Session() as session:
        for job in session.scalars(select(WorkerJob).where(WorkerJob.account_id == account_id)).all():
            job.status = JobStatus.DONE.value
        session.commit()
    with Session() as session:
        assert _inflight_full_root_generation(session, account_id) is None
