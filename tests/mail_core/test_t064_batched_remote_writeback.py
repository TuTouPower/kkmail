"""Unit and integration tests for t064: Batched remote writeback."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import func, select

from mail_core.accounts.credentials import DictCredentialStore
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobStatus, JobType, RemoteOperationStatus
from mail_core.mail.storage.models import Account, RemoteOperation, WorkerJob
from mail_core.providers.base import RemoteOperationItem, RemoteOperationResult
from mail_core.providers.connection_slots import TrafficClass
from mail_core.providers.graph import GraphProvider
from mail_core.providers.imap import ImapProvider, format_imap_remote_id
from mail_core.providers.remote_writeback import compress_uids, compress_uids_chunked
from mail_core.mail.application.remote_ops import enqueue_remote_operation
from mail_core.sync.leases import FencingMismatch, acquire_lease
from mail_core.sync.remote_push import push_remote_operations

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


class RecordingImapClient:
    """Mock IMAP client recording commands and returning configurable responses."""

    def __init__(self, uidvalidity: int = 12345) -> None:
        self.uidvalidity = uidvalidity
        self.select_calls: list[str] = []
        self.store_calls: list[tuple[str, str, str]] = []
        self.move_calls: list[tuple[str, str]] = []
        self.fetch_calls: list[tuple[str, str]] = []
        self.existing_uids: set[int] = set()
        self.seen_uids: set[int] = set()
        self.flagged_uids: set[int] = set()
        self.copyuid_responses: list[str] = []
        self.fail_store = False
        self.fail_select_for: set[str] = set()

    def select(self, mailbox: str) -> tuple[str, list]:
        clean = mailbox.strip('"')
        self.select_calls.append(clean)
        if clean in self.fail_select_for:
            return "NO", [b"Mailbox does not exist"]
        return "OK", [b"100"]

    def status(self, mailbox: str, names: str) -> tuple[str, list]:
        clean = mailbox.strip('"')
        return "OK", [f'"{clean}" (UIDVALIDITY {self.uidvalidity})'.encode()]

    def response(self, name: str) -> tuple[str, list]:
        if name == "COPYUID" and self.copyuid_responses:
            resp = self.copyuid_responses
            self.copyuid_responses = []  # real imaplib pops untagged responses on read
            return "OK", [r.encode() for r in resp]
        return "NO", []

    def uid(self, command: str, *args: str) -> tuple[str, list]:
        cmd = command.upper()
        if cmd == "STORE":
            uid_set, flag_op, flag_val = args
            self.store_calls.append((uid_set, flag_op, flag_val))
            if self.fail_store:
                return "NO", [b"Store failed"]

            # Parse UIDs in set
            target_uids = []
            for part in uid_set.split(","):
                if ":" in part:
                    s, e = map(int, part.split(":"))
                    target_uids.extend(range(s, e + 1))
                else:
                    target_uids.append(int(part))

            res = []
            for u in target_uids:
                if u in self.existing_uids:
                    if "\\Seen" in flag_val:
                        if flag_op.startswith("+"):
                            self.seen_uids.add(u)
                        else:
                            self.seen_uids.discard(u)
                    if "\\Flagged" in flag_val:
                        if flag_op.startswith("+"):
                            self.flagged_uids.add(u)
                        else:
                            self.flagged_uids.discard(u)

                    flags = []
                    if u in self.seen_uids:
                        flags.append(r"\Seen")
                    if u in self.flagged_uids:
                        flags.append(r"\Flagged")
                    flags_str = " ".join(flags)
                    res.append(f"{u} (FLAGS ({flags_str}) UID {u})".encode())
            return "OK", res

        elif cmd == "MOVE":
            uid_set, dest = args
            self.move_calls.append((uid_set, dest))
            return "OK", [b"Move completed"]

        elif cmd == "FETCH":
            uid_set, items = args
            self.fetch_calls.append((uid_set, items))
            target_uids = []
            for part in uid_set.split(","):
                if ":" in part:
                    s, e = map(int, part.split(":"))
                    target_uids.extend(range(s, e + 1))
                else:
                    target_uids.append(int(part))
            res = []
            for u in target_uids:
                if u in self.existing_uids:
                    flags = []
                    if u in self.seen_uids:
                        flags.append(r"\Seen")
                    if u in self.flagged_uids:
                        flags.append(r"\Flagged")
                    flags_str = " ".join(flags)
                    res.append(f"{u} (FLAGS ({flags_str}) UID {u})".encode())
            return "OK", res

        return "NO", [b"Unsupported command"]


def _make_account(session) -> Account:
    aid = uuid.uuid4()
    acc = Account(
        id=aid,
        email=f"acc-{aid.hex[:8]}@example.com",
        provider="imap",
        sync_enabled=True,
    )
    session.add(acc)
    session.commit()
    return acc


def test_ac001_ac002_imap_batching_single_connection_and_grouped_commands():
    """AC-001, AC-002: Operations in same folder batch into single connection and STORE command; multiple folders select once each."""
    client = RecordingImapClient(uidvalidity=100)
    for u in range(1, 10):
        client.existing_uids.add(u)

    provider = ImapProvider("acc@test.com", "host", 993, "acc@test.com", "pass")
    connect_count = 0

    def mock_connect(*args, **kwargs):
        nonlocal connect_count
        connect_count += 1
        return client, None

    provider._connect_with_permit = mock_connect
    provider._close_client = lambda c, p: None

    ops = [
        # 3 mark_read in INBOX
        RemoteOperationItem(op_id=uuid.uuid4(), op_type="mark_read", desired_state={"remote_id": format_imap_remote_id("INBOX", 100, 1), "is_read": True}),
        RemoteOperationItem(op_id=uuid.uuid4(), op_type="mark_read", desired_state={"remote_id": format_imap_remote_id("INBOX", 100, 2), "is_read": True}),
        RemoteOperationItem(op_id=uuid.uuid4(), op_type="mark_read", desired_state={"remote_id": format_imap_remote_id("INBOX", 100, 3), "is_read": True}),
        # 1 set_flag in INBOX
        RemoteOperationItem(op_id=uuid.uuid4(), op_type="set_flag", desired_state={"remote_id": format_imap_remote_id("INBOX", 100, 4), "is_flagged": True}),
        # 2 mark_read in Archive
        RemoteOperationItem(op_id=uuid.uuid4(), op_type="mark_read", desired_state={"remote_id": format_imap_remote_id("Archive", 100, 5), "is_read": True}),
        RemoteOperationItem(op_id=uuid.uuid4(), op_type="mark_read", desired_state={"remote_id": format_imap_remote_id("Archive", 100, 6), "is_read": True}),
    ]

    results = dict(provider.apply_remote_operations(ops))
    assert len(results) == 6
    assert all(r.success for r in results.values())

    # AC-001 & AC-002: Only 1 connection created
    assert connect_count == 1
    # Folders INBOX and Archive each selected exactly once
    assert client.select_calls == ["INBOX", "Archive"]
    # 2 STORE calls in INBOX (1 for Seen on UIDs 1:3, 1 for Flagged on UID 4), 1 STORE in Archive
    assert len(client.store_calls) == 3
    assert client.store_calls[0] == ("1:3", "+FLAGS", r"(\Seen)")
    assert client.store_calls[1] == ("4", "+FLAGS", r"(\Flagged)")
    assert client.store_calls[2] == ("5:6", "+FLAGS", r"(\Seen)")


def test_ac003_ac004_nonexistent_and_unverified_uids_fail_per_item():
    """AC-003, AC-004: Nonexistent UID fails only that op; unverified flag fails."""
    client = RecordingImapClient(uidvalidity=100)
    # Only UID 1 exists; UID 2 does not exist
    client.existing_uids.add(1)

    provider = ImapProvider("acc@test.com", "host", 993, "acc@test.com", "pass")
    provider._connect_with_permit = lambda *a, **k: (client, None)
    provider._close_client = lambda c, p: None

    op1_id = uuid.uuid4()
    op2_id = uuid.uuid4()
    ops = [
        RemoteOperationItem(op_id=op1_id, op_type="mark_read", desired_state={"remote_id": format_imap_remote_id("INBOX", 100, 1), "is_read": True}),
        RemoteOperationItem(op_id=op2_id, op_type="mark_read", desired_state={"remote_id": format_imap_remote_id("INBOX", 100, 2), "is_read": True}),
    ]

    results = dict(provider.apply_remote_operations(ops))
    assert results[op1_id].success is True
    assert results[op2_id].success is False
    assert "not found" in str(results[op2_id].error)


def test_ac005_folder_uidvalidity_mismatch_isolates_folder():
    """AC-005: UIDVALIDITY mismatch in one folder fails only that folder's operations."""
    client = RecordingImapClient(uidvalidity=100)
    client.existing_uids.update({1, 2})

    provider = ImapProvider("acc@test.com", "host", 993, "acc@test.com", "pass")
    provider._connect_with_permit = lambda *a, **k: (client, None)
    provider._close_client = lambda c, p: None

    op1_id = uuid.uuid4()
    op2_id = uuid.uuid4()
    ops = [
        # INBOX expects uv=100 (matches server)
        RemoteOperationItem(op_id=op1_id, op_type="mark_read", desired_state={"remote_id": format_imap_remote_id("INBOX", 100, 1), "is_read": True}),
        # Archive expects uv=999 (mismatches server uv=100)
        RemoteOperationItem(op_id=op2_id, op_type="mark_read", desired_state={"remote_id": format_imap_remote_id("Archive", 999, 2), "is_read": True}),
    ]

    results = dict(provider.apply_remote_operations(ops))
    assert results[op1_id].success is True
    assert results[op2_id].success is False
    assert "UIDVALIDITY mismatch" in str(results[op2_id].error)


def test_ac006_batch_move_maps_copyuid():
    """AC-006: Batch MOVE maps COPYUID destination UIDs to each operation's remote_state."""
    client = RecordingImapClient(uidvalidity=100)
    client.existing_uids.update({10, 11, 12})
    client.copyuid_responses = ["[COPYUID 200 10:12 50:52]"]

    provider = ImapProvider("acc@test.com", "host", 993, "acc@test.com", "pass")
    provider._connect_with_permit = lambda *a, **k: (client, None)
    provider._close_client = lambda c, p: None

    op1_id = uuid.uuid4()
    op2_id = uuid.uuid4()
    op3_id = uuid.uuid4()
    ops = [
        RemoteOperationItem(op_id=op1_id, op_type="move", desired_state={"remote_id": format_imap_remote_id("INBOX", 100, 10), "dest_folder_remote_id": "Archive"}),
        RemoteOperationItem(op_id=op2_id, op_type="move", desired_state={"remote_id": format_imap_remote_id("INBOX", 100, 11), "dest_folder_remote_id": "Archive"}),
        RemoteOperationItem(op_id=op3_id, op_type="move", desired_state={"remote_id": format_imap_remote_id("INBOX", 100, 12), "dest_folder_remote_id": "Archive"}),
    ]

    results = dict(provider.apply_remote_operations(ops))
    assert results[op1_id].success is True
    assert results[op1_id].remote_state.get("uid") == 50
    assert results[op1_id].remote_state.get("remote_id") == format_imap_remote_id("Archive", 200, 50)

    assert results[op2_id].success is True
    assert results[op2_id].remote_state.get("uid") == 51
    assert results[op2_id].remote_state.get("remote_id") == format_imap_remote_id("Archive", 200, 51)

    assert results[op3_id].success is True
    assert results[op3_id].remote_state.get("uid") == 52
    assert results[op3_id].remote_state.get("remote_id") == format_imap_remote_id("Archive", 200, 52)


def test_ac007_uid_string_chunking_over_1000_chars():
    """AC-007: UID strings exceeding 1000 chars are split into multiple command chunks."""
    uids = list(range(1, 2000, 2))  # 1000 non-consecutive UIDs
    chunks = compress_uids(uids, max_chars=1000)
    assert len(chunks) > 1
    assert all(len(c) <= 1000 for c in chunks)


def test_ac008_concurrent_mutation_requeues_pending():
    """AC-008: Operation modified during network call (CAS failure) returns to PENDING."""
    Session = get_session_factory()
    with Session() as session:
        acc = _make_account(session)
        aid = acc.id
        op = enqueue_remote_operation(
            session,
            account_id=aid,
            entity_key="msg:1:read",
            op_type="mark_read",
            desired_state={"remote_id": "100/INBOX/1", "is_read": True, "revision": 1},
        )
        session.commit()
        op_id = op.id

    def fake_apply(operations):
        # Mutate the operation in DB during network call!
        with Session() as s:
            r = s.get(RemoteOperation, op_id)
            r.desired_state = {"remote_id": "100/INBOX/1", "is_read": False, "revision": 2}
            r.updated_at = datetime.now(timezone.utc)
            s.commit()
        return [(op.op_id, RemoteOperationResult(success=True, remote_state={"is_read": True})) for op in operations]

    fake_provider = MagicMock()
    fake_provider.apply_remote_operations.side_effect = fake_apply

    with patch("mail_core.sync.remote_push.build_provider", return_value=fake_provider):
        res = push_remote_operations(aid, worker_id="w-cas", store=DictCredentialStore({"r": "x"}))

    assert res["status"] == "ok"
    assert res["pushed"] == 0

    with Session() as session:
        row = session.get(RemoteOperation, op_id)
        # Preserved PENDING to be retried with the newer revision
        assert row.status == RemoteOperationStatus.PENDING.value
        assert row.desired_state["revision"] == 2


def test_ac009_fencing_loss_keeps_in_progress():
    """AC-009: Fencing lost after network call leaves operations in IN_PROGRESS without marking DONE."""
    Session = get_session_factory()
    with Session() as session:
        acc = _make_account(session)
        aid = acc.id
        op = enqueue_remote_operation(
            session,
            account_id=aid,
            entity_key="msg:2:read",
            op_type="mark_read",
            desired_state={"remote_id": "100/INBOX/2", "is_read": True, "revision": 1},
        )
        session.commit()
        op_id = op.id

    def fake_apply(operations):
        # Break fencing token in DB during network call!
        with Session() as s:
            from mail_core.mail.storage.models import AccountSyncLease
            lease = s.scalar(select(AccountSyncLease).where(AccountSyncLease.account_id == aid))
            lease.fencing_token = 999
            s.commit()
        return [(op.op_id, RemoteOperationResult(success=True)) for op in operations]

    fake_provider = MagicMock()
    fake_provider.apply_remote_operations.side_effect = fake_apply

    with patch("mail_core.sync.remote_push.build_provider", return_value=fake_provider):
        res = push_remote_operations(aid, worker_id="w-fence", store=DictCredentialStore({"r": "x"}))

    assert res["status"] == "fencing_mismatch"

    with Session() as session:
        row = session.get(RemoteOperation, op_id)
        # Remains IN_PROGRESS for reconcile
        assert row.status == RemoteOperationStatus.IN_PROGRESS.value


def test_ac012_large_batch_over_500_processes_first_and_enqueues_followup():
    """AC-012: Over 500 operations processes 500 in first push and enqueues followup for remaining."""
    Session = get_session_factory()
    with Session() as session:
        acc = _make_account(session)
        aid = acc.id
        # Enqueue 550 operations
        for i in range(550):
            enqueue_remote_operation(
                session,
                account_id=aid,
                entity_key=f"msg:b{i}:read",
                op_type="mark_read",
                desired_state={"remote_id": f"100/INBOX/{i}", "is_read": True, "revision": 1},
            )
        session.commit()

    fake_provider = MagicMock()
    fake_provider.apply_remote_operations.side_effect = lambda ops: [
        (op.op_id, RemoteOperationResult(success=True, remote_state={"is_read": True})) for op in ops
    ]

    with patch("mail_core.sync.remote_push.build_provider", return_value=fake_provider):
        res = push_remote_operations(aid, worker_id="w-500", store=DictCredentialStore({"r": "x"}), limit=500)

    assert res["status"] == "ok"
    assert res["pushed"] == 500

    with Session() as session:
        done_count = session.scalar(
            select(func.count(RemoteOperation.id))
            .where(RemoteOperation.account_id == aid)
            .where(RemoteOperation.status == RemoteOperationStatus.DONE.value)
        )
        pending_count = session.scalar(
            select(func.count(RemoteOperation.id))
            .where(RemoteOperation.account_id == aid)
            .where(RemoteOperation.status == RemoteOperationStatus.PENDING.value)
        )
        assert done_count == 500
        assert pending_count == 50

        # Followup job was enqueued
        followup_job = session.scalar(
            select(WorkerJob)
            .where(WorkerJob.account_id == aid)
            .where(WorkerJob.job_type == JobType.REMOTE_OPERATION_PUSH.value)
            .where(WorkerJob.status == JobStatus.PENDING.value)
        )
        assert followup_job is not None


def test_ac013_graph_batch_requests_and_rate_limit():
    """AC-013: Graph operations use JSON batching with chunks <= 20 and handle 429 rate limit per subrequest."""
    batches_received = []

    def fake_call(method, path, body):
        assert method == "POST"
        assert path == "/$batch"
        requests = body["requests"]
        batches_received.append(requests)

        responses = []
        for r in requests:
            if "fail_429" in r["url"]:
                responses.append({
                    "id": r["id"],
                    "status": 429,
                    "headers": {"Retry-After": "15"},
                    "body": {"error": "Too Many Requests"},
                })
            else:
                responses.append({
                    "id": r["id"],
                    "status": 200,
                    "headers": {},
                    "body": {"isRead": True},
                })
        return {"responses": responses}

    provider = GraphProvider("acc@graph.test", transport=MagicMock())
    provider._call = fake_call

    # Create 25 operations to verify chunking into batches of 20 and 5
    ops = [
        RemoteOperationItem(
            op_id=uuid.uuid4(),
            op_type="mark_read",
            desired_state={"remote_id": f"msg-{i}" if i != 0 else "msg-0-fail_429", "is_read": True},
        )
        for i in range(25)
    ]

    results = dict(provider.apply_remote_operations(ops))
    assert len(results) == 25

    # 2 batches: first has 20, second has 5
    assert len(batches_received) == 2
    assert len(batches_received[0]) == 20
    assert len(batches_received[1]) == 5

    # Subrequest with 429 failed with rate limited error
    assert results[ops[0].op_id].success is False
    assert "Rate limited" in str(results[ops[0].op_id].error)
    assert results[ops[0].op_id].remote_state["retry_after"] == 15.0

    # Other subrequests succeeded
    assert results[ops[1].op_id].success is True


def test_rate_limit_and_transient_failure_schedules_delayed_followup_job():
    """A01: Rate limited or transient failed ops schedule delayed followup job with run_after."""
    Session = get_session_factory()
    acc_id = uuid.uuid4()
    with Session() as s:
        acc = Account(
            id=acc_id,
            email=f"push-retry-{acc_id.hex[:6]}@example.com",
            provider="graph",
            credential_ref="cred-graph",
        )
        s.add(acc)
        s.commit()

    store = DictCredentialStore()
    store.put_secret("cred-graph", "tok")

    # Seed one op that will get rate limited with retry_after=45
    with Session() as s:
        enqueue_remote_operation(
            s,
            account_id=acc_id,
            entity_key="msg-rate-limit",
            op_type="mark_read",
            desired_state={"remote_id": "msg-rate-limit", "is_read": True},
        )
        s.commit()

    fake_provider = MagicMock()
    fake_provider.apply_remote_operations = MagicMock(
        return_value=[
            (
                uuid.uuid4(),  # dummy, won't match, or let's match exact op_id
                RemoteOperationResult(
                    success=False,
                    error="Rate limited",
                    remote_state={"retry_after": 45.0},
                ),
            )
        ]
    )

    with Session() as s:
        op = s.scalar(select(RemoteOperation).where(RemoteOperation.account_id == acc_id))
        assert op is not None
        op_id = op.id

    fake_provider.apply_remote_operations.return_value = [
        (
            op_id,
            RemoteOperationResult(
                success=False,
                error="Rate limited",
                remote_state={"retry_after": 45.0},
            ),
        )
    ]

    with patch("mail_core.sync.remote_push.build_provider", return_value=fake_provider):
        res = push_remote_operations(acc_id, worker_id="worker-retry-test", store=store)
        assert res["status"] == "ok"
        assert res["failed"] == 1

    with Session() as s:
        op = s.get(RemoteOperation, op_id)
        assert op is not None
        assert op.status == RemoteOperationStatus.PENDING.value
        assert op.next_attempt_at is not None

        # Verify followup job was scheduled with run_after >= next_attempt_at
        job = s.scalar(
            select(WorkerJob)
            .where(WorkerJob.account_id == acc_id)
            .where(WorkerJob.job_type == JobType.REMOTE_OPERATION_PUSH.value)
            .where(WorkerJob.status == JobStatus.PENDING.value)
        )
        assert job is not None
        assert job.run_after is not None
        now_utc = datetime.now(timezone.utc)
        assert job.run_after >= now_utc + timedelta(seconds=40)

        # Call again when work is empty (job.run_after in future), ensure next_due is re-scheduled
        # First reset job to completed to simulate worker execution
        job.status = JobStatus.DONE.value
        s.commit()

    with patch("mail_core.sync.remote_push.build_provider", return_value=fake_provider):
        res = push_remote_operations(acc_id, worker_id="worker-retry-test", store=store)
        assert res["status"] == "ok"
        assert res["pushed"] == 0
        assert res["failed"] == 0

    with Session() as s:
        re_job = s.scalar(
            select(WorkerJob)
            .where(WorkerJob.account_id == acc_id)
            .where(WorkerJob.job_type == JobType.REMOTE_OPERATION_PUSH.value)
            .where(WorkerJob.status == JobStatus.PENDING.value)
        )
        assert re_job is not None
        assert re_job.run_after is not None
        assert re_job.run_after >= now_utc + timedelta(seconds=40)
