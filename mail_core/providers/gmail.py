"""Gmail provider adapter — History API via injectable HTTP transport.

Cursor / checkpoint mapping
---------------------------
- ``sync_checkpoints.history_id`` holds the last processed ``historyId``.
- ``cursor`` JSON may also include ``{"historyId": "...", "pageToken": "..."}``.
- When History returns ``404`` / ``historyId`` invalid → ``CursorInvalidError``
  (engine falls back to controlled metadata rebuild; never silent delete).

Without ``transport`` (and without a live credential HTTP client), methods raise
``GmailNotConfiguredError``.
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
    RemoteMessageMeta,
    RemoteOperationResult,
)
from mail_core.providers.http import CursorInvalidError, ProviderHttpError, RateLimitedError
from mail_core.providers.parsing.gmail_history import parse_gmail_history


class GmailNotConfiguredError(NotImplementedError):
    """Raised until a real Gmail HTTP transport is supplied."""


# Gmail system label id/name → FolderRole value
_GMAIL_LABEL_ROLES: dict[str, str] = {
    "INBOX": "inbox",
    "SENT": "sent",
    "DRAFT": "drafts",
    "TRASH": "trash",
    "SPAM": "junk",
}


def gmail_label_role(label_id: str | None, name: str | None = None) -> str:
    """Map Gmail system labels to FolderRole; user labels stay ``other``."""
    for key in (label_id, name):
        if key and key in _GMAIL_LABEL_ROLES:
            return _GMAIL_LABEL_ROLES[key]
    return "other"


def _raise_mapped(exc: ProviderHttpError) -> None:
    """Map transport errors. 404/410 → CursorInvalid only for history/sync semantics."""
    status = exc.status or 0
    body = exc.body
    text = str(body).lower() if body is not None else str(exc).lower()
    if status == 429:
        raise RateLimitedError(
            str(exc),
            retry_after_seconds=getattr(exc, "retry_after_seconds", None),
            body=body,
            headers=exc.headers,
        ) from exc
    # Do not treat every resource 404 (labels, messages.get) as cursor invalid.
    if "historyid" in text or (
        status in (404, 410)
        and ("history" in text or ("sync" in text and "invalid" in text))
    ):
        raise CursorInvalidError(str(exc), status=status, body=body, headers=exc.headers) from exc
    raise exc


@dataclass
class GmailProvider:
    credential_ref: str
    user_id: str = "me"
    # Optional injectable transport for contract tests / future OAuth client:
    # callable(method, path, params) -> dict  (may raise ProviderHttpError)
    transport: Any | None = None
    _calls: list[str] = field(default_factory=list, repr=False)

    def _call(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        if self.transport is None:
            raise GmailNotConfiguredError("Gmail HTTP transport not configured")
        try:
            return self.transport(method, path, params or {})
        except RateLimitedError:
            raise
        except CursorInvalidError:
            raise
        except ProviderHttpError as exc:
            _raise_mapped(exc)
            raise  # pragma: no cover

    def list_folders(self) -> Sequence[RemoteFolder]:
        self._calls.append("list_folders")
        if self.transport is None:
            raise GmailNotConfiguredError("Gmail HTTP transport not configured")
        data = self._call("GET", f"/gmail/v1/users/{self.user_id}/labels", {})
        labels = data.get("labels") or []
        out: list[RemoteFolder] = []
        for lab in labels:
            name = lab.get("name") or lab.get("id")
            role = gmail_label_role(lab.get("id"), name)
            out.append(RemoteFolder(remote_id=lab["id"], name=name, role=role))
        return out

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        return self.fetch_metadata_page(folder_remote_id, cursor)

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        self._calls.append("fetch_metadata_page")
        if self.transport is None:
            raise GmailNotConfiguredError("Gmail API metadata fetch not wired yet")
        params: dict[str, Any] = {"labelIds": folder_remote_id, "maxResults": 50}
        if cursor and cursor.get("pageToken"):
            params["pageToken"] = cursor["pageToken"]
        data = self._call("GET", f"/gmail/v1/users/{self.user_id}/messages", params)
        if "page" in data:
            return data["page"]
        # Minimal list shape → empty page stub (full metadata needs messages.get)
        msgs = data.get("messages") or []
        items = [
            RemoteMessageMeta(
                remote_id=m["id"],
                subject="",
                from_address="",
                from_name=None,
                sort_time=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                is_read=True,
                has_attachments=False,
                provider_thread_key=m.get("threadId"),
            )
            for m in msgs
            if m.get("id")
        ]
        token = data.get("nextPageToken")
        return MetadataPage(
            items=items,
            next_cursor={"pageToken": token} if token else None,
            exhausted=not bool(token),
        )

    def fetch_mime(self, remote_id: str, *, folder_remote_id: str | None = None) -> bytes:
        if self.transport is None:
            raise GmailNotConfiguredError("Gmail raw MIME fetch not wired yet")
        data = self._call(
            "GET",
            f"/gmail/v1/users/{self.user_id}/messages/{remote_id}",
            {"format": "raw"},
        )
        if isinstance(data.get("raw_bytes"), (bytes, bytearray)):
            return bytes(data["raw_bytes"])
        import base64

        raw = data.get("raw") or ""
        return base64.urlsafe_b64decode(raw + "==")

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        self._calls.append("delta_changes")
        history_id = cursor.get("historyId") or cursor.get("history_id")
        if not history_id:
            raise ValueError("Gmail delta requires cursor.historyId")
        if self.transport is None:
            raise GmailNotConfiguredError("Gmail History API not wired yet")
        params: dict[str, Any] = {
            "startHistoryId": str(history_id),
            "labelId": folder_remote_id,
            "historyTypes": "messageAdded,messageDeleted,labelAdded,labelRemoved",
        }
        if cursor.get("pageToken"):
            params["pageToken"] = cursor["pageToken"]
        data = self._call("GET", f"/gmail/v1/users/{self.user_id}/history", params)
        if "page" in data:
            return data["page"]
        return parse_gmail_history(data, folder_label=folder_remote_id)

    def apply_remote_operation(self, op_type: str, desired_state: dict[str, Any]) -> RemoteOperationResult:
        from mail_core.providers.remote_writeback import (
            OP_MARK_READ,
            OP_MOVE,
            OP_SET_FLAG,
            OP_TRASH,
            normalize_op_type,
            require_remote_id,
        )

        if self.transport is None:
            raise GmailNotConfiguredError("Gmail modify not wired yet")
        try:
            remote_id = require_remote_id(desired_state)
        except ValueError as exc:
            return RemoteOperationResult(success=False, error=str(exc))
        op = normalize_op_type(op_type)
        base = f"/gmail/v1/users/{self.user_id}/messages/{remote_id}"

        if op == OP_MARK_READ:
            want = bool(desired_state.get("is_read", True))
            body = {"removeLabelIds": ["UNREAD"]} if want else {"addLabelIds": ["UNREAD"]}
            data = self._call("POST", f"{base}/modify", body)
            return RemoteOperationResult(
                success=True,
                remote_state={"is_read": want, "labelIds": data.get("labelIds") or []},
            )

        if op == OP_SET_FLAG:
            want = bool(desired_state.get("is_flagged", True))
            body = {"addLabelIds": ["STARRED"]} if want else {"removeLabelIds": ["STARRED"]}
            data = self._call("POST", f"{base}/modify", body)
            return RemoteOperationResult(
                success=True,
                remote_state={"is_flagged": want, "labelIds": data.get("labelIds") or []},
            )

        if op == OP_MOVE:
            dest = str(desired_state.get("dest_folder_remote_id") or desired_state.get("to_folder") or "")
            src = str(desired_state.get("folder_remote_id") or "")
            if not dest:
                return RemoteOperationResult(success=False, error="missing dest_folder_remote_id")
            body: dict[str, Any] = {"addLabelIds": [dest]}
            if src:
                body["removeLabelIds"] = [src]
            data = self._call("POST", f"{base}/modify", body)
            return RemoteOperationResult(
                success=True,
                remote_state={"folder_remote_id": dest, "labelIds": data.get("labelIds") or []},
            )

        if op == OP_TRASH:
            data = self._call("POST", f"{base}/trash", {})
            return RemoteOperationResult(
                success=True,
                remote_state={"labelIds": data.get("labelIds") or ["TRASH"]},
            )

        return RemoteOperationResult(success=False, error=f"unsupported gmail op {op_type}")

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        if self.transport is None:
            raise GmailNotConfiguredError("Gmail reconcile not wired yet")
        data = self._call("RECONCILE", folder_remote_id, {"local": list(local_remote_ids)})
        return list(data.get("actions") or [])

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=250, reason="gmail default quota hint")
