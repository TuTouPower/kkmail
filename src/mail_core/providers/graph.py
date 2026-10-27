"""Microsoft Graph provider adapter — Delta query via injectable HTTP transport.

Cursor / checkpoint mapping
---------------------------
- ``sync_checkpoints.delta_link`` stores the opaque ``@odata.deltaLink``.
- While paging, ``cursor.next_link`` holds ``@odata.nextLink``.
- Deletions come as explicit ``@removed`` objects — never inferred from a partial page.

Without ``transport``, methods raise ``GraphNotConfiguredError``.
"""

from __future__ import annotations

import inspect
import logging
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
from mail_core.providers.parsing.graph_delta import parse_graph_delta, parse_graph_metadata_page


class GraphNotConfiguredError(NotImplementedError):
    """Raised when Graph has no HTTP transport, typically because credential_ref is missing."""


_GRAPH_WELL_KNOWN_ROLES: dict[str, str] = {
    "inbox": "inbox",
    "sentitems": "sent",
    "deleteditems": "trash",
    "drafts": "drafts",
    "junkemail": "junk",
    "archive": "archive",
}
MAX_GRAPH_PAGES_PER_CALL = 100
MAX_GRAPH_ITEMS_PER_CALL = 50_000


class GraphPaginationError(RuntimeError):
    """Raised when Graph paging cannot complete within its safety bounds."""


def _assert_single_page_within_item_limit(data: Any, context: str) -> None:
    # A290: a single page is one call's worth of items, so the same
    # MAX_GRAPH_ITEMS_PER_CALL bound list/reconcile enforce applies here.
    if isinstance(data, dict):
        value = data.get("value")
        if isinstance(value, (list, tuple)) and len(value) > MAX_GRAPH_ITEMS_PER_CALL:
            raise GraphPaginationError(
                f"Graph {context} page exceeded the {MAX_GRAPH_ITEMS_PER_CALL} item limit"
            )


def graph_folder_role(
    folder: dict[str, Any],
    inbox_id: str | None = None,
    well_known_ids: dict[str, str] | None = None,
) -> str:
    """Classify by verified well-known endpoint ID, else ``other``.

    Real Graph ``mailFolder`` resources carry no ``role``/``wellKnownName``
    properties, so classification must come from IDs resolved through the
    well-known endpoints (``/me/mailFolders/sentitems`` etc.) — that map is
    ``well_known_ids`` (folder id -> role). The only name-based fallback is
    the historical Inbox display-name heuristic, applied solely when the
    canonical inbox ID is unknown so a user folder named "Inbox" can never
    become a second inbox (R01).
    """
    fid = folder.get("id")
    if well_known_ids and fid in well_known_ids:
        return well_known_ids[fid]
    if inbox_id and fid == inbox_id:
        return "inbox"
    inbox_known = inbox_id is not None or (
        well_known_ids is not None and "inbox" in well_known_ids.values()
    )
    disp = (folder.get("displayName") or "").strip().lower()
    if not inbox_known and disp == "inbox":
        return "inbox"
    return "other"


def _raise_mapped(exc: ProviderHttpError, path: str = "") -> None:
    status = exc.status or 0
    body = exc.body
    text = str(body).lower() if body is not None else str(exc).lower()
    if status == 429:
        raise RateLimitedError(str(exc), body=body, headers=exc.headers) from exc
    # Graph cursor invalidation (A367): only 410 Gone, an explicit error
    # code (syncStateNotFound / resyncRequired), or a 404 from a delta /
    # sync-cursor endpoint. An ordinary 404 whose body merely mentions
    # "delta"/"sync" is a plain resource miss, not a stale cursor.
    from mail_core.providers.oauth import _url_is_sync_cursor_endpoint

    if (
        status == 410
        or "syncstatenotfound" in text
        or "resyncrequired" in text
        or (status == 404 and _url_is_sync_cursor_endpoint(path))
    ):
        raise CursorInvalidError(str(exc), status=status, body=body, headers=exc.headers) from exc
    raise exc


@dataclass
class GraphProvider:
    credential_ref: str
    transport: Any | None = None
    timeout: float = 30.0
    # Connection-budget wiring (design §7): the class
    # travels on the instance; build_provider wires the budget into the
    # urllib transport stack and leaves ``permit_factory`` None here.
    traffic_class: Any = "foreground"
    permit_factory: Any = None
    _calls: list[str] = field(default_factory=list, repr=False)

    def _call(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        if self.transport is None:
            raise GraphNotConfiguredError("Graph HTTP transport not configured")
        from mail_core.providers.connection_slots import permit_scope

        try:
            with permit_scope(self.permit_factory, self.traffic_class):
                # A274: self.timeout must not be a dead field — forward it
                # to transports that accept a timeout keyword; legacy
                # three-argument transports keep their existing contract
                # (the factory's urllib transport binds its timeout at
                # construction time).
                try:
                    parameters = inspect.signature(self.transport).parameters
                    accepts_timeout = "timeout" in parameters or any(
                        p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()
                    )
                except (TypeError, ValueError):
                    accepts_timeout = False
                if accepts_timeout:
                    return self.transport(method, path, params or {}, timeout=self.timeout)
                return self.transport(method, path, params or {})
        except RateLimitedError:
            raise
        except CursorInvalidError:
            raise
        except ProviderHttpError as exc:
            _raise_mapped(exc, path)
            raise  # pragma: no cover

    def list_folders(self) -> Sequence[RemoteFolder]:
        self._calls.append("list_folders")
        if self.transport is None:
            raise GraphNotConfiguredError("Graph HTTP transport not configured")
        # Resolve every well-known folder's stable ID through its endpoint;
        # list responses carry no role information (R01). A folder whose
        # endpoint is missing/unreadable simply stays unmapped.
        well_known_ids: dict[str, str] = {}
        for well_known_name, role in _GRAPH_WELL_KNOWN_ROLES.items():
            try:
                data = self._call("GET", f"/me/mailFolders/{well_known_name}", {})
            except ProviderHttpError as exc:
                # A289: only a 404 means "endpoint does not exist" here.
                # Capacity / rate-limit / server errors are real failures
                # and must propagate instead of degrading role mapping.
                if exc.status != 404:
                    raise
                continue
            if isinstance(data, dict) and data.get("id"):
                well_known_ids[str(data["id"])] = role
        inbox_id: str | None = next(
            (fid for fid, role in well_known_ids.items() if role == "inbox"), None
        )

        page_count = 0
        item_count = 0

        def _fetch_all_pages(url: str) -> list[dict[str, Any]]:
            nonlocal page_count, item_count
            items: list[dict[str, Any]] = []
            current_url: str | None = url
            visited_urls: set[str] = set()
            while current_url:
                if current_url in visited_urls:
                    raise GraphPaginationError("Graph folder pagination returned a repeated nextLink")
                if page_count >= MAX_GRAPH_PAGES_PER_CALL:
                    raise GraphPaginationError("Graph folder pagination exceeded the page limit")
                visited_urls.add(current_url)
                data = self._call("GET", current_url, {})
                page_count += 1
                page_items = data.get("value") or []
                item_count += len(page_items)
                if item_count > MAX_GRAPH_ITEMS_PER_CALL:
                    raise GraphPaginationError("Graph folder pagination exceeded the item limit")
                items.extend(page_items)
                current_url = data.get("@odata.nextLink") or data.get("next_link")
            return items

        def _collect(url: str, parent_id: str | None, visited: set[str]) -> list[RemoteFolder]:
            folders: list[RemoteFolder] = []
            for f in _fetch_all_pages(url):
                fid = str(f["id"])
                if fid in visited:
                    continue
                visited.add(fid)
                folders.append(
                    RemoteFolder(
                        remote_id=fid,
                        name=f.get("displayName") or fid,
                        role=graph_folder_role(f, inbox_id=inbox_id, well_known_ids=well_known_ids),
                        parent_remote_id=parent_id,
                    )
                )
                if int(f.get("childFolderCount") or 0) > 0:
                    child_url = f"/me/mailFolders/{fid}/childFolders"
                    folders.extend(_collect(child_url, parent_id=fid, visited=visited))
            return folders

        return _collect("/me/mailFolders", None, set())

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        return self.fetch_metadata_page(folder_remote_id, cursor)

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        self._calls.append("fetch_metadata_page")
        if self.transport is None:
            raise GraphNotConfiguredError("Graph message list not wired yet")
        path = (cursor or {}).get("next_link") or f"/me/mailFolders/{folder_remote_id}/messages"
        data = self._call("GET", path, {})
        _assert_single_page_within_item_limit(data, "metadata")
        return parse_graph_metadata_page(data)

    def fetch_mime(self, remote_id: str, *, folder_remote_id: str | None = None) -> bytes:
        if self.transport is None:
            raise GraphNotConfiguredError("Graph $value MIME not wired yet")
        data = self._call("GET", f"/me/messages/{remote_id}/$value", {})
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        if isinstance(data, dict):
            raw = data.get("raw_bytes")
            if isinstance(raw, (bytes, bytearray)):
                return bytes(raw)
            raw_s = data.get("raw")
            if isinstance(raw_s, (bytes, bytearray)):
                return bytes(raw_s)
            if isinstance(raw_s, str) and raw_s:
                return raw_s.encode("utf-8", errors="surrogateescape")
        raise RuntimeError("Graph $value response missing MIME bytes")

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        self._calls.append("delta_changes")
        link = cursor.get("delta_link") or cursor.get("next_link")
        if not link:
            link = f"/me/mailFolders/{folder_remote_id}/messages/delta"
        if self.transport is None:
            raise GraphNotConfiguredError("Graph delta query not wired yet")
        data = self._call("GET", link, {})
        _assert_single_page_within_item_limit(data, "delta")
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

        def _call_dict(method: str, path: str, params: dict[str, Any]) -> dict[str, Any]:
            # A369: a non-dict transport payload must not AttributeError
            # out of the RemoteOperationResult channel; normalize to {}
            # (branch fallbacks then apply) and leave a log trace.
            data = self._call(method, path, params)
            if isinstance(data, dict):
                return data
            logging.getLogger("mail_core.providers.graph").warning(
                "graph %s %s returned a non-dict response (%s); treating as empty",
                method,
                path,
                type(data).__name__,
            )
            return {}

        if op == OP_MARK_READ:
            want = bool(desired_state.get("is_read", True))
            data = _call_dict("PATCH", msg_path, {"isRead": want})
            return RemoteOperationResult(success=True, remote_state={"is_read": data.get("isRead", want)})

        if op == OP_SET_FLAG:
            want = bool(desired_state.get("is_flagged", True))
            data = _call_dict("PATCH", msg_path, {"flag": {"flagStatus": "flagged" if want else "notFlagged"}})
            return RemoteOperationResult(success=True, remote_state={"is_flagged": want, "flag": data.get("flag")})

        if op == OP_MOVE:
            dest = str(desired_state.get("dest_folder_remote_id") or desired_state.get("to_folder") or "")
            if not dest:
                return RemoteOperationResult(success=False, error="missing dest_folder_remote_id")
            data = _call_dict("POST", f"{msg_path}/move", {"destinationId": dest})
            return RemoteOperationResult(
                success=True,
                remote_state={"folder_remote_id": data.get("parentFolderId") or dest, "id": data.get("id") or remote_id},
            )

        if op == OP_TRASH:
            # Soft-delete: move to deleteditems when provided, else DELETE.
            # Never swallow RateLimitedError / CursorInvalidError into a hard DELETE.
            trash = str(desired_state.get("trash_folder_remote_id") or "deleteditems")
            try:
                data = _call_dict("POST", f"{msg_path}/move", {"destinationId": trash})
                return RemoteOperationResult(
                    success=True,
                    remote_state={
                        "folder_remote_id": data.get("parentFolderId") or trash,
                        "id": data.get("id") or remote_id,
                    },
                )
            except (RateLimitedError, CursorInvalidError):
                raise
            except ProviderHttpError as exc:
                if exc.status == 404:
                    try:
                        self._call("DELETE", msg_path, {})
                    except ProviderHttpError as del_exc:
                        if del_exc.status != 404:
                            raise
                    return RemoteOperationResult(success=True, remote_state={"deleted": True})
                return RemoteOperationResult(success=False, error=str(exc))

        return RemoteOperationResult(success=False, error=f"unsupported graph op {op_type}")

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        if self.transport is None:
            raise GraphNotConfiguredError("Graph reconcile not wired yet")
        remote_ids: set[str] = set()
        next_url: str | None = f"/me/mailFolders/{folder_remote_id}/messages"
        params: dict[str, Any] | None = {"$select": "id"}
        page_count = 0
        item_count = 0
        visited_urls: set[str] = set()
        while next_url:
            if next_url in visited_urls:
                raise GraphPaginationError("Graph reconcile pagination returned a repeated nextLink")
            if page_count >= MAX_GRAPH_PAGES_PER_CALL:
                raise GraphPaginationError("Graph reconcile pagination exceeded the page limit")
            visited_urls.add(next_url)
            data = self._call("GET", next_url, params)
            page_count += 1
            params = None
            page_items = data.get("value") or []
            item_count += len(page_items)
            if item_count > MAX_GRAPH_ITEMS_PER_CALL:
                raise GraphPaginationError("Graph reconcile pagination exceeded the item limit")
            for item in page_items:
                if item.get("id"):
                    remote_ids.add(str(item["id"]))
            next_url = data.get("@odata.nextLink") or data.get("next_link")
        local = set(local_remote_ids)
        return [ReconcileAction(kind="delete", remote_id=rid) for rid in sorted(local - remote_ids)]

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=60, reason="graph default hint")
