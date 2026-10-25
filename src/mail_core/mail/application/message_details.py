"""Application orchestration for message details and on-demand body sync."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.db.session import get_session_factory
from mail_core.mail.application.queries import MessageDetail, get_message_detail
from mail_core.mail.domain.archive import apply_transition
from mail_core.mail.domain.enums import ArchiveState, JobType
from mail_core.mail.storage.models import Message, MessageArchiveState
from mail_core.sync.jobs import enqueue_job


class MessageHasNoProviderRemoteId(ValueError):
    """Raised when on-demand sync cannot address a provider message."""


class MessageArchiveStateUnavailable(ValueError):
    """Raised when on-demand sync cannot safely queue an untracked message."""


class MessageBodyAlreadyArchived(ValueError):
    """Raised when on-demand sync is requested after the body is archived."""


@dataclass(frozen=True, slots=True)
class SyncBodyResult:
    message_id: UUID
    job_id: UUID | None
    status: str  # "queued", "in_progress", "complete"


def get_message_detail_with_archive_status(
    session: Session,
    message_id: UUID,
) -> tuple[MessageDetail, bool | None] | None:
    """Return message detail and archive status without changing archive state."""
    detail = get_message_detail(session, message_id)
    if detail is None:
        return None

    state = session.get(MessageArchiveState, message_id)
    is_archived = state.state == ArchiveState.ARCHIVE_COMPLETE.value if state is not None else None
    return detail, is_archived


def sync_message_body(message_id: UUID) -> SyncBodyResult | None:
    """Queue a highest-priority body archive attempt and return its status result."""
    Session = get_session_factory()
    with Session() as session:
        message = session.get(Message, message_id)
        if message is None:
            return None
        if not message.remote_id or not message.remote_id.strip():
            raise MessageHasNoProviderRemoteId("message has no verified provider remote id")

        account_id = message.account_id
        state = session.scalar(
            select(MessageArchiveState)
            .where(MessageArchiveState.message_id == message_id)
            .with_for_update()
        )
        if state is None:
            raise MessageArchiveStateUnavailable("message archive state is unavailable")

        state_value = ArchiveState(state.state)
        # Idempotent: if already complete, report complete without error
        if state_value == ArchiveState.ARCHIVE_COMPLETE:
            return SyncBodyResult(message_id=message_id, job_id=None, status="complete")

        # In progress: report in_progress without stomping worker claim
        if state_value == ArchiveState.ARCHIVE_IN_PROGRESS:
            return SyncBodyResult(message_id=message_id, job_id=None, status="in_progress")

        state.priority = 0
        if state_value == ArchiveState.METADATA_SYNCED:
            apply_transition(state, ArchiveState.ARCHIVE_PENDING)
        elif state_value in (ArchiveState.ARCHIVE_FAILED, ArchiveState.ARCHIVE_PAUSED_QUOTA):
            apply_transition(state, ArchiveState.ARCHIVE_PENDING)
            state.retry_count = 0
            state.pause_reason = None
            state.claimed_by = None
            state.claimed_at = None
        elif state_value == ArchiveState.ARCHIVE_PENDING and state.retry_count >= 5:
            state.retry_count = 0

        state.last_error = None
        state.pause_reason = None
        state.updated_at = datetime.now(timezone.utc)

        job = enqueue_job(
            session,
            job_type=JobType.ARCHIVE_MIME_BATCH.value,
            account_id=account_id,
            payload={"message_id": str(message_id), "batch_size": 1},
            priority=10,
            dedupe_key=f"archive_msg:{message_id}",
        )
        session.commit()
        return SyncBodyResult(message_id=message_id, job_id=job.id, status="queued")
