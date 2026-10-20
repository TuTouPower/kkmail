"""Microsoft Graph provider adapter skeleton (Delta query)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from mail_core.providers.base import (
    DeltaPage,
    MetadataPage,
    RateLimitHint,
    ReconcileAction,
    RemoteFolder,
    RemoteOperationResult,
)


@dataclass
class GraphProvider:
    credential_ref: str
    _calls: list[str] = field(default_factory=list, repr=False)

    def list_folders(self) -> Sequence[RemoteFolder]:
        self._calls.append("list_folders")
        return [
            RemoteFolder("inbox", "Inbox", "inbox"),
            RemoteFolder("sentitems", "Sent Items", "sent"),
            RemoteFolder("deleteditems", "Deleted Items", "trash"),
            RemoteFolder("junkemail", "Junk Email", "junk"),
        ]

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        return self.fetch_metadata_page(folder_remote_id, cursor)

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        raise NotImplementedError("Graph message list not wired yet")

    def fetch_mime(self, remote_id: str) -> bytes:
        raise NotImplementedError("Graph $value MIME not wired yet")

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        # delta_link persisted on sync_checkpoints.delta_link
        raise NotImplementedError("Graph delta query not wired yet")

    def apply_remote_operation(self, op_type: str, desired_state: dict[str, Any]) -> RemoteOperationResult:
        raise NotImplementedError("Graph patch/move not wired yet")

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        raise NotImplementedError("Graph reconcile not wired yet")

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=60, reason="graph default hint")
