"""Test on-demand message body sync and archive priority governance (t034 AC-001 ~ AC-005)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import ArchiveState, JobStatus, JobType, OutboxEventType
from mail_core.mail.storage.models import Account, Message, MessageArchiveState, MessageBody, OutboxEvent, WorkerJob
from tests.mail_core.conftest import TEST_API_KEY

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_unarchived_message() -> tuple[uuid.UUID, uuid.UUID]:
    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            email=f"ondemand-{uuid.uuid4().hex[:8]}@ex.com",
            provider="stub",
            credential_ref=f"ref-{uuid.uuid4().hex[:6]}",
        )
        session.add(acc)
        session.flush()

        msg = Message(
            account_id=acc.id,
            remote_id=f"remote-{uuid.uuid4().hex[:8]}",
            subject="Test On Demand Subject",
            from_address="sender@ex.com",
            from_name="Sender",
            to_addresses=["user@ex.com"],
            cc_addresses=[],
            sort_time=datetime(2018, 10, 26, 12, 0, 0, tzinfo=timezone.utc),
            is_read=False,
            has_attachments=False,
            snippet="Historical snippet",
        )
        session.add(msg)
        session.flush()

        st = MessageArchiveState(
            message_id=msg.id,
            state=ArchiveState.METADATA_SYNCED.value,
            priority=2,  # P2 older email
            retry_count=0,
        )
        session.add(st)
        session.commit()
        return acc.id, msg.id


def test_ac001_get_message_unarchived_is_read_only():
    acc_id, mid = _seed_unarchived_message()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    resp = client.get(f"/api/mail/messages/{mid}")
    assert resp.status_code == 200
    data = resp.json()
    assert not data["body"]
    assert data["parse_error"] is None

    Session = get_session_factory()
    with Session() as session:
        st = session.get(MessageArchiveState, mid)
        assert st is not None
        assert st.priority == 2, "GET must not change archive priority"

        job = session.scalars(
            select(WorkerJob)
            .where(
                WorkerJob.job_type == JobType.ARCHIVE_MIME_BATCH.value,
                WorkerJob.account_id == acc_id,
            )
            .order_by(WorkerJob.created_at.desc())
        ).first()
        assert job is None, "GET must not enqueue an archive job"


# A293 removes the old synchronous-response test; the endpoint now only accepts work,
# while the separate worker test below verifies archive completion.
def test_a293_post_sync_body_only_queues_archive_job():
    acc_id, mid = _seed_unarchived_message()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    with patch("mail_core.blobs.archive.run_archive_batch") as run_archive_batch:
        resp = client.post(f"/api/mail/messages/{mid}/sync-body")
        assert resp.status_code == 202
        data = resp.json()
        assert data["message_id"] == str(mid)
        assert data["status"] == "queued"
        assert data["job_id"]
        run_archive_batch.assert_not_called()

    Session = get_session_factory()
    with Session() as session:
        st = session.get(MessageArchiveState, mid)
        assert st.state == ArchiveState.ARCHIVE_PENDING.value
        assert st.priority == 0
        body = session.get(MessageBody, mid)
        assert body is None
        job = session.scalars(
            select(WorkerJob)
            .where(
                WorkerJob.job_type == JobType.ARCHIVE_MIME_BATCH.value,
                WorkerJob.account_id == acc_id,
                WorkerJob.status == "pending",
            )
            .order_by(WorkerJob.created_at.desc())
        ).first()
        assert job is not None
        assert str(job.id) == data["job_id"]
        assert job.priority == 10, "explicit POST body sync owns the priority boost"


def test_a293_worker_completes_queued_body_and_emits_status_events(tmp_path, monkeypatch):
    acc_id, mid = _seed_unarchived_message()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    accepted = client.post(f"/api/mail/messages/{mid}/sync-body")
    assert accepted.status_code == 202

    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    mock_provider = MagicMock()
    mock_provider.fetch_mime.return_value = (
        b"From: sender@ex.com\r\n"
        b"To: user@ex.com\r\n"
        b"Subject: Test On Demand Subject\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<div><p>Worker archived the full body.</p></div>"
    )
    from mail_core.blobs.archive import run_archive_batch

    with patch("mail_core.blobs.archive.build_provider", return_value=mock_provider):
        result = run_archive_batch(
            account_id=acc_id,
            worker_id="test-on-demand-worker",
            payload={"message_id": str(mid), "batch_size": 1},
        )

    assert result["status"] == "ok"
    assert result["completed"] == 1
    detail = client.get(f"/api/mail/messages/{mid}").json()
    assert detail["is_archived"] is True
    assert detail["archive_state"] == ArchiveState.ARCHIVE_COMPLETE.value
    assert detail["archive_has_error"] is False
    assert "Worker archived the full body." in detail["body"]

    with get_session_factory()() as session:
        events = session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == OutboxEventType.ARCHIVE_PROGRESS.value)
        ).all()
        target_states = [
            event.payload.get("state")
            for event in events
            if event.payload.get("message_id") == str(mid)
        ]
    assert target_states == [
        ArchiveState.ARCHIVE_IN_PROGRESS.value,
        ArchiveState.ARCHIVE_COMPLETE.value,
    ]


@pytest.mark.parametrize(
    "initial_state",
    [ArchiveState.ARCHIVE_FAILED, ArchiveState.ARCHIVE_PAUSED_QUOTA, ArchiveState.ARCHIVE_PENDING],
)
# A293 removes the old request-time retry/completion test. Retry requests now only
# clear retry state and queue a job; worker outcomes are covered separately.
def test_a293_sync_body_requeues_retryable_archive_state(initial_state):
    _, mid = _seed_unarchived_message()
    Session = get_session_factory()
    with Session() as session:
        state = session.get(MessageArchiveState, mid)
        assert state is not None
        state.state = initial_state.value
        state.retry_count = 5
        state.last_error = "previous attempt failed"
        state.pause_reason = "quota" if initial_state == ArchiveState.ARCHIVE_PAUSED_QUOTA else None
        session.commit()

    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    with patch("mail_core.blobs.archive.run_archive_batch") as run_archive_batch:
        response = client.post(f"/api/mail/messages/{mid}/sync-body")
        run_archive_batch.assert_not_called()

    assert response.status_code == 202
    with Session() as session:
        state = session.get(MessageArchiveState, mid)
        assert state is not None
        assert state.state == ArchiveState.ARCHIVE_PENDING.value
        assert state.retry_count == 0
        assert state.last_error is None
        assert state.pause_reason is None
        job = session.scalar(select(WorkerJob).where(WorkerJob.dedupe_key == f"archive_msg:{mid}"))
        assert job is not None
        assert job.priority == 10


# A293 removes the old inline quota-pause test; this verifies only that an explicit
# retry requeues a quota-paused message for the Worker.
def test_a293_sync_body_requeues_quota_paused_archive():
    _, mid = _seed_unarchived_message()
    Session = get_session_factory()
    with Session() as session:
        state = session.get(MessageArchiveState, mid)
        assert state is not None
        state.state = ArchiveState.ARCHIVE_PAUSED_QUOTA.value
        state.retry_count = 5
        state.pause_reason = "quota"
        session.commit()

    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    with patch("mail_core.blobs.archive.run_archive_batch") as run_archive_batch:
        response = client.post(f"/api/mail/messages/{mid}/sync-body")
        run_archive_batch.assert_not_called()

    assert response.status_code == 202
    with Session() as session:
        state = session.get(MessageArchiveState, mid)
        assert state is not None
        assert state.state == ArchiveState.ARCHIVE_PENDING.value
        assert state.retry_count == 0
        assert state.pause_reason is None
        assert state.claimed_by is None
        assert state.claimed_at is None


def test_ac003_worker_jobs_priority_governance():
    from mail_core.sync.delta import sync_folder_delta
    from mail_core.blobs.archive import run_archive_batch

    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            email=f"priority-{uuid.uuid4().hex[:8]}@ex.com",
            provider="stub",
            credential_ref="stub",
        )
        session.add(acc)
        session.flush()

        from mail_core.mail.storage.models import Folder, SyncCheckpoint
        folder = Folder(
            account_id=acc.id,
            remote_id="INBOX",
            name="INBOX",
            role="inbox",
        )
        session.add(folder)
        session.flush()

        cp = SyncCheckpoint(
            account_id=acc.id,
            folder_id=folder.id,
            full_scan_complete=True,
            uidvalidity=12345,
            cursor={"max_uid": 10},
        )
        session.add(cp)
        session.commit()
        fid = folder.id
        aid = acc.id

    # 验证 delta 轮询任务入队的优先级与去重键
    from mail_core.providers.base import DeltaPage
    mock_prov = MagicMock()
    mock_prov.delta_changes.return_value = DeltaPage(
        changes=[],
        next_cursor={"max_uid": 10},
        exhausted=True,
    )
    with patch("mail_core.sync.delta.build_provider", return_value=mock_prov):
        res = sync_folder_delta(account_id=aid, folder_id=fid, worker_id="test-worker")
        assert res["status"] == "ok"

    with Session() as session:
        delta_job = session.scalars(
            select(WorkerJob)
            .where(
                WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
                WorkerJob.account_id == aid,
                WorkerJob.status == JobStatus.PENDING.value,
            )
        ).first()
        assert delta_job is not None
        assert delta_job.priority == 75, "routine delta polling priority should be 75"
        assert delta_job.dedupe_key == f"delta:{aid}:{fid}", "delta polling should have dedupe_key"


# A293 removes the old request-time failure test because provider I/O now belongs to
# the Worker; this test checks persisted status after a Worker attempt.
def test_a293_worker_failure_visible_in_message_status():
    """A worker fetch error is visible in message status and never becomes a MIME parse error."""
    acc_id, mid = _seed_unarchived_message()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    mock_provider = MagicMock()
    mock_provider.fetch_mime.side_effect = RuntimeError("Remote IMAP server timeout (simulated)")

    resp = client.post(f"/api/mail/messages/{mid}/sync-body")
    assert resp.status_code == 202

    from mail_core.blobs.archive import run_archive_batch

    with patch("mail_core.blobs.archive.build_provider", return_value=mock_provider):
        result = run_archive_batch(
            account_id=acc_id,
            worker_id="test-on-demand-failure",
            payload={"message_id": str(mid), "batch_size": 1},
        )
    assert result["status"] == "ok"
    assert result["failed"] == 1

    detail = client.get(f"/api/mail/messages/{mid}").json()
    assert detail["parse_error"] is None
    assert detail["is_archived"] is False
    assert detail["archive_has_error"] is True

    Session = get_session_factory()
    with Session() as session:
        st = session.get(MessageArchiveState, mid)
        assert st is not None
        assert st.last_error is not None
        assert "Remote IMAP server timeout" in st.last_error

        body = session.get(MessageBody, mid)
        if body is not None:
            assert body.parse_error is None
        events = session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == OutboxEventType.ARCHIVE_PROGRESS.value)
        ).all()
        target_failure = [
            event.payload
            for event in events
            if event.payload.get("message_id") == str(mid)
            and event.payload.get("has_error") is True
        ]
        assert target_failure


# A293 replaces the old unique inline worker-id test: request calls must coalesce
# against one queued Worker job and must not execute the archive function.
def test_a293_repeated_sync_body_requests_deduplicate_active_job():
    """Repeated requests coalesce with the pending job and never run archive inline."""
    _, mid = _seed_unarchived_message()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    with patch("mail_core.blobs.archive.run_archive_batch") as run_archive_batch:
        responses = [client.post(f"/api/mail/messages/{mid}/sync-body") for _ in range(2)]

    assert [response.status_code for response in responses] == [202, 202]
    assert responses[0].json()["job_id"] == responses[1].json()["job_id"]
    run_archive_batch.assert_not_called()


def test_p039_archive_batch_releases_claims_on_fencing_mismatch():
    """Fencing mismatch during archive must restore claimed items to ARCHIVE_PENDING (p039)."""
    acc_id, mid = _seed_unarchived_message()
    from mail_core.blobs.archive import run_archive_batch
    from mail_core.sync.leases import FencingMismatch

    sample_mime = b"From: a@b.c\r\n\r\nHello"
    mock_provider = MagicMock()
    mock_provider.fetch_mime.return_value = sample_mime

    # Simulate fencing token mismatch during the post-fetch commit assert_fencing check
    with patch("mail_core.blobs.archive.build_provider", return_value=mock_provider):
        with patch("mail_core.blobs.archive.assert_fencing", side_effect=[None, FencingMismatch("expired token")]):
            res = run_archive_batch(
                account_id=acc_id,
                worker_id="test-fencing-worker",
                payload={"message_id": str(mid), "batch_size": 1},
            )
            assert res["status"] == "fencing_mismatch"

    Session = get_session_factory()
    with Session() as session:
        st = session.get(MessageArchiveState, mid)
        assert st is not None
        # Must NOT remain stuck in ARCHIVE_IN_PROGRESS with claimed_by held!
        assert st.claimed_by is None, "claimed_by must be released on fencing mismatch"
        assert st.state == ArchiveState.ARCHIVE_PENDING.value, "state must be restored to ARCHIVE_PENDING"


def test_sync_body_idempotent_when_already_complete_or_in_progress():
    """p048: On-demand sync is idempotent; returns 200 complete or 202 in_progress without 409 conflict."""
    _, mid = _seed_unarchived_message()
    Session = get_session_factory()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    # 1. Test in_progress status
    with Session() as session:
        state = session.get(MessageArchiveState, mid)
        assert state is not None
        state.state = ArchiveState.ARCHIVE_IN_PROGRESS.value
        state.claimed_by = "active-worker-99"
        session.commit()

    resp_in_progress = client.post(f"/api/mail/messages/{mid}/sync-body")
    assert resp_in_progress.status_code == 202
    data_ip = resp_in_progress.json()
    assert data_ip["status"] == "in_progress"
    assert data_ip.get("job_id") is None

    # Verify claim was NOT trampled
    with Session() as session:
        state = session.get(MessageArchiveState, mid)
        assert state.claimed_by == "active-worker-99"

    # 2. Test already complete status
    with Session() as session:
        state = session.get(MessageArchiveState, mid)
        state.state = ArchiveState.ARCHIVE_COMPLETE.value
        state.claimed_by = None
        session.commit()

    resp_complete = client.post(f"/api/mail/messages/{mid}/sync-body")
    assert resp_complete.status_code == 200
    data_done = resp_complete.json()
    assert data_done["status"] == "complete"
    assert data_done.get("job_id") is None
