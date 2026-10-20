"""Account sync leases + fencing tokens (architecture §7.5)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import AccountSyncLease


class LeaseBusy(Exception):
    """Another worker holds a non-expired lease."""


class FencingMismatch(Exception):
    """Commit rejected because fencing_token no longer matches the lease."""


@dataclass(frozen=True, slots=True)
class LeaseHandle:
    account_id: uuid.UUID
    owner_id: str
    fencing_token: int
    lease_expires_at: datetime


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def acquire_lease(
    session: Session,
    *,
    account_id: uuid.UUID,
    owner_id: str,
    ttl: timedelta = timedelta(seconds=30),
    now: datetime | None = None,
) -> LeaseHandle:
    """Short-transaction acquire: insert or steal expired lease; bump fencing_token."""
    now = now or _utcnow()
    expires = now + ttl
    row = session.get(AccountSyncLease, account_id)
    if row is None:
        token = 1
        session.add(
            AccountSyncLease(
                account_id=account_id,
                owner_id=owner_id,
                lease_expires_at=expires,
                heartbeat_at=now,
                fencing_token=token,
            )
        )
        session.flush()
        return LeaseHandle(account_id, owner_id, token, expires)

    if row.owner_id != owner_id and row.lease_expires_at > now:
        raise LeaseBusy(f"account {account_id} held by {row.owner_id} until {row.lease_expires_at}")

    # Renew for same owner OR steal expired lease — always increment fencing.
    token = int(row.fencing_token) + 1
    row.owner_id = owner_id
    row.lease_expires_at = expires
    row.heartbeat_at = now
    row.fencing_token = token
    session.flush()
    return LeaseHandle(account_id, owner_id, token, expires)


def heartbeat_lease(
    session: Session,
    *,
    account_id: uuid.UUID,
    owner_id: str,
    fencing_token: int,
    ttl: timedelta = timedelta(seconds=30),
    now: datetime | None = None,
) -> LeaseHandle:
    now = now or _utcnow()
    row = session.get(AccountSyncLease, account_id)
    if row is None or row.owner_id != owner_id or int(row.fencing_token) != fencing_token:
        raise FencingMismatch("lease heartbeat rejected")
    row.heartbeat_at = now
    row.lease_expires_at = now + ttl
    session.flush()
    return LeaseHandle(account_id, owner_id, fencing_token, row.lease_expires_at)


def assert_fencing(session: Session, *, account_id: uuid.UUID, fencing_token: int) -> None:
    """Call inside the same short TX that commits checkpoints / message writes."""
    row = session.get(AccountSyncLease, account_id)
    if row is None or int(row.fencing_token) != fencing_token:
        raise FencingMismatch(
            f"fencing token {fencing_token} rejected; current="
            f"{None if row is None else row.fencing_token}"
        )


def release_lease(
    session: Session,
    *,
    account_id: uuid.UUID,
    owner_id: str,
    fencing_token: int,
    now: datetime | None = None,
) -> None:
    now = now or _utcnow()
    row = session.get(AccountSyncLease, account_id)
    if row is None:
        return
    if row.owner_id != owner_id or int(row.fencing_token) != fencing_token:
        raise FencingMismatch("release rejected")
    # Expire immediately so others can acquire; keep fencing_token as-is.
    row.lease_expires_at = now
    row.heartbeat_at = now
    session.flush()
