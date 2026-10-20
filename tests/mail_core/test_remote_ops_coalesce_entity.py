"""Desired-state coalesce: pending ops with same entity_key collapse."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import func, select

from mail_core.mail.application.remote_ops import enqueue_remote_operation
from mail_core.mail.domain.enums import RemoteOperationStatus
from mail_core.mail.storage.models import Account, RemoteOperation

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_pending_entity_key_coalesce_keeps_latest_desired_state():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"coalesce-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        op1 = enqueue_remote_operation(
            session,
            account_id=acc.id,
            entity_key="msg:r1:read",
            op_type="mark_read",
            desired_state={"is_read": True},
            idempotency_key=f"{uuid.uuid4()}:read:1",
        )
        op2 = enqueue_remote_operation(
            session,
            account_id=acc.id,
            entity_key="msg:r1:read",
            op_type="mark_read",
            desired_state={"is_read": False},
            idempotency_key=f"{uuid.uuid4()}:read:0",
        )
        session.commit()
        assert op1.id == op2.id
        assert op2.desired_state.get("is_read") is False
        assert op2.desired_state.get("revision") == 2
        n = session.scalar(
            select(func.count())
            .select_from(RemoteOperation)
            .where(RemoteOperation.account_id == acc.id)
            .where(RemoteOperation.entity_key == "msg:r1:read")
            .where(RemoteOperation.status == RemoteOperationStatus.PENDING.value)
        )
        assert n == 1


def test_in_progress_entity_key_coalesces_to_pending_with_monotonic_revision():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"coalesce-inp-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        op1 = enqueue_remote_operation(
            session,
            account_id=acc.id,
            entity_key="msg:r2:read",
            op_type="mark_read",
            desired_state={"is_read": True},
        )
        assert op1.desired_state.get("revision") == 1
        # Worker claims op1 and moves it to IN_PROGRESS
        op1.status = RemoteOperationStatus.IN_PROGRESS.value
        session.flush()

        # Concurrent user action enqueues opposite state for the same entity
        op2 = enqueue_remote_operation(
            session,
            account_id=acc.id,
            entity_key="msg:r2:read",
            op_type="mark_read",
            desired_state={"is_read": False},
        )
        session.commit()

        # Must coalesce into the same row and reset to PENDING
        assert op1.id == op2.id
        assert op2.status == RemoteOperationStatus.PENDING.value
        assert op2.desired_state.get("is_read") is False
        assert op2.desired_state.get("revision") == 2

        # Verify only 1 row exists in DB for this entity
        total = session.scalar(
            select(func.count())
            .select_from(RemoteOperation)
            .where(RemoteOperation.account_id == acc.id)
            .where(RemoteOperation.entity_key == "msg:r2:read")
        )
        assert total == 1

