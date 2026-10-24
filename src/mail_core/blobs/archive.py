"""Bounded MIME archive scheduler (architecture §8).

Never pre-creates millions of job rows; selects a limited batch each run.
"""

from __future__ import annotations

import email
import email.errors
from email.policy import default as default_policy
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from mail_core.accounts.credentials import CredentialStore, get_credential_store
from mail_core.blobs.quota import (
    acquire_blob_digest_lock,
    check_quota,
    estimate_encrypted_size,
    release_quota_reservation,
    reserve_quota,
)
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


class QuotaExceededError(RuntimeError):
    """Raised when blob write would exceed hard quota."""


class MimeParseError(RuntimeError):
    """Raised when MIME body, header, or attachment filename parsing/decoding fails."""

    def __init__(
        self,
        stage: str,
        detail: str,
        *,
        partial_plain: str | None = None,
        partial_html: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ):
        super().__init__(f"{stage}: {detail}")
        self.stage = stage
        self.detail = detail
        self.partial_plain = partial_plain
        self.partial_html = partial_html
        self.attachments = attachments or []


def blob_root() -> Path:
    return Path(os.environ.get("MAIL_CORE_BLOB_ROOT", "/tmp/kkmail-mail-core-blobs"))


def parse_mime_content(
    mime_bytes: bytes,
) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """Parse raw MIME bytes into (text_plain, text_html, attachments)."""
    first_error: MimeParseError | None = None
    try:
        msg = email.message_from_bytes(mime_bytes, policy=default_policy)
    except Exception as exc:
        raise MimeParseError("header", f"header_parse_failed: {safe_error(exc)}") from exc

    for defect in getattr(msg, "defects", ()):
        if isinstance(defect, (email.errors.HeaderDefect, email.errors.CharsetError, email.errors.UndecodableBytesDefect)):
            if first_error is None:
                first_error = MimeParseError("header", f"header_defect: {type(defect).__name__}")

    for header_name, header_value in msg.items():
        for defect in getattr(header_value, "defects", ()):
            if isinstance(defect, (email.errors.UndecodableBytesDefect, email.errors.CharsetError)):
                if first_error is None:
                    first_error = MimeParseError("header", f"header_defect in {header_name}: {type(defect).__name__}")

    text_plain_parts: list[str] = []
    text_html_parts: list[str] = []
    attachments: list[dict[str, Any]] = []

    part_index = 0
    for part in msg.walk():
        if part.is_multipart():
            continue

        try:
            disposition = part.get_content_disposition()
            filename = part.get_filename()
        except Exception as exc:
            if first_error is None:
                first_error = MimeParseError("attachment", f"attachment_filename_failed: {safe_error(exc)}")
            disposition = None
            filename = None

        cd = part.get("Content-Disposition")
        if cd and hasattr(cd, "defects"):
            for d in cd.defects:
                if isinstance(d, (email.errors.UndecodableBytesDefect, email.errors.CharsetError)):
                    if first_error is None:
                        first_error = MimeParseError("attachment", f"attachment_filename_failed: {type(d).__name__}")
        ct = part.get("Content-Type")
        if ct and hasattr(ct, "defects"):
            for d in ct.defects:
                if isinstance(d, (email.errors.UndecodableBytesDefect, email.errors.CharsetError)):
                    if first_error is None:
                        first_error = MimeParseError("attachment", f"attachment_filename_failed: {type(d).__name__}")

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
                    "part_id": str(part_index),
                    "filename": clean_filename[:512],
                    "content_type": content_type[:255],
                    "size_bytes": len(payload),
                    "content_id": content_id[:255] if content_id else None,
                    "is_inline": disposition == "inline" or bool(content_id),
                    "data": payload,
                }
            )
        else:
            for defect in getattr(part, "defects", ()):
                if isinstance(defect, (email.errors.UndecodableBytesDefect, email.errors.CharsetError)):
                    if first_error is None:
                        first_error = MimeParseError("body", f"body_defect: {type(defect).__name__}")

            content: str | None = None
            try:
                content = part.get_content(errors="strict")
            except UnicodeDecodeError as ude:
                if first_error is None:
                    first_error = MimeParseError("body", f"body_decode_failed: {safe_error(ude)}")
                param_charset = part.get_param("charset")
                raw_payload = part.get_payload(decode=True)
                if isinstance(raw_payload, bytes):
                    charsets = []
                    if param_charset:
                        charsets.append(str(param_charset).strip("'\""))
                    charsets.extend(["utf-8", "gb18030", "gb2312", "windows-1252", "latin-1"])
                    for cs in charsets:
                        try:
                            content = raw_payload.decode(cs, errors="replace")
                            break
                        except (LookupError, UnicodeError):
                            continue
                    if content is None:
                        content = raw_payload.decode("utf-8", errors="replace")
                elif isinstance(raw_payload, str):
                    content = raw_payload
            except Exception as body_exc:
                if first_error is None:
                    first_error = MimeParseError("body", f"body_decode_failed: {safe_error(body_exc)}")
                raw_payload = part.get_payload(decode=True)
                if isinstance(raw_payload, bytes):
                    try:
                        content = raw_payload.decode("utf-8", errors="replace")
                    except Exception:
                        content = None

            if content is not None:
                if not isinstance(content, str):
                    content = str(content)
                if content_type == "text/plain":
                    text_plain_parts.append(content)
                elif content_type == "text/html":
                    text_html_parts.append(content)

    text_plain = "\n\n".join(text_plain_parts) if text_plain_parts else None
    text_html = "\n".join(text_html_parts) if text_html_parts else None

    if first_error is not None:
        first_error.partial_plain = text_plain
        first_error.partial_html = text_html
        first_error.attachments = attachments
        raise first_error

    return text_plain, text_html, attachments


def _priority_for(sort_time: datetime | None, *, now: datetime, recent_days: int) -> int:
    if sort_time is None:
        return 2  # Unknown dates are scheduled with older messages.
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
    target_message_id: uuid.UUID | None = None,
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
            ),
            MessageArchiveState.claimed_by.is_(None),
            MessageArchiveState.retry_count < 5,
            Message.remote_id.is_not(None),
            Message.remote_id != "",
        )
    )
    if account_id is not None:
        stmt = stmt.where(Message.account_id == account_id)
    if target_message_id is not None:
        stmt = stmt.where(Message.id == target_message_id)
    stmt = (
        stmt.order_by(MessageArchiveState.priority.asc(), Message.sort_time.desc().nulls_last())
        .limit(limit)
        .with_for_update(of=MessageArchiveState, skip_locked=True)
    )
    rows = list(session.execute(stmt).all())
    claimed: list[uuid.UUID] = []
    for state, msg in rows:
        # Promote metadata_synced → pending → in_progress
        if state.state == ArchiveState.METADATA_SYNCED.value:
            apply_transition(state, ArchiveState.ARCHIVE_PENDING)
            if state.priority is None or state.priority > 0:
                state.priority = _priority_for(msg.sort_time, now=now, recent_days=recent_days)
        apply_transition(state, ArchiveState.ARCHIVE_IN_PROGRESS)
        state.claimed_by = worker_id
        state.claimed_at = now
        state.updated_at = now
        claimed.append(msg.id)
    session.flush()
    if target_message_id is not None and target_message_id not in claimed:
        target_st = session.get(MessageArchiveState, target_message_id)
        log.info(
            "claim_archive_batch target_message_id=%s not claimed: state=%s claimed_by=%s retry_count=%s",
            target_message_id,
            getattr(target_st, "state", None),
            getattr(target_st, "claimed_by", None),
            getattr(target_st, "retry_count", None),
        )
    return claimed


def _release_fencing_claims(session, message_ids: list[uuid.UUID], worker_id: str) -> None:
    for mid in message_ids:
        st = session.get(MessageArchiveState, mid)
        if st is not None and st.claimed_by == worker_id:
            st.claimed_by = None
            apply_transition(st, ArchiveState.ARCHIVE_PENDING)
            st.updated_at = datetime.now(timezone.utc)


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
        log.info(
            "reclaim_stale_archive_claim message_id=%s old_claimed_by=%s claimed_at=%s",
            st.message_id,
            st.claimed_by,
            st.claimed_at,
        )
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


def _release_archive_claims_and_lease(
    session,
    message_ids: list[uuid.UUID],
    *,
    worker_id: str,
    account_id: uuid.UUID | None = None,
    fencing: int | None = None,
    error: BaseException | str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    from mail_core.security.redact import safe_provider_summary

    err_str = safe_provider_summary(error) if error else None
    for mid in message_ids:
        st = session.get(MessageArchiveState, mid)
        if st is not None and st.claimed_by == worker_id and st.state == ArchiveState.ARCHIVE_IN_PROGRESS.value:
            apply_transition(st, ArchiveState.ARCHIVE_PENDING)
            st.claimed_by = None
            st.claimed_at = None
            st.updated_at = now
            if err_str:
                st.last_error = err_str
    if account_id is not None and fencing is not None:
        try:
            release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
        except FencingMismatch:
            pass


def resume_quota_paused_archives(
    session=None,
    *,
    account_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> int:
    """Reset ARCHIVE_PAUSED_QUOTA messages to ARCHIVE_PENDING and enqueue archive job."""

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
                    dedupe_key=f"archive_mime_batch:{account_id}",
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
                        dedupe_key=f"archive_mime_batch:{aid}",
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
        Session = __import__("mail_core.db.session", fromlist=["get_session_factory"]).get_session_factory()
        with Session() as s:
            count = _do_resume(s)
            s.commit()
            return count


def maybe_resume_quota_paused_archives(
    session=None,
    *,
    root: Path | None = None,
    account_id: uuid.UUID | None = None,
    limit: int = 100,
    soft_limit_bytes: int | None = None,
    hard_limit_bytes: int | None = None,
) -> int:
    """Check quota; if below recovery threshold, resume paused archives."""
    r = root or blob_root()
    soft = soft_limit_bytes if soft_limit_bytes is not None else (
        int(os.environ["MAIL_CORE_BLOB_SOFT_BYTES"]) if os.environ.get("MAIL_CORE_BLOB_SOFT_BYTES") else None
    )
    hard = hard_limit_bytes if hard_limit_bytes is not None else (
        int(os.environ["MAIL_CORE_BLOB_HARD_BYTES"]) if os.environ.get("MAIL_CORE_BLOB_HARD_BYTES") else None
    )
    quota = check_quota(r, soft_limit_bytes=soft, hard_limit_bytes=hard)
    if not quota.soft_exceeded and not quota.hard_exceeded:
        return resume_quota_paused_archives(session, account_id=account_id, limit=limit)
    return 0


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
                log.info("archive lease busy account=%s worker=%s", account_id, worker_id)
                return {"status": "lease_busy"}
            fencing = lease.fencing_token
            session.commit()

    quota = check_quota(root, soft_limit_bytes=soft_i, hard_limit_bytes=hard_i)
    current_used_bytes = quota.used_bytes
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

    # Capacity is below recovery threshold — automatically resume quota-paused archives (A25)
    resume_quota_paused_archives(account_id=account_id, limit=limit)

    target_msg_id = None
    if payload.get("message_id"):
        try:
            target_msg_id = uuid.UUID(str(payload["message_id"]))
        except (ValueError, TypeError):
            pass

    with Session() as session:
        if account_id is not None and fencing is not None:
            try:
                assert_fencing(session, account_id=account_id, fencing_token=fencing)
            except FencingMismatch:
                log.warning("archive fencing mismatch before claim account=%s worker=%s fencing=%s", account_id, worker_id, fencing)
                return {"status": "fencing_mismatch"}
        claimed_ids = claim_archive_batch(
            session,
            account_id=account_id,
            worker_id=worker_id,
            limit=limit,
            recent_days=recent_days,
            target_message_id=target_msg_id,
        )
        # Load remote ids + account for provider
        work: list[tuple[uuid.UUID, str, uuid.UUID]] = []
        for mid in claimed_ids:
            msg = session.get(Message, mid)
            if msg is None or not msg.remote_id or not msg.remote_id.strip():
                continue
            work.append((mid, msg.remote_id, msg.account_id))
        session.commit()

    completed = 0
    failed = 0
    provider_cache: dict[uuid.UUID, object] = {}

    for idx, (mid, remote_id, msg_account_id) in enumerate(work):
        # Incremental quota check: avoid per-message full disk walk (V4-01)
        soft_exceeded = soft_i is not None and current_used_bytes >= soft_i
        hard_exceeded = hard_i is not None and current_used_bytes >= hard_i
        if soft_exceeded or hard_exceeded:
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
                "used_bytes": current_used_bytes,
            }

        if msg_account_id not in provider_cache:
            try:
                with Session() as session:
                    acc = session.get(Account, msg_account_id)
                    snap = Account(
                        id=acc.id,
                        email=acc.email,
                        provider=acc.provider,
                        credential_ref=acc.credential_ref,
                        config=dict(acc.config or {}),
                    )
                p = build_provider(snap, store or get_credential_store())
                if hasattr(p, "open_session"):
                    try:
                        p.open_session()
                    except Exception as open_exc:
                        log.warning("open_session failed for %s: %s", msg_account_id, safe_error(open_exc))
                provider_cache[msg_account_id] = p
            except Exception as exc:
                with Session() as session:
                    remaining_ids = [w[0] for w in work[idx:]]
                    _release_archive_claims_and_lease(
                        session,
                        remaining_ids,
                        worker_id=worker_id,
                        account_id=account_id,
                        fencing=fencing,
                        error=exc,
                    )
                    session.commit()
                raise
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
                log.warning("archive fencing mismatch during renew account=%s worker=%s fencing=%s", account_id, worker_id, fencing)
                with Session() as s_fencing:
                    remaining_ids = [w[0] for w in work[idx:]]
                    _release_fencing_claims(s_fencing, remaining_ids, worker_id)
                    s_fencing.commit()
                return {"status": "fencing_mismatch", "completed": completed, "failed": failed}

        try:
            t_fetch = time.monotonic()
            log.info("archive fetch_mime start message=%s remote_id=%s provider=%s", mid, remote_id, type(provider).__name__)
            mime = provider.fetch_mime(remote_id)  # network
            log.info("archive fetch_mime success message=%s bytes=%d elapsed_ms=%.1f", mid, len(mime), (time.monotonic() - t_fetch) * 1000)
        except Exception as exc:
            log.warning("archive fetch failed message=%s: %s", mid, safe_error(exc))
            with Session() as session:
                if account_id is not None and fencing is not None:
                    try:
                        assert_fencing(session, account_id=account_id, fencing_token=fencing)
                    except FencingMismatch:
                        log.warning("archive fencing mismatch after fetch failure account=%s worker=%s fencing=%s", account_id, worker_id, fencing)
                        remaining_ids = [w[0] for w in work[idx:]]
                        _release_fencing_claims(session, remaining_ids, worker_id)
                        session.commit()
                        return {"status": "fencing_mismatch", "completed": completed, "failed": failed}
                st = session.get(MessageArchiveState, mid)
                if (
                    st is not None
                    and st.claimed_by == worker_id
                    and st.state == ArchiveState.ARCHIVE_IN_PROGRESS.value
                ):
                    st.retry_count = int(st.retry_count) + 1
                    err_msg = safe_error(exc)
                    st.last_error = err_msg
                    apply_transition(
                        st,
                        ArchiveState.ARCHIVE_FAILED if st.retry_count >= 5 else ArchiveState.ARCHIVE_PENDING,
                    )
                    st.claimed_by = None
                    st.updated_at = datetime.now(timezone.utc)
                session.commit()
            failed += 1
            continue

        mime_digest = hashlib.sha256(mime).hexdigest()
        needed_bytes = 0 if blob_store.exists(mime_digest) else estimate_encrypted_size(len(mime))
        res_id = None
        if needed_bytes > 0:
            with Session() as s_res:
                res_id = reserve_quota(
                    s_res,
                    root=root,
                    needed_bytes=needed_bytes,
                    worker_id=worker_id,
                    message_id=mid,
                    hard_limit_bytes=hard_i,
                )
                if res_id is None:
                    remaining = [w[0] for w in work[idx:]]
                    _pause_quota(s_res, remaining, account_id, worker_id=worker_id)
                    if account_id is not None and fencing is not None:
                        try:
                            release_lease(s_res, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                        except FencingMismatch:
                            pass
                    s_res.commit()
                    return {
                        "status": "paused_quota",
                        "completed": completed,
                        "failed": failed,
                        "used_bytes": current_used_bytes,
                    }
                s_res.commit()

        try:
            write = blob_store.put(mime)
            current_used_bytes += write.size_bytes
        except Exception:
            if res_id is not None:
                with Session() as s_cleanup:
                    release_quota_reservation(s_cleanup, res_id)
                    s_cleanup.commit()
            raise

        with Session() as session:
            try:
                if res_id is not None:
                    release_quota_reservation(session, res_id)

                if account_id is not None and fencing is not None:
                    try:
                        assert_fencing(session, account_id=account_id, fencing_token=fencing)
                    except FencingMismatch:
                        log.warning("archive fencing mismatch before commit account=%s worker=%s fencing=%s", account_id, worker_id, fencing)
                        remaining_ids = [w[0] for w in work[idx:]]
                        _release_fencing_claims(session, remaining_ids, worker_id)
                        session.commit()
                        return {"status": "fencing_mismatch", "completed": completed, "failed": failed}

                # A35: 以 digest 跨进程锁协调发布与回收
                acquire_blob_digest_lock(session, write.content_sha256)

                st = session.get(MessageArchiveState, mid)
                if (
                    st is None
                    or st.state != ArchiveState.ARCHIVE_IN_PROGRESS.value
                    or st.claimed_by != worker_id
                ):
                    # 状态失效时安全核验孤儿文件
                    live = session.scalar(
                        select(func.count())
                        .select_from(MessageBlob)
                        .where(MessageBlob.content_sha256 == write.content_sha256)
                    ) or 0
                    if int(live) == 0:
                        try:
                            blob_store.path_for(write.content_sha256).unlink(missing_ok=True)
                        except OSError:
                            pass
                    session.commit()
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
                    session.add(MessageBlobLink(message_id=mid, blob_id=blob.id))
                    blob.ref_count = int(blob.ref_count) + 1
                    blob.gc_eligible_at = None

                # A26: Parse MIME body and attachments into domain models; sync FTS
                parsed_attachments = []
                try:
                    plain_text, html_text, parsed_attachments = parse_mime_content(mime)
                    parse_err = None
                except MimeParseError as parse_exc:
                    stage = getattr(parse_exc, "stage", "content")
                    err_str = safe_error(parse_exc)[:2000]
                    log.warning("archive mime parse error for message %s stage=%s: %s", mid, stage, err_str)
                    plain_text = parse_exc.partial_plain
                    html_text = parse_exc.partial_html
                    parsed_attachments = parse_exc.attachments
                    parse_err = err_str
                except Exception as parse_exc:
                    stage = getattr(parse_exc, "stage", "content")
                    err_str = safe_error(parse_exc)[:2000]
                    log.warning("archive mime parse error for message %s stage=%s: %s", mid, stage, err_str)
                    plain_text = None
                    html_text = None
                    parsed_attachments = []
                    parse_err = err_str

                body = session.get(MessageBody, mid)
                if body is None:
                    session.add(MessageBody(message_id=mid, text_plain=plain_text, text_html=html_text, parse_error=parse_err))
                else:
                    body.text_plain = plain_text
                    body.text_html = html_text
                    body.parse_error = parse_err
                    body.updated_at = datetime.now(timezone.utc)
                session.flush()

                # A26: 正文归档事务同步更新 FTS 索引
                # 若因元数据增量缺陷导致发件人或主题缺失，自动从 MIME 报头回填
                msg_record = session.get(Message, mid)
                if msg_record is not None and (not msg_record.from_address or not msg_record.subject):
                    try:
                        import email.utils
                        raw_em = email.message_from_bytes(mime, policy=default_policy)
                        em_name, em_addr = email.utils.parseaddr(str(raw_em.get("From") or ""))
                        if not msg_record.from_address and em_addr:
                            msg_record.from_address = em_addr
                            msg_record.from_name = em_name or msg_record.from_name
                        if not msg_record.subject and raw_em.get("Subject"):
                            msg_record.subject = str(raw_em.get("Subject") or "").strip()
                    except Exception:
                        pass

                if plain_text:
                    from mail_core.search.index import upsert_message_search
                    upsert_message_search(session, message_id=mid, body_text=plain_text)

                storage_failed = False
                if parsed_attachments:
                    try:
                        msg_record = session.get(Message, mid)
                        if msg_record is not None:
                            msg_record.has_attachments = True

                        existing_atts = {
                            att.part_id: att
                            for att in session.scalars(select(Attachment).where(Attachment.message_id == mid)).all()
                            if att.part_id
                        }

                        for att_info in parsed_attachments:
                            pid = str(att_info["part_id"])
                            att_data = att_info["data"]
                            att_digest = hashlib.sha256(att_data).hexdigest()

                            att_needed = 0 if blob_store.exists(att_digest) else estimate_encrypted_size(len(att_data))
                            att_res_id = None
                            if att_needed > 0:
                                att_res_id = reserve_quota(
                                    session,
                                    root=root,
                                    needed_bytes=att_needed,
                                    worker_id=worker_id,
                                    message_id=mid,
                                    hard_limit_bytes=hard_i,
                                )
                                if att_res_id is None:
                                    raise QuotaExceededError(f"attachment quota exceeded for message {mid}")

                            try:
                                acquire_blob_digest_lock(session, att_digest)
                                att_write = blob_store.put(att_data)
                                current_used_bytes += att_write.size_bytes
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

                                if pid in existing_atts:
                                    # A38: 保护已有 UUID
                                    attachment = existing_atts[pid]
                                    if attachment.blob_id != att_blob.id:
                                        attachment.blob_id = att_blob.id
                                        att_blob.ref_count = int(att_blob.ref_count) + 1
                                        att_blob.gc_eligible_at = None
                                    attachment.filename = att_info["filename"]
                                    attachment.content_type = att_info["content_type"]
                                    attachment.size_bytes = att_info["size_bytes"]
                                    attachment.content_id = att_info["content_id"]
                                    attachment.is_inline = att_info["is_inline"]
                                else:
                                    # A38: 稳定 MIME part 身份入库
                                    attachment = Attachment(
                                        message_id=mid,
                                        part_id=pid,
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
                                    existing_atts[pid] = attachment
                            finally:
                                if att_res_id is not None:
                                    release_quota_reservation(session, att_res_id)
                    except QuotaExceededError:
                        session.rollback()
                        with Session() as s_pause:
                            remaining = [w[0] for w in work[idx:]]
                            _pause_quota(s_pause, remaining, account_id, worker_id=worker_id)
                            if account_id is not None and fencing is not None:
                                try:
                                    release_lease(s_pause, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
                                except FencingMismatch:
                                    pass
                            s_pause.commit()
                        return {
                            "status": "paused_quota",
                            "completed": completed,
                            "failed": failed,
                            "used_bytes": current_used_bytes,
                        }
                    except Exception as store_exc:
                        log.warning("archive attachment storage error for message %s: %s", mid, safe_error(store_exc))
                        session.rollback()
                        st = session.get(MessageArchiveState, mid)
                        if st is not None:
                            st.retry_count = int(st.retry_count) + 1
                            st.last_error = safe_error(store_exc)
                            apply_transition(
                                st,
                                ArchiveState.ARCHIVE_FAILED if st.retry_count >= 5 else ArchiveState.ARCHIVE_PENDING,
                            )
                            st.claimed_by = None
                            st.updated_at = datetime.now(timezone.utc)
                        session.commit()
                        failed += 1
                        storage_failed = True

                if storage_failed:
                    continue

                apply_transition(st, ArchiveState.ARCHIVE_COMPLETE)
                st.claimed_by = None
                st.updated_at = datetime.now(timezone.utc)
                completed += 1
                session.commit()
                log.info("archive commit success message=%s", mid)
            except Exception:
                session.rollback()
                raise

    for p in provider_cache.values():
        if hasattr(p, "close_session"):
            try:
                p.close_session()
            except Exception:
                pass

    with Session() as session:
        if completed:
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.ARCHIVE_PROGRESS.value,
                    account_id=account_id,
                    payload={"completed": completed, "failed": failed},
                )
            )
            # Schedule another batch if work may remain (only for routine batch archive)
            if not target_msg_id:
                enqueue_job(
                    session,
                    job_type=JobType.ARCHIVE_MIME_BATCH.value,
                    account_id=account_id,
                    payload={"batch_size": limit, "recent_days": recent_days,
                             "soft_limit_bytes": soft_i, "hard_limit_bytes": hard_i},
                    priority=60,
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
            if not target_msg_id:
                enqueue_job(
                    session,
                    job_type=JobType.ARCHIVE_MIME_BATCH.value,
                    account_id=account_id,
                    payload={"batch_size": limit, "recent_days": recent_days,
                             "soft_limit_bytes": soft_i, "hard_limit_bytes": hard_i},
                    priority=60,
                    run_after=datetime.now(timezone.utc) + timedelta(seconds=30),
                )
        if account_id is not None and fencing is not None:
            try:
                release_lease(session, account_id=account_id, owner_id=worker_id, fencing_token=fencing)
            except FencingMismatch:
                pass
        session.commit()

    return {"status": "ok", "completed": completed, "failed": failed, "claimed": len(work)}
