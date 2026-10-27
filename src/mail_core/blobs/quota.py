"""Disk quota helpers for MIME archive backpressure."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from mail_core.blobs.crypto import CHUNK_SIZE, HEADER_LEN, TAG_LEN

log = logging.getLogger(__name__)
QUOTA_RESERVATION_LOCK_NAMESPACE = 0x4B4B5154  # Dedicated two-key PostgreSQL advisory-lock namespace.
QUOTA_RESERVATION_LOCK_RESOURCE = 0x52455356  # Singleton resource for global hard-quota reservations.


class QuotaExceededError(RuntimeError):
    """A quota reservation would exceed the hard limit (A108).

    Distinct from "no reservation needed": reserve_quota returns None
    only when there is nothing to reserve, and raises this error when the
    hard limit would be exceeded, so callers cannot confuse the two.
    """


@dataclass(frozen=True, slots=True)
class QuotaStatus:
    used_bytes: int
    soft_limit_bytes: int | None
    hard_limit_bytes: int | None
    soft_exceeded: bool
    hard_exceeded: bool


def estimate_encrypted_size(plain_size: int) -> int:
    """Calculate exact framed ciphertext size produced by iter_wrap/wrap."""
    if plain_size <= 0:
        return HEADER_LEN + 4 + TAG_LEN
    num_chunks = (plain_size + CHUNK_SIZE - 1) // CHUNK_SIZE
    return HEADER_LEN + plain_size + num_chunks * (4 + TAG_LEN)


def dir_size_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total


# A108: the hard-quota path used to walk the whole blob directory on every
# reservation. Reservations instead read a short-TTL cached snapshot; the
# exact walk remains available via dir_size_bytes for reporting paths.
_DIR_SIZE_CACHE_TTL_SECONDS = 5.0
_dir_size_cache: dict[str, tuple[float, int]] = {}


def dir_size_bytes_cached(root: Path, *, ttl_seconds: float = _DIR_SIZE_CACHE_TTL_SECONDS) -> int:
    import time

    key = str(root)
    now_mono = time.monotonic()
    entry = _dir_size_cache.get(key)
    if entry is not None and entry[0] > now_mono:
        return entry[1]
    value = dir_size_bytes(root)
    _dir_size_cache[key] = (now_mono + ttl_seconds, value)
    return value


def _clear_dir_size_cache() -> None:
    _dir_size_cache.clear()


def check_quota(
    root: Path,
    *,
    soft_limit_bytes: int | None = None,
    hard_limit_bytes: int | None = None,
    reserved_bytes: int = 0,
) -> QuotaStatus:
    used = dir_size_bytes(root) + max(0, reserved_bytes)
    soft = soft_limit_bytes
    hard = hard_limit_bytes
    return QuotaStatus(
        used_bytes=used,
        soft_limit_bytes=soft,
        hard_limit_bytes=hard,
        soft_exceeded=soft is not None and used >= soft,
        hard_exceeded=hard is not None and used >= hard,
    )


def get_active_reserved_bytes(session: Session, now: datetime | None = None) -> int:
    from mail_core.mail.storage.models import BlobQuotaReservation

    now = now or datetime.now(timezone.utc)
    stmt = (
        select(func.coalesce(func.sum(BlobQuotaReservation.reserved_bytes), 0))
        .where(BlobQuotaReservation.expires_at > now)
    )
    return int(session.scalar(stmt) or 0)


def _lock_hard_quota_reservations(session: Session) -> None:
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("hard quota reservations require PostgreSQL advisory locks")
    session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :resource)"),
        {
            "namespace": QUOTA_RESERVATION_LOCK_NAMESPACE,
            "resource": QUOTA_RESERVATION_LOCK_RESOURCE,
        },
    )


def reserve_quota(
    session: Session,
    *,
    root: Path,
    needed_bytes: int,
    worker_id: str,
    message_id: uuid.UUID | None = None,
    hard_limit_bytes: int | None = None,
    ttl_seconds: int = 300,
    now: datetime | None = None,
) -> uuid.UUID | None:
    """Atomically reserve ciphertext quota before physical disk write.

    Returns the reservation_id on success, or None when no reservation
    is needed (needed_bytes <= 0). Raises QuotaExceededError when the
    hard limit would be exceeded (A108) — the two outcomes are no longer
    conflated into one ambiguous None.

    The directory size snapshot is taken (via the TTL cache) *before*
    the advisory lock is acquired, so the lock's critical section covers
    only reading active reservations, deciding, and inserting.
    """
    if needed_bytes <= 0:
        return None
    now = now or datetime.now(timezone.utc)
    if hard_limit_bytes is not None:
        disk_used = dir_size_bytes_cached(root)
        _lock_hard_quota_reservations(session)
        active_reserved = get_active_reserved_bytes(session, now=now)
        if disk_used + active_reserved + needed_bytes > hard_limit_bytes:
            raise QuotaExceededError(
                f"hard quota exceeded: used={disk_used} reserved={active_reserved} "
                f"needed={needed_bytes} hard_limit={hard_limit_bytes}"
            )
    from mail_core.mail.storage.models import BlobQuotaReservation

    res_id = uuid.uuid4()
    res = BlobQuotaReservation(
        id=res_id,
        worker_id=worker_id,
        message_id=message_id,
        reserved_bytes=needed_bytes,
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    session.add(res)
    session.flush()
    return res_id


def release_quota_reservation(session: Session, reservation_id: uuid.UUID | None) -> None:
    if reservation_id is None:
        return
    from mail_core.mail.storage.models import BlobQuotaReservation

    res = session.get(BlobQuotaReservation, reservation_id)
    if res is not None:
        session.delete(res)
        session.flush()


def prune_expired_quota_reservations(session: Session, now: datetime | None = None) -> int:
    from mail_core.mail.storage.models import BlobQuotaReservation
    from sqlalchemy import delete

    now = now or datetime.now(timezone.utc)
    ids = list(
        session.scalars(
            select(BlobQuotaReservation.id)
            .where(BlobQuotaReservation.expires_at <= now)
            .limit(1000)
        ).all()
    )
    if not ids:
        return 0
    session.execute(delete(BlobQuotaReservation).where(BlobQuotaReservation.id.in_(ids)))
    session.flush()
    return len(ids)


def digest_to_lock_id(digest: str) -> int:
    """Map a 64-character hex SHA-256 digest to a signed 64-bit int for PostgreSQL advisory locks."""
    val = int(digest[:16], 16)
    if val >= (1 << 63):
        val -= (1 << 64)
    return val


def acquire_blob_digest_lock(session: Session, digest: str) -> None:
    """Acquire transaction-level advisory lock on PostgreSQL for the given blob digest."""
    bind = getattr(session, "bind", None) or (session.get_bind() if hasattr(session, "get_bind") else None)
    if bind is None or getattr(getattr(bind, "dialect", None), "name", None) != "postgresql":
        return

    from sqlalchemy import text

    lock_id = digest_to_lock_id(digest)
    try:
        session.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": lock_id})
    except Exception:
        log.exception("failed to acquire PostgreSQL blob digest advisory lock")
        raise


