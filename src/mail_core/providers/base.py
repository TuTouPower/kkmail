"""Unified provider adapter interface (architecture §6.1).

Protocol details (Graph Delta, IMAP UID/MODSEQ) must stay
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
    selectable: bool = True


@dataclass(frozen=True, slots=True)
class RemoteMessageMeta:
    remote_id: str
    subject: str
    from_address: str
    from_name: str | None
    sort_time: datetime | None
    is_read: bool | None
    has_attachments: bool | None
    is_flagged: bool | None = None
    internet_message_id: str | None = None
    snippet: str | None = None
    provider_thread_key: str | None = None
    uid: int | None = None
    size_bytes: int | None = None
    to_addresses: tuple[str, ...] = ()
    cc_addresses: tuple[str, ...] = ()
    in_reply_to: str | None = None
    references: str | None = None
    # None denotes a complete snapshot; partial projections name supplied fields.
    supplied_fields: frozenset[str] | None = None


@dataclass(frozen=True, slots=True)
class MetadataPage:
    items: Sequence[RemoteMessageMeta]
    next_cursor: dict[str, Any] | None
    exhausted: bool


#: The only DeltaChange kinds apply_delta_page understands (A366).
DELTA_CHANGE_KINDS = frozenset({"upsert", "delete", "flag"})


@dataclass(frozen=True, slots=True)
class DeltaChange:
    """Normalized incremental change; deletions are explicit — never inferred."""

    kind: str  # upsert | delete | flag
    remote_id: str
    meta: RemoteMessageMeta | None = None
    flags: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # A366: reject unknown kinds at construction instead of letting
        # them be silently ignored when the page is applied.
        if self.kind not in DELTA_CHANGE_KINDS:
            raise ValueError(f"unknown DeltaChange kind: {self.kind!r}")


@dataclass(frozen=True, slots=True)
class DeltaPage:
    changes: Sequence[DeltaChange]
    next_cursor: dict[str, Any] | None
    exhausted: bool


@dataclass(frozen=True, slots=True)
class FolderStatus:
    """Cheap folder-level probe snapshot (t061 STATUS patrol).

    Every dimension is optional: servers that omit an item (e.g.
    Coremail omits UIDNEXT) report ``None`` for it, and change detection
    only compares dimensions both snapshots actually carry.
    """

    messages: int | None = None
    uidnext: int | None = None
    unseen: int | None = None
    highestmodseq: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        return {
            "messages": self.messages,
            "uidnext": self.uidnext,
            "unseen": self.unseen,
            "highestmodseq": self.highestmodseq,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "FolderStatus | None":
        if not isinstance(data, dict):
            return None

        def _int(key: str) -> int | None:
            value = data.get(key)
            return value if isinstance(value, int) and not isinstance(value, bool) else None

        return cls(
            messages=_int("messages"),
            uidnext=_int("uidnext"),
            unseen=_int("unseen"),
            highestmodseq=_int("highestmodseq"),
        )


class IdleNotSupportedError(RuntimeError):
    """The provider/server cannot maintain an IDLE watch session."""


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
class RemoteOperationItem:
    op_id: Any
    op_type: str
    desired_state: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReconcileAction:
    kind: str
    remote_id: str
    detail: dict[str, Any] = field(default_factory=dict)


class MailProvider(Protocol):
    """Must-implement adapter surface. Concrete adapters: imap / graph."""

    def list_folders(self) -> Sequence[RemoteFolder]:
        ...

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        ...

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        ...

    def fetch_mime(self, remote_id: str, *, folder_remote_id: str | None = None) -> bytes:
        ...

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        ...

    def apply_remote_operations(
        self, operations: Sequence[RemoteOperationItem]
    ) -> Sequence[tuple[Any, RemoteOperationResult]]:
        ...

    def apply_remote_operation(self, op_type: str, desired_state: dict[str, Any]) -> RemoteOperationResult:
        ...

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        ...

    def rate_limit_hint(self) -> RateLimitHint:
        ...

    def probe_folder_status(self, folder_remote_id: str) -> FolderStatus | None:
        """Cheap folder status probe (t061); ``None`` = unsupported."""
        ...

    def open_idle_session(self, folder_remote_id: str) -> Any:
        """Open a dedicated IDLE watch session (t061, IMAP only).

        Raises :class:`IdleNotSupportedError` when the provider or the
        server cannot IDLE. The returned session owns its connection —
        it never consumes a connection-slot permit.
        """
        ...


class StubProvider:
    """Unit-test double only — never returned by ``build_provider``.

    Production ``stub`` / ``memory`` accounts use ``MemoryProvider``. Do not wire
    this class into the sync engine; silent empty pages would look like a finished sync.
    """

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

    def fetch_mime(self, remote_id: str, *, folder_remote_id: str | None = None) -> bytes:
        return b"From: stub@example.com\r\nSubject: stub\r\n\r\nbody\r\n"

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        return DeltaPage(changes=(), next_cursor=cursor, exhausted=True)

    def apply_remote_operations(
        self, operations: Sequence[RemoteOperationItem]
    ) -> Sequence[tuple[Any, RemoteOperationResult]]:
        return [
            (
                op.op_id,
                self.apply_remote_operation(op.op_type, op.desired_state)
                if hasattr(self, "apply_remote_operation")
                else RemoteOperationResult(success=True, idempotent_noop=True),
            )
            for op in operations
        ]

    def apply_remote_operation(self, op_type: str, desired_state: dict[str, Any]) -> RemoteOperationResult:
        return RemoteOperationResult(success=True, idempotent_noop=True)

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        return ()

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=60)

    def probe_folder_status(self, folder_remote_id: str) -> FolderStatus | None:
        return None

    def open_idle_session(self, folder_remote_id: str) -> Any:
        raise IdleNotSupportedError("stub provider does not support IDLE")
