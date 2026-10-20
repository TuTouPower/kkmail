"""Gmail provider adapter — History API contract (OAuth/HTTP TODO).

Cursor / checkpoint mapping
---------------------------
- ``sync_checkpoints.history_id`` holds the last processed ``historyId``.
- ``cursor`` JSON may also include ``{"historyId": "...", "pageToken": "..."}``.
- When History returns ``404`` / ``historyId`` invalid → caller must fall back to
  a controlled partial/full rebuild (engine responsibility; not silent delete).

TODO(mail-core):
- OAuth via credential_ref → access token
- users.messages.list / users.history.list HTTP clients
- users.messages.get format=raw for MIME
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


class GmailNotConfiguredError(NotImplementedError):
    """Raised until real Gmail HTTP client is wired."""


@dataclass
class GmailProvider:
    credential_ref: str
    user_id: str = "me"
    # Optional injectable transport for contract tests: callable(method, path, params) -> dict
    transport: Any | None = None
    _calls: list[str] = field(default_factory=list, repr=False)

    def list_folders(self) -> Sequence[RemoteFolder]:
        self._calls.append("list_folders")
        if self.transport is not None:
            data = self.transport("GET", f"/gmail/v1/users/{self.user_id}/labels", {})
            labels = data.get("labels") or []
            out: list[RemoteFolder] = []
            for lab in labels:
                name = lab.get("name") or lab.get("id")
                role = "inbox" if name == "INBOX" else "other"
                out.append(RemoteFolder(remote_id=lab["id"], name=name, role=role))
            return out
        return [
            RemoteFolder("INBOX", "INBOX", "inbox"),
            RemoteFolder("CATEGORY_PERSONAL", "Personal", "other"),
        ]

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        return self.fetch_metadata_page(folder_remote_id, cursor)

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        self._calls.append("fetch_metadata_page")
        if self.transport is None:
            raise GmailNotConfiguredError("Gmail API metadata fetch not wired yet")
        params = {"labelIds": folder_remote_id, "maxResults": 50}
        if cursor and cursor.get("pageToken"):
            params["pageToken"] = cursor["pageToken"]
        data = self.transport("GET", f"/gmail/v1/users/{self.user_id}/messages", params)
        # Contract: transport returns already-normalized MetadataPage fields for tests,
        # or raw API shape — tests use normalized.
        if "page" in data:
            return data["page"]
        raise GmailNotConfiguredError("raw Gmail list parsing not implemented")

    def fetch_mime(self, remote_id: str) -> bytes:
        if self.transport is None:
            raise GmailNotConfiguredError("Gmail raw MIME fetch not wired yet")
        data = self.transport(
            "GET",
            f"/gmail/v1/users/{self.user_id}/messages/{remote_id}",
            {"format": "raw"},
        )
        return data["raw_bytes"]

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        self._calls.append("delta_changes")
        history_id = cursor.get("historyId")
        if not history_id:
            raise ValueError("Gmail delta requires cursor.historyId")
        if self.transport is None:
            raise GmailNotConfiguredError("Gmail History API not wired yet")
        params = {"startHistoryId": history_id, "labelId": folder_remote_id}
        if cursor.get("pageToken"):
            params["pageToken"] = cursor["pageToken"]
        data = self.transport("GET", f"/gmail/v1/users/{self.user_id}/history", params)
        if "page" in data:
            return data["page"]
        raise GmailNotConfiguredError("raw Gmail history parsing not implemented")

    def apply_remote_operation(self, op_type: str, desired_state: dict[str, Any]) -> RemoteOperationResult:
        if self.transport is None:
            raise GmailNotConfiguredError("Gmail modify not wired yet")
        data = self.transport("POST", f"/gmail/v1/users/{self.user_id}/messages/modify", {"op": op_type, **desired_state})
        return RemoteOperationResult(success=bool(data.get("success", True)), remote_state=data.get("remote_state") or {})

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        if self.transport is None:
            raise GmailNotConfiguredError("Gmail reconcile not wired yet")
        data = self.transport("RECONCILE", folder_remote_id, {"local": list(local_remote_ids)})
        return list(data.get("actions") or [])

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=250, reason="gmail default quota hint")
