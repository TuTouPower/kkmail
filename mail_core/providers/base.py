"""Unified provider adapter interface (architecture §6.1).

Protocol details (Gmail History, Graph Delta, IMAP UID/MODSEQ) must stay
inside providers/* implementations — never leak into mail/application.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Protocol, Sequence


@dataclass(frozen=True, slots=True)
class RemoteFolder:
    remote_id: str
    name: str
    role: str  # FolderRole value
    parent_remote_id: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteMessageMeta:
    remote_id: str
    subject: str
    from_address: str
    from_name: str | None
    sort_time: datetime
    is_read: bool
    has_attachments: bool
    internet_message_id: str | None = None
    snippet: str | None = None
    provider_thread_key: str | None = None
    uid: int | None = None
    size_bytes: int | None = None
    to_addresses: tuple[str, ...] = ()
    cc_addresses: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MetadataPage:
    items: Sequence[RemoteMessageMeta]
    next_cursor: dict[str, Any] | None
    exhausted: bool


@dataclass(frozen=True, slots=True)
class DeltaChange:
    """Normalized incremental change; deletions are explicit — never inferred."""

    kind: str  # upsert | delete | flag
    remote_id: str
    meta: RemoteMessageMeta | None = None
    flags: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeltaPage:
    changes: Sequence[DeltaChange]
    next_cursor: dict[str, Any] | None
    exhausted: bool


@dataclass(frozen=True, slots=True)
class RateLimitHint:
    max_requests_per_minute: int | None = None
    retry_after_seconds: float | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteOperationResult:
    success: bool
    idempotent_noop: bool = False
    error: str | None = None
    remote_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReconcileAction:
    kind: str
    remote_id: str
    detail: dict[str, Any] = field(default_factory=dict)


class MailProvider(Protocol):
    """Must-implement adapter surface. Concrete adapters: imap / gmail / graph."""

    def list_folders(self) -> Sequence[RemoteFolder]:
        ...

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        ...

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        ...

    def fetch_mime(self, remote_id: str) -> bytes:
        ...

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        ...

    def apply_remote_operation(self, op_type: str, desired_state: dict[str, Any]) -> RemoteOperationResult:
        ...

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        ...

    def rate_limit_hint(self) -> RateLimitHint:
        ...


class StubProvider:
    """In-memory stub for unit tests — not a real protocol client."""

    def __init__(self, folders: Sequence[RemoteFolder] | None = None) -> None:
        self._folders = list(folders or [RemoteFolder("INBOX", "INBOX", "inbox")])
        self._messages: dict[str, list[RemoteMessageMeta]] = {f.remote_id: [] for f in self._folders}

    def list_folders(self) -> Sequence[RemoteFolder]:
        return list(self._folders)

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        return self.fetch_metadata_page(folder_remote_id, cursor)

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        items = self._messages.get(folder_remote_id, [])
        return MetadataPage(items=items, next_cursor=None, exhausted=True)

    def fetch_mime(self, remote_id: str) -> bytes:
        return b"From: stub@example.com\r\nSubject: stub\r\n\r\nbody\r\n"

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        return DeltaPage(changes=(), next_cursor=cursor, exhausted=True)

    def apply_remote_operation(self, op_type: str, desired_state: dict[str, Any]) -> RemoteOperationResult:
        return RemoteOperationResult(success=True, idempotent_noop=True)

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        return ()

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=60)
