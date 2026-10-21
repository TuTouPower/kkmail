"""Extreme offline and concurrent toggling convergence tests for flag and read status (SEC/SYNC).

Covers:
- Rapid oscillation / toggling of read and flag status while offline.
- Idempotent coalescing under identical repeated mutations.
- Versioned (revision) state tracking and CAS conflict protection during concurrent in-flight push.
- Transient network disconnection, exponential backoff, and eventual convergence on recovery.
- Stale in-progress lease reclamation and idempotency on reconnect.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.db.session import get_session_factory
from mail_core.mail.application.mutations import set_message_flagged, set_message_read
from mail_core.mail.application.remote_ops import reclaim_stale_in_progress
from mail_core.mail.domain.enums import RemoteOperationStatus
from mail_core.mail.storage import Folder, Message, MessageLocation, RemoteOperation
from mail_core.providers.base import RemoteFolder, RemoteMessageMeta
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.sync import push_remote_operations
import mail_core.sync.remote_push as push_mod

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _patch_push_provider(provider):
    orig = push_mod.build_provider
    push_mod.build_provider = lambda account, store=None: provider
    return orig


def _restore_push_provider(orig):
    push_mod.build_provider = orig


def _seed_account_and_message(session, *, remote_id: str = "msg-1") -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    now = datetime.now(timezone.utc)
    acc = create_account(session, email=f"conv-{uuid.uuid4().hex[:8]}@example.com", provider="memory", credential_ref="r")
    session.flush()
    folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
    session.add(folder)
    session.flush()
    msg = Message(
        account_id=acc.id,
        remote_id=remote_id,
        subject="Convergence Subject",
        from_address="sender@example.com",
        from_name="Sender",
        sort_time=now,
        is_read=False,
        is_flagged=False,
    )
    session.add(msg)
    session.flush()
    session.add(MessageLocation(message_id=msg.id, folder_id=folder.id, uid=1))
    session.commit()
    return acc.id, folder.id, msg.id


def test_rapid_offline_toggling_coalesces_to_latest_state():
    store = DictCredentialStore({"r": "secret"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed("INBOX", [RemoteMessageMeta("msg-1", "Subject", "a@b.c", "A", now, False, False, uid=1)])

    orig = _patch_push_provider(provider)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc_id, folder_id, msg_id = _seed_account_and_message(session, remote_id="msg-1")

        # Simulate offline rapid user toggling of read and flag states:
        # Read sequence: True -> False -> True -> False -> True
        # Flag sequence: True -> False -> True
        with Session() as session:
            for is_read_target in [True, False, True, False, True]:
                set_message_read(session, msg_id, is_read=is_read_target)
            for is_flag_target in [True, False, True]:
                set_message_flagged(session, msg_id, is_flagged=is_flag_target)
            session.commit()

        # In DB, there must be only 1 pending op for read and 1 for flag
        with Session() as session:
            ops = list(
                session.scalars(
                    select(RemoteOperation)
                    .where(RemoteOperation.account_id == acc_id)
                    .order_by(RemoteOperation.entity_key.asc())
                ).all()
            )
            assert len(ops) == 2

            flag_op = next(o for o in ops if o.op_type == "set_flag")
            read_op = next(o for o in ops if o.op_type == "mark_read")

            assert flag_op.status == RemoteOperationStatus.PENDING.value
            assert flag_op.desired_state.get("is_flagged") is True
            assert flag_op.desired_state.get("revision") == 3

            assert read_op.status == RemoteOperationStatus.PENDING.value
            assert read_op.desired_state.get("is_read") is True
            assert read_op.desired_state.get("revision") == 5

            # Local message must reflect the final states
            msg = session.get(Message, msg_id)
            assert msg.is_read is True
            assert msg.is_flagged is True

        # Now reconnect / push to remote provider
        res = push_remote_operations(acc_id, worker_id="worker-conv", store=store)
        assert res["status"] == "ok"
        assert res["pushed"] == 2

        # Remote provider should be updated to converged state
        assert provider.messages["INBOX"][0].is_read is True
        assert "msg-1" in provider.flagged

        # Remote operations are all DONE
        with Session() as session:
            pending_count = session.scalar(
                select(func.count())
                .select_from(RemoteOperation)
                .where(RemoteOperation.account_id == acc_id)
                .where(RemoteOperation.status == RemoteOperationStatus.PENDING.value)
            )
            assert pending_count == 0
    finally:
        _restore_push_provider(orig)


def test_idempotent_repeated_mutations_merge_cleanly():
    store = DictCredentialStore({"r": "secret"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed("INBOX", [RemoteMessageMeta("msg-idem", "Sub", "a@b.c", "A", now, False, False, uid=1)])

    orig = _patch_push_provider(provider)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc_id, _, msg_id = _seed_account_and_message(session, remote_id="msg-idem")

        # Repeatedly set read=True 4 times
        with Session() as session:
            for _ in range(4):
                set_message_read(session, msg_id, is_read=True)
            session.commit()

        with Session() as session:
            read_ops = list(
                session.scalars(
                    select(RemoteOperation)
                    .where(RemoteOperation.account_id == acc_id)
                    .where(RemoteOperation.op_type == "mark_read")
                ).all()
            )
            assert len(read_ops) == 1
            assert read_ops[0].desired_state.get("is_read") is True
            assert read_ops[0].desired_state.get("revision") == 4

        res = push_remote_operations(acc_id, worker_id="worker-idem", store=store)
        assert res["status"] == "ok"
        assert res["pushed"] == 1
        assert provider.messages["INBOX"][0].is_read is True
    finally:
        _restore_push_provider(orig)


def test_concurrent_in_flight_mutation_cas_protection():
    store = DictCredentialStore({"r": "secret"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed("INBOX", [RemoteMessageMeta("msg-cas", "Sub", "a@b.c", "A", now, False, False, uid=1)])

    orig = _patch_push_provider(provider)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc_id, _, msg_id = _seed_account_and_message(session, remote_id="msg-cas")
            # Step 1: User initially sets is_read=True
            set_message_read(session, msg_id, is_read=True)
            session.commit()

        # Step 2: Hook provider.apply_remote_operation to simulate a concurrent user mutation
        # while the worker is actively communicating with the remote server.
        original_apply = provider.apply_remote_operation

        def _apply_with_concurrent_mutation(op_type, desired):
            # Concurrent user action: user marks it unread (is_read=False) while push is in flight
            with Session() as concurrent_session:
                set_message_read(concurrent_session, msg_id, is_read=False)
                concurrent_session.commit()
            return original_apply(op_type, desired)

        provider.apply_remote_operation = _apply_with_concurrent_mutation

        # Step 3: Run push. The worker pushes the claimed revision 1 (is_read=True),
        # but CAS detects that the operation row was modified concurrently to revision 2 (is_read=False).
        # It must preserve PENDING without overwriting the newer state with DONE.
        res = push_remote_operations(acc_id, worker_id="worker-cas", store=store)
        assert res["status"] == "ok"
        # Since CAS triggered, pushed count in this round is 0
        assert res["pushed"] == 0

        with Session() as session:
            op = session.scalar(
                select(RemoteOperation)
                .where(RemoteOperation.account_id == acc_id)
                .where(RemoteOperation.entity_key == "msg:msg-cas:read")
            )
            assert op.status == RemoteOperationStatus.PENDING.value
            assert op.desired_state.get("is_read") is False
            assert op.desired_state.get("revision") == 2

        # Step 4: Restore normal apply and push again
        provider.apply_remote_operation = original_apply
        res2 = push_remote_operations(acc_id, worker_id="worker-cas", store=store)
        assert res2["status"] == "ok"
        assert res2["pushed"] == 1

        # Remote provider must converge on the final user intention: is_read=False
        assert provider.messages["INBOX"][0].is_read is False

        with Session() as session:
            op = session.scalar(
                select(RemoteOperation)
                .where(RemoteOperation.account_id == acc_id)
                .where(RemoteOperation.entity_key == "msg:msg-cas:read")
            )
            assert op.status == RemoteOperationStatus.DONE.value
    finally:
        _restore_push_provider(orig)


def test_network_failure_transient_retry_and_recovery():
    store = DictCredentialStore({"r": "secret"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed("INBOX", [RemoteMessageMeta("msg-net", "Sub", "a@b.c", "A", now, False, False, uid=1)])

    orig = _patch_push_provider(provider)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc_id, _, msg_id = _seed_account_and_message(session, remote_id="msg-net")
            set_message_flagged(session, msg_id, is_flagged=True)
            session.commit()

        # Step 1: Simulate network disconnection during apply
        def _failing_apply(op_type, desired):
            raise ConnectionResetError("Connection lost: peer reset by network breakdown")

        provider.apply_remote_operation = _failing_apply

        res = push_remote_operations(acc_id, worker_id="worker-net", store=store)
        assert res["status"] == "ok"
        assert res["pushed"] == 0

        # Operation should remain PENDING with an exponential backoff next_attempt_at
        with Session() as session:
            op = session.scalar(
                select(RemoteOperation)
                .where(RemoteOperation.account_id == acc_id)
                .where(RemoteOperation.entity_key == "msg:msg-net:flag")
            )
            assert op.status == RemoteOperationStatus.PENDING.value
            assert op.attempts == 1
            assert "ConnectionResetError" in (op.last_error or "")
            assert op.next_attempt_at is not None

            # Reset next_attempt_at to simulate backoff elapsing
            op.next_attempt_at = None
            session.commit()

        # Step 2: Simulate network reconnection
        real_provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
        real_provider.seed("INBOX", [RemoteMessageMeta("msg-net", "Sub", "a@b.c", "A", now, False, False, uid=1)])
        _restore_push_provider(orig)
        orig = _patch_push_provider(real_provider)

        res2 = push_remote_operations(acc_id, worker_id="worker-net", store=store)
        assert res2["status"] == "ok"
        assert res2["pushed"] == 1

        with Session() as session:
            op = session.scalar(
                select(RemoteOperation)
                .where(RemoteOperation.account_id == acc_id)
                .where(RemoteOperation.entity_key == "msg:msg-net:flag")
            )
            assert op.status == RemoteOperationStatus.DONE.value
            assert op.next_attempt_at is None

        assert "msg-net" in real_provider.flagged
    finally:
        _restore_push_provider(orig)


def test_stale_in_progress_reclaim_and_idempotent_push():
    store = DictCredentialStore({"r": "secret"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed("INBOX", [RemoteMessageMeta("msg-stale", "Sub", "a@b.c", "A", now, False, False, uid=1)])

    orig = _patch_push_provider(provider)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc_id, _, msg_id = _seed_account_and_message(session, remote_id="msg-stale")
            set_message_read(session, msg_id, is_read=True)
            session.commit()

        # Manually put the operation into IN_PROGRESS with a stale updated_at timestamp (30 mins ago)
        with Session() as session:
            op = session.scalar(
                select(RemoteOperation)
                .where(RemoteOperation.account_id == acc_id)
                .where(RemoteOperation.entity_key == "msg:msg-stale:read")
            )
            op.status = RemoteOperationStatus.IN_PROGRESS.value
            op.updated_at = datetime.now(timezone.utc) - timedelta(minutes=30)
            session.commit()

        # push_remote_operations automatically runs reclaim_stale_in_progress at start
        res = push_remote_operations(acc_id, worker_id="worker-reclaim", store=store)
        assert res["status"] == "ok"
        assert res["pushed"] == 1

        with Session() as session:
            op = session.scalar(
                select(RemoteOperation)
                .where(RemoteOperation.account_id == acc_id)
                .where(RemoteOperation.entity_key == "msg:msg-stale:read")
            )
            assert op.status == RemoteOperationStatus.DONE.value

        assert provider.messages["INBOX"][0].is_read is True
    finally:
        _restore_push_provider(orig)
