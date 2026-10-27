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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

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
from mail_core.providers.connection_slots import (
    CAPACITY_ERRORS,
    ProviderCapacityUnavailable,
    TrafficClass,
    traffic_class_for_job,
)
from mail_core.providers.factory import build_provider
from mail_core.sync.jobs import enqueue_job

log = logging.getLogger("mail_core.blobs.archive")

DEFAULT_RECENT_DAYS = 30
DEFAULT_BATCH = 20

# Hard caps so one poison-pill message cannot OOM the worker: the raw
# MIME is already materialised by fetch, so parsing must not amplify it
# without bound. Oversized input is rejected as a MimeParseError and the
# caller settles it through the normal parse_error path instead of the
# process being killed mid-batch.
MAX_MIME_BYTES = 50 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


def _size_limit_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        log.warning("invalid %s=%r; using default %d", name, raw, default)
        return default
    if value <= 0:
        log.warning("invalid %s=%r; using default %d", name, raw, default)
        return default
    return value


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


@dataclass(frozen=True)
class ArchiveClaim:
    """One archive execution's ownership token (repair design §4.1).

    Every success / error / quota-pause / release / heartbeat write for an
    in-flight archive takes this object; ownership is never judged by
    ``worker_id`` alone. ``revision`` is the ``claim_revision`` value this
    execution claimed at, and ``remote_id_snapshot`` is the provider remote
    id observed at claim time.
    """

    message_id: uuid.UUID
    owner: str
    revision: int
    remote_id_snapshot: str


def _revision_of(state: Any) -> int:
    return int(getattr(state, "claim_revision", 0) or 0)


def _is_postgres(session: Any) -> bool:
    try:
        bind = session.get_bind()
    except Exception:
        return False
    return getattr(getattr(bind, "dialect", None), "name", None) == "postgresql"


def _lock_archive_rows(session: Any, claim: ArchiveClaim, *, lock_message: bool) -> None:
    """Lock Message -> MessageArchiveState (in that order) for ``claim``.

    The SELECTs only take the row locks; the caller re-reads the rows via
    ``session.get`` (identity map) and revalidates them. On PostgreSQL this
    is a real ``FOR UPDATE`` lock held until the caller commits; other
    dialects fall back to a plain read (single-writer test doubles).
    """
    if lock_message:
        stmt = select(Message.id).where(Message.id == claim.message_id)
        if _is_postgres(session):
            stmt = stmt.with_for_update()
        session.execute(stmt)
    stmt = select(MessageArchiveState.message_id).where(
        MessageArchiveState.message_id == claim.message_id
    )
    if _is_postgres(session):
        stmt = stmt.with_for_update()
    session.execute(stmt)


def _claim_is_current(
    session: Any, claim: ArchiveClaim
) -> tuple[Message | None, MessageArchiveState | None, bool]:
    """Revalidate a claim against the (already locked) current rows."""
    msg = session.get(Message, claim.message_id)
    st = session.get(MessageArchiveState, claim.message_id)
    ok = (
        msg is not None
        and st is not None
        and st.state == ArchiveState.ARCHIVE_IN_PROGRESS.value
        and st.claimed_by == claim.owner
        and _revision_of(st) == claim.revision
        and (msg.remote_id or "") == (claim.remote_id_snapshot or "")
    )
    return msg, st, ok


def settle_archive_claim(
    session: Any,
    claim: ArchiveClaim,
    outcome: str,
    *,
    error: BaseException | str | None = None,
    account_id: uuid.UUID | None = None,
) -> bool:
    """Unified failure / quota / release settlement for one claim (design §4.2).

    Locks the archive-state row, revalidates (state, owner, revision,
    remote_id) and only then writes. A claim that is no longer current is
    left completely untouched, so a stale execution can never overwrite a
    newer claim. The caller commits. Returns True when applied.

    Outcomes:
    - ``provider_error`` / ``storage_error``: sanitized ``last_error`` is
      persisted, ``retry_count`` is incremented, the claim is released and
      the row returns to ``archive_pending`` (or ``archive_failed`` once
      retries are exhausted).
    - ``quota``: ``archive_paused_quota`` with ``pause_reason=quota``; the
      claim and reservation are released and no retry is counted.
    - ``capacity``: local connection-slot shortage; the claim is released
      back to ``archive_pending`` without counting a retry/failure and
      without touching ``last_error``.
    - ``release``: plain release back to ``archive_pending``.
    """
    _lock_archive_rows(session, claim, lock_message=False)
    _msg, st, ok = _claim_is_current(session, claim)
    if not ok or st is None:
        return False
    now = datetime.now(timezone.utc)
    event_type = OutboxEventType.ARCHIVE_PROGRESS.value
    if outcome == "quota":
        apply_transition(st, ArchiveState.ARCHIVE_PAUSED_QUOTA)
        st.pause_reason = "quota"
        event_type = OutboxEventType.ARCHIVE_PAUSED_QUOTA.value
    elif outcome in ("provider_error", "storage_error"):
        st.retry_count = int(st.retry_count or 0) + 1
        if error is not None:
            st.last_error = safe_error(error)[:2000]
        apply_transition(
            st,
            ArchiveState.ARCHIVE_FAILED if st.retry_count >= 5 else ArchiveState.ARCHIVE_PENDING,
        )
    elif outcome in ("capacity", "release"):
        apply_transition(st, ArchiveState.ARCHIVE_PENDING)
    else:
        raise ValueError(f"unknown archive settlement outcome: {outcome!r}")
    st.claimed_by = None
    st.claimed_at = None
    st.updated_at = now
    session.add(
        OutboxEvent(
            event_type=event_type,
            account_id=account_id,
            payload={
                "message_id": str(claim.message_id),
                "message_ids": [str(claim.message_id)],
                "state": st.state,
                "has_error": bool(st.last_error),
            },
        )
    )
    return True


def settle_archive_claims(
    session: Any,
    claims: list[ArchiveClaim],
    outcome: str,
    *,
    error: BaseException | str | None = None,
    account_id: uuid.UUID | None = None,
) -> int:
    """Apply :func:`settle_archive_claim` to each claim; returns how many applied."""
    applied = 0
    for claim in claims:
        if settle_archive_claim(session, claim, outcome, error=error, account_id=account_id):
            applied += 1
    return applied


def heartbeat_archive_claims(
    session: Any,
    claims: list[ArchiveClaim],
    *,
    now: datetime | None = None,
) -> list[ArchiveClaim]:
    """Refresh ``claimed_at`` for still-owned claims; returns the live ones.

    The UPDATE is conditioned on (owner, revision, state), so a claim that
    was reclaimed/revoked by another worker is never refreshed. The caller
    commits this short transaction; no business row locks are held during
    network I/O.
    """
    now = now or datetime.now(timezone.utc)
    alive: list[ArchiveClaim] = []
    for claim in claims:
        result = session.execute(
            update(MessageArchiveState)
            .where(
                MessageArchiveState.message_id == claim.message_id,
                MessageArchiveState.claimed_by == claim.owner,
                MessageArchiveState.claim_revision == claim.revision,
                MessageArchiveState.state == ArchiveState.ARCHIVE_IN_PROGRESS.value,
            )
            .values(claimed_at=now, updated_at=now)
        )
        rowcount = getattr(result, "rowcount", None)
        if isinstance(rowcount, int) and rowcount != 1:
            continue
        alive.append(claim)
    return alive


def blob_root() -> Path:
    return Path(os.environ.get("MAIL_CORE_BLOB_ROOT", "[REDACTED]mail-core-blobs"))


def parse_mime_content(
    mime_bytes: bytes,
) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """Parse raw MIME bytes into (text_plain, text_html, attachments)."""
    mime_limit = _size_limit_from_env("MAIL_CORE_MIME_MAX_BYTES", MAX_MIME_BYTES)
    if len(mime_bytes) > mime_limit:
        raise MimeParseError(
            "mime", f"mime_size_exceeded: {len(mime_bytes)} bytes > limit {mime_limit}"
        )
    attachment_limit = _size_limit_from_env(
        "MAIL_CORE_ATTACHMENT_MAX_BYTES", MAX_ATTACHMENT_BYTES
    )
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
            # Reject oversized attachments before decoding them into yet
            # another in-memory copy; the encoded length bounds the
            # decoded size closely enough for a pre-check.
            raw_probe = part.get_payload()
            if isinstance(raw_probe, str) and len(raw_probe) * 3 // 4 > attachment_limit:
                if first_error is None:
                    first_error = MimeParseError(
                        "attachment",
                        f"attachment_size_exceeded: encoded {len(raw_probe)} chars > limit {attachment_limit} bytes",
                    )
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                raw_p = part.get_payload()
                if isinstance(raw_p, str):
                    payload = raw_p.encode("utf-8", errors="replace")
                elif isinstance(raw_p, bytes):
                    payload = raw_p
                else:
                    payload = b""

            if len(payload) > attachment_limit:
                if first_error is None:
                    first_error = MimeParseError(
                        "attachment",
                        f"attachment_size_exceeded: {len(payload)} bytes > limit {attachment_limit} bytes",
                    )
                continue

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
) -> list[ArchiveClaim]:
    """Select metadata_synced / pending rows and mark archive_in_progress.

    Short claim transaction: ``claim_revision`` is incremented here and the
    caller commits before any network I/O. Each claimed row is returned as
    an :class:`ArchiveClaim` carrying the new revision and the remote_id
    snapshot observed at claim time.
    """
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
    claimed: list[ArchiveClaim] = []
    for state, msg in rows:
        # Promote metadata_synced → pending → in_progress
        if state.state == ArchiveState.METADATA_SYNCED.value:
            apply_transition(state, ArchiveState.ARCHIVE_PENDING)
            if state.priority is None or state.priority > 0:
                state.priority = _priority_for(msg.sort_time, now=now, recent_days=recent_days)
        apply_transition(state, ArchiveState.ARCHIVE_IN_PROGRESS)
        state.claim_revision = int(getattr(state, "claim_revision", 0) or 0) + 1
        state.claimed_by = worker_id
        state.claimed_at = now
        state.updated_at = now
        claimed.append(
            ArchiveClaim(
                message_id=msg.id,
                owner=worker_id,
                revision=int(state.claim_revision),
                remote_id_snapshot=msg.remote_id or "",
            )
        )
    session.flush()
    claimed_ids = [c.message_id for c in claimed]
    if target_message_id is not None and target_message_id not in claimed_ids:
        target_st = session.get(MessageArchiveState, target_message_id)
        log.info(
            "claim_archive_batch target_message_id=%s not claimed: state=%s claimed_by=%s retry_count=%s",
            target_message_id,
            getattr(target_st, "state", None),
            getattr(target_st, "claimed_by", None),
            getattr(target_st, "retry_count", None),
        )
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
        log.info(
            "reclaim_stale_archive_claim message_id=%s old_claimed_by=%s claimed_at=%s",
            st.message_id,
            st.claimed_by,
            st.claimed_at,
        )
        apply_transition(st, ArchiveState.ARCHIVE_PENDING)
        st.claimed_by = None
        st.claimed_at = None
        # Revoking a claim bumps its revision so the stale execution's
        # heartbeat / publish validation can never succeed afterwards.
        st.claim_revision = int(getattr(st, "claim_revision", 0) or 0) + 1
        st.updated_at = now
        suffix = "|reclaimed_stale_archive_claim"
        prev = st.last_error or ""
        if suffix not in prev:
            st.last_error = (prev + suffix)[:2000]
    if rows:
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.ARCHIVE_PROGRESS.value,
                payload={
                    "message_ids": [str(st.message_id) for st in rows],
                    "state": ArchiveState.ARCHIVE_PENDING.value,
                },
            )
        )
    session.flush()
    return len(rows)


def _pause_quota(
    session,
    claims: list[ArchiveClaim],
    account_id: uuid.UUID | None,
) -> int:
    """Quota-pause every still-current claim via the unified settlement."""
    return settle_archive_claims(session, claims, "quota", account_id=account_id)


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
                    payload={
                        "resumed_from_quota": len(rows),
                        "message_ids": [str(st.message_id) for st in rows],
                        "state": ArchiveState.ARCHIVE_PENDING.value,
                    },
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


class _ArchiveConfigError(ValueError):
    """A batch/quota configuration value cannot be parsed as an integer."""


def _config_int(value: Any, *, name: str) -> int:
    try:
        if isinstance(value, str):
            return int(value.strip())
        return int(value)
    except (TypeError, ValueError) as exc:
        raise _ArchiveConfigError(f"invalid archive config {name}={value!r}") from exc


def _resolve_archive_config(payload: dict) -> tuple[int, int, int | None, int | None]:
    """Centrally parse and clamp run_archive_batch configuration.

    Batch size is clamped to 1..200 so a malformed or oversized value
    cannot claim an unbounded batch; quota byte limits are clamped to
    >= 0. Non-numeric values raise _ArchiveConfigError.
    """
    limit = _config_int(
        payload.get("batch_size") or os.environ.get("MAIL_CORE_ARCHIVE_BATCH") or DEFAULT_BATCH,
        name="batch_size",
    )
    limit = max(1, min(200, limit))
    recent_days = _config_int(payload.get("recent_days") or DEFAULT_RECENT_DAYS, name="recent_days")

    def _bytes(name: str, env_name: str) -> int | None:
        raw = payload.get(name)
        if raw is None:
            raw = os.environ.get(env_name)
        if raw is None or raw == "":
            return None
        return max(0, _config_int(raw, name=name))

    soft_i = _bytes("soft_limit_bytes", "MAIL_CORE_BLOB_SOFT_BYTES")
    hard_i = _bytes("hard_limit_bytes", "MAIL_CORE_BLOB_HARD_BYTES")
    return limit, recent_days, soft_i, hard_i


def run_archive_batch(
    *,
    account_id: uuid.UUID | None,
    worker_id: str,
    store: CredentialStore | None = None,
    payload: dict | None = None,
    traffic_class: TrafficClass | None = None,
) -> dict:
    payload = payload or {}
    if traffic_class is None:
        # Routine batches are background; a batch targeted at one
        # message_id is an on-demand foreground fetch (design §7).
        traffic_class = traffic_class_for_job(JobType.ARCHIVE_MIME_BATCH.value, payload=payload)
    try:
        limit, recent_days, soft_i, hard_i = _resolve_archive_config(payload)
    except _ArchiveConfigError as exc:
        log.error("archive batch aborted: %s", exc)
        return {"status": "config_error", "error": str(exc)}

    root = blob_root()
    blob_store = BlobStore(root)
    Session = __import__("mail_core.db.session", fromlist=["get_session_factory"]).get_session_factory()

    target_msg_id = None
    if payload.get("message_id"):
        try:
            target_msg_id = uuid.UUID(str(payload["message_id"]))
        except (ValueError, TypeError):
            pass

    quota = check_quota(root, soft_limit_bytes=soft_i, hard_limit_bytes=hard_i)
    current_used_bytes = quota.used_bytes
    if quota.hard_exceeded or quota.soft_exceeded:
        with Session() as session:
            event_payload = {
                "used_bytes": quota.used_bytes,
                "soft_limit_bytes": soft_i,
                "hard_limit_bytes": hard_i,
                "soft_exceeded": quota.soft_exceeded,
                "hard_exceeded": quota.hard_exceeded,
            }
            if target_msg_id is not None:
                state = session.get(MessageArchiveState, target_msg_id)
                if state is not None and state.state == ArchiveState.ARCHIVE_PENDING.value:
                    apply_transition(state, ArchiveState.ARCHIVE_PAUSED_QUOTA)
                    state.pause_reason = "quota"
                    state.claimed_by = None
                    state.claimed_at = None
                    state.updated_at = datetime.now(timezone.utc)
                event_payload.update(
                    message_id=str(target_msg_id),
                    state=ArchiveState.ARCHIVE_PAUSED_QUOTA.value,
                )
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.ARCHIVE_PAUSED_QUOTA.value,
                    account_id=account_id,
                    payload=event_payload,
                )
            )
            session.commit()
        return {"status": "paused_quota", "used_bytes": quota.used_bytes}

    # Capacity is below recovery threshold — automatically resume quota-paused archives (A25)
    resume_quota_paused_archives(account_id=account_id, limit=limit)

    # Short claim transaction: revision is incremented and committed before
    # any network I/O (design §4.1 step 1).
    with Session() as session:
        raw_claims = claim_archive_batch(
            session,
            account_id=account_id,
            worker_id=worker_id,
            limit=limit,
            recent_days=recent_days,
            target_message_id=target_msg_id,
        )
        claims: list[ArchiveClaim] = []
        account_by_message: dict[uuid.UUID, uuid.UUID] = {}
        for item in raw_claims:
            if isinstance(item, ArchiveClaim):
                claim = item
            else:
                # Test doubles may still return bare message ids; normalize
                # them into claims from the rows read in this transaction.
                bare_id = item if isinstance(item, uuid.UUID) else uuid.UUID(str(item))
                bare_msg = session.get(Message, bare_id)
                bare_st = session.get(MessageArchiveState, bare_id)
                if bare_msg is None or bare_st is None:
                    continue
                claim = ArchiveClaim(
                    message_id=bare_id,
                    owner=worker_id,
                    revision=_revision_of(bare_st),
                    remote_id_snapshot=bare_msg.remote_id or "",
                )
            msg = session.get(Message, claim.message_id)
            if msg is None or not msg.remote_id or not msg.remote_id.strip():
                continue
            claims.append(claim)
            account_by_message[claim.message_id] = msg.account_id
        if claims:
            claimed_ids = [c.message_id for c in claims]
            status_payload = {
                "message_ids": [str(mid) for mid in claimed_ids],
                "state": ArchiveState.ARCHIVE_IN_PROGRESS.value,
            }
            if target_msg_id is not None and target_msg_id in claimed_ids:
                status_payload["message_id"] = str(target_msg_id)
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.ARCHIVE_PROGRESS.value,
                    account_id=account_id,
                    payload=status_payload,
                )
            )
        session.commit()

    completed = 0
    failed = 0
    provider_cache: dict[uuid.UUID, object] = {}
    done_ids: set[uuid.UUID] = set()

    def _close_providers() -> None:
        for p in provider_cache.values():
            if hasattr(p, "close_session"):
                try:
                    p.close_session()
                except Exception:
                    pass

    def _active_claims() -> list[ArchiveClaim]:
        return [c for c in claims if c.message_id not in done_ids]

    def _heartbeat_active() -> list[ArchiveClaim]:
        """Refresh claimed_at for this batch's in-flight claims (short txn)."""
        active = _active_claims()
        if not active:
            return active
        with Session() as hb_session:
            alive = heartbeat_archive_claims(hb_session, active)
            hb_session.commit()
        return alive

    def _release_reservation(reservation_id: uuid.UUID | None) -> None:
        if reservation_id is None:
            return
        with Session() as s_cleanup:
            release_quota_reservation(s_cleanup, reservation_id)
            s_cleanup.commit()

    for claim in claims:
        mid = claim.message_id
        remote_id = claim.remote_id_snapshot
        if mid in done_ids:
            continue

        # Heartbeat this batch's in-flight claims before touching the next
        # message; a claim whose heartbeat fails was revoked and must not be
        # fetched for or published by this stale execution.
        alive_ids = {c.message_id for c in _heartbeat_active()}
        if mid not in alive_ids:
            done_ids.add(mid)
            continue

        # Incremental quota check: avoid per-message full disk walk (V4-01)
        soft_exceeded = soft_i is not None and current_used_bytes >= soft_i
        hard_exceeded = hard_i is not None and current_used_bytes >= hard_i
        if soft_exceeded or hard_exceeded:
            with Session() as session:
                _pause_quota(session, _active_claims(), account_id)
                session.commit()
            _close_providers()
            return {
                "status": "paused_quota",
                "completed": completed,
                "failed": failed,
                "used_bytes": current_used_bytes,
            }

        msg_account_id = account_by_message.get(mid)
        if msg_account_id is None:
            done_ids.add(mid)
            continue

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
                p = build_provider(snap, store or get_credential_store(), traffic_class=traffic_class)
                if hasattr(p, "open_session"):
                    try:
                        p.open_session()
                    except Exception:
                        # B4: a failed handshake must not poison the cache
                        # (the unconnected provider would fail every fetch),
                        # and CAPACITY_ERRORS must reach the outer handler's
                        # batch capacity settlement instead of being
                        # swallowed here. Close any partial session first.
                        if hasattr(p, "close_session"):
                            try:
                                p.close_session()
                            except Exception:
                                pass
                        raise
                provider_cache[msg_account_id] = p
            except Exception as exc:
                # Provider construction failure (R18): persist the sanitized
                # error through the unified settlement for every still-active
                # claim of this account instead of silently reverting to
                # pending; other accounts in the batch continue.
                if isinstance(exc, CAPACITY_ERRORS):
                    with Session() as session:
                        applied = settle_archive_claims(
                            session, _active_claims(), "capacity", account_id=account_id
                        )
                        session.commit()
                    _close_providers()
                    return {
                        "status": "capacity_unavailable",
                        "completed": completed,
                        "failed": failed,
                        "deferred": applied,
                        "used_bytes": current_used_bytes,
                    }
                log.warning("archive provider construction failed account=%s: %s", msg_account_id, safe_error(exc))
                affected = [c for c in _active_claims() if account_by_message.get(c.message_id) == msg_account_id]
                with Session() as session:
                    applied = settle_archive_claims(
                        session, affected, "provider_error", error=exc, account_id=account_id
                    )
                    session.commit()
                failed += applied
                done_ids.update(c.message_id for c in affected)
                continue
        provider = provider_cache[msg_account_id]

        try:
            t_fetch = time.monotonic()
            log.info("archive fetch_mime start message=%s remote_id=%s provider=%s", mid, remote_id, type(provider).__name__)
            mime = provider.fetch_mime(remote_id)  # network
            log.info("archive fetch_mime success message=%s bytes=%d elapsed_ms=%.1f", mid, len(mime), (time.monotonic() - t_fetch) * 1000)
        except Exception as exc:
            if isinstance(exc, CAPACITY_ERRORS):
                with Session() as session:
                    applied = settle_archive_claims(
                        session, _active_claims(), "capacity", account_id=account_id
                    )
                    session.commit()
                _close_providers()
                return {
                    "status": "capacity_unavailable",
                    "completed": completed,
                    "failed": failed,
                    "deferred": applied,
                    "used_bytes": current_used_bytes,
                }
            log.warning("archive fetch failed message=%s: %s", mid, safe_error(exc))
            with Session() as session:
                applied = settle_archive_claims(
                    session, [claim], "provider_error", error=exc, account_id=account_id
                )
                session.commit()
            failed += applied
            done_ids.add(mid)
            continue

        # The fetch may have taken long enough for this claim to be revoked;
        # refresh the batch heartbeat and never publish a revoked claim.
        alive_ids = {c.message_id for c in _heartbeat_active()}
        if mid not in alive_ids:
            done_ids.add(mid)
            continue

        # MIME parsing and attachment digest computation happen OUTSIDE the
        # publish transaction (design §4.1 step 2). A parse failure keeps the
        # raw MIME plus whatever partial results the parser produced.
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

        mime_digest = hashlib.sha256(mime).hexdigest()
        attachment_digests = [
            hashlib.sha256(att_info["data"]).hexdigest() for att_info in parsed_attachments
        ]

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
                    _pause_quota(s_res, _active_claims(), account_id)
                    s_res.commit()
                    _close_providers()
                    return {
                        "status": "paused_quota",
                        "completed": completed,
                        "failed": failed,
                        "used_bytes": current_used_bytes,
                    }
                s_res.commit()

        # Publish transaction (design §4.1 steps 3-4): lock Message ->
        # MessageArchiveState FOR UPDATE, revalidate the claim, only then
        # take quota/digest locks (digests in stable order) and atomically
        # save blob refs, body, attachments, archive state and Outbox event.
        publish_outcome = "completed"
        storage_error: Exception | None = None
        with Session() as session:
            try:
                _lock_archive_rows(session, claim, lock_message=True)
                msg_record, st, claim_ok = _claim_is_current(session, claim)
                if not claim_ok:
                    # Stale execution: commit nothing derived. This
                    # execution's quota reservation is released by ownership
                    # below; any file it may already have published without
                    # references is left to the existing safe GC.
                    session.rollback()
                    _release_reservation(res_id)
                    done_ids.add(mid)
                    continue

                if res_id is not None:
                    release_quota_reservation(session, res_id)

                # A35: digest cross-process locks coordinate publish vs GC.
                # All digests are locked in stable order, and never while
                # waiting on message/archive-state rows (already held).
                for digest in sorted({mime_digest, *attachment_digests}):
                    acquire_blob_digest_lock(session, digest)

                # Keep the digest locks' transaction open across file
                # publication and the MessageBlob/MessageBlobLink inserts
                # below. GC uses the same locks while checking references
                # and unlinking files.
                mime_existed = blob_store.exists(mime_digest)
                write = blob_store.put(mime)
                if not mime_existed:
                    current_used_bytes += write.size_bytes

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

                if parsed_attachments:
                    if msg_record is not None:
                        msg_record.has_attachments = True

                    existing_atts = {
                        att.part_id: att
                        for att in session.scalars(select(Attachment).where(Attachment.message_id == mid)).all()
                        if att.part_id
                    }

                    for att_info, att_digest in zip(parsed_attachments, attachment_digests):
                        pid = str(att_info["part_id"])
                        att_data = att_info["data"]

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
                            att_existed = blob_store.exists(att_digest)
                            att_write = blob_store.put(att_data)
                            if not att_existed:
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

                apply_transition(st, ArchiveState.ARCHIVE_COMPLETE)
                st.claimed_by = None
                st.claimed_at = None
                st.last_error = None
                st.pause_reason = None
                st.updated_at = datetime.now(timezone.utc)
                session.add(
                    OutboxEvent(
                        event_type=OutboxEventType.ARCHIVE_PROGRESS.value,
                        account_id=account_id,
                        payload={
                            "message_id": str(mid),
                            "message_ids": [str(mid)],
                            "state": ArchiveState.ARCHIVE_COMPLETE.value,
                            "has_error": False,
                        },
                    )
                )
                session.commit()
                completed += 1
                log.info("archive commit success message=%s", mid)
            except QuotaExceededError:
                # Roll back the derived transaction, then quota-pause the
                # still-current claims in a separate short transaction.
                session.rollback()
                publish_outcome = "quota"
            except Exception as store_exc:
                # Storage I/O failure: roll back the derived transaction,
                # then record the archive error under the still-valid claim
                # in a separate short transaction (design §4.2).
                session.rollback()
                log.warning("archive storage error for message %s: %s", mid, safe_error(store_exc))
                publish_outcome = "storage_error"
                storage_error = store_exc

        if publish_outcome == "quota":
            _release_reservation(res_id)
            with Session() as s_pause:
                # Current claim is still active here, so this pauses it and
                # every remaining claim of the batch.
                _pause_quota(s_pause, _active_claims(), account_id)
                s_pause.commit()
            _close_providers()
            return {
                "status": "paused_quota",
                "completed": completed,
                "failed": failed,
                "used_bytes": current_used_bytes,
            }
        if publish_outcome == "storage_error":
            _release_reservation(res_id)
            with Session() as s_err:
                applied = settle_archive_claims(
                    s_err, [claim], "storage_error", error=storage_error, account_id=account_id
                )
                s_err.commit()
            failed += applied
        done_ids.add(mid)


    _close_providers()

    with Session() as session:
        target_state = session.get(MessageArchiveState, target_msg_id) if target_msg_id is not None else None
        target_event_fields = (
            {
                "message_id": str(target_msg_id),
                "state": target_state.state if target_state is not None else None,
                "has_error": bool(target_state and target_state.last_error),
            }
            if target_msg_id is not None
            else {}
        )
        batch_message_ids = [str(c.message_id) for c in claims]
        if completed:
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.ARCHIVE_PROGRESS.value,
                    account_id=account_id,
                    payload={
                        "completed": completed,
                        "failed": failed,
                        "message_ids": batch_message_ids,
                        **target_event_fields,
                    },
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
                    payload={
                        "completed": completed,
                        "failed": failed,
                        "message_ids": batch_message_ids,
                        **target_event_fields,
                    },
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
        session.commit()

    return {"status": "ok", "completed": completed, "failed": failed, "claimed": len(claims)}
