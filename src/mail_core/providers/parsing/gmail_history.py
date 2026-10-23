"""Parse Gmail users.history.list JSON into DeltaPage."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta


def parse_gmail_internal_date(raw: Any) -> datetime | None:
    """Parse Gmail's millisecond Unix timestamp without coercing other JSON types."""
    if isinstance(raw, bool) or not isinstance(raw, (str, int)):
        return None
    if isinstance(raw, str):
        digits = raw[1:] if raw.startswith(("+", "-")) else raw
        if not digits or not digits.isascii() or not digits.isdecimal():
            return None
    try:
        return datetime.fromtimestamp(int(raw) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _parse_address_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    import email.utils

    return tuple(addr for _, addr in email.utils.getaddresses([raw]) if addr)


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
    sort_time = parse_gmail_internal_date(message.get("internalDate"))
    label_ids = set(message.get("labelIds") or [])
    to_addrs = tuple(message.get("to_addresses") or ()) or _parse_address_list(headers.get("to"))
    cc_addrs = tuple(message.get("cc_addresses") or ()) or _parse_address_list(headers.get("cc"))
    return RemoteMessageMeta(
        remote_id=str(message["id"]),
        subject=str(subject),
        from_address=str(frm),
        from_name=from_name,
        sort_time=sort_time,
        is_read="UNREAD" not in label_ids,
        has_attachments=(
            bool(message["has_attachments"]) if message.get("has_attachments") is not None else None
        ),
        is_flagged="STARRED" in label_ids,
        internet_message_id=headers.get("message-id") or message.get("internet_message_id"),
        snippet=message.get("snippet"),
        provider_thread_key=message.get("threadId"),
        to_addresses=to_addrs,
        cc_addresses=cc_addrs,
        in_reply_to=headers.get("in-reply-to"),
        references=headers.get("references"),
    )


def parse_gmail_history(
    data: dict[str, Any],
    *,
    folder_label: str | None = None,
    start_history_id: str | None = None,
) -> DeltaPage:
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
            if folder_label and folder_label in labels:
                meta = _minimal_meta({**msg, "labelIds": list(set(msg.get("labelIds") or []) | labels)})
                changes.append(DeltaChange(kind="upsert", remote_id=rid, meta=meta))
                continue
            flag_updates: dict[str, Any] = {}
            if "UNREAD" in labels:
                flag_updates["is_read"] = False
            if "STARRED" in labels:
                flag_updates["is_flagged"] = True
            if flag_updates:
                meta = _minimal_meta({**msg, "labelIds": list(set(msg.get("labelIds") or []) | labels)})
                changes.append(DeltaChange(kind="flag", remote_id=rid, meta=meta, flags=flag_updates))
        for entry in hist.get("labelsRemoved") or []:
            msg = entry.get("message") or {}
            rid = str(msg.get("id") or "")
            labels = set(entry.get("labelIds") or [])
            if not rid or rid in seen_delete:
                continue
            if folder_label and folder_label in labels:
                changes.append(DeltaChange(kind="delete", remote_id=rid))
                continue
            flag_updates: dict[str, Any] = {}
            if "UNREAD" in labels:
                flag_updates["is_read"] = True
            if "STARRED" in labels:
                flag_updates["is_flagged"] = False
            if flag_updates:
                remaining = set(msg.get("labelIds") or []) - labels
                meta = _minimal_meta({**msg, "labelIds": list(remaining)})
                changes.append(DeltaChange(kind="flag", remote_id=rid, meta=meta, flags=flag_updates))

    history_id = str(data.get("historyId") or "")
    page_token = data.get("nextPageToken")
    cursor: dict[str, Any] = {}
    if page_token:
        # Paging in progress: preserve initial startHistoryId
        if start_history_id:
            cursor["historyId"] = str(start_history_id)
        elif history_id:
            cursor["historyId"] = history_id
        cursor["pageToken"] = page_token
        return DeltaPage(changes=changes, next_cursor=cursor, exhausted=False)
    # Final page: advance to head historyId
    if history_id:
        cursor["historyId"] = history_id
    return DeltaPage(changes=changes, next_cursor=cursor or None, exhausted=True)
