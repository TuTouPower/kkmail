"""Parse Microsoft Graph messages/delta JSON into DeltaPage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from mail_core.providers.base import DeltaChange, DeltaPage, MetadataPage, RemoteMessageMeta


def _parse_dt(raw: str | None) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed.utcoffset() is not None else None


def _meta_from_graph(item: dict[str, Any]) -> RemoteMessageMeta:
    frm = (item.get("from") or {}).get("emailAddress") or {}
    flag_obj = item.get("flag") or {}
    flag_status = flag_obj.get("flagStatus")
    is_flagged = flag_status == "flagged" if flag_status is not None else None
    to_addrs = tuple(
        str(r.get("emailAddress", {}).get("address") or "")
        for r in item.get("toRecipients") or []
        if (r.get("emailAddress") or {}).get("address")
    ) or tuple(item.get("to_addresses") or ())
    cc_addrs = tuple(
        str(r.get("emailAddress", {}).get("address") or "")
        for r in item.get("ccRecipients") or []
        if (r.get("emailAddress") or {}).get("address")
    ) or tuple(item.get("cc_addresses") or ())
    field_sources = {
        "subject": ("subject",), "from": ("from_address", "from_name"),
        "receivedDateTime": ("sort_time",), "isRead": ("is_read",),
        "hasAttachments": ("has_attachments",), "flag": ("is_flagged",),
        "internetMessageId": ("internet_message_id",), "bodyPreview": ("snippet",),
        "conversationId": ("provider_thread_key",),
        "toRecipients": ("to_addresses",), "ccRecipients": ("cc_addresses",),
        "to_addresses": ("to_addresses",), "cc_addresses": ("cc_addresses",),
    }
    supplied = frozenset(field for source, fields in field_sources.items() if source in item for field in fields)
    return RemoteMessageMeta(
        supplied_fields=supplied,
        remote_id=str(item["id"]),
        subject=str(item.get("subject") or ""),
        from_address=str(frm.get("address") or ""),
        from_name=frm.get("name"),
        sort_time=_parse_dt(item.get("receivedDateTime")),
        is_read=bool(item["isRead"]) if item.get("isRead") is not None else None,
        has_attachments=(
            bool(item["hasAttachments"]) if item.get("hasAttachments") is not None else None
        ),
        is_flagged=is_flagged,
        internet_message_id=item.get("internetMessageId"),
        snippet=item.get("bodyPreview"),
        provider_thread_key=item.get("conversationId"),
        to_addresses=to_addrs,
        cc_addresses=cc_addrs,
    )


def parse_graph_metadata_page(data: dict[str, Any]) -> MetadataPage:
    """Parse a messages-list page without treating status-only items as delta patches."""
    items: list[RemoteMessageMeta] = []
    for item in data.get("value") or []:
        if not isinstance(item, dict) or not item.get("id") or "@removed" in item:
            continue
        items.append(_meta_from_graph(item))

    next_link = data.get("@odata.nextLink") or data.get("next_link")
    delta_link = data.get("@odata.deltaLink") or data.get("delta_link")
    if next_link:
        cursor: dict[str, Any] = {"next_link": next_link}
        if delta_link:
            cursor["delta_link"] = delta_link
        return MetadataPage(items=items, next_cursor=cursor, exhausted=False)
    cursor = {"delta_link": delta_link} if delta_link else None
    return MetadataPage(items=items, next_cursor=cursor, exhausted=True)


def parse_graph_delta(data: dict[str, Any]) -> DeltaPage:
    """Normalize a Graph delta JSON body.

    - ``@removed`` → explicit delete
    - otherwise → upsert for supplied content, or a status-only patch
    - ``@odata.nextLink`` / ``@odata.deltaLink`` → cursor
    """
    changes: list[DeltaChange] = []
    for item in data.get("value") or []:
        rid = str(item.get("id") or "")
        if not rid:
            continue
        if "@removed" in item or item.get("@removed"):
            changes.append(DeltaChange(kind="delete", remote_id=rid))
            continue
        meta = _meta_from_graph(item)
        flags: dict[str, Any] = {}
        if meta.is_read is not None:
            flags["is_read"] = meta.is_read
        if meta.is_flagged is not None:
            flags["is_flagged"] = meta.is_flagged
        has_content = bool(meta.supplied_fields - {"is_read", "is_flagged"})
        kind = "flag" if (item.get("_flag_only") or not has_content) else "upsert"
        changes.append(
            DeltaChange(
                kind=kind,
                remote_id=rid,
                meta=meta if has_content else None,
                flags=flags,
            )
        )

    next_link = data.get("@odata.nextLink") or data.get("next_link")
    delta_link = data.get("@odata.deltaLink") or data.get("delta_link")
    if next_link:
        cursor: dict[str, Any] = {"next_link": next_link}
        if delta_link:
            cursor["delta_link"] = delta_link
        return DeltaPage(changes=changes, next_cursor=cursor, exhausted=False)
    cursor = {}
    if delta_link:
        cursor["delta_link"] = delta_link
    return DeltaPage(changes=changes, next_cursor=cursor or None, exhausted=True)
