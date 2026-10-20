"""IMAP provider adapter (UID + optional CONDSTORE/MODSEQ).

Never infers deletions from an incomplete UID scan (architecture §6.2).
"""

from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import re
import ssl
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
            try:
                out.append(chunk.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                out.append(chunk.decode("utf-8", errors="replace"))
        else:
            out.append(str(chunk))
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


def _get_server_uidvalidity(c: imaplib.IMAP4, folder: str) -> int | None:
    if not hasattr(c, "status"):
        return None
    try:
        status = c.status(folder, "(UIDVALIDITY)")
        if status[0] == "OK" and status[1] and status[1][0]:
            blob = status[1][0].decode() if isinstance(status[1][0], bytes) else str(status[1][0])
            m = re.search(r"UIDVALIDITY\s+(\d+)", blob)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None

@dataclass
class ImapProvider:
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    use_ssl: bool = True
    timeout: float = 30.0

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
        client.login(self.username, self.password)
        return client

    def list_folders(self) -> Sequence[RemoteFolder]:
        c = self._connect()
        try:
            typ, data = c.list()
            if typ != "OK":
                raise RuntimeError(f"IMAP LIST failed: {typ}")
            if not data:
                return [RemoteFolder("INBOX", "INBOX", "inbox")]
            folders: list[RemoteFolder] = []
            for raw in data:
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
                m = re.search(r' "?"?([^"]+)"?\s*$', line)
                name = m.group(1).strip() if m else line.rsplit(" ", 1)[-1].strip('"')
                if name.upper() == "INBOX":
                    role = "inbox"
                else:
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
            batch_size = int((cursor or {}).get("page_size") or 50)
            batch: list[int] = []
            has_more = False
            for chunk in (data or ()):
                if not chunk:
                    continue
                raw_chunk = chunk if isinstance(chunk, bytes) else str(chunk).encode()
                for m in re.finditer(rb"\d+", raw_chunk):
                    val = int(m.group(0))
                    if val < start:
                        continue
                    if len(batch) < batch_size:
                        batch.append(val)
                    else:
                        has_more = True
                        break
                if has_more:
                    break
            items: list[RemoteMessageMeta] = []
            for uid in batch:
                typ, fetched = c.uid(
                    "FETCH",
                    str(uid),
                    "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES)])",
                )
                if typ != "OK" or not fetched or fetched[0] is None:
                    # Do not advance uid_next past a failed FETCH — raise so the
                    # caller retries from the same cursor (architecture: no silent skip).
                    raise RuntimeError(f"UID FETCH {folder_remote_id} uid={uid} failed: {typ}")
                flags_blob = fetched[0]
                if isinstance(flags_blob, tuple):
                    meta_bytes = flags_blob[0]
                    header_bytes = flags_blob[1] if len(flags_blob) > 1 else b""
                else:
                    raise RuntimeError(
                        f"UID FETCH {folder_remote_id} uid={uid}: unexpected payload shape"
                    )
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
                        in_reply_to=headers.get("In-Reply-To"),
                        references=headers.get("References"),
                    )
                )
            if not batch:
                return MetadataPage(
                    items=(),
                    next_cursor={"uid_next": start, "uidvalidity": uidvalidity},
                    exhausted=True,
                )
            next_uid = batch[-1] + 1
            exhausted = not has_more
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
            _uv = None
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
        finally:
            try:
                c.logout()
            except Exception:
                pass

    def _fetch_flags_for_uids(
        self,
        c: imaplib.IMAP4,
        folder_remote_id: str,
        uidvalidity: int,
        uids: list[int],
    ) -> list[DeltaChange]:
        """FETCH FLAGS for MODSEQ-changed UIDs and emit flag deltas (not discarded)."""
        changes: list[DeltaChange] = []
        for uid in uids:
            typ, fetched = c.uid("FETCH", str(uid), "(FLAGS)")
            if typ != "OK" or not fetched or fetched[0] is None:
                continue
            blob = fetched[0]
            meta_bytes = blob[0] if isinstance(blob, tuple) else blob
            meta_s = meta_bytes.decode("utf-8", errors="replace") if isinstance(meta_bytes, bytes) else str(meta_bytes)
            is_read = "\\Seen" in meta_s
            is_flagged = "\\Flagged" in meta_s
            rid = format_imap_remote_id(folder_remote_id, int(uidvalidity), uid)
            changes.append(
                DeltaChange(
                    kind="flag",
                    remote_id=rid,
                    flags={"is_read": is_read, "is_flagged": is_flagged},
                )
            )
        return changes

    def delta_changes(self, folder_remote_id: str, cursor: dict[str, Any]) -> DeltaPage:
        """Incremental sync.

        Prefer CONDSTORE/MODSEQ when the server advertises it; emit explicit flag
        changes for MODSEQ hits. Also page new UIDs since ``uid_next``. Deletions
        are *not* inferred here — use reconcile after a complete scan.
        """
        c = self._connect()
        try:
            typ, _ = c.select(folder_remote_id, readonly=True)
            if typ != "OK":
                raise RuntimeError(f"select {folder_remote_id} failed")
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
            uv = int(uidvalidity) if uidvalidity is not None else 0

            changes: list[DeltaChange] = []
            since_modseq = cursor.get("modseq")
            if highest is not None and since_modseq is not None:
                try:
                    typ, data = c.uid("SEARCH", None, "MODSEQ", str(int(since_modseq) + 1))
                    if typ == "OK":
                        changed_uids = [int(x) for x in (data[0] or b"").split() if x]
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
                                self._fetch_flags_for_uids(c, folder_remote_id, uv, batch_flag_uids)
                            )

                        next_cursor = dict(cursor)
                        if uidvalidity is not None:
                            next_cursor["uidvalidity"] = uidvalidity

                        has_more_new = False
                        if new_uids:
                            # Page via temporary cursor starting at the lowest new UID.
                            batch_size = min(50, len(new_uids))
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
                except Exception:
                    pass

            # UID-based incremental (always safe): fetch metadata since uid_next.
            page = self.fetch_metadata_page(folder_remote_id, cursor)
            changes = [DeltaChange(kind="upsert", remote_id=m.remote_id, meta=m) for m in page.items]
            next_cursor = dict(page.next_cursor or {})
            if highest is not None and page.exhausted:
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
                dest = str(desired_state.get("dest_folder_remote_id") or desired_state.get("to_folder") or "")
                if not dest:
                    return RemoteOperationResult(success=False, error="missing dest_folder_remote_id")
                # Prefer UID MOVE (RFC 6851); never STORE \Deleted or expunge entire mailbox
                typ, _ = c.uid("MOVE", uid_str, dest)
                if typ != "OK":
                    return RemoteOperationResult(
                        success=False,
                        error="IMAP server does not support atomic MOVE/delete",
                    )
                return RemoteOperationResult(success=True, remote_state={"folder_remote_id": dest})

            if op == OP_TRASH:
                trash = str(desired_state.get("trash_folder_remote_id") or "Trash")
                # Try move into trash mailbox first; never STORE \Deleted or expunge entire mailbox
                typ, _ = c.uid("MOVE", uid_str, trash)
                if typ != "OK":
                    return RemoteOperationResult(
                        success=False,
                        error="IMAP server does not support atomic MOVE/delete",
                    )
                return RemoteOperationResult(success=True, remote_state={"folder_remote_id": trash})

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
