from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from mail_core.db.session import get_session_factory
from mail_core.mail.application.mutations import mark_all_messages_read, set_message_read
from mail_core.mail.application.queries import unified_inbox
from mail_core.mail.application.remote_ops import (
    enqueue_remote_operation,
    mark_remote_operation,
)
from mail_core.mail.domain.enums import JobStatus, JobType, RemoteOperationStatus
from mail_core.mail.storage.models import (
    Account,
    Folder,
    FolderStats,
    Message,
    MessageLocation,
    RemoteOperation,
    WorkerJob,
)
from mail_core.providers.base import DeltaChange, DeltaPage, MetadataPage, RemoteMessageMeta
from mail_core.sync.delta import apply_delta_page
from mail_core.sync.jobs import claim_jobs, complete_job, enqueue_job
from mail_core.sync.leases import acquire_lease
from mail_core.sync.metadata import apply_metadata_page
from mail_core.sync.remote_push import (
    get_unconverged_field_intents,
    push_remote_operations,
    reconcile_account_writeback_and_stats,
)
from mail_core.worker.handlers import handle_job

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


# --- AC-001: 超过一批（>20条）自动续跑与自然收敛 ---


def test_ac001_multi_batch_mark_read_auto_convergence(monkeypatch):
    from mail_core.db.session import get_session_factory
    from mail_core.providers.base import RemoteOperationResult

    class FakeBatchPushProvider:
        def __init__(self):
            self.applied = []

        def apply_remote_operation(self, op_type, desired):
            self.applied.append(desired)
            return RemoteOperationResult(success=True)

    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"conv-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()

        # Create 26 unread messages (> default batch limit of 20)
        messages = []
        for i in range(26):
            m = Message(
                account_id=acc.id,
                remote_id=f"msg-{i:02d}",
                subject=f"Batch {i}",
                from_address="a@b.c",
                sort_time=datetime(2026, 10, 21, 10, i, tzinfo=timezone.utc),
                is_read=False,
            )
            session.add(m)
            session.flush()
            session.add(MessageLocation(message_id=m.id, folder_id=folder.id, uid=i + 1))
            messages.append(m)
        session.commit()

        # Execute "mark all read" -> creates 26 pending remote operations and 1 WorkerJob
        batch = mark_all_messages_read(session, account_id=acc.id)
        session.commit()
        assert batch.count == 26
        assert batch.last_message_id is not None

        # Wire fake provider
        fake_provider = FakeBatchPushProvider()
        from mail_core.sync import remote_push

        monkeypatch.setattr(remote_push, "build_provider", lambda *args, **kwargs: fake_provider)

        # Worker loop 1: Claim first job
        jobs_round1 = claim_jobs(session, worker_id="w1", limit=1)
        assert len(jobs_round1) == 1
        job1 = jobs_round1[0]
        assert job1.status == JobStatus.CLAIMED.value

        # Handle job 1 (pushes 20 operations)
        ok1 = handle_job(session, job1, worker_id="w1")
        session.commit()
        assert ok1 is True
        assert len(fake_provider.applied) == 20

        # CRITICAL ASSERTION: After job 1 completes, a follow-up job MUST be automatically PENDING!
        # (Without any manual secondary call to push)
        followup_job = session.scalar(
            select(WorkerJob)
            .where(WorkerJob.account_id == acc.id)
            .where(WorkerJob.status == JobStatus.PENDING.value)
            .where(WorkerJob.dedupe_key == f"remote-op-push:{acc.id}")
        )
        assert followup_job is not None, "Follow-up job was swallowed by claimed job!"

        # Worker loop 2: Claim follow-up job
        jobs_round2 = claim_jobs(session, worker_id="w1", limit=1)
        assert len(jobs_round2) == 1
        job2 = jobs_round2[0]
        assert job2.id == followup_job.id

        ok2 = handle_job(session, job2, worker_id="w1")
        session.commit()
        assert ok2 is True
        assert len(fake_provider.applied) == 26

        # Now all 26 operations are DONE, and no orphan pending jobs remain
        pending_ops = session.scalars(
            select(RemoteOperation)
            .where(RemoteOperation.account_id == acc.id)
            .where(RemoteOperation.status == RemoteOperationStatus.PENDING.value)
        ).all()
        assert len(pending_ops) == 0


# --- AC-004 & AC-005: 本地意图保护 vs 远端正常同步 ---


def test_ac004_ac005_local_intent_protection_and_convergence():
    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"prot-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()

        msg = Message(
            account_id=acc.id,
            remote_id="msg-protected",
            subject="Original Subject",
            from_address="sender@test.com",
            sort_time=datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc),
            is_read=True,  # User marked as read locally
            is_flagged=False,
        )
        session.add(msg)
        session.flush()
        session.add(MessageLocation(message_id=msg.id, folder_id=folder.id, uid=10))
        session.commit()

        # Active pending local read operation
        op = enqueue_remote_operation(
            session,
            account_id=acc.id,
            entity_key=f"msg:{msg.remote_id}:read",
            op_type="mark_read",
            desired_state={"is_read": True},
        )
        session.commit()

        lease = acquire_lease(session, account_id=acc.id, owner_id="w1", ttl=timedelta(minutes=5))

        # 1. AC-004: Inbound metadata sync with stale is_read=False
        page_stale_meta = MetadataPage(
            items=[
                RemoteMessageMeta(
                    remote_id="msg-protected",
                    subject="Updated Remote Subject",  # Other fields should still update
                    from_address="sender@test.com",
                    from_name="Sender Name",
                    sort_time=datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc),
                    is_read=False,  # Stale remote says False
                    has_attachments=False,
                    uid=10,
                )
            ],
            next_cursor={"uid_next": 11, "uidvalidity": 1},
            exhausted=True,
        )
        apply_metadata_page(session, account_id=acc.id, folder_id=folder.id, fencing_token=lease.fencing_token, page=page_stale_meta)
        session.commit()

        # Verify msg.is_read was PROTECTED (still True), but subject updated to "Updated Remote Subject"
        m_after_meta = session.get(Message, msg.id)
        assert m_after_meta.is_read is True
        assert m_after_meta.subject == "Updated Remote Subject"

        # 2. AC-004: Inbound delta flag change with stale is_read=False
        page_stale_delta = DeltaPage(
            changes=[
                DeltaChange(kind="flag", remote_id="msg-protected", flags={"is_read": False})
            ],
            next_cursor={"modseq": 100},
            exhausted=True,
        )
        apply_delta_page(session, account_id=acc.id, folder_id=folder.id, fencing_token=lease.fencing_token, page=page_stale_delta)
        session.commit()

        # Still protected!
        m_after_delta = session.get(Message, msg.id)
        assert m_after_delta.is_read is True

        # 3. AC-005: When operation completes and grace period passes, genuine remote changes sync normally
        mark_remote_operation(session, op, status=RemoteOperationStatus.DONE)
        # Artificially age the operation past the grace period (e.g. 70s ago)
        op.updated_at = datetime.now(timezone.utc) - timedelta(seconds=70)
        session.commit()

        # Inbound remote change now marks as unread from another client
        page_new_delta = DeltaPage(
            changes=[
                DeltaChange(kind="flag", remote_id="msg-protected", flags={"is_read": False})
            ],
            next_cursor={"modseq": 101},
            exhausted=True,
        )
        apply_delta_page(session, account_id=acc.id, folder_id=folder.id, fencing_token=lease.fencing_token, page=page_new_delta)
        session.commit()

        m_converged = session.get(Message, msg.id)
        assert m_converged.is_read is False, "Genuine remote update was blocked after intent was converged!"


# --- AC-006: 预先存在 FolderStats 行时，autoflush=False 会话计数一致性 ---


def test_ac006_existing_folder_stats_flush_order_consistency():
    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"stats-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()

        m = Message(
            account_id=acc.id,
            remote_id="msg-stats-1",
            subject="Test Stats",
            from_address="a@b.c",
            sort_time=datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc),
            is_read=False,
        )
        session.add(m)
        session.flush()
        session.add(MessageLocation(message_id=m.id, folder_id=folder.id, uid=1))

        # Explicitly create pre-existing FolderStats with unread_count=1
        stats = FolderStats(folder_id=folder.id, total_count=1, unread_count=1)
        session.add(stats)
        session.commit()

        # Now apply flag patch in a session where autoflush is False
        lease = acquire_lease(session, account_id=acc.id, owner_id="w1", ttl=timedelta(minutes=5))
        page = DeltaPage(
            changes=[DeltaChange(kind="flag", remote_id="msg-stats-1", flags={"is_read": True})],
            next_cursor={"modseq": 200},
            exhausted=True,
        )
        apply_delta_page(session, account_id=acc.id, folder_id=folder.id, fencing_token=lease.fencing_token, page=page)
        session.commit()

        # Open completely new session to verify disk catalog
        with Session() as new_session:
            updated_stats = new_session.get(FolderStats, folder.id)
            assert updated_stats.unread_count == 0, f"Expected 0 unread, got {updated_stats.unread_count} due to pre-flush aggregation bug!"
            assert updated_stats.total_count == 1


# --- AC-007: 孤儿 pending 写回与失真统计安全恢复 ---


def test_ac007_orphan_pending_and_drift_recovery():
    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"rec-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()

        m = Message(
            account_id=acc.id,
            remote_id="msg-drift",
            subject="Drift Subject",
            from_address="a@b.c",
            sort_time=datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc),
            is_read=True,
        )
        session.add(m)
        session.flush()
        session.add(MessageLocation(message_id=m.id, folder_id=folder.id, uid=1))

        # Simulating drift: message is read=True, but FolderStats says unread=5
        session.add(FolderStats(folder_id=folder.id, total_count=1, unread_count=5))

        # Simulating orphan pending op: pending op exists, but NO WorkerJob exists
        op = RemoteOperation(
            account_id=acc.id,
            entity_key=f"msg:{m.remote_id}:read",
            op_type="mark_read",
            desired_state={"is_read": True},
            status=RemoteOperationStatus.PENDING.value,
        )
        session.add(op)
        session.commit()

        # Run recovery on this account
        res = reconcile_account_writeback_and_stats(session, account_id=acc.id)
        session.commit()

        assert res["pending_ops"] == 1
        assert res["enqueued_jobs"] == 1

        # Check job was enqueued
        job = session.scalar(
            select(WorkerJob)
            .where(WorkerJob.account_id == acc.id)
            .where(WorkerJob.status == JobStatus.PENDING.value)
        )
        assert job is not None

        # Check stats were recalculated to exact truth (unread=0)
        recomputed = session.get(FolderStats, folder.id)
        assert recomputed.unread_count == 0

        # Run recovery a second time: must be idempotent, not creating duplicate jobs
        res2 = reconcile_account_writeback_and_stats(session, account_id=acc.id)
        session.commit()
        assert res2["enqueued_jobs"] == 0
        jobs_count = session.scalar(
            select(func.count(WorkerJob.id)).where(WorkerJob.account_id == acc.id)
        )
        assert jobs_count == 1
