"""Mutable in-memory provider for sync/archive/remote_ops tests."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Sequence

from mail_core.providers.base import (
    DeltaChange,
    DeltaPage,
    FolderStatus,
    IdleNotSupportedError,
    MetadataPage,
    RateLimitHint,
    ReconcileAction,
    RemoteFolder,
    RemoteMessageMeta,
    RemoteOperationResult,
)
from mail_core.providers.http import CursorInvalidError

_MAX_CHANGE_LOG_ENTRIES = 10_000


@dataclass
class MemoryProvider:
    folders: list[RemoteFolder] = field(default_factory=list)
    messages: dict[str, list[RemoteMessageMeta]] = field(default_factory=dict)
    mime: dict[str, bytes] = field(default_factory=dict)
    page_size: int = 50
    # Per-folder monotonic modseq; change log for incremental sync.
    modseq: dict[str, int] = field(default_factory=dict)
    # folder -> list of (modseq, DeltaChange); bounded, with a rebuild fallback
    # for consumers whose cursor predates the retained history.
    change_log: dict[str, list[tuple[int, DeltaChange]]] = field(default_factory=dict)
    change_log_pruned_through: dict[str, int] = field(default_factory=dict)
    flagged: set[str] = field(default_factory=set)

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> MemoryProvider:
        folders = [
            RemoteFolder(**f) if not isinstance(f, RemoteFolder) else f
            for f in cfg.get("folders")
            or [{"remote_id": "INBOX", "name": "INBOX", "role": "inbox"}]
        ]
        return cls(folders=list(folders), page_size=int(cfg.get("page_size") or 50))

    def _bump(self, folder_remote_id: str, change: DeltaChange) -> None:
        n = int(self.modseq.get(folder_remote_id, 0)) + 1
        self.modseq[folder_remote_id] = n
        log = self.change_log.setdefault(folder_remote_id, [])
        log.append((n, change))
        overflow = len(log) - _MAX_CHANGE_LOG_ENTRIES
        if overflow > 0:
            self.change_log_pruned_through[folder_remote_id] = log[overflow - 1][0]
            del log[:overflow]

    def seed(
        self,
        folder_remote_id: str,
        metas: Sequence[RemoteMessageMeta],
        mime_by_remote_id: dict[str, bytes] | None = None,
    ) -> None:
        self.messages[folder_remote_id] = list(metas)
        self.modseq.setdefault(folder_remote_id, 0)
        self.change_log.setdefault(folder_remote_id, [])
        for m in metas:
            self._bump(folder_remote_id, DeltaChange(kind="upsert", remote_id=m.remote_id, meta=m))
        if mime_by_remote_id:
            self.mime.update(mime_by_remote_id)

    def append_message(self, folder_remote_id: str, meta: RemoteMessageMeta, mime: bytes | None = None) -> None:
        self.messages.setdefault(folder_remote_id, []).append(meta)
        if mime is not None:
            self.mime[meta.remote_id] = mime
        self._bump(folder_remote_id, DeltaChange(kind="upsert", remote_id=meta.remote_id, meta=meta))

    def flag_message(self, folder_remote_id: str, remote_id: str, *, is_read: bool) -> None:
        msgs = self.messages.get(folder_remote_id, [])
        for i, m in enumerate(msgs):
            if m.remote_id != remote_id:
                continue
            updated = replace(m, is_read=is_read)
            msgs[i] = updated
            self._bump(
                folder_remote_id,
                DeltaChange(kind="flag", remote_id=remote_id, meta=updated, flags={"is_read": is_read}),
            )
            return

    def move_message(self, from_folder: str, to_folder: str, remote_id: str) -> bool:
        msgs = self.messages.get(from_folder, [])
        found = None
        keep = []
        for m in msgs:
            if m.remote_id == remote_id:
                found = m
            else:
                keep.append(m)
        if found is None:
            return False
        self.messages[from_folder] = keep
        self.messages.setdefault(to_folder, []).append(found)
        self._bump(from_folder, DeltaChange(kind="delete", remote_id=remote_id))
        self._bump(to_folder, DeltaChange(kind="upsert", remote_id=remote_id, meta=found))
        return True

    def remove_message(self, folder_remote_id: str, remote_id: str) -> None:
        self.messages[folder_remote_id] = [m for m in self.messages.get(folder_remote_id, []) if m.remote_id != remote_id]
        self.mime.pop(remote_id, None)
        self._bump(folder_remote_id, DeltaChange(kind="delete", remote_id=remote_id))

    def list_folders(self) -> Sequence[RemoteFolder]:
        return list(self.folders)

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        return self.fetch_metadata_page(folder_remote_id, cursor)

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        # A370: page by remote_id anchor, not by offset. With offset
        # paging, inserting/removing entries before the scan position
        # mid-scan shifts the window and skips or repeats entries; an
        # anchor on the last returned remote_id is immune to mutations
        # before the scan position (matching real providers' cursor
        # semantics). ``offset`` is still emitted for observability and
        # used only as a degraded fallback when the anchor entry itself
        # was deleted mid-scan, or for legacy offset-only cursors.
        items = list(self.messages.get(folder_remote_id, []))
        cursor = cursor or {}
        anchor = cursor.get("after_remote_id")
        start: int | None = None
        if anchor is not None:
            for idx, meta in enumerate(items):
                if meta.remote_id == anchor:
                    start = idx + 1
                    break
        if start is None:
            start = min(int(cursor.get("offset") or 0), len(items))
        batch = items[start : start + self.page_size]
        next_offset = start + len(batch)
        exhausted = next_offset >= len(items)
        return MetadataPage(
            items=batch,
            next_cursor={
                "after_remote_id": batch[-1].remote_id if batch else anchor,
                "offset": next_offset,
                "page_size": self.page_size,
                "modseq": self.modseq.get(folder_remote_id, 0),
            },
            exhausted=exhausted,
        )

    def fetch_mime(self, remote_id: str, *, folder_remote_id: str | None = None) -> bytes:
        if remote_id not in self.mime:
            raise KeyError(remote_id)
        return self.mime[remote_id]

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        """Return retained deltas or request a full rebuild for a stale cursor."""
        since = int(cursor.get("modseq") or 0)
        if since < self.change_log_pruned_through.get(folder_remote_id, 0):
            raise CursorInvalidError("memory provider cursor predates retained change history")
        log = self.change_log.get(folder_remote_id, [])
        pending = [(n, ch) for n, ch in log if n > since]
        batch = pending[: self.page_size]
        changes = [ch for _, ch in batch]
        next_modseq = batch[-1][0] if batch else since
        exhausted = len(pending) <= self.page_size
        return DeltaPage(
            changes=changes,
            next_cursor={"modseq": next_modseq, "page_size": self.page_size},
            exhausted=exhausted,
        )

    def apply_remote_operation(self, op_type: str, desired_state: dict[str, Any]) -> RemoteOperationResult:
        from mail_core.providers.remote_writeback import (
            OP_MARK_READ,
            OP_MOVE,
            OP_SET_FLAG,
            OP_TRASH,
            normalize_op_type,
            require_remote_id,
        )

        try:
            remote_id = require_remote_id(desired_state)
        except ValueError as exc:
            return RemoteOperationResult(success=False, error=str(exc))
        folder = str(desired_state.get("folder_remote_id") or "INBOX")
        op = normalize_op_type(op_type)

        if op == OP_MARK_READ:
            want = bool(desired_state.get("is_read", True))
            self.flag_message(folder, remote_id, is_read=want)
            return RemoteOperationResult(success=True, remote_state={"is_read": want})

        if op == OP_SET_FLAG:
            want = bool(desired_state.get("is_flagged", True))
            if want:
                self.flagged.add(remote_id)
            else:
                self.flagged.discard(remote_id)
            # Emit a flag change for sync consumers
            for m in self.messages.get(folder, []):
                if m.remote_id == remote_id:
                    self._bump(
                        folder,
                        DeltaChange(kind="flag", remote_id=remote_id, meta=m, flags={"is_flagged": want}),
                    )
                    break
            return RemoteOperationResult(success=True, remote_state={"is_flagged": want})

        if op == OP_MOVE:
            dest = str(desired_state.get("dest_folder_remote_id") or desired_state.get("to_folder") or "")
            if not dest:
                return RemoteOperationResult(success=False, error="missing dest_folder_remote_id")
            ok = self.move_message(folder, dest, remote_id)
            return RemoteOperationResult(
                success=ok,
                idempotent_noop=not ok,
                error=None if ok else "message not found",
                remote_state={"folder_remote_id": dest} if ok else {},
            )

        if op == OP_TRASH:
            trash = str(desired_state.get("trash_folder_remote_id") or "Trash")
            # Prefer move-to-trash when folder exists; else hard delete
            roles = {f.remote_id: f.role for f in self.folders}
            if trash in self.messages or trash in roles or any(f.role == "trash" for f in self.folders):
                if any(f.role == "trash" for f in self.folders) and trash not in self.messages:
                    trash = next(f.remote_id for f in self.folders if f.role == "trash")
                self.messages.setdefault(trash, [])
                ok = self.move_message(folder, trash, remote_id)
                if ok:
                    return RemoteOperationResult(success=True, remote_state={"folder_remote_id": trash})
            before = len(self.messages.get(folder, []))
            self.remove_message(folder, remote_id)
            after = len(self.messages.get(folder, []))
            return RemoteOperationResult(success=True, idempotent_noop=before == after)

        return RemoteOperationResult(success=False, error=f"unsupported op {op_type}")

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        remote = {m.remote_id for m in self.messages.get(folder_remote_id, [])}
        local = set(local_remote_ids)
        return [ReconcileAction(kind="delete", remote_id=rid) for rid in sorted(local - remote)]

    def probe_folder_status(self, folder_remote_id: str) -> FolderStatus | None:
        items = self.messages.get(folder_remote_id)
        if items is None:
            return None
        unseen = sum(1 for m in items if m.is_read is False)
        return FolderStatus(
            messages=len(items),
            uidnext=None,
            unseen=unseen,
            highestmodseq=int(self.modseq.get(folder_remote_id, 0)) or None,
        )

    def open_idle_session(self, folder_remote_id: str) -> Any:
        raise IdleNotSupportedError("memory provider does not support IDLE")

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=1000)
