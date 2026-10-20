"""Lease fencing + SKIP LOCKED job claim against live Postgres."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from mail_core.db.session import get_session_factory
from mail_core.mail.storage import Account, AccountSyncLease, Folder, SyncCheckpoint
from mail_core.sync import (
    FencingMismatch,
    LeaseBusy,
    acquire_lease,
    claim_jobs,
    commit_checkpoint,
    enqueue_job,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _account(session):
    acc = Account(email=f"sync-{uuid.uuid4().hex[:10]}@example.com", provider="imap")
    session.add(acc)
    session.flush()
    folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
    session.add(folder)
    session.flush()
    return acc, folder


def test_skip_locked_claim_exclusive():
    Session = get_session_factory()
    with Session() as s1:
        acc, _ = _account(s1)
        enqueue_job(s1, job_type="sync_account_folders", account_id=acc.id)
        enqueue_job(s1, job_type="sync_account_folders", account_id=acc.id)
        s1.commit()
        account_id = acc.id

    with Session() as s_a, Session() as s_b:
        claimed_a = claim_jobs(s_a, worker_id="wa", limit=1, account_id=account_id)
        claimed_b = claim_jobs(s_b, worker_id="wb", limit=2, account_id=account_id)
        assert len(claimed_a) == 1
        # Second transaction skips the row locked by s_a
        assert len(claimed_b) == 1
        assert claimed_a[0].id != claimed_b[0].id
        s_a.commit()
        s_b.commit()


def test_fencing_rejects_stale_checkpoint_commit():
    Session = get_session_factory()
    with Session() as session:
        acc, folder = _account(session)
        lease_a = acquire_lease(session, account_id=acc.id, owner_id="worker-a", ttl=timedelta(seconds=60))
        session.commit()
        token_a = lease_a.fencing_token
        account_id, folder_id = acc.id, folder.id

    with Session() as session:
        row = session.get(AccountSyncLease, account_id)
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    with Session() as session:
        lease_b = acquire_lease(session, account_id=account_id, owner_id="worker-b", ttl=timedelta(seconds=60))
        session.commit()
        token_b = lease_b.fencing_token
        assert token_b > token_a

    with Session() as session:
        with pytest.raises(FencingMismatch):
            commit_checkpoint(
                session,
                account_id=account_id,
                folder_id=folder_id,
                fencing_token=token_a,
                cursor={"page": 1},
            )
        session.rollback()

    with Session() as session:
        commit_checkpoint(
            session,
            account_id=account_id,
            folder_id=folder_id,
            fencing_token=token_b,
            cursor={"page": 2},
            full_scan_complete=False,
        )
        session.commit()
        cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
        assert cp.cursor["page"] == 2
        assert cp.fencing_token == token_b


def test_lease_busy_while_held():
    Session = get_session_factory()
    with Session() as session:
        acc, _ = _account(session)
        acquire_lease(session, account_id=acc.id, owner_id="owner-1", ttl=timedelta(minutes=5))
        session.commit()
        account_id = acc.id
    with Session() as session:
        with pytest.raises(LeaseBusy):
            acquire_lease(session, account_id=account_id, owner_id="owner-2", ttl=timedelta(minutes=5))
