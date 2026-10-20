"""Pure domain value objects / entities (no ORM)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from mail_core.mail.domain.enums import ArchiveState, FolderRole, ProviderType, SyncStatus


@dataclass(frozen=True, slots=True)
class AccountRef:
    id: UUID
    email: str
    provider: ProviderType


@dataclass(frozen=True, slots=True)
class FolderRef:
    id: UUID
    account_id: UUID
    role: FolderRole
    remote_id: str
    name: str


@dataclass(frozen=True, slots=True)
class MessageMetadata:
    """Unified message metadata visible to application / UI layers."""

    id: UUID
    account_id: UUID
    subject: str
    from_address: str
    from_name: str | None
    sort_time: datetime
    is_read: bool
    has_attachments: bool
    internet_message_id: str | None = None
    snippet: str | None = None
    provider_thread_key: str | None = None


@dataclass(slots=True)
class SyncCheckpointView:
    account_id: UUID
    folder_id: UUID
    cursor: dict[str, Any] = field(default_factory=dict)
    uidvalidity: int | None = None
    modseq: int | None = None
    status: SyncStatus = SyncStatus.IDLE
