"""Chaos: worker dies mid-job → lease steal + stale claim reclaim."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobStatus
from mail_core.mail.storage import Account, AccountSyncLease, Folder
from mail_core.sync import (
    FencingMismatch,
    LeaseBusy,
    acquire_lease,
    assert_fencing,
    claim_jobs,
    enqueue_job,
    reclaim_stale_claims,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _account(session):
    acc = Account(email=f"chaos-{uuid.uuid4().hex[:10]}@example.com", provider="imap")
    session.add(acc)
    session.flush()
    session.add(Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox"))
    session.flush()
    return acc


def test_worker_kill_allows_lease_steal_and_rejects_stale_fencing():
    Session = get_session_factory()
    with Session() as session:
        acc = _account(session)
        lease = acquire_lease(session, account_id=acc.id, owner_id="worker-dead", ttl=timedelta(seconds=30))
        session.commit()
        account_id = acc.id
        stale_token = lease.fencing_token

    # Survivor cannot steal while lease is fresh
    with Session() as session:
        with pytest.raises(LeaseBusy):
            acquire_lease(session, account_id=account_id, owner_id="worker-alive", ttl=timedelta(seconds=30))
        session.rollback()

    # Simulate SIGKILL: lease expires without release_lease
    with Session() as session:
        row = session.get(AccountSyncLease, account_id)
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    with Session() as session:
        lease2 = acquire_lease(session, account_id=account_id, owner_id="worker-alive", ttl=timedelta(seconds=60))
        session.commit()
        assert lease2.fencing_token > stale_token

    with Session() as session:
        with pytest.raises(FencingMismatch):
            assert_fencing(session, account_id=account_id, fencing_token=stale_token)
        assert_fencing(session, account_id=account_id, fencing_token=lease2.fencing_token)


def test_stale_claimed_job_reclaimed_after_worker_death():
    Session = get_session_factory()
    with Session() as session:
        acc = _account(session)
        enqueue_job(session, job_type="sync_folder_metadata", account_id=acc.id, payload={"folder_id": "x"})
        session.commit()
        account_id = acc.id

    with Session() as session:
        claimed = claim_jobs(session, worker_id="worker-dead", limit=1, account_id=account_id)
        assert len(claimed) == 1
        job_id = claimed[0].id
        # Backdate lock as if worker died hours ago
        claimed[0].locked_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.commit()

    with Session() as session:
        n = reclaim_stale_claims(session, older_than=timedelta(minutes=5))
        session.commit()
        assert n >= 1
        from mail_core.mail.storage.models import WorkerJob

        job = session.get(WorkerJob, job_id)
        assert job.status == JobStatus.PENDING.value
        assert job.locked_by is None

    with Session() as session:
        again = claim_jobs(session, worker_id="worker-alive", limit=1, account_id=account_id)
        session.commit()
        assert len(again) == 1
        assert again[0].id == job_id
        assert again[0].locked_by == "worker-alive"
