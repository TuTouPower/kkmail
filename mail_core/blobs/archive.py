"""Bounded MIME archive scheduler (architecture §8).

Never pre-creates millions of job rows; selects a limited batch each run.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import and_, or_, select, update

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.blobs.quota import check_quota
from mail_core.blobs.store import BlobStore
from mail_core.mail.domain.archive import assert_transition
from mail_core.mail.domain.enums import ArchiveState, JobType, OutboxEventType
from mail_core.mail.storage.models import (
    Account,
    Message,
    MessageArchiveState,
    MessageBlob,
    MessageBlobLink,
    OutboxEvent,
)
from mail_core.providers.factory import build_provider
from mail_core.sync.jobs import enqueue_job
from mail_core.sync.leases import FencingMismatch, LeaseBusy, acquire_lease, assert_fencing, release_lease

log = logging.getLogger("mail_core.blobs.archive")

DEFAULT_RECENT_DAYS = 30
DEFAULT_BATCH = 20


def blob_root() -> Path:
    return Path(os.environ.get("MAIL_CORE_BLOB_ROOT", "[REDACTED]mail-core-blobs"))


def _priority_for(sort_time: datetime, *, now: datetime, recent_days: int) -> int:
    age = now - sort_time
    if age <= timedelta(days=recent_days):
        return 1  # P1 recent
    return 2  # P2 older


def claim_archive_batch(
    session,
    *,
    account_id: uuid.UUID | None,
    worker_id: str,
    limit: int,
    recent_days: int,
    now: datetime | None = None,
) -> list[uuid.UUID]:
    """Select metadata_synced / pending rows and mark archive_in_progress."""
    now = now or datetime.now(timezone.utc)
    stmt = (
        select(MessageArchiveState, Message)
        .join(Message, Message.id == MessageArchiveState.message_id)
        .where(
            MessageArchiveState.state.in_(
                [
                    ArchiveState.METADATA_SYNCED.value,
                    ArchiveState.ARCHIVE_PENDING.value,
                ]
            )
        )
        .order_by(MessageArchiveState.priority.asc(), Message.sort_time.desc())
        .limit(limit)
        .with_for_update(of=MessageArchiveState, skip_locked=True)
    )
    if account_id is not None:
        stmt = stmt.where(Message.account_id == account_id)
    rows = list(session.execute(stmt).all())
    claimed: list[uuid.UUID] = []
    for state, msg in rows:
        # Promote metadata_synced → pending → in_progress
        if state.state == ArchiveState.METADATA_SYNCED.value:
            assert_transition(ArchiveState.METADATA_SYNCED, ArchiveState.ARCHIVE_PENDING)
            state.state = ArchiveState.ARCHIVE_PENDING.value
            state.priority = _priority_for(msg.sort_time, now=now, recent_days=recent_days)
        assert_transition(ArchiveState(state.state), ArchiveState.ARCHIVE_IN_PROGRESS)
        state.state = ArchiveState.ARCHIVE_IN_PROGRESS.value
        state.claimed_by = worker_id
        state.claimed_at = now
        state.updated_at = now
        claimed.append(msg.id)
    session.flush()
    return claimed


def _pause_quota(session, message_ids: list[uuid.UUID], account_id: uuid.UUID | None) -> None:
    for mid in message_ids:
        st = session.get(MessageArchiveState, mid)
        if st is None:
            continue
        st.state = ArchiveState.ARCHIVE_PAUSED_QUOTA.value
        st.pause_reason = "hard_quota"
        st.claimed_by = None
        st.updated_at = datetime.now(timezone.utc)
    session.add(
        OutboxEvent(
            event_type=OutboxEventType.ARCHIVE_PAUSED_QUOTA.value,
            account_id=account_id,
            payload={"count": len(message_ids)},
        )
    )


def run_archive_batch(
    *,
    account_id: uuid.UUID | None,
    worker_id: str,
    store: CredentialStore | None = None,
    payload: dict | None = None,
) -> dict:
    payload = payload or {}
    limit = int(payload.get("batch_size") or os.environ.get("MAIL_CORE_ARCHIVE_BATCH") or DEFAULT_BATCH)
    recent_days = int(payload.get("recent_days") or DEFAULT_RECENT_DAYS)
    soft = payload.get("soft_limit_bytes")
    hard = payload.get("hard_limit_bytes")
    soft_i = int(soft) if soft is not None else (
        int(os.environ["MAIL_CORE_BLOB_SOFT_BYTES"]) if os.environ.get("MAIL_CORE_BLOB_SOFT_BYTES") else None
    )
    hard_i = int(hard) if hard is not None else (
        int(os.environ["MAIL_CORE_BLOB_HARD_BYTES"]) if os.environ.get("MAIL_CORE_BLOB_HARD_BYTES") else None
    )

    root = blob_root()
    blob_store = BlobStore(root)
    Session = __import__("mail_core.db.session", fromlist=["get_session_factory"]).get_session_factory()

    fencing = None
    if account_id is not None:
        with Session() as session:
            try:
                lease = acquire_lease(session, account_id=account_id, owner_id=worker_id, ttl=timedelta(seconds=120))
            except LeaseBusy:
                return {"status": "lease_busy"}
            fencing = lease.fencing_token
            session.commit()

    quota = check_quota(root, soft_limit_bytes=soft_i, hard_limit_bytes=hard_i)
    if quota.hard_exceeded:
        with Session() as session:
            # Nothing claimed yet — emit pause event and stop.
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.ARCHIVE_PAUSED_QUOTA.value,
                    account_id=account_id,
                    payload={"used_bytes": quota.used_bytes, "hard_limit_bytes": hard_i},
                )
            )
            if account_id is not None and fencing is not None:
                try:
                    release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                except FencingMismatch:
                    pass
            session.commit()
        return {"status": "paused_quota", "used_bytes": quota.used_bytes}

    with Session() as session:
        if account_id is not None and fencing is not None:
            try:
                assert_fencing(session, account_id=account_id, fencing_token=fencing)
            except FencingMismatch:
                return {"status": "fencing_mismatch"}
        claimed_ids = claim_archive_batch(
            session,
            account_id=account_id,
            worker_id=worker_id,
            limit=limit,
            recent_days=recent_days,
        )
        # Load remote ids + account for provider
        work: list[tuple[uuid.UUID, str, uuid.UUID]] = []
        for mid in claimed_ids:
            msg = session.get(Message, mid)
            if msg is None:
                continue
            work.append((mid, msg.remote_id, msg.account_id))
        session.commit()

    completed = 0
    failed = 0
    provider_cache: dict[uuid.UUID, object] = {}

    for mid, remote_id, msg_account_id in work:
        # Re-check quota before each download
        quota = check_quota(root, soft_limit_bytes=soft_i, hard_limit_bytes=hard_i)
        if quota.hard_exceeded:
            with Session() as session:
                remaining = [mid] + [w[0] for w in work[work.index((mid, remote_id, msg_account_id)) + 1 :]]
                _pause_quota(session, remaining, account_id)
                if account_id is not None and fencing is not None:
                    try:
                        release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                    except FencingMismatch:
                        pass
                session.commit()
            return {
                "status": "paused_quota",
                "completed": completed,
                "failed": failed,
                "used_bytes": quota.used_bytes,
            }

        if msg_account_id not in provider_cache:
            with Session() as session:
                acc = session.get(Account, msg_account_id)
                snap = Account(
                    id=acc.id,
                    email=acc.email,
                    provider=acc.provider,
                    credential_ref=acc.credential_ref,
                    config=dict(acc.config or {}),
                )
            provider_cache[msg_account_id] = build_provider(snap, store or get_credential_store())
        provider = provider_cache[msg_account_id]

        try:
            mime = provider.fetch_mime(remote_id)  # network
            write = blob_store.put(mime)
        except Exception as exc:
            log.warning("archive fetch failed message=%s: %s", mid, exc)
            with Session() as session:
                st = session.get(MessageArchiveState, mid)
                if st is not None:
                    st.retry_count = int(st.retry_count) + 1
                    st.last_error = str(exc)
                    if st.retry_count >= 5:
                        st.state = ArchiveState.ARCHIVE_FAILED.value
                    else:
                        st.state = ArchiveState.ARCHIVE_PENDING.value
                    st.claimed_by = None
                    st.updated_at = datetime.now(timezone.utc)
                session.commit()
            failed += 1
            continue

        with Session() as session:
            if account_id is not None and fencing is not None:
                try:
                    assert_fencing(session, account_id=account_id, fencing_token=fencing)
                except FencingMismatch:
                    return {"status": "fencing_mismatch", "completed": completed, "failed": failed}
            st = session.get(MessageArchiveState, mid)
            if st is None or st.state != ArchiveState.ARCHIVE_IN_PROGRESS.value:
                continue
            blob = session.scalar(
                select(MessageBlob).where(
                    MessageBlob.content_sha256 == write.content_sha256,
                    MessageBlob.key_version == write.key_version,
                )
            )
            if blob is None:
                blob = MessageBlob(
                    content_sha256=write.content_sha256,
                    key_version=write.key_version,
                    size_bytes=write.size_bytes,
                    storage_path=write.storage_path,
                    ref_count=1,
                )
                session.add(blob)
                session.flush()
            else:
                blob.ref_count = int(blob.ref_count) + 1
            existing_link = session.get(MessageBlobLink, mid)
            if existing_link is None:
                session.add(MessageBlobLink(message_id=mid, blob_id=blob.id))
            assert_transition(ArchiveState.ARCHIVE_IN_PROGRESS, ArchiveState.ARCHIVE_COMPLETE)
            st.state = ArchiveState.ARCHIVE_COMPLETE.value
            st.claimed_by = None
            st.updated_at = datetime.now(timezone.utc)
            completed += 1
            session.commit()

    with Session() as session:
        if completed:
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.ARCHIVE_PROGRESS.value,
                    account_id=account_id,
                    payload={"completed": completed, "failed": failed},
                )
            )
            # Schedule another batch if work may remain
            enqueue_job(
                session,
                job_type=JobType.ARCHIVE_MIME_BATCH.value,
                account_id=account_id,
                payload={"batch_size": limit, "recent_days": recent_days,
                         "soft_limit_bytes": soft_i, "hard_limit_bytes": hard_i},
                priority=90,
            )
        if account_id is not None and fencing is not None:
            try:
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
            except FencingMismatch:
                pass
        session.commit()

    return {"status": "ok", "completed": completed, "failed": failed, "claimed": len(work)}
