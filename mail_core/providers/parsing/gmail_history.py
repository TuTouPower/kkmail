"""Parse Gmail users.history.list JSON into DeltaPage."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta


def _minimal_meta(message: dict[str, Any]) -> RemoteMessageMeta:
    """Build meta from a History message stub or fuller fixture payload."""
    headers = {h["name"].lower(): h["value"] for h in (message.get("payload") or {}).get("headers") or [] if "name" in h}
    subject = message.get("subject") or headers.get("subject") or ""
    frm = message.get("from_address") or headers.get("from") or ""
    from_name = message.get("from_name")
    if "<" in frm and ">" in frm and not from_name:
        # "Name <a@b.c>" → split
        name_part, _, rest = frm.partition("<")
        from_name = name_part.strip().strip('"') or None
        frm = rest.rstrip(">").strip()
    sort_raw = message.get("internalDate")
    if sort_raw is not None:
        try:
            sort_time = datetime.fromtimestamp(int(sort_raw) / 1000.0, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            sort_time = datetime.now(timezone.utc)
    else:
        sort_time = datetime.now(timezone.utc)
    label_ids = set(message.get("labelIds") or [])
    return RemoteMessageMeta(
        remote_id=str(message["id"]),
        subject=str(subject),
        from_address=str(frm),
        from_name=from_name,
        sort_time=sort_time,
        is_read="UNREAD" not in label_ids,
        has_attachments=bool(message.get("has_attachments", False)),
        snippet=message.get("snippet"),
        provider_thread_key=message.get("threadId"),
    )


def parse_gmail_history(data: dict[str, Any], *, folder_label: str | None = None) -> DeltaPage:
    """Normalize Gmail History list response.

    ``messagesDeleted`` → delete; ``messagesAdded`` → upsert;
    label add/remove of UNREAD → flag. Cursor carries historyId + optional pageToken.
    """
    changes: list[DeltaChange] = []
    seen_delete: set[str] = set()
    for hist in data.get("history") or []:
        for entry in hist.get("messagesDeleted") or []:
            msg = entry.get("message") or entry
            rid = str(msg.get("id") or "")
            if rid and rid not in seen_delete:
                seen_delete.add(rid)
                changes.append(DeltaChange(kind="delete", remote_id=rid))
        for entry in hist.get("messagesAdded") or []:
            msg = entry.get("message") or entry
            rid = str(msg.get("id") or "")
            if not rid or rid in seen_delete:
                continue
            if folder_label and folder_label not in (msg.get("labelIds") or [folder_label]):
                # Still accept when fixture omits labelIds
                if msg.get("labelIds") is not None:
                    continue
            meta = _minimal_meta(msg)
            changes.append(DeltaChange(kind="upsert", remote_id=rid, meta=meta))
        for entry in hist.get("labelsAdded") or []:
            msg = entry.get("message") or {}
            rid = str(msg.get("id") or "")
            labels = set(entry.get("labelIds") or [])
            if not rid or rid in seen_delete:
                continue
            if "UNREAD" in labels:
                meta = _minimal_meta({**msg, "labelIds": list(set(msg.get("labelIds") or []) | {"UNREAD"})})
                changes.append(DeltaChange(kind="flag", remote_id=rid, meta=meta, flags={"is_read": False}))
        for entry in hist.get("labelsRemoved") or []:
            msg = entry.get("message") or {}
            rid = str(msg.get("id") or "")
            labels = set(entry.get("labelIds") or [])
            if not rid or rid in seen_delete:
                continue
            if "UNREAD" in labels:
                remaining = set(msg.get("labelIds") or []) - {"UNREAD"}
                meta = _minimal_meta({**msg, "labelIds": list(remaining)})
                changes.append(DeltaChange(kind="flag", remote_id=rid, meta=meta, flags={"is_read": True}))

    history_id = str(data.get("historyId") or "")
    page_token = data.get("nextPageToken")
    cursor: dict[str, Any] = {}
    if history_id:
        cursor["historyId"] = history_id
    if page_token:
        cursor["pageToken"] = page_token
        return DeltaPage(changes=changes, next_cursor=cursor, exhausted=False)
    return DeltaPage(changes=changes, next_cursor=cursor or None, exhausted=True)
