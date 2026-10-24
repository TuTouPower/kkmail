"""Application orchestration for message details and on-demand body sync."""

from __future__ import annotations

import logging
import time
import uuid
from uuid import UUID

from sqlalchemy.orm import Session

from mail_core.db.session import get_session_factory
from mail_core.mail.application.queries import MessageDetail, get_message_detail
from mail_core.mail.domain.archive import apply_transition
from mail_core.mail.domain.enums import ArchiveState, JobType
from mail_core.mail.storage.models import Message, MessageArchiveState
from mail_core.security.redact import safe_error
from mail_core.sync.jobs import enqueue_job

log = logging.getLogger("mail_core.mail.application.message_details")


class MessageHasNoProviderRemoteId(ValueError):
    """Raised when on-demand sync cannot address a provider message."""


def get_message_detail_with_archive_nudge(
    session: Session,
    message_id: UUID,
) -> tuple[MessageDetail, bool | None] | None:
    detail = get_message_detail(session, message_id)
    if detail is None:
        return None

    state = session.get(MessageArchiveState, message_id)
    message = session.get(Message, message_id)
    is_archived = state.state == ArchiveState.ARCHIVE_COMPLETE.value if state is not None else None
    if (
        is_archived is False
        and message is not None
        and message.remote_id
        and message.remote_id.strip()
        and not detail.parse_error
        and state is not None
        and state.state in (ArchiveState.METADATA_SYNCED.value, ArchiveState.ARCHIVE_PENDING.value)
    ):
        state.priority = 0
        if state.state == ArchiveState.METADATA_SYNCED.value:
            apply_transition(state, ArchiveState.ARCHIVE_PENDING)
        enqueue_job(
            session,
            job_type=JobType.ARCHIVE_MIME_BATCH.value,
            account_id=detail.account_id,
            payload={"message_id": str(message_id), "batch_size": 1},
            priority=10,
            dedupe_key=f"archive_msg:{message_id}",
        )
        session.commit()

    return detail, is_archived


def sync_message_body(message_id: UUID) -> tuple[MessageDetail, bool | None] | None:
    """Queue and run one highest-priority body archive attempt, returning current detail."""
    Session = get_session_factory()
    with Session() as session:
        message = session.get(Message, message_id)
        if message is None:
            return None
        if not message.remote_id or not message.remote_id.strip():
            raise MessageHasNoProviderRemoteId("message has no verified provider remote id")

        account_id = message.account_id
        state = session.get(MessageArchiveState, message_id)
        if state is not None:
            state.priority = 0
            if state.state == ArchiveState.METADATA_SYNCED.value:
                apply_transition(state, ArchiveState.ARCHIVE_PENDING)
            enqueue_job(
                session,
                job_type=JobType.ARCHIVE_MIME_BATCH.value,
                account_id=account_id,
                payload={"message_id": str(message_id), "batch_size": 1},
                priority=10,
                dedupe_key=f"archive_msg:{message_id}",
            )
            session.commit()

    # Import at call time to keep the application queries and archive worker decoupled.
    from mail_core.blobs.archive import run_archive_batch

    attempt_id = uuid.uuid4().hex[:12]
    worker_id = f"api-on-demand:{attempt_id}"
    started_at = time.monotonic()
    log.info(
        "api_sync_message_body start attempt=%s account_id=%s message_id=%s",
        attempt_id,
        account_id,
        message_id,
    )
    try:
        result = run_archive_batch(
            account_id=account_id,
            worker_id=worker_id,
            payload={"message_id": str(message_id), "batch_size": 1},
        )
    except Exception as exc:
        result = {"status": "error", "error": safe_error(exc)}
        log.warning("on-demand sync error attempt=%s for message %s: %s", attempt_id, message_id, result["error"])

    elapsed_ms = (time.monotonic() - started_at) * 1000
    log.info(
        "api_sync_message_body end attempt=%s message_id=%s elapsed_ms=%.1f result=%s",
        attempt_id,
        message_id,
        elapsed_ms,
        result,
    )

    with Session() as session:
        detail = get_message_detail(session, message_id)
        if detail is None:
            return None
        state = session.get(MessageArchiveState, message_id)
        is_archived = state.state == ArchiveState.ARCHIVE_COMPLETE.value if state is not None else None
        return detail, is_archived
