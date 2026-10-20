"""Gmail provider adapter skeleton (History API). Real OAuth/HTTP later."""

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
class GmailProvider:
    """Placeholder — credentials via credential_ref / Keychain in a later milestone."""

    credential_ref: str
    user_id: str = "me"
    _calls: list[str] = field(default_factory=list, repr=False)

    def list_folders(self) -> Sequence[RemoteFolder]:
        self._calls.append("list_folders")
        # Gmail labels mapped to roles — stub returns INBOX + All Mail.
        return [
            RemoteFolder("INBOX", "INBOX", "inbox"),
            RemoteFolder("CATEGORY_PERSONAL", "Personal", "other"),
        ]

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        return self.fetch_metadata_page(folder_remote_id, cursor)

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        self._calls.append("fetch_metadata_page")
        raise NotImplementedError("Gmail API metadata fetch not wired yet")

    def fetch_mime(self, remote_id: str) -> bytes:
        raise NotImplementedError("Gmail raw MIME fetch not wired yet")

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        # historyId lives in checkpoint.cursor / history_id column.
        raise NotImplementedError("Gmail History API not wired yet")

    def apply_remote_operation(self, op_type: str, desired_state: dict[str, Any]) -> RemoteOperationResult:
        raise NotImplementedError("Gmail modify not wired yet")

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        raise NotImplementedError("Gmail reconcile not wired yet")

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=250, reason="gmail default quota hint")
