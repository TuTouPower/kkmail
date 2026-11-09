"""A30: capacity deferral must not consume a remote op's attempt budget.

Claiming an op marks it IN_PROGRESS, which increments ``attempts``. The
capacity branch resets the op to PENDING so it can be retried when the
connection budget frees up, but it used to keep the incremented count:
five purely capacity-driven rounds exhausted
``DEFAULT_MAX_REMOTE_OP_ATTEMPTS`` and the next real failure became
terminal even though no delivery had ever been attempted.

Runs against the real PostgreSQL schema created by ``alembic upgrade head``:
JSONB ``desired_state``, timestamptz columns and FOR UPDATE row locks are
all exercised by the real ``push_remote_operations`` path.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobStatus, JobType, RemoteOperationStatus
from mail_core.mail.storage.models import Account, RemoteOperation, WorkerJob
from mail_core.providers.connection_slots import ProviderCapacityUnavailable
from mail_core.sync import remote_push as remote_push_mod

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)
_WORKER = "w-a30"


class _CapacityProvider:
    def apply_remote_operation(self, _op_type, _desired_state):
        raise ProviderCapacityUnavailable("connection budget saturated")


def test_capacity_deferral_rounds_do_not_consume_attempts():
    Session = get_session_factory()
    account_id = uuid.uuid4()
    op_id = uuid.uuid4()
    with Session() as session:
        session.add(
            Account(
                id=account_id, email="push@example.test", provider="memory",
                credential_ref="ref", config={}, sync_enabled=True,
            )
        )
        session.add(
            WorkerJob(
                id=uuid.uuid4(), execution_generation=uuid.uuid4(),
                job_type=JobType.REMOTE_OPERATION_PUSH.value,
                account_id=account_id, payload={}, status=JobStatus.CLAIMED.value,
                locked_by=_WORKER, locked_at=_NOW,
                dedupe_key=f"remote-op-push:{account_id}",
                run_after=_NOW, created_at=_NOW, updated_at=_NOW,
            )
        )
        session.add(
            RemoteOperation(
                id=op_id, account_id=account_id, entity_key="msg:msg-1:read",
                op_type="mark_read",
                desired_state={"remote_id": "msg-1", "is_read": True},
                status=RemoteOperationStatus.PENDING.value, attempts=0,
                created_at=_NOW, updated_at=_NOW,
            )
        )
        session.commit()

    with patch.object(remote_push_mod, "build_provider", lambda *a, **k: _CapacityProvider()):
        for round_no in range(1, 6):
            result = remote_push_mod.push_remote_operations(account_id, worker_id=_WORKER, store=object())
            assert result["status"] == "capacity_unavailable"
            with Session() as session:
                op = session.get(RemoteOperation, op_id)
                assert op is not None
                assert op.status == RemoteOperationStatus.PENDING.value
                assert op.attempts == 0, (
                    f"round {round_no}: pure capacity waiting consumed an attempt "
                    f"(attempts={op.attempts})"
                )
                op.next_attempt_at = None
                session.commit()
