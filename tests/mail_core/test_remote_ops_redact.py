"""Test that mark_remote_operation redacts error messages (SEC-04)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from mail_core.mail.application.remote_ops import mark_remote_operation
from mail_core.mail.domain.enums import RemoteOperationStatus
from mail_core.mail.storage.models import RemoteOperation


def test_mark_remote_operation_redacts_last_error():
    session = MagicMock()
    op = RemoteOperation(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        entity_key="test_entity",
        op_type="mark_read",
        desired_state={},
        status=RemoteOperationStatus.IN_PROGRESS.value,
        attempts=1,
    )

    sensitive_error = "Sync error: postgresql://my_user:secret_password@db.example.com/kkmail with Bearer ya29.a0AfH6"
    mark_remote_operation(
        session,
        op,
        status=RemoteOperationStatus.FAILED,
        error=sensitive_error,
    )

    assert op.last_error is not None
    assert "secret_password" not in op.last_error
    assert "[REDACTED]" in op.last_error


def test_coalesce_in_progress_operation_with_monotonic_revision():
    from mail_core.mail.application.remote_ops import enqueue_remote_operation

    account_id = uuid.uuid4()
    in_progress_op = RemoteOperation(
        id=uuid.uuid4(),
        account_id=account_id,
        entity_key="msg:item_1:read",
        op_type="mark_read",
        desired_state={"is_read": True, "revision": 1},
        status=RemoteOperationStatus.IN_PROGRESS.value,
    )

    session = MagicMock()
    # Mock session.scalar to return in_progress_op when querying active op
    session.scalar.return_value = in_progress_op

    coalesced = enqueue_remote_operation(
        session,
        account_id=account_id,
        entity_key="msg:item_1:read",
        op_type="mark_read",
        desired_state={"is_read": False},
    )

    assert coalesced.id == in_progress_op.id
    assert coalesced.status == RemoteOperationStatus.PENDING.value
    assert coalesced.desired_state["is_read"] is False
    assert coalesced.desired_state["revision"] == 2

