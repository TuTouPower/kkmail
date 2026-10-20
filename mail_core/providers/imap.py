"""IMAP provider adapter (UID + optional CONDSTORE/MODSEQ).

Never infers deletions from an incomplete UID scan (architecture §6.2).
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import re
from dataclasses import dataclass
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

_FOLDER_ROLE = {
    "INBOX": "inbox",
    "Junk": "junk",
    "Junk Email": "junk",
    "Spam": "junk",
    "Trash": "trash",
    "Deleted": "trash",
    "Deleted Items": "trash",
    "Sent": "sent",
    "Sent Items": "sent",
    "Drafts": "drafts",
    "Archive": "archive",
}


def _decode_header(raw: str | None) -> str:
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    out: list[str] = []
    for chunk, charset in parts:
        if isinstance(chunk, bytes):
            out.append(chunk.decode(charset or "utf-8", errors="replace"))
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

@dataclass
class ImapProvider:
    host: str
    port: int
    username: str
    password: str
    use_ssl: bool = True
    timeout: float = 30.0

    def _connect(self) -> imaplib.IMAP4:
        timeout = float(self.timeout)
        if self.use_ssl:
            client: imaplib.IMAP4 = imaplib.IMAP4_SSL(self.host, self.port, timeout=timeout)
        else:
            client = imaplib.IMAP4(self.host, self.port, timeout=timeout)
        client.login(self.username, self.password)
        return client

    def list_folders(self) -> Sequence[RemoteFolder]:
        c = self._connect()
        try:
            typ, data = c.list()
            if typ != "OK" or not data:
                return [RemoteFolder("INBOX", "INBOX", "inbox")]
            folders: list[RemoteFolder] = []
            for raw in data:
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                m = re.search(r' "?"?([^"]+)"?\s*$', line)
                name = m.group(1).strip() if m else line.rsplit(" ", 1)[-1].strip('"')
                role = _FOLDER_ROLE.get(name, "other")
                folders.append(RemoteFolder(remote_id=name, name=name, role=role))
            if not any(f.remote_id.upper() == "INBOX" for f in folders):
                folders.insert(0, RemoteFolder("INBOX", "INBOX", "inbox"))
            return folders
        finally:
            try:
                c.logout()
            except Exception:
                pass

    def full_scan(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        return self.fetch_metadata_page(folder_remote_id, cursor)

    def fetch_metadata_page(self, folder_remote_id: str, cursor: dict[str, Any] | None) -> MetadataPage:
        """Page by UID ascending. Cursor keys: uid_next, uidvalidity, page_size."""
        c = self._connect()
        try:
            typ, _ = c.select(folder_remote_id, readonly=True)
            if typ != "OK":
                raise RuntimeError(f"select {folder_remote_id} failed: {typ}")
            uidvalidity = None
            status = c.status(folder_remote_id, "(UIDVALIDITY)")
            if status[0] == "OK" and status[1] and status[1][0]:
                blob = status[1][0].decode() if isinstance(status[1][0], bytes) else str(status[1][0])
                m = re.search(r"UIDVALIDITY\s+(\d+)", blob)
                if m:
                    uidvalidity = int(m.group(1))
            _check_uidvalidity(cursor, uidvalidity)
            start = int((cursor or {}).get("uid_next") or 1)
            typ, data = c.uid("SEARCH", None, f"UID {start}:*")
            if typ != "OK":
                # Never treat a failed SEARCH as "folder exhausted" — that silently stops sync.
                raise RuntimeError(f"UID SEARCH {folder_remote_id} failed: {typ}")
            uids = [int(x) for x in (data[0] or b"").split() if x]
            uids = [u for u in uids if u >= start]
            batch_size = int((cursor or {}).get("page_size") or 50)
            batch = uids[:batch_size]
            items: list[RemoteMessageMeta] = []
            for uid in batch:
                typ, fetched = c.uid(
                    "FETCH",
                    str(uid),
                    "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])",
                )
                if typ != "OK" or not fetched or fetched[0] is None:
                    continue
                flags_blob = fetched[0]
                if isinstance(flags_blob, tuple):
                    meta_bytes = flags_blob[0]
                    header_bytes = flags_blob[1] if len(flags_blob) > 1 else b""
                else:
                    continue
                meta_s = meta_bytes.decode("utf-8", errors="replace") if isinstance(meta_bytes, bytes) else str(meta_bytes)
                is_read = "\\Seen" in meta_s
                header_text = header_bytes.decode("utf-8", errors="replace") if isinstance(header_bytes, bytes) else str(header_bytes)
                headers = email.message_from_string(header_text)
                subject = _decode_header(headers.get("Subject"))
                from_raw = _decode_header(headers.get("From"))
                addr, name = _parse_from(from_raw)
                date_raw = headers.get("Date")
                try:
                    sort_time = parsedate_to_datetime(date_raw) if date_raw else datetime.now(timezone.utc)
                    if sort_time.tzinfo is None:
                        sort_time = sort_time.replace(tzinfo=timezone.utc)
                except Exception:
                    sort_time = datetime.now(timezone.utc)
                uv = int(uidvalidity) if uidvalidity is not None else 0
                items.append(
                    RemoteMessageMeta(
                        remote_id=format_imap_remote_id(folder_remote_id, uv, uid),
                        subject=subject,
                        from_address=addr,
                        from_name=name,
                        sort_time=sort_time,
                        is_read=is_read,
                        has_attachments=False,
                        internet_message_id=headers.get("Message-ID"),
                        uid=uid,
                    )
                )
            if not batch:
                return MetadataPage(
                    items=(),
                    next_cursor={"uid_next": start, "uidvalidity": uidvalidity},
                    exhausted=True,
                )
            next_uid = batch[-1] + 1
            exhausted = len(uids) <= batch_size
            return MetadataPage(
                items=items,
                next_cursor={"uid_next": next_uid, "uidvalidity": uidvalidity, "page_size": batch_size},
                exhausted=exhausted,
            )
        finally:
            try:
                c.logout()
            except Exception:
                pass

    def fetch_mime(self, remote_id: str, *, folder_remote_id: str | None = None) -> bytes:
        parsed = parse_imap_remote_id(remote_id)
        if parsed is not None:
            _uv, folder_from_id, uid = parsed
            folder = folder_remote_id or folder_from_id
            uid_str = str(uid)
        else:
            folder = folder_remote_id
            uid_str = str(remote_id)
        if not folder:
            raise ValueError(
                "IMAP fetch_mime requires folder_remote_id= or a namespaced remote_id "
                "(uidvalidity\\x1ffolder\\x1fuid)"
            )
        c = self._connect()
        try:
            typ, _ = c.select(folder, readonly=True)
            if typ != "OK":
                raise RuntimeError(f"select {folder} failed for fetch_mime")
            typ, data = c.uid("FETCH", uid_str, "(BODY.PEEK[])")
            if typ != "OK" or not data or data[0] is None:
                raise RuntimeError(f"fetch mime {remote_id} failed")
            part = data[0]
            if isinstance(part, tuple) and len(part) > 1:
                body = part[1]
                return body if isinstance(body, bytes) else bytes(body)
            raise RuntimeError("unexpected FETCH payload")
        finally:
            try:
                c.logout()
            except Exception:
                pass

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        """Incremental sync.

        Prefer CONDSTORE/MODSEQ when the server advertises it; otherwise page new
        UIDs since ``uid_next``. Deletions are *not* inferred here — use reconcile
        after a complete scan.
        """
        c = self._connect()
        try:
            typ, _ = c.select(folder_remote_id, readonly=True)
            if typ != "OK":
                raise RuntimeError(f"select {folder_remote_id} failed")
            # Detect HIGHESTMODSEQ via STATUS when possible.
            highest = None
            try:
                st = c.status(folder_remote_id, "(HIGHESTMODSEQ UIDVALIDITY)")
                if st[0] == "OK" and st[1] and st[1][0]:
                    blob = st[1][0].decode() if isinstance(st[1][0], bytes) else str(st[1][0])
                    m = re.search(r"HIGHESTMODSEQ\s+(\d+)", blob)
                    if m:
                        highest = int(m.group(1))
                    m2 = re.search(r"UIDVALIDITY\s+(\d+)", blob)
                    uidvalidity = int(m2.group(1)) if m2 else cursor.get("uidvalidity")
                else:
                    uidvalidity = cursor.get("uidvalidity")
            except Exception:
                uidvalidity = cursor.get("uidvalidity")
                highest = None

            _check_uidvalidity(cursor, uidvalidity if uidvalidity is not None else None)

            since_modseq = cursor.get("modseq")
            if highest is not None and since_modseq is not None:
                # CHANGEDSINCE may be unsupported on pymap; fall back silently.
                try:
                    typ, data = c.uid("SEARCH", None, "MODSEQ", str(int(since_modseq) + 1))
                    if typ == "OK":
                        uids = [int(x) for x in (data[0] or b"").split() if x]
                        # Reuse header fetch path by setting cursor to each uid range
                        # Fall through to UID page for those uids via temporary cursor.
                        if not uids:
                            return DeltaPage(
                                changes=(),
                                next_cursor={**cursor, "modseq": highest, "uidvalidity": uidvalidity},
                                exhausted=True,
                            )
                except Exception:
                    pass

            # UID-based incremental (always safe): fetch metadata since uid_next.
            page = self.fetch_metadata_page(folder_remote_id, cursor)
            changes = [DeltaChange(kind="upsert", remote_id=m.remote_id, meta=m) for m in page.items]
            next_cursor = dict(page.next_cursor or {})
            if highest is not None:
                next_cursor["modseq"] = highest
            if uidvalidity is not None:
                next_cursor["uidvalidity"] = uidvalidity
            return DeltaPage(changes=changes, next_cursor=next_cursor, exhausted=page.exhausted)
        finally:
            try:
                c.logout()
            except Exception:
                pass

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
        c = self._connect()
        try:
            typ, _ = c.select(folder)
            if typ != "OK":
                return RemoteOperationResult(success=False, error=f"select {folder} failed")

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
                dest = str(desired_state.get("dest_folder_remote_id") or desired_state.get("to_folder") or "")
                if not dest:
                    return RemoteOperationResult(success=False, error="missing dest_folder_remote_id")
                # Prefer UID MOVE (RFC 6851); fall back to COPY + delete.
                typ, _ = c.uid("MOVE", uid_str, dest)
                if typ != "OK":
                    typ, _ = c.uid("COPY", uid_str, dest)
                    if typ != "OK":
                        return RemoteOperationResult(success=False, error=f"COPY/MOVE to {dest} failed")
                    typ, _ = c.uid("STORE", uid_str, "+FLAGS", r"(\Deleted)")
                    if typ != "OK":
                        return RemoteOperationResult(success=False, error="STORE Deleted after COPY failed")
                    try:
                        c.expunge()
                    except Exception:
                        pass
                return RemoteOperationResult(success=True, remote_state={"folder_remote_id": dest})

            if op == OP_TRASH:
                trash = str(desired_state.get("trash_folder_remote_id") or "Trash")
                # Try move into trash mailbox first
                typ, _ = c.uid("MOVE", uid_str, trash)
                if typ == "OK":
                    return RemoteOperationResult(success=True, remote_state={"folder_remote_id": trash})
                typ, _ = c.uid("COPY", uid_str, trash)
                if typ == "OK":
                    c.uid("STORE", uid_str, "+FLAGS", r"(\Deleted)")
                    try:
                        c.expunge()
                    except Exception:
                        pass
                    return RemoteOperationResult(success=True, remote_state={"folder_remote_id": trash})
                typ, _ = c.uid("STORE", uid_str, "+FLAGS", r"(\Deleted)")
                if typ != "OK":
                    return RemoteOperationResult(success=False, error="STORE Deleted failed")
                try:
                    c.expunge()
                except Exception:
                    pass
                return RemoteOperationResult(success=True)

            return RemoteOperationResult(success=False, error=f"imap apply not implemented: {op_type}")
        finally:
            try:
                c.logout()
            except Exception:
                pass

    def reconcile(self, folder_remote_id: str, local_remote_ids: Sequence[str]) -> Sequence[ReconcileAction]:
        """Return delete actions for local IDs missing remotely — caller must have completed a full scan."""
        c = self._connect()
        try:
            typ, _ = c.select(folder_remote_id, readonly=True)
            if typ != "OK":
                raise RuntimeError(f"select {folder_remote_id} failed during reconcile: {typ}")
            uidvalidity = 0
            status = c.status(folder_remote_id, "(UIDVALIDITY)")
            if status[0] == "OK" and status[1] and status[1][0]:
                blob = status[1][0].decode() if isinstance(status[1][0], bytes) else str(status[1][0])
                m = re.search(r"UIDVALIDITY\s+(\d+)", blob)
                if m:
                    uidvalidity = int(m.group(1))
            typ, data = c.uid("SEARCH", None, "ALL")
            if typ != "OK":
                raise RuntimeError(f"UID SEARCH {folder_remote_id} failed during reconcile: {typ}")
            remote_uids = []
            for x in (data[0] or b"").split():
                s = x.decode() if isinstance(x, bytes) else str(x)
                try:
                    remote_uids.append(int(s))
                except ValueError:
                    continue
            remote = {format_imap_remote_id(folder_remote_id, uidvalidity, u) for u in remote_uids}
            # Also accept legacy bare-UID locals during transition.
            remote |= {str(u) for u in remote_uids}
            local = set(local_remote_ids)
            return [ReconcileAction(kind="delete", remote_id=rid) for rid in sorted(local - remote)]
        finally:
            try:
                c.logout()
            except Exception:
                pass

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=120, reason="imap default")
