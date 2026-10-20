"""Bounded MIME archive scheduler (architecture §8).

Never pre-creates millions of job rows; selects a limited batch each run.
"""

from __future__ import annotations

import email
from email.policy import default as default_policy
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_, select, update

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.blobs.quota import check_quota
from mail_core.blobs.store import BlobStore
from mail_core.mail.domain.archive import apply_transition
from mail_core.security.redact import safe_error
from mail_core.mail.domain.enums import ArchiveState, JobType, OutboxEventType
from mail_core.mail.storage.models import (
    Account,
    Attachment,
    Message,
    MessageArchiveState,
    MessageBlob,
    MessageBlobLink,
    MessageBody,
    OutboxEvent,
)
from mail_core.providers.factory import build_provider
from mail_core.sync.jobs import enqueue_job
from mail_core.sync.leases import (
    FencingMismatch,
    LeaseBusy,
    acquire_lease,
    assert_fencing,
    release_lease,
    renew_lease,
)

log = logging.getLogger("mail_core.blobs.archive")

DEFAULT_RECENT_DAYS = 30
DEFAULT_BATCH = 20


def blob_root() -> Path:
    return Path(os.environ.get("MAIL_CORE_BLOB_ROOT", "/tmp/kkmail-mail-core-blobs"))


def parse_mime_content(
    mime_bytes: bytes,
) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """Parse raw MIME bytes into (text_plain, text_html, attachments)."""
    msg = email.message_from_bytes(mime_bytes, policy=default_policy)
    text_plain_parts: list[str] = []
    text_html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []

    part_index = 0
    for part in msg.walk():
        if part.is_multipart():
            continue

        disposition = part.get_content_disposition()
        filename = part.get_filename()
        content_id_raw = part.get("Content-ID")
        content_id = content_id_raw.strip("<>") if content_id_raw else None
        content_type = part.get_content_type() or "application/octet-stream"

        is_attachment = disposition == "attachment" or filename is not None
        is_inline_asset = (
            disposition == "inline"
            and (content_id is not None or not content_type.startswith("text/"))
        ) or (
            not disposition
            and not filename
            and not content_type.startswith("text/")
        )

        if is_attachment or is_inline_asset:
            part_index += 1
            payload = part.get_payload(decode=True)
            if payload is None:
                raw_p = part.get_payload()
                if isinstance(raw_p, str):
                    payload = raw_p.encode("utf-8", errors="replace")
                elif isinstance(raw_p, bytes):
                    payload = raw_p
                else:
                    payload = b""

            clean_filename = Path(filename).name if filename else ""
            if not clean_filename:
                param_name = part.get_param("name")
                if param_name:
                    clean_filename = Path(str(param_name)).name
            if not clean_filename:
                clean_filename = f"inline_{content_id}" if content_id else f"attachment_{part_index}.bin"

            attachments.append(
                {
                    "filename": clean_filename[:512],
                    "content_type": content_type[:255],
                    "size_bytes": len(payload),
                    "content_id": content_id[:255] if content_id else None,
                    "is_inline": disposition == "inline" or bool(content_id),
                    "data": payload,
                }
            )
        else:
            try:
                content = part.get_content()
            except Exception:
                raw = part.get_payload(decode=True)
                if isinstance(raw, bytes):
                    content = raw.decode("utf-8", errors="replace")
                elif isinstance(raw, str):
                    content = raw
                else:
                    content = ""
            if not isinstance(content, str):
                content = str(content)

            if content_type == "text/plain":
                text_plain_parts.append(content)
            elif content_type == "text/html":
                text_html_parts.append(content)

    text_plain = "\n\n".join(text_plain_parts) if text_plain_parts else None
    text_html = "\n".join(text_html_parts) if text_html_parts else None
    return text_plain, text_html, attachments


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
            apply_transition(state, ArchiveState.ARCHIVE_PENDING)
            state.priority = _priority_for(msg.sort_time, now=now, recent_days=recent_days)
        apply_transition(state, ArchiveState.ARCHIVE_IN_PROGRESS)
        state.claimed_by = worker_id
        state.claimed_at = now
        state.updated_at = now
        claimed.append(msg.id)
    session.flush()
    return claimed


def reclaim_stale_archive_claims(
    session,
    *,
    older_than: timedelta = timedelta(minutes=15),
    now: datetime | None = None,
    limit: int = 100,
) -> int:
    """Return stuck ``archive_in_progress`` rows to ``archive_pending``.

    Workers that die mid-fetch leave claims forever; reclaim so another batch can retry.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - older_than
    stmt = (
        select(MessageArchiveState)
        .where(MessageArchiveState.state == ArchiveState.ARCHIVE_IN_PROGRESS.value)
        .where(MessageArchiveState.claimed_at.is_not(None))
        .where(MessageArchiveState.claimed_at < cutoff)
        .order_by(MessageArchiveState.claimed_at.asc())
        .with_for_update(skip_locked=True)
        .limit(max(1, int(limit)))
    )
    rows = list(session.scalars(stmt).all())
    for st in rows:
        apply_transition(st, ArchiveState.ARCHIVE_PENDING)
        st.claimed_by = None
        st.claimed_at = None
        st.updated_at = now
        suffix = "|reclaimed_stale_archive_claim"
        prev = st.last_error or ""
        if suffix not in prev:
            st.last_error = (prev + suffix)[:2000]
    session.flush()
    return len(rows)


def _pause_quota(
    session,
    message_ids: list[uuid.UUID],
    account_id: uuid.UUID | None,
    worker_id: str | None = None,
) -> None:
    paused_count = 0
    for mid in message_ids:
        st = session.get(MessageArchiveState, mid)
        if st is None:
            continue
        if worker_id is not None and st.claimed_by != worker_id:
            continue
        if st.state != ArchiveState.ARCHIVE_IN_PROGRESS.value:
            continue
        apply_transition(st, ArchiveState.ARCHIVE_PAUSED_QUOTA)
        st.pause_reason = "quota"
        st.claimed_by = None
        st.updated_at = datetime.now(timezone.utc)
        paused_count += 1
    session.add(
        OutboxEvent(
            event_type=OutboxEventType.ARCHIVE_PAUSED_QUOTA.value,
            account_id=account_id,
            payload={"count": paused_count},
        )
    )


def resume_quota_paused_archives(
    session=None,
    *,
    account_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> int:
    """Reset ARCHIVE_PAUSED_QUOTA messages to ARCHIVE_PENDING and enqueue archive job."""
    Session = __import__("mail_core.db.session", fromlist=["get_session_factory"]).get_session_factory()

    def _do_resume(s) -> int:
        stmt = (
            select(MessageArchiveState)
            .where(MessageArchiveState.state == ArchiveState.ARCHIVE_PAUSED_QUOTA.value)
            .order_by(MessageArchiveState.updated_at.asc())
        )
        if account_id is not None:
            stmt = stmt.join(Message, Message.id == MessageArchiveState.message_id).where(
                Message.account_id == account_id
            )
        if limit is not None:
            stmt = stmt.limit(limit)
        stmt = stmt.with_for_update(skip_locked=True)
        rows = list(s.scalars(stmt).all())
        now = datetime.now(timezone.utc)
        for st in rows:
            apply_transition(st, ArchiveState.ARCHIVE_PENDING)
            st.pause_reason = None
            st.claimed_by = None
            st.claimed_at = None
            st.updated_at = now

        if rows:
            if account_id is not None:
                enqueue_job(
                    s,
                    job_type=JobType.ARCHIVE_MIME_BATCH.value,
                    account_id=account_id,
                    priority=50,
                )
            else:
                mids = [st.message_id for st in rows]
                acc_ids = list(s.scalars(select(Message.account_id).where(Message.id.in_(mids)).distinct()).all())
                for aid in acc_ids:
                    enqueue_job(
                        s,
                        job_type=JobType.ARCHIVE_MIME_BATCH.value,
                        account_id=aid,
                        priority=50,
                    )
            s.add(
                OutboxEvent(
                    event_type=OutboxEventType.ARCHIVE_PROGRESS.value,
                    account_id=account_id,
                    payload={"resumed_from_quota": len(rows)},
                )
            )
        return len(rows)

    if session is not None:
        count = _do_resume(session)
        session.flush()
        return count
    else:
        with Session() as s:
            count = _do_resume(s)
            s.commit()
            return count


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
    if quota.hard_exceeded or quota.soft_exceeded:
        with Session() as session:
            # Nothing claimed yet — emit pause event and stop (soft + hard).
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.ARCHIVE_PAUSED_QUOTA.value,
                    account_id=account_id,
                    payload={
                        "used_bytes": quota.used_bytes,
                        "soft_limit_bytes": soft_i,
                        "hard_limit_bytes": hard_i,
                        "soft_exceeded": quota.soft_exceeded,
                        "hard_exceeded": quota.hard_exceeded,
                    },
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

    for idx, (mid, remote_id, msg_account_id) in enumerate(work):
        # Re-check quota before each download
        quota = check_quota(root, soft_limit_bytes=soft_i, hard_limit_bytes=hard_i)
        if quota.hard_exceeded or quota.soft_exceeded:
            with Session() as session:
                # O(n) slice from current index — avoid work.index (O(n²) over the loop).
                remaining = [w[0] for w in work[idx:]]
                _pause_quota(session, remaining, account_id, worker_id=worker_id)
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

        # Heartbeat account lease during batch downloads (R10)
        if account_id is not None and fencing is not None:
            try:
                with Session() as session:
                    renew_lease(
                        session,
                        account_id=account_id,
                        owner_id=worker_id,
                        fencing_token=fencing,
                        ttl=timedelta(seconds=120),
                    )
                    session.commit()
            except FencingMismatch:
                return {"status": "fencing_mismatch", "completed": completed, "failed": failed}

        try:
            mime = provider.fetch_mime(remote_id)  # network
            write = blob_store.put(mime)
        except Exception as exc:
            log.warning("archive fetch failed message=%s: %s", mid, safe_error(exc))
            with Session() as session:
                if account_id is not None and fencing is not None:
                    try:
                        assert_fencing(session, account_id=account_id, fencing_token=fencing)
                    except FencingMismatch:
                        return {"status": "fencing_mismatch", "completed": completed, "failed": failed}
                st = session.get(MessageArchiveState, mid)
                if (
                    st is not None
                    and st.claimed_by == worker_id
                    and st.state == ArchiveState.ARCHIVE_IN_PROGRESS.value
                ):
                    st.retry_count = int(st.retry_count) + 1
                    st.last_error = safe_error(exc)
                    apply_transition(
                        st,
                        ArchiveState.ARCHIVE_FAILED if st.retry_count >= 5 else ArchiveState.ARCHIVE_PENDING,
                    )
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
            if (
                st is None
                or st.state != ArchiveState.ARCHIVE_IN_PROGRESS.value
                or st.claimed_by != worker_id
            ):
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
                    ref_count=0,
                )
                session.add(blob)
                session.flush()
            if session.get(MessageBlobLink, mid) is None:
                # ref_count tracks links: only a new link takes a reference.
                session.add(MessageBlobLink(message_id=mid, blob_id=blob.id))
                blob.ref_count = int(blob.ref_count) + 1
                blob.gc_eligible_at = None

            # Parse MIME body and attachments into domain models (V2-03)
            try:
                plain_text, html_text, parsed_attachments = parse_mime_content(mime)
                body = session.get(MessageBody, mid)
                if body is None:
                    session.add(MessageBody(message_id=mid, text_plain=plain_text, text_html=html_text))
                else:
                    body.text_plain = plain_text
                    body.text_html = html_text
                    body.parse_error = None
                    body.updated_at = datetime.now(timezone.utc)

                if parsed_attachments:
                    msg_record = session.get(Message, mid)
                    if msg_record is not None:
                        msg_record.has_attachments = True

                    existing_atts = session.scalars(
                        select(Attachment).where(Attachment.message_id == mid)
                    ).all()
                    existing_keys = {
                        (att.filename, att.content_id) for att in existing_atts
                    }

                    for att_info in parsed_attachments:
                        key = (att_info["filename"], att_info["content_id"])
                        if key in existing_keys:
                            continue
                        existing_keys.add(key)

                        att_write = blob_store.put(att_info["data"])
                        att_blob = session.scalar(
                            select(MessageBlob).where(
                                MessageBlob.content_sha256 == att_write.content_sha256,
                                MessageBlob.key_version == att_write.key_version,
                            )
                        )
                        if att_blob is None:
                            att_blob = MessageBlob(
                                content_sha256=att_write.content_sha256,
                                key_version=att_write.key_version,
                                size_bytes=att_write.size_bytes,
                                storage_path=att_write.storage_path,
                                ref_count=0,
                            )
                            session.add(att_blob)
                            session.flush()

                        attachment = Attachment(
                            message_id=mid,
                            blob_id=att_blob.id,
                            filename=att_info["filename"],
                            content_type=att_info["content_type"],
                            size_bytes=att_info["size_bytes"],
                            content_id=att_info["content_id"],
                            is_inline=att_info["is_inline"],
                        )
                        session.add(attachment)
                        att_blob.ref_count = int(att_blob.ref_count) + 1
                        att_blob.gc_eligible_at = None
            except Exception as parse_exc:
                log.warning("archive mime parse error for message %s: %s", mid, safe_error(parse_exc))
                body = session.get(MessageBody, mid)
                if body is None:
                    session.add(MessageBody(message_id=mid, parse_error=safe_error(parse_exc)[:2000]))
                else:
                    body.parse_error = safe_error(parse_exc)[:2000]

            apply_transition(st, ArchiveState.ARCHIVE_COMPLETE)
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
        elif failed > 0:
            # Batch fully failed: continue scheduling retries with backoff (V2-30 / R08)
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.ARCHIVE_PROGRESS.value,
                    account_id=account_id,
                    payload={"completed": completed, "failed": failed},
                )
            )
            enqueue_job(
                session,
                job_type=JobType.ARCHIVE_MIME_BATCH.value,
                account_id=account_id,
                payload={"batch_size": limit, "recent_days": recent_days,
                         "soft_limit_bytes": soft_i, "hard_limit_bytes": hard_i},
                priority=90,
                run_after=datetime.now(timezone.utc) + timedelta(seconds=30),
            )
        if account_id is not None and fencing is not None:
            try:
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
            except FencingMismatch:
                pass
        session.commit()

    return {"status": "ok", "completed": completed, "failed": failed, "claimed": len(work)}
