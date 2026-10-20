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
from mail_core.providers import GmailProvider, GraphProvider

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
            provider=ProviderType.GMAIL,
            credential_ref="keychain:gmail/user-1",
        )
        session.commit()
        assert acc.credential_ref.startswith("keychain:")
        assert "password" not in (acc.config or {})
        rows, _total = list_accounts(session, limit=500)
        assert any(a.id == acc.id for a in rows)


def test_enqueue_remote_operation_outbox():
    Session = get_session_factory()
    with Session() as session:
        acc = create_account(session, email=f"rop-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
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


def test_gmail_graph_stubs_list_folders():
    assert GmailProvider(credential_ref="x").list_folders()[0].role == "inbox"
    assert GraphProvider(credential_ref="x").list_folders()[0].role == "inbox"
