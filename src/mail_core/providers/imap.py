"""IMAP provider adapter (UID + optional CONDSTORE/MODSEQ).

Never infers deletions from an incomplete UID scan (architecture §6.2).
"""

from __future__ import annotations

import base64
import email
import email.header
import email.utils
import imaplib
import logging
import queue
import re
import socket
import ssl
import threading
import time
import uuid
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Sequence

from mail_core.providers.base import (
    DeltaChange,
    DeltaPage,
    FolderStatus,
    IdleNotSupportedError,
    MetadataPage,
    RateLimitHint,
    ReconcileAction,
    RemoteFolder,
    RemoteMessageMeta,
    RemoteOperationResult,
)
from mail_core.providers.http import CursorInvalidError
from mail_core.providers.host_security import validate_imap_peer_address
from mail_core.security.redact import safe_error

log = logging.getLogger("mail_core.providers.imap")

_IMAP_ID_FIELDS = {"name": "kkmail", "version": "3.0.20", "vendor": "kkmail"}
_IMAP_ID_ARGUMENT = '("name" "kkmail" "version" "3.0.20" "vendor" "kkmail")'
_IMAP_COMMANDS_LOCK = threading.Lock()
with _IMAP_COMMANDS_LOCK:
    imaplib.Commands.setdefault("ID", ("AUTH", "SELECTED"))
    # t061: IDLE (RFC 2177) is not in the stdlib command table; the watch
    # session below drives it manually, registration documents the state
    # requirement and keeps capability-driven command gating consistent.
    imaplib.Commands.setdefault("IDLE", ("SELECTED",))

_STATUS_ITEM_FIELDS = {
    "MESSAGES": "messages",
    "UIDNEXT": "uidnext",
    "UNSEEN": "unseen",
    "HIGHESTMODSEQ": "highestmodseq",
}


def _parse_status_items(data: Any) -> FolderStatus | None:
    """Parse an imaplib STATUS response into a FolderStatus (t061).

    Items are optional per-server (Coremail omits UIDNEXT): missing
    items stay ``None``. Returns ``None`` when no item could be parsed
    at all — callers must treat that as a failed probe, never as
    "no change".
    """
    for raw in data or ():
        if raw is None:
            continue
        text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        match = re.search(r"\(([^()]*)\)", text)
        if not match:
            continue
        tokens = match.group(1).split()
        pairs = dict(zip(tokens[0::2], tokens[1::2]))
        values: dict[str, int | None] = {}
        for item, field_name in _STATUS_ITEM_FIELDS.items():
            raw_value = pairs.get(item)
            try:
                values[field_name] = int(raw_value) if raw_value is not None else None
            except ValueError:
                values[field_name] = None
        if all(value is None for value in values.values()):
            continue
        return FolderStatus(**values)
    return None


class IdleSessionDisconnected(ConnectionError):
    """The IDLE watch connection dropped or the server said BYE."""


_IDLE_EOF = object()


class ImapIdleSession:
    """A dedicated IMAP connection idling on one selected mailbox (t061).

    Design (validated by the t061 spike against a fake IMAP server):
    a daemon reader thread owns the socket's read side for the whole
    session lifetime and queues lines; the controlling thread is the
    only writer (IDLE / DONE) and consumes untagged lines with
    timeouts, so no cross-thread write race exists. The session never
    acquires a connection-slot permit — long-lived IDLE connections
    live under their own quota, not the task slot budget. Teardown is
    a socket close (the reader exits on EOF); no LOGOUT is attempted.
    """

    def __init__(self, client: Any):
        self._client = client
        self._lines: "queue.Queue[Any]" = queue.Queue()
        self._reader = threading.Thread(
            target=self._pump, name="imap-idle-reader", daemon=True
        )
        self._reader.start()

    def _pump(self) -> None:
        try:
            while True:
                line = self._client.readline()
                if not line:
                    self._lines.put(_IDLE_EOF)
                    return
                self._lines.put(line)
        except Exception:
            self._lines.put(_IDLE_EOF)

    def wait_for_change(
        self,
        *,
        timeout_s: float,
        stop_event: threading.Event,
        slice_s: float = 0.25,
    ) -> str:
        """IDLE until the server reports a change; return the outcome.

        Outcomes: ``"changed"`` (untagged EXISTS/EXPUNGE/FETCH seen),
        ``"timeout"`` (``timeout_s`` elapsed — caller re-enters),
        ``"stopped"`` (``stop_event`` set). Raises
        :class:`IdleSessionDisconnected` on drop or server BYE.
        """
        client = self._client
        tag = client._new_tag()
        tag_b = tag.encode() if isinstance(tag, str) else tag
        client.send(tag_b + b" IDLE\r\n")
        try:
            first = self._lines.get(timeout=10.0)
        except queue.Empty:
            raise IdleSessionDisconnected("no IDLE continuation response") from None
        if first is _IDLE_EOF:
            raise IdleSessionDisconnected("connection closed before IDLE continuation")
        if not first.startswith(b"+"):
            raise IdleSessionDisconnected(f"unexpected IDLE response: {first!r}")

        deadline = time.monotonic() + timeout_s
        outcome = "timeout"
        while True:
            if stop_event.is_set():
                outcome = "stopped"
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                outcome = "timeout"
                break
            try:
                line = self._lines.get(timeout=min(slice_s, remaining))
            except queue.Empty:
                continue
            if line is _IDLE_EOF:
                raise IdleSessionDisconnected("connection closed during IDLE")
            stripped = line.strip()
            if stripped.startswith(b"* BYE"):
                raise IdleSessionDisconnected(f"server BYE during IDLE: {stripped!r}")
            if stripped.startswith(b"*") and any(
                token in stripped for token in (b" EXISTS", b" EXPUNGE", b" FETCH")
            ):
                outcome = "changed"
                break
        client.send(b"DONE\r\n")
        while True:
            line = self._lines.get(timeout=10.0)
            if line is _IDLE_EOF:
                raise IdleSessionDisconnected("connection closed while ending IDLE")
            if line.strip().startswith(tag_b):
                break
        return outcome

    def close(self) -> None:
        sock = getattr(self._client, "sock", None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        self._reader.join(timeout=2.0)


def _send_imap_id(client: imaplib.IMAP4):
    """Use public imaplib ID support when available, with a legacy fallback."""
    public_method = getattr(client, "id", None)
    if callable(public_method):
        return public_method(dict(_IMAP_ID_FIELDS))
    private_method = getattr(client, "_simple_command", None)
    if callable(private_method):
        return private_method("ID", _IMAP_ID_ARGUMENT)
    return None


_FOLDER_ROLE = {
    "INBOX": "inbox",
    "收件箱": "inbox",
    "Junk": "junk",
    "Junk Email": "junk",
    "Spam": "junk",
    "垃圾邮件": "junk",
    "Trash": "trash",
    "Deleted": "trash",
    "Deleted Items": "trash",
    "Deleted Messages": "trash",
    "已删除": "trash",
    "已删除邮件": "trash",
    "废纸篓": "trash",
    "Sent": "sent",
    "Sent Items": "sent",
    "Sent Messages": "sent",
    "已发送": "sent",
    "已发送邮件": "sent",
    "Drafts": "drafts",
    "草稿": "drafts",
    "草稿箱": "drafts",
    "Archive": "archive",
    "Archives": "archive",
    "归档": "archive",
    "All Mail": "all",
    "所有邮件": "all",
    "Starred": "flagged",
    "已加星标": "flagged",
    "Important": "important",
    "重要": "important",
}


def decode_mutf7(s: str) -> str:
    """Decode IMAP Modified UTF-7 (RFC 3501 §5.1.3) into standard Unicode."""
    res = []
    i = 0
    while i < len(s):
        if s[i] == "&":
            end = s.find("-", i + 1)
            if end == -1:
                res.append(s[i:])
                break
            chunk = s[i + 1 : end]
            if not chunk:
                res.append("&")
            else:
                b64 = chunk.replace(",", "/")
                pad = "=" * (-len(b64) % 4)
                try:
                    raw = base64.b64decode(b64 + pad)
                    res.append(raw.decode("utf-16-be"))
                except Exception:
                    res.append(s[i : end + 1])
            i = end + 1
        else:
            res.append(s[i])
            i += 1
    return "".join(res)


def _decode_chunk_bytes(chunk: bytes, charset: str | None) -> str:
    if charset and str(charset).lower() != "unknown-8bit":
        try:
            return chunk.decode(charset, errors="replace")
        except LookupError:
            pass
    # No declared charset or unknown charset:
    # 1. Strict UTF-8 (also covers ASCII)
    try:
        return chunk.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # 2. Strict GB18030 (covers GBK and GB2312)
    try:
        return chunk.decode("gb18030")
    except UnicodeDecodeError:
        pass
    # 3. Deterministic lossy fallback
    return chunk.decode("utf-8", errors="replace")


def _decode_header(raw: str | email.header.Header | bytes | None) -> str:
    if not raw:
        return ""
    if isinstance(raw, bytes):
        return _decode_chunk_bytes(raw, None)
    try:
        parts = email.header.decode_header(raw)
    except Exception:
        return str(raw)

    out: list[str] = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            if (charset is None or str(charset).lower() == "unknown-8bit") and b"=?" in chunk and b"?=" in chunk:
                try:
                    subparts = email.header.decode_header(chunk.decode("latin1"))
                    for sub_chunk, sub_charset in subparts:
                        if isinstance(sub_chunk, bytes):
                            out.append(_decode_chunk_bytes(sub_chunk, sub_charset))
                        elif isinstance(sub_chunk, str):
                            if any(0xD800 <= ord(c) <= 0xDFFF for c in sub_chunk):
                                sub_bytes = sub_chunk.encode("utf-8", errors="surrogateescape")
                            else:
                                sub_bytes = sub_chunk.encode("latin1")
                            out.append(_decode_chunk_bytes(sub_bytes, sub_charset))
                    continue
                except Exception:
                    pass
            out.append(_decode_chunk_bytes(chunk, charset))
        elif isinstance(chunk, str):
            if any(0xD800 <= ord(c) <= 0xDFFF for c in chunk):
                raw_bytes = chunk.encode("utf-8", errors="surrogateescape")
                out.append(_decode_chunk_bytes(raw_bytes, charset))
            else:
                out.append(chunk)
    return "".join(out)


def _parse_from(value: str) -> tuple[str, str | None]:
    name, addr = email.utils.parseaddr(value or "")
    return (addr or value or "", name or None)

# IMAP UIDs are per-mailbox; bare UIDs collide across folders. Namespace with
# UIDVALIDITY + folder so (account_id, remote_id) stays unique and fetch_mime
# can select the right mailbox without defaulting to INBOX.
_IMAP_REMOTE_SEP = "\x1f"


def format_imap_remote_id(folder: str, uidvalidity: int, uid: int) -> str:
    safe_folder = folder.replace(_IMAP_REMOTE_SEP, " ")
    return f"{int(uidvalidity)}{_IMAP_REMOTE_SEP}{safe_folder}{_IMAP_REMOTE_SEP}{int(uid)}"


def parse_imap_remote_id(remote_id: str) -> tuple[int, str, int] | None:
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
        else:
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
        else:
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
    texts: list[str] = []
    for value in values:
        text = value.decode("ascii", errors="ignore") if isinstance(value, bytes) else str(value)
        texts.append(text)
    return texts


def _copyuid_remote_states(
    copyuid_texts: list[str],
    source_uids: Sequence[int],
    dest_folder: str,
) -> dict[int, dict[str, Any]]:
    """Build destination identities for multiple source UIDs from pre-extracted COPYUID texts."""
    results: dict[int, dict[str, Any]] = {
        u: {"folder_remote_id": dest_folder} for u in source_uids
    }
    for text in copyuid_texts:
        match = re.search(r"(?:\[\s*)?COPYUID\s+(\d+)\s+([0-9,:]+)\s+([0-9,:]+)", text, re.IGNORECASE)
        if match is None:
            match = re.fullmatch(r"\s*(\d+)\s+([0-9,:]+)\s+([0-9,:]+)\s*", text)
        if match is None:
            continue
        uidvalidity = int(match.group(1))
        source_set = match.group(2)
        destination_set = match.group(3)
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


def _check_uidvalidity(cursor: dict[str, Any] | None, uidvalidity: int | None) -> None:
    """Raise CursorInvalidError when server UIDVALIDITY differs from checkpoint cursor.

    Callers must rebuild the folder (clear cursor + full_scan) — never continue
    with the old UID namespace (architecture §7.3).
    """
    if uidvalidity is None:
        return
    prev = (cursor or {}).get("uidvalidity")
    if prev is None:
        return
    if int(prev) != int(uidvalidity):
        raise CursorInvalidError(
            f"UIDVALIDITY changed: was {prev}, now {uidvalidity}",
            status=None,
        )


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


def _unescape_imap_quoted(text: str) -> str:
    """Resolve backslash escapes inside an IMAP quoted string (A348)."""
    return re.sub(r"\\(.)", r"\1", text)


def _is_mailbox_noselect(c: imaplib.IMAP4, folder_remote_id: str) -> bool:
    """Check whether a mailbox has \\Noselect or \\NonExistent attribute."""
    if not hasattr(c, "list"):
        return False
    try:
        typ, data = c.list("", _quote_mailbox(folder_remote_id))
        if typ == "OK" and data:
            for raw in data:
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                m = re.search(r"\(([^)]*)\)", line)
                if m:
                    flags = {f.strip().lower() for f in m.group(1).split()}
                    if "\\noselect" in flags or "\\nonexistent" in flags:
                        return True
    except Exception:
        pass
    return False


def _get_server_uidvalidity(c: imaplib.IMAP4, folder: str) -> int | None:
    if not hasattr(c, "status"):
        return None
    try:
        status = c.status(_quote_mailbox(folder), "(UIDVALIDITY)")
        if status[0] == "OK" and status[1] and status[1][0]:
            blob = status[1][0].decode() if isinstance(status[1][0], bytes) else str(status[1][0])
            m = re.search(r"UIDVALIDITY\s+(\d+)", blob)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


def _search_uids(data: Any) -> list[int]:
    """Parse UIDs from an IMAP SEARCH response, across *all* data chunks.

    Servers may split the UID list over several chunks; reading only
    ``data[0]`` drops UIDs, which makes reconcile treat the dropped UIDs
    as remotely deleted (A31). Non-numeric tokens are ignored.
    """
    uids: list[int] = []
    for chunk in data or ():
        if not chunk:
            continue
        if isinstance(chunk, tuple):
            chunk = chunk[0] if chunk else b""
            if not chunk:
                continue
        tokens = chunk.split() if isinstance(chunk, (bytes, str)) else str(chunk).split()
        for token in tokens:
            text = token.decode("ascii", errors="ignore") if isinstance(token, bytes) else str(token)
            try:
                uids.append(int(text))
            except ValueError:
                continue
    return uids


def _parse_fetch_flags(meta: str) -> tuple[bool | None, bool | None]:
    match = re.search(r"\bFLAGS\s*\(([^)]*)\)", meta, flags=re.IGNORECASE)
    if match is None:
        return None, None
    flags = set(match.group(1).casefold().split())
    return "\\seen" in flags, "\\flagged" in flags


def _parse_uids_flags_from_response(data: Sequence[Any]) -> dict[int, tuple[bool | None, bool | None]]:
    result: dict[int, tuple[bool | None, bool | None]] = {}
    for blob in data or ():
        if blob is None:
            continue
        meta_bytes = blob[0] if isinstance(blob, tuple) else blob
        if not isinstance(meta_bytes, (bytes, str)):
            continue
        meta = meta_bytes.decode("utf-8", errors="replace") if isinstance(meta_bytes, bytes) else str(meta_bytes)
        m = re.search(r"\bUID\s+(\d+)", meta, flags=re.IGNORECASE)
        if m:
            uid = int(m.group(1))
            is_read, is_flagged = _parse_fetch_flags(meta)
            result[uid] = (is_read, is_flagged)
    return result


def _uid_from_fetch_blob(flags_blob: tuple[Any, ...]) -> int | None:
    if not flags_blob:
        return None
    meta_bytes = flags_blob[0]
    meta = meta_bytes.decode("utf-8", errors="replace") if isinstance(meta_bytes, bytes) else str(meta_bytes)
    match = re.search(r"\bUID\s+(\d+)", meta, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _fetch_flags_for_uid(c: Any, uid_str: str) -> tuple[bool, bool | None, bool | None] | None:
    """FETCH (FLAGS UID) for a single UID (A368).

    Returns ``None`` when the FETCH itself fails, otherwise
    ``(found, is_read, is_flagged)`` where ``found`` is False when the
    server returns no FETCH entry for the UID — i.e. the message no
    longer exists in the selected mailbox, however the server answered
    other commands for it.
    """
    try:
        target = int(uid_str)
    except ValueError:
        return None
    try:
        typ, data = c.uid("FETCH", uid_str, "(FLAGS UID)")
    except Exception:
        return None
    if typ != "OK":
        return None
    for blob in data or ():
        if blob is None:
            continue
        meta_bytes = blob[0] if isinstance(blob, tuple) else blob
        if not isinstance(meta_bytes, (bytes, str)):
            continue
        meta = meta_bytes.decode("utf-8", errors="replace") if isinstance(meta_bytes, bytes) else str(meta_bytes)
        match = re.search(r"\bUID\s+(\d+)", meta, flags=re.IGNORECASE)
        if match is None or int(match.group(1)) != target:
            continue
        is_read, is_flagged = _parse_fetch_flags(meta)
        return True, is_read, is_flagged
    return False, None, None


def _parse_message_meta_from_fetch(
    flags_blob: tuple[Any, ...],
    uid_fallback: int,
    folder_remote_id: str,
    uidvalidity: int,
) -> RemoteMessageMeta | None:
    meta_bytes = flags_blob[0]
    header_bytes = flags_blob[1] if len(flags_blob) > 1 else b""
    meta_s = meta_bytes.decode("utf-8", errors="replace") if isinstance(meta_bytes, bytes) else str(meta_bytes)
    m_uid = re.search(r"\bUID\s+(\d+)", meta_s)
    uid = int(m_uid.group(1)) if m_uid else uid_fallback
    is_read, is_flagged = _parse_fetch_flags(meta_s)
    if isinstance(header_bytes, bytes):
        headers = email.message_from_bytes(header_bytes)
    else:
        headers = email.message_from_string(str(header_bytes))

    subject = _decode_header(headers.get("Subject"))
    from_raw = _decode_header(headers.get("From"))
    addr, name = _parse_from(from_raw)

    to_headers = headers.get_all("To") or []
    to_raw = ", ".join(_decode_header(h) for h in to_headers) if to_headers else ""
    cc_headers = headers.get_all("Cc") or []
    cc_raw = ", ".join(_decode_header(h) for h in cc_headers) if cc_headers else ""

    to_addresses = tuple(a for _, a in email.utils.getaddresses([to_raw]) if a) if to_raw else ()
    cc_addresses = tuple(a for _, a in email.utils.getaddresses([cc_raw]) if a) if cc_raw else ()
    internal_date = re.search(r'\bINTERNALDATE\s+"([^"]+)"', meta_s, flags=re.IGNORECASE)
    try:
        sort_time = parsedate_to_datetime(internal_date.group(1)) if internal_date else None
        if sort_time is not None and sort_time.tzinfo is None:
            sort_time = sort_time.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        sort_time = None
    uv = int(uidvalidity) if uidvalidity is not None else 0

    def _header_opt(name: str) -> str | None:
        val = headers.get(name)
        if val is None:
            return None
        s = _decode_header(val).strip()
        return s if s else None

    return RemoteMessageMeta(
        remote_id=format_imap_remote_id(folder_remote_id, uv, uid),
        subject=subject,
        from_address=addr,
        from_name=name,
        sort_time=sort_time,
        is_read=is_read,
        has_attachments=None,
        is_flagged=is_flagged,
        internet_message_id=_header_opt("Message-ID"),
        uid=uid,
        to_addresses=to_addresses,
        cc_addresses=cc_addresses,
        in_reply_to=_header_opt("In-Reply-To"),
        references=_header_opt("References"),
    )


class _ImapFlagFetchError(RuntimeError):
    """A MODSEQ flag FETCH did not return a complete usable result."""


@dataclass
class ImapProvider:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    use_ssl: bool = True
    timeout: float = 60.0
    # Connection-budget wiring (design §7): the permit is acquired before
    # the real connection is established and held for exactly the
    # connection's lifetime — a reused session counts as one connection.
    traffic_class: Any = "foreground"
    permit_factory: Any = None
    _active_client: Any = field(default=None, init=False, repr=False)
    _session_permit: Any = field(default=None, init=False, repr=False)
    _current_folder: str | None = field(default=None, init=False, repr=False)
    # (folder, uidvalidity, scan_start, uids) — scan_start is the lower
    # bound the cached UID list was built from (A170).
    _metadata_uid_scan: tuple[str, int | None, int, list[int]] | None = field(
        default=None, init=False, repr=False
    )

    def _connect_with_permit(self) -> tuple[Any, Any]:
        """Acquire a permit first, then establish the real connection.

        Auth failure, peer-verification failure, or any other connect
        error releases the permit before propagating.  A control-plane
        failure raises before any provider I/O is attempted.
        """
        from mail_core.providers.connection_slots import acquire_permit

        permit = acquire_permit(self.permit_factory, self.traffic_class)
        try:
            client = self._connect()
        except BaseException:
            if permit is not None:
                permit.release()
            raise
        return client, permit

    @staticmethod
    def _close_client(client: Any, permit: Any) -> None:
        try:
            client.logout()
        except Exception:
            # A117: logout failure must not leak the connection — fall back
            # to close() and then the raw socket.
            try:
                client.close()
            except Exception:
                pass
            sock = getattr(client, "sock", None)
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
        if permit is not None:
            permit.release()

    def open_session(self) -> None:
        if self._active_client is None:
            self._active_client, self._session_permit = self._connect_with_permit()
            self._current_folder = None

    def close_session(self) -> None:
        if self._active_client is not None:
            client, permit = self._active_client, self._session_permit
            self._active_client = None
            self._session_permit = None
            self._current_folder = None
            self._close_client(client, permit)

    def __repr__(self) -> str:
        # Never leak IMAP password via logging / traceback repr.
        return (
            f"ImapProvider(host={self.host!r}, port={self.port}, "
            f"username={self.username!r}, password=***, use_ssl={self.use_ssl}, "
            f"timeout={self.timeout})"
        )

    def _connect(self) -> imaplib.IMAP4:
        timeout = float(self.timeout)
        if self.use_ssl:
            ssl_context = ssl.create_default_context()
            client: imaplib.IMAP4 = imaplib.IMAP4_SSL(
                self.host, self.port, ssl_context=ssl_context, timeout=timeout
            )
        else:
            client = imaplib.IMAP4(self.host, self.port, timeout=timeout)
        sock = getattr(client, "sock", None)
        try:
            validate_imap_peer_address(sock.getpeername()[0])
        except Exception:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
            raise
        try:
            try:
                client.login(self.username, self.password)
                # RFC 2971: Client identification (required by NetEase 163/126 to prevent 'SELECT Unsafe Login')
                try:
                    _send_imap_id(client)
                except Exception:
                    pass
            except imaplib.IMAP4.error as exc:
                msg = str(exc)
                response_code = re.search(r"\[([A-Z0-9-]+)(?:\s|\])", msg, re.IGNORECASE)
                # RFC 5530 defines EXPIRED as requiring a new passphrase. Other
                # authentication failures may be temporary provider lockouts.
                if response_code and response_code.group(1).upper() == "EXPIRED":
                    from mail_core.providers.http import PermanentAuthError

                    raise PermanentAuthError(f"IMAP authentication rejected permanently: {msg}") from exc
                raise
        except BaseException:
            # A117: any login-phase failure (OSError/SSLError/timeout, not
            # just IMAP4.error) must close the socket before propagating.
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
            raise
        return client

    def list_folder_catalog(self) -> Sequence[RemoteFolder]:
        c, _permit = self._connect_with_permit()
        try:
            typ, data = c.list()
            if typ != "OK":
                raise RuntimeError(f"IMAP LIST failed: {typ}")
            if not data:
                return [RemoteFolder("INBOX", "INBOX", "inbox")]
            folders: list[RemoteFolder] = []
            list_pattern = re.compile(
                r"\((?P<flags>[^)]*)\)\s+(?:\"(?P<delim>(?:[^\"\\]|\\.)*)\"|(?P<delim_bare>\S+))\s+(?:\"(?P<name>(?:[^\"\\]|\\.)*)\"|(?P<name_bare>.+))\s*$"
            )
            for raw in data:
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                m = list_pattern.search(line)
                if m:
                    flags_raw = m.group("flags")
                    flags = [f.strip() for f in flags_raw.split() if f.strip()]
                    delim = m.group("delim")
                    if delim is not None:
                        delim = _unescape_imap_quoted(delim)
                    else:
                        delim = m.group("delim_bare")
                    if delim == "NIL":
                        delim = None
                    if m.group("name") is not None:
                        # A348: quoted name — resolve escapes and preserve
                        # spaces inside the quotes exactly as sent.
                        remote_id = _unescape_imap_quoted(m.group("name"))
                    else:
                        remote_id = (m.group("name_bare") or "").strip()
                else:
                    flags_match = re.search(r"\(([^)]*)\)", line)
                    flags = flags_match.group(1).split() if flags_match else []
                    delim = None
                    m_fallback = re.search(r' "?"?([^"]+)"?\s*$', line)
                    remote_id = m_fallback.group(1).strip() if m_fallback else line.rsplit(" ", 1)[-1].strip('"')

                flag_lower = {f.lower() for f in flags}
                if "\\nonexistent" in flag_lower:
                    continue
                selectable = "\\noselect" not in flag_lower

                name = decode_mutf7(remote_id)
                parent_remote_id = None
                if delim and delim in remote_id:
                    parent_remote_id = remote_id.rsplit(delim, 1)[0]

                # 1. INBOX is always inbox
                if remote_id.upper() == "INBOX" or name.upper() == "INBOX":
                    role = "inbox"
                else:
                    # 2. SPECIAL-USE flags (RFC 6154) - flags take priority over names
                    flag_lower = {f.lower() for f in flags}
                    if "\\sent" in flag_lower:
                        role = "sent"
                    elif "\\drafts" in flag_lower:
                        role = "drafts"
                    elif "\\trash" in flag_lower:
                        role = "trash"
                    elif "\\junk" in flag_lower:
                        role = "junk"
                    elif "\\archive" in flag_lower:
                        role = "archive"
                    elif "\\all" in flag_lower:
                        role = "all"
                    elif "\\flagged" in flag_lower or "\\starred" in flag_lower:
                        role = "flagged"
                    else:
                        # 3. Known names
                        role = None
                        for candidate in (name, remote_id):
                            if candidate in _FOLDER_ROLE:
                                role = _FOLDER_ROLE[candidate]
                                break
                            for k, v in _FOLDER_ROLE.items():
                                if k.lower() == candidate.lower():
                                    role = v
                                    break
                            if role:
                                break
                        if not role:
                            role = "other"

                folders.append(
                    RemoteFolder(
                        remote_id=remote_id,
                        name=name,
                        role=role,
                        parent_remote_id=parent_remote_id,
                        selectable=selectable,
                    )
                )
            if not any(f.remote_id.upper() == "INBOX" for f in folders):
                folders.insert(0, RemoteFolder("INBOX", "INBOX", "inbox"))
            return folders
        finally:
            self._close_client(c, _permit)

    def list_folders(self) -> Sequence[RemoteFolder]:
        """Return only mailboxes that can be selected for message operations."""
        return [folder for folder in self.list_folder_catalog() if folder.selectable]

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        return self.fetch_metadata_page(folder_remote_id, cursor)

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        """Page by UID ascending, reusing one UID search for this provider scan."""
        c, _permit = self._connect_with_permit()
        try:
            typ, _ = c.select(_quote_mailbox(folder_remote_id), readonly=True)
            if typ != "OK":
                if _is_mailbox_noselect(c, folder_remote_id):
                    return MetadataPage(items=[], next_cursor=None, exhausted=True)
                raise RuntimeError(f"select {folder_remote_id} failed: {typ}")
            uidvalidity = None
            status = c.status(_quote_mailbox(folder_remote_id), "(UIDVALIDITY)")
            if status[0] == "OK" and status[1] and status[1][0]:
                blob = status[1][0].decode() if isinstance(status[1][0], bytes) else str(status[1][0])
                m = re.search(r"UIDVALIDITY\s+(\d+)", blob)
                if m:
                    uidvalidity = int(m.group(1))
            if uidvalidity is None:
                # Never mint remote_ids under a uv=0 namespace (A28): like
                # reconcile (B1), abort the round when UIDVALIDITY cannot be
                # verified. \Noselect mailboxes keep their empty-page path.
                if _is_mailbox_noselect(c, folder_remote_id):
                    return MetadataPage(items=[], next_cursor=None, exhausted=True)
                raise RuntimeError(
                    f"unable to verify UIDVALIDITY for folder {folder_remote_id}; aborting metadata scan"
                )
            try:
                _check_uidvalidity(cursor, uidvalidity)
            except CursorInvalidError:
                self._metadata_uid_scan = None
                raise
            start = int((cursor or {}).get("uid_next") or 1)
            scan_uidvalidity = uidvalidity
            cached_scan = self._metadata_uid_scan
            if (
                cached_scan is None
                or cached_scan[0] != folder_remote_id
                or cached_scan[1] != scan_uidvalidity
                or cached_scan[2] > start
            ):
                self._metadata_uid_scan = None
                typ, data = c.uid("SEARCH", None, f"UID {start}:*")
                if typ != "OK":
                    if typ == "NO" and _is_mailbox_noselect(c, folder_remote_id):
                        return MetadataPage(items=[], next_cursor=None, exhausted=True)
                    # Never treat a failed SEARCH as "folder exhausted" — that silently stops sync.
                    raise RuntimeError(f"UID SEARCH {folder_remote_id} failed: {typ}")
                uids = []
                for chunk in data or ():
                    if not chunk:
                        continue
                    raw_chunk = chunk if isinstance(chunk, bytes) else str(chunk).encode()
                    for match in re.finditer(rb"\d+", raw_chunk):
                        value = int(match.group(0))
                        if value >= start:
                            uids.append(value)
                uids.sort()
                self._metadata_uid_scan = (folder_remote_id, scan_uidvalidity, start, uids)
                cached_scan = self._metadata_uid_scan

            # A323: page_size comes from the persisted cursor — bound it.
            # Non-numeric or non-positive values fall back to 50; anything
            # above 500 is clamped so one FETCH cannot pull a whole mailbox.
            try:
                batch_size = int((cursor or {}).get("page_size") or 50)
            except (TypeError, ValueError):
                batch_size = 50
            if batch_size < 1:
                batch_size = 50
            elif batch_size > 500:
                batch_size = 500
            uid_list = cached_scan[3]
            offset = bisect_left(uid_list, start)
            batch = uid_list[offset : offset + batch_size]
            has_more = offset + len(batch) < len(uid_list)
            items: list[RemoteMessageMeta] = []
            if batch:
                uid_spec = ",".join(str(u) for u in batch)
                typ, fetched = c.uid(
                    "FETCH",
                    uid_spec,
                    "(UID FLAGS INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM TO CC SUBJECT MESSAGE-ID IN-REPLY-TO REFERENCES)])",
                )
                if typ != "OK":
                    raise RuntimeError(f"UID FETCH {folder_remote_id} uids={uid_spec} failed: {typ}")
                blobs = [blob for blob in (fetched or ()) if isinstance(blob, tuple)]
                returned_uids: set[int] = set()
                for idx, blob in enumerate(blobs):
                    fetched_uid = _uid_from_fetch_blob(blob)
                    if fetched_uid is None:
                        if len(blobs) != len(batch):
                            continue
                        fetched_uid = batch[idx]
                    if fetched_uid not in batch:
                        continue
                    returned_uids.add(fetched_uid)
                    meta = _parse_message_meta_from_fetch(
                        blob, fetched_uid, folder_remote_id, int(uidvalidity)
                    )
                    if meta is not None:
                        items.append(meta)
            if not batch:
                self._metadata_uid_scan = None
                return MetadataPage(
                    items=(),
                    next_cursor={"uid_next": start, "uidvalidity": uidvalidity},
                    exhausted=True,
                )
            missing_uids = [uid for uid in batch if uid not in returned_uids]
            if missing_uids:
                # Retry the first UID omitted by FETCH using a fresh SEARCH.
                self._metadata_uid_scan = None
                next_uid = missing_uids[0]
                exhausted = False
            else:
                next_uid = batch[-1] + 1
                exhausted = not has_more
                if exhausted:
                    self._metadata_uid_scan = None
            return MetadataPage(
                items=items,
                next_cursor={"uid_next": next_uid, "uidvalidity": uidvalidity, "page_size": batch_size},
                exhausted=exhausted,
            )
        finally:
            self._close_client(c, _permit)

    def fetch_mime(self, remote_id: str, *, folder_remote_id: str | None = None) -> bytes:
        parsed = parse_imap_remote_id(remote_id)
        if parsed is not None:
            _uv, folder_from_id, uid = parsed
            if folder_remote_id is not None and folder_remote_id != folder_from_id:
                # A185: the UID/UIDVALIDITY belong to the id-embedded folder;
                # a contradicting explicit folder would fetch the wrong mail.
                raise ValueError(
                    f"IMAP fetch_mime folder_remote_id={folder_remote_id!r} does not match "
                    f"remote_id folder {folder_from_id!r}"
                )
            folder = folder_from_id
            uid_str = str(uid)
        else:
            folder = folder_remote_id
            uid_str = str(remote_id)
            _uv = None
        if not folder:
            raise ValueError(
                "IMAP fetch_mime requires folder_remote_id= or a namespaced remote_id "
                "(uidvalidity\\x1ffolder\\x1fuid)"
            )
        reuse = self._active_client
        if reuse is not None:
            c, _permit = reuse, None  # session permit already held by open_session
        else:
            c, _permit = self._connect_with_permit()
        try:
            if reuse is None or self._current_folder != folder:
                typ, _ = c.select(_quote_mailbox(folder), readonly=True)
                if typ != "OK":
                    raise RuntimeError(f"select {folder} failed for fetch_mime")
                self._current_folder = folder
            if _uv is not None and _uv > 0:
                srv_uv = _get_server_uidvalidity(c, folder)
                if srv_uv is not None and srv_uv != _uv:
                    raise RuntimeError(f"UIDVALIDITY mismatch for {folder}: expected {_uv}, got {srv_uv}")
            typ, data = c.uid("FETCH", uid_str, "(BODY.PEEK[])")
            if typ != "OK" or not data or data[0] is None:
                raise RuntimeError(f"fetch mime {remote_id} failed")
            part = data[0]
            if isinstance(part, tuple) and len(part) > 1:
                body = part[1]
                return body if isinstance(body, bytes) else bytes(body)
            raise RuntimeError("unexpected FETCH payload")
        except Exception:
            if reuse is not None:
                self.close_session()
            raise
        finally:
            if reuse is None:
                self._close_client(c, _permit)

    def _fetch_flags_for_uids(
        self,
        c: imaplib.IMAP4,
        folder_remote_id: str,
        uidvalidity: int,
        uids: list[int],
        *,
        abort_on_missing_flags: bool = False,
    ) -> list[DeltaChange]:
        """FETCH FLAGS for MODSEQ-changed UIDs and emit flag deltas (not discarded)."""
        if not uids:
            return []
        changes: list[DeltaChange] = []
        uid_spec = ",".join(str(u) for u in uids)
        try:
            typ, fetched = c.uid("FETCH", uid_spec, "(FLAGS UID)")
        except Exception as exc:
            raise _ImapFlagFetchError(f"IMAP flag FETCH failed for {folder_remote_id}") from exc
        if typ != "OK" or not fetched:
            raise _ImapFlagFetchError(f"IMAP flag FETCH failed for {folder_remote_id}")

        try:
            expected_uids = set(uids)
            seen_uids: set[int] = set()
            for blob in fetched:
                if blob is None:
                    continue
                meta_bytes = blob[0] if isinstance(blob, tuple) else blob
                if not isinstance(meta_bytes, (bytes, str)):
                    raise _ImapFlagFetchError("IMAP flag FETCH returned an invalid response")
                meta_s = meta_bytes.decode("utf-8", errors="replace") if isinstance(meta_bytes, bytes) else str(meta_bytes)
                m_uid = re.search(r"\bUID\s+(\d+)", meta_s)
                if m_uid is None:
                    if meta_s.strip() in ("", ")"):
                        continue
                    raise _ImapFlagFetchError("IMAP flag FETCH response omitted UID")
                uid = int(m_uid.group(1))
                if uid not in expected_uids or uid in seen_uids:
                    raise _ImapFlagFetchError("IMAP flag FETCH returned an unexpected UID")
                is_read, is_flagged = _parse_fetch_flags(meta_s)
                seen_uids.add(uid)
                if is_read is None or is_flagged is None:
                    if abort_on_missing_flags:
                        raise _ImapFlagFetchError("IMAP flag FETCH response omitted FLAGS")
                    continue
                rid = format_imap_remote_id(folder_remote_id, int(uidvalidity), uid)
                changes.append(
                    DeltaChange(
                        kind="flag",
                        remote_id=rid,
                        flags={"is_read": is_read, "is_flagged": is_flagged},
                    )
                )

            if seen_uids != expected_uids:
                raise _ImapFlagFetchError("IMAP flag FETCH returned an incomplete UID set")
        except _ImapFlagFetchError:
            raise
        except Exception as exc:
            raise _ImapFlagFetchError("IMAP flag FETCH returned an invalid response") from exc
        return changes

    def _sweep_existing_flags(
        self,
        c: imaplib.IMAP4,
        folder_remote_id: str,
        uidvalidity: int,
        cursor: dict[str, Any],
    ) -> tuple[list[DeltaChange], bool, int]:
        """One bounded FLAGS window over already-known UIDs (R06).

        For servers without CONDSTORE: candidates are UIDs below the
        cursor's ``uid_next`` (their metadata is already stored; only
        flags can have changed on another client). Progress is the
        ``flag_scan_after`` cursor key; a completed sweep wraps it to 0
        so the next delta run re-checks from the start. A failed SEARCH
        or FLAGS FETCH skips the sweep for this round without wedging
        the delta (A145).
        Returns (changes, sweep_complete, next_flag_scan_after).
        """
        existing_max = int(cursor.get("uid_next") or 1) - 1
        after = int(cursor.get("flag_scan_after") or 0)
        if existing_max <= 0:
            return [], True, 0
        try:
            typ, data = c.uid("SEARCH", None, "ALL")
        except Exception as exc:
            log.warning(
                "IMAP flag sweep SEARCH failed for %s; skipping this round: %s",
                folder_remote_id,
                safe_error(exc),
            )
            return [], True, after
        if typ != "OK" or not data:
            return [], True, after
        all_uids = sorted(set(_search_uids(data)))
        candidates = [u for u in all_uids if after < u <= existing_max]
        window = candidates[:200]
        changes: list[DeltaChange] = []
        if window:
            try:
                changes = self._fetch_flags_for_uids(
                    c, folder_remote_id, uidvalidity, window, abort_on_missing_flags=True
                )
            except _ImapFlagFetchError as exc:
                # A145: one poisoned FETCH must not kill the whole delta —
                # skip this sweep round like a SEARCH failure, keeping the
                # flag_scan_after progress for the next round.
                log.warning(
                    "IMAP flag sweep FETCH failed for %s; skipping this round: %s",
                    folder_remote_id,
                    safe_error(exc),
                )
                return [], True, after
        complete = len(candidates) <= len(window)
        return changes, complete, 0 if complete else window[-1]

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        """Incremental sync.

        Prefer CONDSTORE/MODSEQ when the server advertises it; emit explicit flag
        changes for MODSEQ hits. Also page new UIDs since ``uid_next``. Without
        MODSEQ, additionally sweep existing UIDs' FLAGS in bounded windows
        (``flag_scan_after`` cursor progress, R06) so flag changes made by
        other clients are observed. Deletions
        are *not* inferred here — use reconcile after a complete scan.
        """
        c, _permit = self._connect_with_permit()
        connection_open = True

        def close_connection() -> None:
            nonlocal connection_open
            if not connection_open:
                return
            connection_open = False
            self._close_client(c, _permit)

        try:
            typ, _ = c.select(_quote_mailbox(folder_remote_id), readonly=True)
            if typ != "OK":
                if _is_mailbox_noselect(c, folder_remote_id):
                    return DeltaPage(changes=(), next_cursor=cursor, exhausted=True)
                raise RuntimeError(f"select {folder_remote_id} failed")
            highest = None
            try:
                st = c.status(_quote_mailbox(folder_remote_id), "(HIGHESTMODSEQ UIDVALIDITY)")
                if st[0] == "OK" and st[1] and st[1][0]:
                    blob = st[1][0].decode() if isinstance(st[1][0], bytes) else str(st[1][0])
                    m = re.search(r"HIGHESTMODSEQ\s+(\d+)", blob)
                    if m:
                        highest = int(m.group(1))
                    m2 = re.search(r"UIDVALIDITY\s+(\d+)", blob)
                    uidvalidity = int(m2.group(1)) if m2 else cursor.get("uidvalidity")
                else:
                    uidvalidity = cursor.get("uidvalidity")
            except CursorInvalidError:
                raise
            except Exception as exc:
                log.warning(
                    "could not read IMAP MODSEQ status for %s: %s",
                    folder_remote_id,
                    safe_error(exc),
                )
                uidvalidity = cursor.get("uidvalidity")
                highest = None

            _check_uidvalidity(cursor, uidvalidity if uidvalidity is not None else None)
            if uidvalidity is None:
                # A28: no verified UIDVALIDITY (server or cursor) — abort
                # rather than minting flag/upsert remote_ids with uv=0.
                raise RuntimeError(
                    f"unable to verify UIDVALIDITY for folder {folder_remote_id}; aborting delta"
                )
            uv = int(uidvalidity)

            changes: list[DeltaChange] = []
            since_modseq = int(cursor.get("modseq") or 0)
            if highest is not None:
                try:
                    typ, data = c.uid("SEARCH", None, "MODSEQ", str(int(since_modseq) + 1))
                    if typ == "OK":
                        changed_uids = _search_uids(data)
                        if not changed_uids:
                            return DeltaPage(
                                changes=(),
                                next_cursor={**cursor, "modseq": highest, "uidvalidity": uidvalidity},
                                exhausted=True,
                            )
                        uid_next = int(cursor.get("uid_next") or 1)
                        flag_uid_after = int(cursor.get("flag_uid_after") or 0)
                        # New UIDs: full metadata upsert; older UIDs: flag-only.
                        new_uids = sorted([u for u in changed_uids if u >= uid_next])
                        flag_uids = sorted([u for u in changed_uids if u < uid_next and u > flag_uid_after])

                        batch_flag_uids = flag_uids[:200]
                        has_more_flags = len(flag_uids) > 200
                        if batch_flag_uids:
                            changes.extend(
                                self._fetch_flags_for_uids(
                                    c,
                                    folder_remote_id,
                                    uv,
                                    batch_flag_uids,
                                    abort_on_missing_flags=True,
                                )
                            )

                        next_cursor = dict(cursor)
                        if uidvalidity is not None:
                            next_cursor["uidvalidity"] = uidvalidity

                        has_more_new = False
                        if new_uids:
                            # Page via temporary cursor starting at the lowest new UID.
                            batch_size = min(50, len(new_uids))
                            close_connection()
                            page = self.fetch_metadata_page(
                                folder_remote_id,
                                {**cursor, "uid_next": min(new_uids), "page_size": batch_size},
                            )
                            changes.extend(
                                DeltaChange(kind="upsert", remote_id=m.remote_id, meta=m) for m in page.items
                            )
                            p_next = page.next_cursor.get("uid_next")
                            if p_next is not None:
                                next_cursor["uid_next"] = p_next
                                has_more_new = not page.exhausted or any(u >= p_next for u in new_uids)
                            else:
                                has_more_new = not page.exhausted

                        if has_more_flags:
                            next_cursor["flag_uid_after"] = batch_flag_uids[-1]
                            next_cursor["modseq"] = since_modseq
                        else:
                            next_cursor.pop("flag_uid_after", None)
                            if has_more_new:
                                next_cursor["modseq"] = since_modseq
                            else:
                                next_cursor["modseq"] = highest

                        exhausted = not (has_more_flags or has_more_new)
                        return DeltaPage(
                            changes=changes,
                            next_cursor=next_cursor,
                            exhausted=exhausted,
                        )
                    log.warning(
                        "IMAP MODSEQ SEARCH failed for %s with status %s; falling back to UID scan",
                        folder_remote_id,
                        typ,
                    )
                except CursorInvalidError:
                    raise
                except _ImapFlagFetchError:
                    raise
                except Exception as exc:
                    log.warning(
                        "IMAP MODSEQ delta failed for %s; falling back to UID scan: %s",
                        folder_remote_id,
                        safe_error(exc),
                    )

            # UID-based incremental (always safe): fetch metadata since uid_next.
            # Without MODSEQ, first sweep one bounded window of existing
            # UIDs' FLAGS on this connection (R06).
            flag_changes: list[DeltaChange] = []
            sweep_complete = True
            flag_scan_after = int(cursor.get("flag_scan_after") or 0)
            if highest is None and uv > 0:
                flag_changes, sweep_complete, flag_scan_after = self._sweep_existing_flags(
                    c, folder_remote_id, uv, cursor
                )
            close_connection()
            page = self.fetch_metadata_page(folder_remote_id, cursor)
            changes = flag_changes + [
                DeltaChange(kind="upsert", remote_id=m.remote_id, meta=m) for m in page.items
            ]
            next_cursor = dict(page.next_cursor or {})
            if cursor.get("modseq") is not None:
                next_cursor["modseq"] = cursor["modseq"]
            if uidvalidity is not None:
                next_cursor["uidvalidity"] = uidvalidity
            if highest is None:
                if sweep_complete:
                    next_cursor.pop("flag_scan_after", None)
                else:
                    next_cursor["flag_scan_after"] = flag_scan_after
            return DeltaPage(
                changes=changes,
                next_cursor=next_cursor,
                exhausted=page.exhausted and sweep_complete,
            )
        finally:
            close_connection()

    def apply_remote_operations(
        self, operations: Sequence[Any]
    ) -> Sequence[tuple[Any, RemoteOperationResult]]:
        from mail_core.providers.remote_writeback import (
            OP_MARK_READ,
            OP_MOVE,
            OP_SET_FLAG,
            OP_TRASH,
            compress_uids_chunked,
            normalize_op_type,
            require_remote_id,
        )

        if not operations:
            return []

        results: dict[Any, RemoteOperationResult] = {}
        valid_ops: list[tuple[Any, str, dict[str, Any], int, str, int | None, str | None]] = []

        for item in operations:
            op_id = item.op_id
            desired = dict(item.desired_state or {})
            op_type = normalize_op_type(item.op_type)
            try:
                remote_id = require_remote_id(desired)
            except ValueError as exc:
                results[op_id] = RemoteOperationResult(success=False, error=str(exc))
                continue

            parsed = parse_imap_remote_id(remote_id)
            folder = str(desired.get("folder_remote_id") or (parsed[1] if parsed else "") or "INBOX")
            if parsed is not None and desired.get("folder_remote_id"):
                if str(desired["folder_remote_id"]) != parsed[1]:
                    results[op_id] = RemoteOperationResult(
                        success=False,
                        error=f"folder_remote_id {desired['folder_remote_id']!r} does not match remote_id folder {parsed[1]!r}",
                    )
                    continue

            uid_str = imap_uid_for_command(remote_id)
            try:
                numeric_uid = int(uid_str)
            except ValueError:
                results[op_id] = RemoteOperationResult(success=False, error=f"invalid numeric UID {uid_str!r}")
                continue

            uv = parsed[0] if parsed is not None else None
            dest_folder: str | None = None
            if op_type == OP_MOVE:
                dest = str(desired.get("dest_folder_remote_id") or desired.get("to_folder") or "")
                if not dest:
                    results[op_id] = RemoteOperationResult(success=False, error="missing dest_folder_remote_id")
                    continue
                dest_folder = dest
            elif op_type == OP_TRASH:
                dest_folder = str(desired.get("trash_folder_remote_id") or "Trash")

            valid_ops.append((op_id, op_type, desired, numeric_uid, folder, uv, dest_folder))

        if not valid_ops:
            return [(op.op_id, results.get(op.op_id, RemoteOperationResult(success=False, error="unknown error"))) for op in operations]

        folder_groups: dict[str, list[tuple[Any, str, dict[str, Any], int, str, int | None, str | None]]] = {}
        for entry in valid_ops:
            folder = entry[4]
            folder_groups.setdefault(folder, []).append(entry)

        c, _permit = self._connect_with_permit()
        try:
            for folder, items in folder_groups.items():
                try:
                    typ, _ = c.select(_quote_mailbox(folder))
                    if typ != "OK":
                        for it in items:
                            results[it[0]] = RemoteOperationResult(success=False, error=f"select {folder} failed")
                        continue

                    srv_uv = _get_server_uidvalidity(c, folder)
                    valid_folder_items = []
                    for it in items:
                        expected_uv = it[5]
                        if (
                            expected_uv is not None
                            and expected_uv > 0
                            and srv_uv is not None
                            and srv_uv != expected_uv
                        ):
                            results[it[0]] = RemoteOperationResult(
                                success=False,
                                error=f"UIDVALIDITY mismatch for {folder}: expected {expected_uv}, got {srv_uv}",
                            )
                        else:
                            valid_folder_items.append(it)

                    if not valid_folder_items:
                        continue

                    subgroups: dict[tuple[str, Any], list[tuple[Any, str, dict[str, Any], int, str, int | None, str | None]]] = {}
                    for it in valid_folder_items:
                        op_id, op_type, desired, num_uid, fld, uv, dest_fld = it
                        if op_type == OP_MARK_READ:
                            target_val = bool(desired.get("is_read", True))
                        elif op_type == OP_SET_FLAG:
                            target_val = bool(desired.get("is_flagged", True))
                        else:
                            target_val = dest_fld
                        subgroups.setdefault((op_type, target_val), []).append(it)

                    for (op_type, target_val), sub_items in subgroups.items():
                        uid_to_item = {it[3]: it for it in sub_items}
                        uids = sorted(uid_to_item.keys())
                        chunks = compress_uids_chunked(uids)

                        for chunk_str, chunk_uids in chunks:
                            if op_type == OP_MARK_READ:
                                want_read = bool(target_val)
                                flag_op = "+FLAGS" if want_read else "-FLAGS"
                                typ, data = c.uid("STORE", chunk_str, flag_op, r"(\Seen)")
                                if typ != "OK":
                                    for u in chunk_uids:
                                        results[uid_to_item[u][0]] = RemoteOperationResult(success=False, error="STORE Seen failed")
                                    continue
                                flags_by_uid = _parse_uids_flags_from_response(data)
                                missing_uids = [u for u in chunk_uids if u not in flags_by_uid]
                                if missing_uids:
                                    f_chunks = compress_uids_chunked(missing_uids)
                                    for fc, _ in f_chunks:
                                        f_typ, f_data = c.uid("FETCH", fc, "(FLAGS UID)")
                                        if f_typ == "OK":
                                            flags_by_uid.update(_parse_uids_flags_from_response(f_data))
                                for u in chunk_uids:
                                    op_id = uid_to_item[u][0]
                                    if u not in flags_by_uid:
                                        results[op_id] = RemoteOperationResult(
                                            success=False,
                                            error=f"UID {u} not found in {folder}",
                                        )
                                    else:
                                        is_read, _ = flags_by_uid[u]
                                        if is_read is want_read:
                                            results[op_id] = RemoteOperationResult(
                                                success=True,
                                                remote_state={"is_read": want_read},
                                            )
                                        else:
                                            results[op_id] = RemoteOperationResult(
                                                success=False,
                                                error=f"STORE Seen for UID {u} could not be verified via FETCH",
                                            )

                            elif op_type == OP_SET_FLAG:
                                want_flag = bool(target_val)
                                flag_op = "+FLAGS" if want_flag else "-FLAGS"
                                typ, data = c.uid("STORE", chunk_str, flag_op, r"(\Flagged)")
                                if typ != "OK":
                                    for u in chunk_uids:
                                        results[uid_to_item[u][0]] = RemoteOperationResult(success=False, error="STORE Flagged failed")
                                    continue
                                flags_by_uid = _parse_uids_flags_from_response(data)
                                missing_uids = [u for u in chunk_uids if u not in flags_by_uid]
                                if missing_uids:
                                    f_chunks = compress_uids_chunked(missing_uids)
                                    for fc, _ in f_chunks:
                                        f_typ, f_data = c.uid("FETCH", fc, "(FLAGS UID)")
                                        if f_typ == "OK":
                                            flags_by_uid.update(_parse_uids_flags_from_response(f_data))
                                for u in chunk_uids:
                                    op_id = uid_to_item[u][0]
                                    if u not in flags_by_uid:
                                        results[op_id] = RemoteOperationResult(
                                            success=False,
                                            error=f"UID {u} not found in {folder}",
                                        )
                                    else:
                                        _, is_flagged = flags_by_uid[u]
                                        if is_flagged is want_flag:
                                            results[op_id] = RemoteOperationResult(
                                                success=True,
                                                remote_state={"is_flagged": want_flag},
                                            )
                                        else:
                                            results[op_id] = RemoteOperationResult(
                                                success=False,
                                                error=f"STORE Flagged for UID {u} could not be verified via FETCH",
                                            )

                            elif op_type in (OP_MOVE, OP_TRASH):
                                dest_target = str(target_val)
                                typ, response_data = c.uid("MOVE", chunk_str, _quote_mailbox(dest_target))
                                if typ != "OK":
                                    for u in chunk_uids:
                                        results[uid_to_item[u][0]] = RemoteOperationResult(
                                            success=False,
                                            error="IMAP server does not support atomic MOVE/delete",
                                        )
                                else:
                                    copyuid_texts = _extract_copyuid_texts(c, response_data)
                                    states_by_uid = _copyuid_remote_states(copyuid_texts, chunk_uids, dest_target)
                                    for u in chunk_uids:
                                        op_id = uid_to_item[u][0]
                                        results[op_id] = RemoteOperationResult(
                                            success=True,
                                            remote_state=states_by_uid[u],
                                        )
                except Exception as exc:
                    from mail_core.security.redact import safe_error

                    err_msg = f"IMAP operation group error: {safe_error(exc)}"
                    for it in items:
                        if it[0] not in results:
                            results[it[0]] = RemoteOperationResult(success=False, error=err_msg)
        finally:
            self._close_client(c, _permit)

        return [
            (
                op.op_id,
                results.get(
                    op.op_id, RemoteOperationResult(success=False, error="operation unhandled")
                ),
            )
            for op in operations
        ]

    def apply_remote_operation(self, op_type: str, desired_state: dict[str, Any]) -> RemoteOperationResult:
        from mail_core.providers.base import RemoteOperationItem

        dummy_id = uuid.uuid4()
        item = RemoteOperationItem(op_id=dummy_id, op_type=op_type, desired_state=desired_state)
        res = dict(self.apply_remote_operations([item]))
        return res[dummy_id]

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        """Return delete actions for local IDs missing remotely — caller must have completed a full scan."""
        c, _permit = self._connect_with_permit()
        try:
            typ, _ = c.select(_quote_mailbox(folder_remote_id), readonly=True)
            if typ != "OK":
                if _is_mailbox_noselect(c, folder_remote_id):
                    return []
                raise RuntimeError(f"select {folder_remote_id} failed during reconcile: {typ}")
            uidvalidity = 0
            status = c.status(_quote_mailbox(folder_remote_id), "(UIDVALIDITY)")
            if status[0] == "OK" and status[1] and status[1][0]:
                blob = status[1][0].decode() if isinstance(status[1][0], bytes) else str(status[1][0])
                m = re.search(r"UIDVALIDITY\s+(\d+)", blob)
                if m:
                    uidvalidity = int(m.group(1))
            if uidvalidity <= 0:
                # Without a verified UIDVALIDITY every remote key would be
                # built with uv=0, the local-remote diff would cover the
                # whole folder, and the caller would delete all local mail
                # in it. Abort the reconcile instead (B1).
                raise RuntimeError(
                    f"unable to verify UIDVALIDITY for folder {folder_remote_id}; aborting reconcile"
                )
            typ, data = c.uid("SEARCH", None, "ALL")
            if typ != "OK":
                if typ == "NO" and _is_mailbox_noselect(c, folder_remote_id):
                    return []
                raise RuntimeError(f"UID SEARCH {folder_remote_id} failed during reconcile: {typ}")
            remote_uids = _search_uids(data)
            remote = {format_imap_remote_id(folder_remote_id, uidvalidity, u) for u in remote_uids}
            # Also accept legacy bare-UID locals during transition.
            remote |= {str(u) for u in remote_uids}
            local = set(local_remote_ids)
            return [ReconcileAction(kind="delete", remote_id=rid) for rid in sorted(local - remote)]
        finally:
            self._close_client(c, _permit)

    def probe_folder_status(self, folder_remote_id: str) -> FolderStatus | None:
        """Cheap STATUS probe (t061): one short connection, no SELECT."""
        c, permit = self._connect_with_permit()
        try:
            typ, data = c.status(
                _quote_mailbox(folder_remote_id),
                "(MESSAGES UIDNEXT UNSEEN HIGHESTMODSEQ)",
            )
            if typ != "OK":
                return None
            return _parse_status_items(data)
        finally:
            self._close_client(c, permit)

    def open_idle_session(self, folder_remote_id: str) -> ImapIdleSession:
        """Open the dedicated IDLE watch connection (t061).

        Deliberately bypasses the connection-slot permit: long-lived
        IDLE connections are governed by the watcher's own quota, not
        the task slot budget. Raises IdleNotSupportedError when the
        server does not advertise IDLE.
        """
        client = self._connect()
        try:
            capabilities = {str(cap).upper() for cap in (client.capabilities or ())}
            try:
                typ, cap_data = client.capability()
                if typ == "OK" and cap_data and cap_data[0]:
                    raw = cap_data[0]
                    text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
                    capabilities |= {token.upper() for token in text.split()}
            except Exception:
                pass
            if "IDLE" not in capabilities:
                raise IdleNotSupportedError("server does not advertise IDLE")
            typ, _ = client.select(_quote_mailbox(folder_remote_id), readonly=True)
            if typ != "OK":
                raise IdleNotSupportedError(f"SELECT {folder_remote_id} failed: {typ}")
            sock = getattr(client, "sock", None)
            if sock is not None:
                # The reader thread blocks indefinitely; a finite socket
                # timeout would poison the buffered reader (t061 spike).
                sock.settimeout(None)
        except BaseException:
            sock = getattr(client, "sock", None)
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
            raise
        return ImapIdleSession(client)

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=120, reason="imap default")
