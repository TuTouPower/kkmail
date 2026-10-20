"""Microsoft Graph provider adapter — Delta query via injectable HTTP transport.

Cursor / checkpoint mapping
---------------------------
- ``sync_checkpoints.delta_link`` stores the opaque ``@odata.deltaLink``.
- While paging, ``cursor.next_link`` holds ``@odata.nextLink``.
- Deletions come as explicit ``@removed`` objects — never inferred from a partial page.

Without ``transport``, methods raise ``GraphNotConfiguredError``.
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
from mail_core.providers.parsing.graph_delta import parse_graph_delta


class GraphNotConfiguredError(NotImplementedError):
    """Raised until a real Graph HTTP transport is supplied."""


def _raise_mapped(exc: ProviderHttpError) -> None:
    status = exc.status or 0
    body = exc.body
    text = str(body).lower() if body is not None else str(exc).lower()
    if status == 429:
        raise RateLimitedError(str(exc), body=body, headers=exc.headers) from exc
    # Graph: 410 Gone / syncStateNotFound when delta token is stale
    if status in (404, 410) or "syncstatenotfound" in text or "resyncrequired" in text:
        raise CursorInvalidError(str(exc), status=status, body=body, headers=exc.headers) from exc
    raise exc


@dataclass
class GraphProvider:
    credential_ref: str
    transport: Any | None = None
    _calls: list[str] = field(default_factory=list, repr=False)

    def _call(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        if self.transport is None:
            raise GraphNotConfiguredError("Graph HTTP transport not configured")
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
            raise GraphNotConfiguredError("Graph HTTP transport not configured")
        data = self._call("GET", "/me/mailFolders", {})
        return [
            RemoteFolder(
                remote_id=f["id"],
                name=f.get("displayName") or f["id"],
                role=f.get("role") or "other",
            )
            for f in data.get("value") or []
        ]

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        return self.fetch_metadata_page(folder_remote_id, cursor)

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        self._calls.append("fetch_metadata_page")
        if self.transport is None:
            raise GraphNotConfiguredError("Graph message list not wired yet")
        path = (cursor or {}).get("next_link") or f"/me/mailFolders/{folder_remote_id}/messages"
        data = self._call("GET", path, {})
        if "page" in data:
            return data["page"]
        # Reuse delta parser shape for list (value + nextLink)
        page = parse_graph_delta(data)
        items = [c.meta for c in page.changes if c.meta is not None]
        return MetadataPage(items=items, next_cursor=page.next_cursor, exhausted=page.exhausted)

    def fetch_mime(self, remote_id: str, *, folder_remote_id: str | None = None) -> bytes:
        if self.transport is None:
            raise GraphNotConfiguredError("Graph $value MIME not wired yet")
        data = self._call("GET", f"/me/messages/{remote_id}/$value", {})
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        return bytes(data["raw_bytes"])

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        self._calls.append("delta_changes")
        link = cursor.get("delta_link") or cursor.get("next_link")
        if not link:
            link = f"/me/mailFolders/{folder_remote_id}/messages/delta"
        if self.transport is None:
            raise GraphNotConfiguredError("Graph delta query not wired yet")
        data = self._call("GET", link, {})
        if "page" in data:
            return data["page"]
        return parse_graph_delta(data)

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
            raise GraphNotConfiguredError("Graph patch/move not wired yet")
        try:
            remote_id = require_remote_id(desired_state)
        except ValueError as exc:
            return RemoteOperationResult(success=False, error=str(exc))
        op = normalize_op_type(op_type)
        msg_path = f"/me/messages/{remote_id}"

        if op == OP_MARK_READ:
            want = bool(desired_state.get("is_read", True))
            data = self._call("PATCH", msg_path, {"isRead": want})
            return RemoteOperationResult(success=True, remote_state={"is_read": data.get("isRead", want)})

        if op == OP_SET_FLAG:
            want = bool(desired_state.get("is_flagged", True))
            data = self._call("PATCH", msg_path, {"flag": {"flagStatus": "flagged" if want else "notFlagged"}})
            return RemoteOperationResult(success=True, remote_state={"is_flagged": want, "flag": data.get("flag")})

        if op == OP_MOVE:
            dest = str(desired_state.get("dest_folder_remote_id") or desired_state.get("to_folder") or "")
            if not dest:
                return RemoteOperationResult(success=False, error="missing dest_folder_remote_id")
            data = self._call("POST", f"{msg_path}/move", {"destinationId": dest})
            return RemoteOperationResult(
                success=True,
                remote_state={"folder_remote_id": data.get("parentFolderId") or dest, "id": data.get("id") or remote_id},
            )

        if op == OP_TRASH:
            # Soft-delete: move to deleteditems when provided, else DELETE
            trash = str(desired_state.get("trash_folder_remote_id") or "deleteditems")
            try:
                data = self._call("POST", f"{msg_path}/move", {"destinationId": trash})
                return RemoteOperationResult(
                    success=True,
                    remote_state={"folder_remote_id": data.get("parentFolderId") or trash},
                )
            except Exception:
                self._call("DELETE", msg_path, {})
                return RemoteOperationResult(success=True, remote_state={"deleted": True})

        return RemoteOperationResult(success=False, error=f"unsupported graph op {op_type}")

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        if self.transport is None:
            raise GraphNotConfiguredError("Graph reconcile not wired yet")
        data = self._call("RECONCILE", folder_remote_id, {"local": list(local_remote_ids)})
        return list(data.get("actions") or [])

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=60, reason="graph default hint")
