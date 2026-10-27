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
import re
import ssl
import threading
from bisect import bisect_left
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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
from mail_core.providers.http import CursorInvalidError
from mail_core.providers.host_security import validate_imap_peer_address
from mail_core.security.redact import safe_error

log = logging.getLogger("mail_core.providers.imap")

_IMAP_ID_FIELDS = {"name": "kkmail", "version": "3.0.20", "vendor": "kkmail"}
_IMAP_ID_ARGUMENT = '("name" "kkmail" "version" "3.0.20" "vendor" "kkmail")'
_IMAP_COMMANDS_LOCK = threading.Lock()
with _IMAP_COMMANDS_LOCK:
    imaplib.Commands.setdefault("ID", ("AUTH", "SELECTED"))


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


def _copyuid_remote_state(c: imaplib.IMAP4, response_data: Any, source_uid: int, dest_folder: str) -> dict[str, Any]:
    """Build destination identity from the UIDPLUS COPYUID response when present."""
    remote_state: dict[str, Any] = {"folder_remote_id": dest_folder}
    values = list(response_data or [])
    try:
        resp = c.response("COPYUID")
        if isinstance(resp, (tuple, list)) and len(resp) == 2:
            _, response_values = resp
            values.extend(response_values or [])
    except (AttributeError, ValueError, imaplib.IMAP4.error):
        pass
    for value in values:
        text = value.decode("ascii", errors="ignore") if isinstance(value, bytes) else str(value)
        match = re.search(r"(?:\[\s*)?COPYUID\s+(\d+)\s+([0-9,:]+)\s+([0-9,:]+)", text, re.IGNORECASE)
        if match is None:
            match = re.fullmatch(r"\s*(\d+)\s+([0-9,:]+)\s+([0-9,:]+)\s*", text)
        if match is None:
            continue
        uidvalidity = int(match.group(1))
        source_set = match.group(2)
        destination_set = match.group(3)
        index = _uid_sequence_index(source_set, source_uid)
        if index is None:
            continue
        destination_uid = _uid_sequence_value(destination_set, index)
        if destination_uid is None:
            continue
        remote_state["remote_id"] = format_imap_remote_id(dest_folder, uidvalidity, destination_uid)
        remote_state["uid"] = destination_uid
        break
    return remote_state


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


def _uid_from_fetch_blob(flags_blob: tuple[Any, ...]) -> int | None:
    if not flags_blob:
        return None
    meta_bytes = flags_blob[0]
    meta = meta_bytes.decode("utf-8", errors="replace") if isinstance(meta_bytes, bytes) else str(meta_bytes)
    match = re.search(r"\bUID\s+(\d+)", meta, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


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
    _metadata_uid_scan: tuple[str, int | None, list[int]] | None = field(
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
                r"\((?P<flags>[^)]*)\)\s+(?:\"(?P<delim>[^\"]*)\"|(?P<delim_bare>\S+))\s+(?:\"(?P<name>[^\"]*)\"|(?P<name_bare>.+))\s*$"
            )
            for raw in data:
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                m = list_pattern.search(line)
                if m:
                    flags_raw = m.group("flags")
                    flags = [f.strip() for f in flags_raw.split() if f.strip()]
                    delim = m.group("delim") or m.group("delim_bare")
                    if delim == "NIL":
                        delim = None
                    remote_id = (m.group("name") or m.group("name_bare")).strip()
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
                self._metadata_uid_scan = (folder_remote_id, scan_uidvalidity, uids)
                cached_scan = self._metadata_uid_scan

            batch_size = int((cursor or {}).get("page_size") or 50)
            uid_list = cached_scan[2]
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
            folder = folder_remote_id or folder_from_id
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
        skips the sweep for this round without wedging the delta.
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
            changes = self._fetch_flags_for_uids(
                c, folder_remote_id, uidvalidity, window, abort_on_missing_flags=True
            )
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

    def apply_remote_operation(self, op_type: str, desired_state: dict[str, Any]) -> RemoteOperationResult:
        from mail_core.providers.remote_writeback import (
            OP_MARK_READ,
            OP_MOVE,
            OP_SET_FLAG,
            OP_TRASH,
            normalize_op_type,
            require_remote_id,
        )

        try:
            remote_id = require_remote_id(desired_state)
        except ValueError as exc:
            return RemoteOperationResult(success=False, error=str(exc))
        parsed = parse_imap_remote_id(remote_id)
        folder = str(desired_state.get("folder_remote_id") or (parsed[1] if parsed else "") or "INBOX")
        uid_str = imap_uid_for_command(remote_id)
        op = normalize_op_type(op_type)
        try:
            quoted_folder = _quote_mailbox(folder)
            quoted_dest: str | None = None
            if op == OP_MOVE:
                dest = str(desired_state.get("dest_folder_remote_id") or desired_state.get("to_folder") or "")
                if not dest:
                    return RemoteOperationResult(success=False, error="missing dest_folder_remote_id")
                quoted_dest = _quote_mailbox(dest)
            elif op == OP_TRASH:
                trash = str(desired_state.get("trash_folder_remote_id") or "Trash")
                quoted_dest = _quote_mailbox(trash)
        except ValueError as exc:
            return RemoteOperationResult(success=False, error=str(exc))

        c, _permit = self._connect_with_permit()
        try:
            typ, _ = c.select(quoted_folder)
            if typ != "OK":
                return RemoteOperationResult(success=False, error=f"select {folder} failed")

            if parsed is not None:
                _uv = parsed[0]
                if _uv > 0:
                    srv_uv = _get_server_uidvalidity(c, folder)
                    if srv_uv is not None and srv_uv != _uv:
                        return RemoteOperationResult(
                            success=False,
                            error=f"UIDVALIDITY mismatch for {folder}: expected {_uv}, got {srv_uv}",
                        )

            if op == OP_MARK_READ:
                want_read = bool(desired_state.get("is_read", True))
                flag_op = "+FLAGS" if want_read else "-FLAGS"
                typ, _ = c.uid("STORE", uid_str, flag_op, r"(\Seen)")
                if typ != "OK":
                    return RemoteOperationResult(success=False, error="STORE Seen failed")
                return RemoteOperationResult(success=True, remote_state={"is_read": want_read})

            if op == OP_SET_FLAG:
                want = bool(desired_state.get("is_flagged", True))
                flag_op = "+FLAGS" if want else "-FLAGS"
                typ, _ = c.uid("STORE", uid_str, flag_op, r"(\Flagged)")
                if typ != "OK":
                    return RemoteOperationResult(success=False, error="STORE Flagged failed")
                return RemoteOperationResult(success=True, remote_state={"is_flagged": want})

            if op == OP_MOVE:
                # Prefer UID MOVE (RFC 6851); never STORE \Deleted or expunge entire mailbox
                assert quoted_dest is not None
                typ, response_data = c.uid("MOVE", uid_str, quoted_dest)
                if typ != "OK":
                    return RemoteOperationResult(
                        success=False,
                        error="IMAP server does not support atomic MOVE/delete",
                    )
                try:
                    source_uid = int(uid_str)
                except ValueError:
                    remote_state = {"folder_remote_id": dest}
                else:
                    remote_state = _copyuid_remote_state(c, response_data, source_uid, dest)
                return RemoteOperationResult(success=True, remote_state=remote_state)

            if op == OP_TRASH:
                # Try move into trash mailbox first; never STORE \Deleted or expunge entire mailbox
                assert quoted_dest is not None
                typ, response_data = c.uid("MOVE", uid_str, quoted_dest)
                if typ != "OK":
                    return RemoteOperationResult(
                        success=False,
                        error="IMAP server does not support atomic MOVE/delete",
                    )
                try:
                    source_uid = int(uid_str)
                except ValueError:
                    remote_state = {"folder_remote_id": trash}
                else:
                    remote_state = _copyuid_remote_state(c, response_data, source_uid, trash)
                return RemoteOperationResult(success=True, remote_state=remote_state)

            return RemoteOperationResult(success=False, error=f"imap apply not implemented: {op_type}")
        finally:
            self._close_client(c, _permit)

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

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=120, reason="imap default")
