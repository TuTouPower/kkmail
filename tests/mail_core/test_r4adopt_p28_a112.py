"""A112: mark DONE must be rejected when desired_state revision has advanced."""
from __future__ import annotations
import uuid
from unittest.mock import MagicMock
from mail_core.mail.application.remote_ops import mark_remote_operation
from mail_core.mail.domain.enums import RemoteOperationStatus
from mail_core.mail.storage.models import RemoteOperation

def _op(revision):
    return RemoteOperation(id=uuid.uuid4(), account_id=uuid.uuid4(), entity_key="msg:1:read", op_type="mark_read", desired_state={"is_read": True, "revision": revision}, status=RemoteOperationStatus.IN_PROGRESS.value, attempts=1)

def test_done_rejected_when_revision_advanced():
    session = MagicMock()
    op = _op(revision=3)  # coalesce bumped 2 -> 3 while worker was executing rev 2
    result = mark_remote_operation(session, op, status=RemoteOperationStatus.DONE, expected_revision=2)
    assert result is False
    assert op.status == RemoteOperationStatus.PENDING.value
    assert op.next_attempt_at is None

def test_done_applied_when_revision_matches():
    session = MagicMock()
    op = _op(revision=2)
    result = mark_remote_operation(session, op, status=RemoteOperationStatus.DONE, expected_revision=2)
    assert result is True
    assert op.status == RemoteOperationStatus.DONE.value

def test_done_without_expected_revision_keeps_legacy_behaviour():
    session = MagicMock()
    op = _op(revision=9)
    result = mark_remote_operation(session, op, status=RemoteOperationStatus.DONE)
    assert result is True
    assert op.status == RemoteOperationStatus.DONE.value

def test_non_done_status_not_gated_by_revision():
    session = MagicMock()
    op = _op(revision=3)
    op.status = RemoteOperationStatus.PENDING.value
    result = mark_remote_operation(session, op, status=RemoteOperationStatus.IN_PROGRESS, expected_revision=2)
    assert result is True
    assert op.status == RemoteOperationStatus.IN_PROGRESS.value
    assert op.attempts == 2
