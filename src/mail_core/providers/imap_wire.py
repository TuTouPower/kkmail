"""Low-level IMAP remote ID, mailbox quoting, COPYUID, and FLAGS wire primitives."""

from __future__ import annotations

from collections.abc import Sequence
import imaplib
import re
from typing import Any

# IMAP UIDs are per-mailbox; bare UIDs collide across folders. Namespace with
# UIDVALIDITY + folder so (account_id, remote_id) stays unique and fetch_mime
# can select the right mailbox without defaulting to INBOX.
_IMAP_REMOTE_SEP = "\x1f"


def format_imap_remote_id(folder: str, uidvalidity: int, uid: int) -> str:
    """Format a namespaced IMAP remote_id encoding UIDVALIDITY, folder, and UID."""
    safe_folder = folder.replace(_IMAP_REMOTE_SEP, " ")
    return f"{int(uidvalidity)}{_IMAP_REMOTE_SEP}{safe_folder}{_IMAP_REMOTE_SEP}{int(uid)}"


def parse_imap_remote_id(remote_id: str) -> tuple[int, str, int] | None:
    """Parse a namespaced IMAP remote_id into ``(uidvalidity, folder, uid)``."""
    parts = remote_id.split(_IMAP_REMOTE_SEP)
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), parts[1], int(parts[2])
    except ValueError:
        return None


def imap_uid_for_command(remote_id: str) -> str:
    """Bare UID string for UID FETCH/STORE (strips namespace when present)."""
    parsed = parse_imap_remote_id(remote_id)
    return str(parsed[2]) if parsed else str(remote_id)


def _uid_sequence_index(sequence_set: str, target_uid: int) -> int | None:
    offset = 0
    for part in sequence_set.split(","):
        if ":" in part:
            try:
                first, last = (int(value) for value in part.split(":", 1))
            except ValueError:
                return None
            step = 1 if last >= first else -1
            count = abs(last - first) + 1
            distance = (target_uid - first) * step
            if 0 <= distance < count:
                return offset + distance
            offset += count
            continue
        try:
            value = int(part)
        except ValueError:
            return None
        if value == target_uid:
            return offset
        offset += 1
    return None


def _uid_sequence_value(sequence_set: str, index: int) -> int | None:
    offset = 0
    for part in sequence_set.split(","):
        if ":" in part:
            try:
                first, last = (int(value) for value in part.split(":", 1))
            except ValueError:
                return None
            step = 1 if last >= first else -1
            count = abs(last - first) + 1
            if offset <= index < offset + count:
                return first + step * (index - offset)
            offset += count
            continue
        try:
            value = int(part)
        except ValueError:
            return None
        if offset == index:
            return value
        offset += 1
    return None


def _extract_copyuid_texts(c: imaplib.IMAP4, response_data: Any) -> list[str]:
    """Extract COPYUID response lines once before client.response() pops untagged responses."""
    values = list(response_data or [])
    try:
        resp = c.response("COPYUID")
        if isinstance(resp, (tuple, list)) and len(resp) == 2:
            _, response_values = resp
            values.extend(response_values or [])
    except (AttributeError, ValueError, imaplib.IMAP4.error):
        pass
    return [value.decode("ascii", errors="ignore") if isinstance(value, bytes) else str(value) for value in values]


def _match_copyuid_line(text: str) -> tuple[int, str, str] | None:
    match = re.search(r"(?:\[\s*)?COPYUID\s+(\d+)\s+([0-9,:]+)\s+([0-9,:]+)", text, re.IGNORECASE)
    if match is None:
        match = re.fullmatch(r"\s*(\d+)\s+([0-9,:]+)\s+([0-9,:]+)\s*", text)
    if match is None:
        return None
    return int(match.group(1)), match.group(2), match.group(3)


def _copyuid_remote_states(
    copyuid_texts: list[str],
    source_uids: Sequence[int],
    dest_folder: str,
) -> dict[int, dict[str, Any]]:
    """Build destination identities for multiple source UIDs from pre-extracted COPYUID texts."""
    results: dict[int, dict[str, Any]] = {u: {"folder_remote_id": dest_folder} for u in source_uids}
    for text in copyuid_texts:
        parsed = _match_copyuid_line(text)
        if parsed is None:
            continue
        uidvalidity, source_set, destination_set = parsed
        for u in source_uids:
            if "remote_id" in results[u]:
                continue
            index = _uid_sequence_index(source_set, u)
            if index is None:
                continue
            destination_uid = _uid_sequence_value(destination_set, index)
            if destination_uid is None:
                continue
            results[u]["remote_id"] = format_imap_remote_id(dest_folder, uidvalidity, destination_uid)
            results[u]["uid"] = destination_uid
    return results


def _copyuid_remote_state(c: imaplib.IMAP4, response_data: Any, source_uid: int, dest_folder: str) -> dict[str, Any]:
    """Build destination identity from the UIDPLUS COPYUID response when present."""
    copyuid_texts = _extract_copyuid_texts(c, response_data)
    mapping = _copyuid_remote_states(copyuid_texts, [source_uid], dest_folder)
    return mapping[source_uid]


def _quote_mailbox(name: str) -> str:
    """Safely quote an IMAP mailbox name if it contains spaces or special characters."""
    if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in name):
        raise ValueError("IMAP mailbox name contains control characters")
    if not name:
        return '""'
    if name.startswith('"') and name.endswith('"'):
        return name
    escaped = name.replace("\\", "\\\\").replace('"', '\\"')
    if any(c in name for c in ' ()[]{}\\"%*'):
        return f'"{escaped}"'
    return name


def _get_server_uidvalidity(c: imaplib.IMAP4, folder: str) -> int | None:
    """Query server UIDVALIDITY via IMAP STATUS, returning None when unavailable."""
    if not hasattr(c, "status"):
        return None
    try:
        status = c.status(_quote_mailbox(folder), "(UIDVALIDITY)")
        if status[0] == "OK" and status[1] and status[1][0]:
            blob = status[1][0].decode() if isinstance(status[1][0], bytes) else str(status[1][0])
            match = re.search(r"UIDVALIDITY\s+(\d+)", blob)
            if match:
                return int(match.group(1))
    except Exception:
        pass
    return None


def _parse_fetch_flags(meta: str) -> tuple[bool | None, bool | None]:
    """Extract (is_read, is_flagged) booleans from an IMAP FETCH response header."""
    match = re.search(r"\bFLAGS\s*\(([^)]*)\)", meta, flags=re.IGNORECASE)
    if match is None:
        return None, None
    flags = set(match.group(1).casefold().split())
    return "\\seen" in flags, "\\flagged" in flags


def _parse_uids_flags_from_response(data: Sequence[Any]) -> dict[int, tuple[bool | None, bool | None]]:
    """Map UID -> (is_read, is_flagged) across IMAP FETCH/STORE untagged responses."""
    result: dict[int, tuple[bool | None, bool | None]] = {}
    for blob in data or ():
        if blob is None:
            continue
        meta_bytes = blob[0] if isinstance(blob, tuple) else blob
        if not isinstance(meta_bytes, (bytes, str)):
            continue
        meta = meta_bytes.decode("utf-8", errors="replace") if isinstance(meta_bytes, bytes) else str(meta_bytes)
        match = re.search(r"\bUID\s+(\d+)", meta, flags=re.IGNORECASE)
        if match:
            uid = int(match.group(1))
            result[uid] = _parse_fetch_flags(meta)
    return result
