"""Microsoft Graph provider adapter — Delta query contract (OAuth/HTTP TODO).

Cursor / checkpoint mapping
---------------------------
- ``sync_checkpoints.delta_link`` stores the opaque ``@odata.deltaLink``.
- While paging, ``cursor.next_link`` holds ``@odata.nextLink``.
- Deletions come as explicit ``@removed`` objects in delta payloads — never infer
  from a partial page.

TODO(mail-core):
- OAuth client-credentials / delegated token from credential_ref
- GET /me/mailFolders, /messages/delta HTTP clients
- /$value for MIME
"""

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


class GraphNotConfiguredError(NotImplementedError):
    """Raised until real Graph HTTP client is wired."""


@dataclass
class GraphProvider:
    credential_ref: str
    transport: Any | None = None
    _calls: list[str] = field(default_factory=list, repr=False)

    def list_folders(self) -> Sequence[RemoteFolder]:
        self._calls.append("list_folders")
        if self.transport is not None:
            data = self.transport("GET", "/me/mailFolders", {})
            return [
                RemoteFolder(
                    remote_id=f["id"],
                    name=f.get("displayName") or f["id"],
                    role=f.get("role") or "other",
                )
                for f in data.get("value") or []
            ]
        return [
            RemoteFolder("inbox", "Inbox", "inbox"),
            RemoteFolder("sentitems", "Sent Items", "sent"),
            RemoteFolder("deleteditems", "Deleted Items", "trash"),
            RemoteFolder("junkemail", "Junk Email", "junk"),
        ]

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        return self.fetch_metadata_page(folder_remote_id, cursor)

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        self._calls.append("fetch_metadata_page")
        if self.transport is None:
            raise GraphNotConfiguredError("Graph message list not wired yet")
        path = (cursor or {}).get("next_link") or f"/me/mailFolders/{folder_remote_id}/messages"
        data = self.transport("GET", path, {})
        if "page" in data:
            return data["page"]
        raise GraphNotConfiguredError("raw Graph list parsing not implemented")

    def fetch_mime(self, remote_id: str) -> bytes:
        if self.transport is None:
            raise GraphNotConfiguredError("Graph $value MIME not wired yet")
        data = self.transport("GET", f"/me/messages/{remote_id}/$value", {})
        return data["raw_bytes"]

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        self._calls.append("delta_changes")
        link = cursor.get("delta_link") or cursor.get("next_link")
        if not link:
            # First delta call
            link = f"/me/mailFolders/{folder_remote_id}/messages/delta"
        if self.transport is None:
            raise GraphNotConfiguredError("Graph delta query not wired yet")
        data = self.transport("GET", link, {})
        if "page" in data:
            return data["page"]
        raise GraphNotConfiguredError("raw Graph delta parsing not implemented")

    def apply_remote_operation(self, op_type: str, desired_state: dict[str, Any]) -> RemoteOperationResult:
        if self.transport is None:
            raise GraphNotConfiguredError("Graph patch/move not wired yet")
        data = self.transport("PATCH", "/me/messages", {"op": op_type, **desired_state})
        return RemoteOperationResult(success=bool(data.get("success", True)), remote_state=data.get("remote_state") or {})

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        if self.transport is None:
            raise GraphNotConfiguredError("Graph reconcile not wired yet")
        data = self.transport("RECONCILE", folder_remote_id, {"local": list(local_remote_ids)})
        return list(data.get("actions") or [])

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=60, reason="graph default hint")
