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

import logging
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
from mail_core.providers.http import CursorInvalidError, ProviderHttpError, RateLimitedError
from mail_core.providers.parsing.gmail_history import (
    parse_gmail_history,
    parse_gmail_internal_date,
)

logger = logging.getLogger(__name__)


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



_GMAIL_META_HEADERS = (
    "From",
    "To",
    "Cc",
    "Subject",
    "Date",
    "Message-ID",
    "In-Reply-To",
    "References",
)


def _parse_address_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    import email.utils

    return tuple(addr for _, addr in email.utils.getaddresses([raw]) if addr)


def _meta_from_gmail_message(message: dict[str, Any]) -> RemoteMessageMeta:
    """Build RemoteMessageMeta from messages.get format=metadata (or richer)."""
    headers = {
        h["name"].lower(): h["value"]
        for h in (message.get("payload") or {}).get("headers") or []
        if "name" in h
    }
    subject = headers.get("subject") or ""
    from_raw = headers.get("from") or ""
    from_name = None
    frm = from_raw
    if "<" in from_raw and ">" in from_raw:
        name_part, _, rest = from_raw.partition("<")
        from_name = name_part.strip().strip('"') or None
        frm = rest.rstrip(">").strip()
    sort_time = parse_gmail_internal_date(message.get("internalDate"))
    label_ids = set(message.get("labelIds") or [])
    to_addrs = _parse_address_list(headers.get("to"))
    cc_addrs = _parse_address_list(headers.get("cc"))
    supplied = {"subject", "from_address", "from_name", "internet_message_id", "to_addresses", "cc_addresses", "in_reply_to", "references"} if "headers" in (message.get("payload") or {}) else set()
    for source, fields in {
        "labelIds": ("is_read", "is_flagged"), "internalDate": ("sort_time",),
        "snippet": ("snippet",), "threadId": ("provider_thread_key",),
        "has_attachments": ("has_attachments",),
    }.items():
        if source in message:
            supplied.update(fields)
    return RemoteMessageMeta(
        supplied_fields=frozenset(supplied),
        remote_id=str(message["id"]),
        subject=str(subject),
        from_address=str(frm),
        from_name=from_name,
        sort_time=sort_time,
        is_read="UNREAD" not in label_ids if "labelIds" in message else None,
        has_attachments=(
            bool(message["has_attachments"]) if message.get("has_attachments") is not None else None
        ),
        is_flagged="STARRED" in label_ids if "labelIds" in message else None,
        internet_message_id=headers.get("message-id"),
        snippet=message.get("snippet"),
        provider_thread_key=message.get("threadId"),
        to_addresses=to_addrs,
        cc_addresses=cc_addrs,
        in_reply_to=headers.get("in-reply-to"),
        references=headers.get("references"),
    )


def _validate_metadata_response(detail: Any, remote_id: str) -> None:
    if (
        not isinstance(detail, dict)
        or detail.get("id") != remote_id
        or not isinstance(detail.get("labelIds"), list)
        or not isinstance(detail.get("payload"), dict)
        or not isinstance(detail["payload"].get("headers"), list)
    ):
        raise ValueError("Gmail metadata response is incomplete or has mismatched id")


@dataclass
class GmailProvider:
    credential_ref: str
    user_id: str = "me"
    # Optional injectable transport for contract tests / future OAuth client:
    # callable(method, path, params) -> dict  (may raise ProviderHttpError)
    transport: Any | None = None
    timeout: float = 30.0
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

    def _confirmed_deleted_ids(self, folder_remote_id: str, remote_ids: Sequence[str]) -> set[str]:
        actions = self.reconcile(folder_remote_id, remote_ids)
        return {action.remote_id for action in actions if action.kind == "delete"}

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
        cur = dict(cursor or {})
        baseline_history_id = cur.get("historyId")
        if not baseline_history_id and not cur.get("pageToken"):
            # Record baseline history watermark before full scan starts
            try:
                profile = self._call("GET", f"/gmail/v1/users/{self.user_id}/profile", {})
                hid = profile.get("historyId") if isinstance(profile, dict) else None
                if hid:
                    baseline_history_id = str(hid)
            except Exception:
                pass

        params: dict[str, Any] = {"labelIds": folder_remote_id, "maxResults": 50}
        if cur.get("pageToken"):
            params["pageToken"] = cur["pageToken"]
        data = self._call("GET", f"/gmail/v1/users/{self.user_id}/messages", params)
        if "page" in data:
            return data["page"]
        msgs = data.get("messages") or []
        items: list[RemoteMessageMeta] = []
        missing_404: dict[str, ProviderHttpError] = {}
        for stub in msgs:
            mid = stub.get("id")
            if not mid:
                continue
            # Batch-detail: one messages.get(metadata) per id (no fabricated empty meta).
            try:
                detail = self._call(
                    "GET",
                    f"/gmail/v1/users/{self.user_id}/messages/{mid}",
                    {
                        "format": "metadata",
                        "metadataHeaders": list(_GMAIL_META_HEADERS),
                    },
                )
            except ProviderHttpError as exc:
                if exc.status == 404 and not isinstance(exc, CursorInvalidError):
                    missing_404[str(mid)] = exc
                    continue
                raise
            _validate_metadata_response(detail, str(mid))
            items.append(_meta_from_gmail_message(detail))
        if missing_404:
            confirmed_deleted = self._confirmed_deleted_ids(folder_remote_id, list(missing_404))
            unconfirmed = next((remote_id for remote_id in missing_404 if remote_id not in confirmed_deleted), None)
            if unconfirmed is not None:
                raise missing_404[unconfirmed]
            logger.warning(
                "Gmail metadata hydration confirmed %d message(s) deleted before detail fetch; skipping",
                len(confirmed_deleted),
            )
        token = data.get("nextPageToken")
        next_cursor: dict[str, Any] = {}
        if token:
            next_cursor["pageToken"] = token
        exhausted = not bool(token)
        if not baseline_history_id and exhausted:
            # Fallback stamp historyId if start probe failed
            try:
                profile = self._call("GET", f"/gmail/v1/users/{self.user_id}/profile", {})
                hid = profile.get("historyId") if isinstance(profile, dict) else None
                if hid:
                    baseline_history_id = str(hid)
            except Exception:
                pass
        if baseline_history_id:
            next_cursor["historyId"] = baseline_history_id
        return MetadataPage(
            items=items,
            next_cursor=next_cursor or None,
            exhausted=exhausted,
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

        raw = data.get("raw")
        if not isinstance(raw, str) or not raw:
            raise RuntimeError("Gmail messages.get(format=raw) missing raw MIME")
        # urlsafe_b64decode needs length % 4 == 0; pad only as needed (never force "==").
        pad = "=" * ((4 - len(raw) % 4) % 4)
        return base64.urlsafe_b64decode(raw + pad)

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
            "historyTypes": ["messageAdded", "messageDeleted", "labelAdded", "labelRemoved"],
        }
        if cursor.get("pageToken"):
            params["pageToken"] = cursor["pageToken"]
        data = self._call("GET", f"/gmail/v1/users/{self.user_id}/history", params)
        if "page" in data:
            return data["page"]
        page = parse_gmail_history(
            data,
            folder_label=folder_remote_id,
            start_history_id=str(history_id),
        )
        hydrated_changes: list[DeltaChange] = []
        missing_404: dict[str, ProviderHttpError] = {}
        missing_positions: list[tuple[int, str]] = []
        for change in page.changes:
            if change.kind == "upsert":
                try:
                    detail = self._call(
                        "GET",
                        f"/gmail/v1/users/{self.user_id}/messages/{change.remote_id}",
                        {"format": "metadata", "metadataHeaders": list(_GMAIL_META_HEADERS)},
                    )
                except ProviderHttpError as exc:
                    if exc.status == 404 and not isinstance(exc, CursorInvalidError):
                        missing_404[change.remote_id] = exc
                        missing_positions.append((len(hydrated_changes), change.remote_id))
                        hydrated_changes.append(change)
                        continue
                    raise
                _validate_metadata_response(detail, change.remote_id)
                change = DeltaChange(
                    kind="upsert", remote_id=change.remote_id,
                    meta=_meta_from_gmail_message(detail), flags=change.flags,
                )
            hydrated_changes.append(change)
        if missing_404:
            confirmed_deleted = self._confirmed_deleted_ids(folder_remote_id, list(missing_404))
            unconfirmed = next((remote_id for remote_id in missing_404 if remote_id not in confirmed_deleted), None)
            if unconfirmed is not None:
                raise missing_404[unconfirmed]
            for position, remote_id in missing_positions:
                hydrated_changes[position] = DeltaChange(kind="delete", remote_id=remote_id)
            logger.warning(
                "Gmail delta hydration confirmed %d message(s) deleted before detail fetch; applying deletes",
                len(confirmed_deleted),
            )
        return DeltaPage(
            changes=hydrated_changes,
            next_cursor=page.next_cursor,
            exhausted=page.exhausted,
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
        remote_ids: set[str] = set()
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"labelIds": folder_remote_id, "maxResults": 500}
            if page_token:
                params["pageToken"] = page_token
            data = self._call("GET", f"/gmail/v1/users/{self.user_id}/messages", params)
            if "page" in data:
                page = data["page"]
                items = getattr(page, "items", []) or []
                for it in items:
                    remote_ids.add(str(getattr(it, "remote_id", "")))
                cursor = getattr(page, "next_cursor", None)
                page_token = cursor.get("pageToken") if isinstance(cursor, dict) else None
                if not page_token:
                    break
            else:
                for m in data.get("messages") or []:
                    if m.get("id"):
                        remote_ids.add(str(m["id"]))
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
        local = set(local_remote_ids)
        return [ReconcileAction(kind="delete", remote_id=rid) for rid in sorted(local - remote_ids)]

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=250, reason="gmail default quota hint")
