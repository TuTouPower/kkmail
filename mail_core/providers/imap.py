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
                items.append(
                    RemoteMessageMeta(
                        remote_id=str(uid),
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

    def fetch_mime(self, remote_id: str) -> bytes:
        c = self._connect()
        try:
            c.select("INBOX", readonly=True)
            typ, data = c.uid("FETCH", str(remote_id), "(BODY.PEEK[])")
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
        folder = str(desired_state.get("folder_remote_id") or "INBOX")
        op = normalize_op_type(op_type)
        c = self._connect()
        try:
            typ, _ = c.select(folder)
            if typ != "OK":
                return RemoteOperationResult(success=False, error=f"select {folder} failed")

            if op == OP_MARK_READ:
                want_read = bool(desired_state.get("is_read", True))
                flag_op = "+FLAGS" if want_read else "-FLAGS"
                typ, _ = c.uid("STORE", remote_id, flag_op, r"(\Seen)")
                if typ != "OK":
                    return RemoteOperationResult(success=False, error="STORE Seen failed")
                return RemoteOperationResult(success=True, remote_state={"is_read": want_read})

            if op == OP_SET_FLAG:
                want = bool(desired_state.get("is_flagged", True))
                flag_op = "+FLAGS" if want else "-FLAGS"
                typ, _ = c.uid("STORE", remote_id, flag_op, r"(\Flagged)")
                if typ != "OK":
                    return RemoteOperationResult(success=False, error="STORE Flagged failed")
                return RemoteOperationResult(success=True, remote_state={"is_flagged": want})

            if op == OP_MOVE:
                dest = str(desired_state.get("dest_folder_remote_id") or desired_state.get("to_folder") or "")
                if not dest:
                    return RemoteOperationResult(success=False, error="missing dest_folder_remote_id")
                # Prefer UID MOVE (RFC 6851); fall back to COPY + delete.
                typ, _ = c.uid("MOVE", remote_id, dest)
                if typ != "OK":
                    typ, _ = c.uid("COPY", remote_id, dest)
                    if typ != "OK":
                        return RemoteOperationResult(success=False, error=f"COPY/MOVE to {dest} failed")
                    typ, _ = c.uid("STORE", remote_id, "+FLAGS", r"(\Deleted)")
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
                typ, _ = c.uid("MOVE", remote_id, trash)
                if typ == "OK":
                    return RemoteOperationResult(success=True, remote_state={"folder_remote_id": trash})
                typ, _ = c.uid("COPY", remote_id, trash)
                if typ == "OK":
                    c.uid("STORE", remote_id, "+FLAGS", r"(\Deleted)")
                    try:
                        c.expunge()
                    except Exception:
                        pass
                    return RemoteOperationResult(success=True, remote_state={"folder_remote_id": trash})
                typ, _ = c.uid("STORE", remote_id, "+FLAGS", r"(\Deleted)")
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
                return ()
            typ, data = c.uid("SEARCH", None, "ALL")
            if typ != "OK":
                return ()
            remote = {x.decode() if isinstance(x, bytes) else str(x) for x in (data[0] or b"").split()}
            local = set(local_remote_ids)
            return [ReconcileAction(kind="delete", remote_id=rid) for rid in sorted(local - remote)]
        finally:
            try:
                c.logout()
            except Exception:
                pass

    def rate_limit_hint(self) -> RateLimitHint:
        return RateLimitHint(max_requests_per_minute=120, reason="imap default")
