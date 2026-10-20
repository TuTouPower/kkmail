"""Push pending remote_operations via provider.apply_remote_operation."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.mail.application.remote_ops import mark_remote_operation
from mail_core.mail.domain.enums import RemoteOperationStatus
from mail_core.mail.storage.models import Account, RemoteOperation
from mail_core.providers.factory import build_provider
from mail_core.sync.leases import FencingMismatch, LeaseBusy, acquire_lease, assert_fencing, release_lease

log = logging.getLogger("mail_core.sync.remote_push")


def push_remote_operations(
    account_id: uuid.UUID,
    *,
    worker_id: str,
    store: CredentialStore | None = None,
    limit: int = 20,
    lease_ttl: timedelta = timedelta(seconds=60),
) -> dict:
    Session = __import__("mail_core.db.session", fromlist=["get_session_factory"]).get_session_factory()
    with Session() as session:
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError("account not found")
        try:
            lease = acquire_lease(session, account_id=account_id, owner_id=worker_id, ttl=lease_ttl)
        except LeaseBusy:
            return {"status": "lease_busy"}
        ops = list(
            session.scalars(
                select(RemoteOperation)
                .where(RemoteOperation.account_id == account_id)
                .where(RemoteOperation.status == RemoteOperationStatus.PENDING.value)
                .order_by(RemoteOperation.created_at.asc())
                .limit(limit)
            ).all()
        )
        for op in ops:
            mark_remote_operation(session, op, status=RemoteOperationStatus.IN_PROGRESS)
        session.commit()
        fencing = lease.fencing_token
        op_ids = [op.id for op in ops]
        account_snapshot = Account(
            id=account.id,
            email=account.email,
            provider=account.provider,
            credential_ref=account.credential_ref,
            config=dict(account.config or {}),
        )

    if not op_ids:
        with Session() as session:
            release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
            session.commit()
        return {"status": "ok", "pushed": 0}

    provider = build_provider(account_snapshot, store or get_credential_store())
    pushed = 0
    failed = 0
    with Session() as session:
        try:
            assert_fencing(session, account_id=account_id, fencing_token=fencing)
        except FencingMismatch:
            return {"status": "fencing_mismatch"}
        for op_id in op_ids:
            op = session.get(RemoteOperation, op_id)
            if op is None:
                continue
            # Network per op — still outside long locks; we hold no row lock on provider call
            desired = dict(op.desired_state or {})
            # Re-fetch detached fields
            op_type = op.op_type
            session.commit()  # release before network
            result = provider.apply_remote_operation(op_type, desired)
            with Session() as s2:
                try:
                    assert_fencing(s2, account_id=account_id, fencing_token=fencing)
                except FencingMismatch:
                    return {"status": "fencing_mismatch", "pushed": pushed, "failed": failed}
                op2 = s2.get(RemoteOperation, op_id)
                if op2 is None:
                    continue
                if result.success:
                    mark_remote_operation(s2, op2, status=RemoteOperationStatus.DONE)
                    pushed += 1
                else:
                    mark_remote_operation(
                        s2, op2, status=RemoteOperationStatus.FAILED, error=result.error or "push failed"
                    )
                    failed += 1
                s2.commit()

    with Session() as session:
        try:
            release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
            session.commit()
        except FencingMismatch:
            pass
    return {"status": "ok", "pushed": pushed, "failed": failed}
