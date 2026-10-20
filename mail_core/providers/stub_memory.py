"""Mutable in-memory provider for sync/archive/remote_ops tests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    # folder_remote_id -> list of metas
    messages: dict[str, list[RemoteMessageMeta]] = field(default_factory=dict)
    mime: dict[str, bytes] = field(default_factory=dict)
    page_size: int = 50

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> MemoryProvider:
        folders = [
            RemoteFolder(**f) if not isinstance(f, RemoteFolder) else f
            for f in cfg.get("folders")
            or [{"remote_id": "INBOX", "name": "INBOX", "role": "inbox"}]
        ]
        # Allow serialized metas in config for bootstrap; usually tests mutate instance.
        return cls(folders=list(folders), page_size=int(cfg.get("page_size") or 50))

    def seed(
        self,
        folder_remote_id: str,
        metas: Sequence[RemoteMessageMeta],
        mime_by_remote_id: dict[str, bytes] | None = None,
    ) -> None:
        self.messages[folder_remote_id] = list(metas)
        if mime_by_remote_id:
            self.mime.update(mime_by_remote_id)

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
            next_cursor={"offset": next_offset, "page_size": self.page_size},
            exhausted=exhausted,
        )

    def fetch_mime(self, remote_id: str) -> bytes:
        if remote_id not in self.mime:
            raise KeyError(remote_id)
        return self.mime[remote_id]

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        page = self.fetch_metadata_page(folder_remote_id, cursor)
        return DeltaPage(
            changes=[DeltaChange(kind="upsert", remote_id=m.remote_id, meta=m) for m in page.items],
            next_cursor=page.next_cursor,
            exhausted=page.exhausted,
        )

    def apply_remote_operation(self, op_type: str, desired_state: dict[str, Any]) -> RemoteOperationResult:
        remote_id = str(desired_state.get("remote_id") or "")
        folder = str(desired_state.get("folder_remote_id") or "INBOX")
        msgs = self.messages.get(folder, [])
        if op_type == "mark_read":
            for i, m in enumerate(msgs):
                if m.remote_id == remote_id:
                    msgs[i] = RemoteMessageMeta(
                        remote_id=m.remote_id,
                        subject=m.subject,
                        from_address=m.from_address,
                        from_name=m.from_name,
                        sort_time=m.sort_time,
                        is_read=bool(desired_state.get("is_read", True)),
                        has_attachments=m.has_attachments,
                        internet_message_id=m.internet_message_id,
                        snippet=m.snippet,
                        provider_thread_key=m.provider_thread_key,
                        uid=m.uid,
                        size_bytes=m.size_bytes,
                        to_addresses=m.to_addresses,
                        cc_addresses=m.cc_addresses,
                    )
                    return RemoteOperationResult(success=True, remote_state={"is_read": msgs[i].is_read})
            return RemoteOperationResult(success=False, error="message not found")
        if op_type == "delete":
            before = len(msgs)
            self.messages[folder] = [m for m in msgs if m.remote_id != remote_id]
            self.mime.pop(remote_id, None)
            return RemoteOperationResult(success=True, idempotent_noop=before == len(self.messages[folder]))
        return RemoteOperationResult(success=False, error=f"unsupported op {op_type}")

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        remote = {m.remote_id for m in self.messages.get(folder_remote_id, [])}
        local = set(local_remote_ids)
        return [ReconcileAction(kind="delete", remote_id=rid) for rid in sorted(local - remote)]

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=1000)
