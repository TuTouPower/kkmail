from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select

from mail_core.accounts import create_account, list_accounts
from mail_core.db.session import get_session_factory
from mail_core.mail.application.remote_ops import enqueue_remote_operation, mark_remote_operation
from mail_core.mail.domain.enums import ProviderType, RemoteOperationStatus
from mail_core.mail.storage import OutboxEvent, RemoteOperation

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_create_account_stores_credential_ref_only():
    Session = get_session_factory()
    with Session() as session:
        acc = create_account(
            session,
            email=f"acc-{uuid.uuid4().hex[:8]}@example.com",
            provider=ProviderType.GRAPH,
            credential_ref="keychain:graph/user-1",
        )
        session.commit()
        assert acc.credential_ref.startswith("keychain:")
        assert "password" not in (acc.config or {})
        rows, _total = list_accounts(session, limit=500)
        assert any(a.id == acc.id for a in rows)


def test_enqueue_remote_operation_outbox():
    Session = get_session_factory()
    with Session() as session:
        acc = create_account(
            session,
            email=f"rop-{uuid.uuid4().hex[:8]}@example.com",
            provider="imap",
            config={"imap_host": "8.8.8.8"},
        )
        session.flush()
        op = enqueue_remote_operation(
            session,
            account_id=acc.id,
            entity_key="msg:1",
            op_type="mark_read",
            desired_state={"is_read": True},
            idempotency_key=f"idem-{uuid.uuid4().hex}",
        )
        mark_remote_operation(session, op, status=RemoteOperationStatus.IN_PROGRESS)
        session.commit()
        loaded = session.get(RemoteOperation, op.id)
        assert loaded.status == "in_progress"
        assert loaded.attempts == 1
        events = session.scalars(select(OutboxEvent).where(OutboxEvent.account_id == acc.id)).all()
        assert any(e.event_type == "remote_operation.updated" for e in events)




def test_enqueue_remote_operation_upserts_same_idempotency_key():
    Session = get_session_factory()
    with Session() as session:
        acc = create_account(
            session,
            email=f"rop-up-{uuid.uuid4().hex[:8]}@example.com",
            provider="imap",
            config={"imap_host": "8.8.8.8"},
        )
        session.flush()
        key = f"idem-upsert-{uuid.uuid4().hex}"
        op1 = enqueue_remote_operation(
            session,
            account_id=acc.id,
            entity_key="msg:1:read",
            op_type="mark_read",
            desired_state={"is_read": True},
            idempotency_key=key,
        )
        session.flush()
        op2 = enqueue_remote_operation(
            session,
            account_id=acc.id,
            entity_key="msg:1:read",
            op_type="mark_read",
            desired_state={"is_read": True, "retry": 1},
            idempotency_key=key,
        )
        session.commit()
        assert op1.id == op2.id
        loaded = session.get(RemoteOperation, op1.id)
        assert loaded.desired_state.get("retry") == 1
        assert loaded.status == RemoteOperationStatus.PENDING.value
