"""Mutable in-memory provider for sync/archive/remote_ops tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from mail_core.providers.base import (
    DeltaChange,
    DeltaPage,
    MetadataPage,
    RateLimitHint,
    ReconcileAction,
    RemoteFolder,
    RemoteMessageMeta,
    RemoteOperationResult,
)


@dataclass
class MemoryProvider:
    folders: list[RemoteFolder] = field(default_factory=list)
    messages: dict[str, list[RemoteMessageMeta]] = field(default_factory=dict)
    mime: dict[str, bytes] = field(default_factory=dict)
    page_size: int = 50
    # Per-folder monotonic modseq; change log for incremental sync.
    modseq: dict[str, int] = field(default_factory=dict)
    # folder -> list of (modseq, DeltaChange)
    change_log: dict[str, list[tuple[int, DeltaChange]]] = field(default_factory=dict)

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
        self.change_log.setdefault(folder_remote_id, []).append((n, change))

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
            updated = RemoteMessageMeta(
                remote_id=m.remote_id,
                subject=m.subject,
                from_address=m.from_address,
                from_name=m.from_name,
                sort_time=m.sort_time,
                is_read=is_read,
                has_attachments=m.has_attachments,
                internet_message_id=m.internet_message_id,
                snippet=m.snippet,
                provider_thread_key=m.provider_thread_key,
                uid=m.uid,
                size_bytes=m.size_bytes,
                to_addresses=m.to_addresses,
                cc_addresses=m.cc_addresses,
            )
            msgs[i] = updated
            self._bump(
                folder_remote_id,
                DeltaChange(kind="flag", remote_id=remote_id, meta=updated, flags={"is_read": is_read}),
            )
            return

    def remove_message(self, folder_remote_id: str, remote_id: str) -> None:
        self.messages[folder_remote_id] = [m for m in self.messages.get(folder_remote_id, []) if m.remote_id != remote_id]
        self.mime.pop(remote_id, None)
        self._bump(folder_remote_id, DeltaChange(kind="delete", remote_id=remote_id))

    def list_folders(self) -> Sequence[RemoteFolder]:
        return list(self.folders)

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        return self.fetch_metadata_page(folder_remote_id, cursor)

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        items = list(self.messages.get(folder_remote_id, []))
        offset = int((cursor or {}).get("offset") or 0)
        batch = items[offset : offset + self.page_size]
        next_offset = offset + len(batch)
        exhausted = next_offset >= len(items)
        return MetadataPage(
            items=batch,
            next_cursor={
                "offset": next_offset,
                "page_size": self.page_size,
                "modseq": self.modseq.get(folder_remote_id, 0),
            },
            exhausted=exhausted,
        )

    def fetch_mime(self, remote_id: str) -> bytes:
        if remote_id not in self.mime:
            raise KeyError(remote_id)
        return self.mime[remote_id]

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        since = int(cursor.get("modseq") or 0)
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
        remote_id = str(desired_state.get("remote_id") or "")
        folder = str(desired_state.get("folder_remote_id") or "INBOX")
        if op_type == "mark_read":
            self.flag_message(folder, remote_id, is_read=bool(desired_state.get("is_read", True)))
            return RemoteOperationResult(success=True, remote_state={"is_read": bool(desired_state.get("is_read", True))})
        if op_type == "delete":
            before = len(self.messages.get(folder, []))
            self.remove_message(folder, remote_id)
            after = len(self.messages.get(folder, []))
            return RemoteOperationResult(success=True, idempotent_noop=before == after)
        return RemoteOperationResult(success=False, error=f"unsupported op {op_type}")

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        remote = {m.remote_id for m in self.messages.get(folder_remote_id, [])}
        local = set(local_remote_ids)
        return [ReconcileAction(kind="delete", remote_id=rid) for rid in sorted(local - remote)]

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=1000)
