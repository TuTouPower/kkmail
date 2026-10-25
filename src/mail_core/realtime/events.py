"""Canonical SSE wire event names (architecture §13).

Clients (EventSource) must register listeners for every name they care about;
the server always emits an explicit ``event:`` field (never unnamed ``message``).
"""

from __future__ import annotations

from mail_core.mail.domain.enums import OutboxEventType

# All event types the server may emit on /api/events (outbox + synthetic hints).
SSE_WIRE_EVENTS: frozenset[str] = frozenset(e.value for e in OutboxEventType)

# Core events every mail UI should subscribe to. Archive.* are optional for UIs
# that do not surface MIME-archive progress.
SSE_CORE_CLIENT_EVENTS: tuple[str, ...] = (
    OutboxEventType.ACCOUNT_UPDATED.value,
    OutboxEventType.MESSAGE_UPSERTED.value,
    OutboxEventType.MESSAGE_REMOVED.value,
    OutboxEventType.FOLDER_STATS_UPDATED.value,
    OutboxEventType.SYNC_PROGRESS.value,
    OutboxEventType.SYNC_COMPLETED.value,
    OutboxEventType.SYNC_ERROR.value,
    OutboxEventType.REMOTE_OPERATION_UPDATED.value,
    OutboxEventType.CLIENT_RESYNC_HINT.value,
)

SSE_ARCHIVE_CLIENT_EVENTS: tuple[str, ...] = (
    OutboxEventType.ARCHIVE_PROGRESS.value,
    OutboxEventType.ARCHIVE_COMPLETED.value,
    OutboxEventType.ARCHIVE_PAUSED_QUOTA.value,
)
