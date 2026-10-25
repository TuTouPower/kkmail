from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from mail_core.mail.application.remote_ops import enqueue_remote_operation


class _Session:
    def __init__(self, existing):
        self.existing = existing
        self.statements = []
        self.added = []

    def scalar(self, statement):
        self.statements.append(statement)
        return self.existing

    def add(self, value):
        self.added.append(value)

    def flush(self):
        pass


def _operation(*, account_id, entity_key, op_type):
    return SimpleNamespace(
        id=uuid.uuid4(),
        account_id=account_id,
        entity_key=entity_key,
        op_type=op_type,
        status="pending",
        desired_state={"revision": 1, "is_read": True},
        next_attempt_at=None,
        idempotency_key="idem-1",
        created_at=None,
        updated_at=None,
    )


def test_idempotency_lookup_is_account_scoped_and_locked():
    account_id = uuid.uuid4()
    entity_key = "msg:remote-1:read"
    existing = _operation(account_id=account_id, entity_key=entity_key, op_type="mark_read")
    session = _Session(existing)

    result = enqueue_remote_operation(
        session,
        account_id=account_id,
        entity_key=entity_key,
        op_type="mark_read",
        desired_state={"is_read": False},
        idempotency_key="idem-1",
    )

    assert result is existing
    statement = session.statements[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert "remote_operations.account_id =" in str(compiled)
    assert "FOR UPDATE" in str(compiled)
    assert account_id in compiled.params.values()


@pytest.mark.parametrize("mismatch", ["account_id", "entity_key", "op_type"])
def test_idempotency_coalesce_rejects_different_operation_owner(mismatch):
    account_id = uuid.uuid4()
    entity_key = "msg:remote-1:read"
    op_type = "mark_read"
    existing_values = {"account_id": account_id, "entity_key": entity_key, "op_type": op_type}
    if mismatch == "account_id":
        existing_values["account_id"] = uuid.uuid4()
    else:
        existing_values[mismatch] = f"other-{mismatch}"
    existing = _operation(**existing_values)
    original_state = dict(existing.desired_state)
    session = _Session(existing)

    with pytest.raises(ValueError, match="cannot coalesce remote operation"):
        enqueue_remote_operation(
            session,
            account_id=account_id,
            entity_key=entity_key,
            op_type=op_type,
            desired_state={"is_read": False},
            idempotency_key="idem-1",
        )

    assert existing.desired_state == original_state
    assert not session.added
