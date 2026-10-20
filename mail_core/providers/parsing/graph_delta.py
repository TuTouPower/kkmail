"""Parse Microsoft Graph messages/delta JSON into DeltaPage."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta


def _parse_dt(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    text = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)


def _meta_from_graph(item: dict[str, Any]) -> RemoteMessageMeta:
    frm = (item.get("from") or {}).get("emailAddress") or {}
    flag_obj = item.get("flag") or {}
    is_flagged = flag_obj.get("flagStatus") == "flagged"
    return RemoteMessageMeta(
        remote_id=str(item["id"]),
        subject=str(item.get("subject") or ""),
        from_address=str(frm.get("address") or ""),
        from_name=frm.get("name"),
        sort_time=_parse_dt(item.get("receivedDateTime") or item.get("lastModifiedDateTime")),
        is_read=bool(item.get("isRead", False)),
        has_attachments=bool(item.get("hasAttachments", False)),
        is_flagged=is_flagged,
        internet_message_id=item.get("internetMessageId"),
        snippet=item.get("bodyPreview"),
        provider_thread_key=item.get("conversationId"),
    )


def parse_graph_delta(data: dict[str, Any]) -> DeltaPage:
    """Normalize a Graph delta JSON body.

    - ``@removed`` → explicit delete
    - otherwise → upsert (full message resource)
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
        kind = "flag" if item.get("_flag_only") else "upsert"
        changes.append(
            DeltaChange(
                kind=kind,
                remote_id=rid,
                meta=meta,
                flags={"is_read": meta.is_read, "is_flagged": meta.is_flagged},
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
