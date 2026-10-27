"""A368: UID STORE/MOVE on a nonexistent UID must not report success.

Many IMAP servers answer ``UID STORE`` (and some answer ``UID MOVE``)
for an already-expunged UID with ``OK`` and no effect. Pre-fix,
``apply_remote_operation`` trusted only the STORE/MOVE status, claimed
``remote_state`` reflected the change, and the remote-push layer marked
the operation DONE — local intent and remote reality diverged silently.

The fake below models that silent-OK server: STORE/MOVE return OK for
any UID, existing or not. Only a FETCH of the UID reveals the truth.
"""

from __future__ import annotations

from mail_core.providers.imap import ImapProvider


class _SilentOkClient:
    """IMAP fake whose STORE/MOVE return OK even for missing UIDs."""

    def __init__(self, existing: dict[int, set[str]] | None = None, *, store_lies: bool = False):
        # uid -> set of flag names (without backslash), e.g. {"Seen"}
        self.existing = {uid: set(flags) for uid, flags in (existing or {}).items()}
        self.store_lies = store_lies
        self.calls: list[tuple] = []

    def select(self, mailbox, readonly=False):
        return "OK", [b"1"]

    def status(self, mailbox, items):
        return "OK", [b"INBOX (UIDVALIDITY 42)"]

    def logout(self):
        return "BYE", [b"bye"]

    def _flags_blob(self, uid: int) -> bytes:
        flags = " ".join(f"\\{name}" for name in sorted(self.existing[uid]))
        return f"1 (FLAGS ({flags}) UID {uid})".encode()

    def uid(self, command, *args):
        self.calls.append((command, args))
        if command == "FETCH":
            uid = int(args[0])
            if uid not in self.existing:
                return "OK", [None]
            return "OK", [self._flags_blob(uid)]
        if command == "STORE":
            uid = int(args[0])
            if uid in self.existing and not self.store_lies:
                flag = args[2].strip("()").lstrip("\\")
                if args[1] == "+FLAGS":
                    self.existing[uid].add(flag)
                else:
                    self.existing[uid].discard(flag)
            # Silent OK even when the UID does not exist (the A368 bug).
            return "OK", [b""]
        if command == "MOVE":
            uid = int(args[0])
            self.existing.pop(uid, None)
            return "OK", [b""]
        return "NO", []


def _provider(client: _SilentOkClient) -> ImapProvider:
    provider = ImapProvider(host="h", port=993, username="u", password="p")
    provider._connect_with_permit = lambda: (client, None)
    return provider


def test_mark_read_missing_uid_fails_and_never_stores():
    client = _SilentOkClient(existing={10: set()})
    result = _provider(client).apply_remote_operation(
        "mark_read", {"remote_id": "999", "folder_remote_id": "INBOX", "is_read": True}
    )
    assert result.success is False
    assert "999" in (result.error or "")
    assert not any(cmd == "STORE" for cmd, _ in client.calls)


def test_set_flag_missing_uid_fails_and_never_stores():
    client = _SilentOkClient(existing={10: set()})
    result = _provider(client).apply_remote_operation(
        "set_flag", {"remote_id": "999", "folder_remote_id": "INBOX", "is_flagged": True}
    )
    assert result.success is False
    assert "999" in (result.error or "")
    assert not any(cmd == "STORE" for cmd, _ in client.calls)


def test_move_missing_uid_fails_and_never_moves():
    client = _SilentOkClient(existing={10: set()})
    result = _provider(client).apply_remote_operation(
        "move", {"remote_id": "999", "folder_remote_id": "INBOX", "dest_folder_remote_id": "Archive"}
    )
    assert result.success is False
    assert "999" in (result.error or "")
    assert not any(cmd == "MOVE" for cmd, _ in client.calls)


def test_trash_missing_uid_fails_and_never_moves():
    client = _SilentOkClient(existing={10: set()})
    result = _provider(client).apply_remote_operation(
        "trash", {"remote_id": "999", "folder_remote_id": "INBOX", "trash_folder_remote_id": "Trash"}
    )
    assert result.success is False
    assert "999" in (result.error or "")
    assert not any(cmd == "MOVE" for cmd, _ in client.calls)


def test_mark_read_existing_uid_succeeds_with_verified_flag():
    client = _SilentOkClient(existing={10: set()})
    result = _provider(client).apply_remote_operation(
        "mark_read", {"remote_id": "10", "folder_remote_id": "INBOX", "is_read": True}
    )
    assert result.success is True
    assert result.remote_state == {"is_read": True}
    assert client.existing[10] == {"Seen"}


def test_mark_unread_existing_uid_succeeds_with_verified_flag():
    client = _SilentOkClient(existing={10: {"Seen"}})
    result = _provider(client).apply_remote_operation(
        "mark_read", {"remote_id": "10", "folder_remote_id": "INBOX", "is_read": False}
    )
    assert result.success is True
    assert result.remote_state == {"is_read": False}
    assert client.existing[10] == set()


def test_set_flag_existing_uid_succeeds_with_verified_flag():
    client = _SilentOkClient(existing={10: set()})
    result = _provider(client).apply_remote_operation(
        "set_flag", {"remote_id": "10", "folder_remote_id": "INBOX", "is_flagged": True}
    )
    assert result.success is True
    assert result.remote_state == {"is_flagged": True}
    assert client.existing[10] == {"Flagged"}


def test_store_ok_but_flag_not_applied_fails_verification():
    # Server answers OK to STORE but the flag never changes (read-back
    # via FETCH is the success criterion, not the STORE status alone).
    client = _SilentOkClient(existing={10: set()}, store_lies=True)
    result = _provider(client).apply_remote_operation(
        "mark_read", {"remote_id": "10", "folder_remote_id": "INBOX", "is_read": True}
    )
    assert result.success is False
    assert "verified" in (result.error or "")


def test_move_existing_uid_succeeds():
    client = _SilentOkClient(existing={10: set()})
    result = _provider(client).apply_remote_operation(
        "move", {"remote_id": "10", "folder_remote_id": "INBOX", "dest_folder_remote_id": "Archive"}
    )
    assert result.success is True
    assert result.remote_state is not None
    assert result.remote_state.get("folder_remote_id") == "Archive"
    assert 10 not in client.existing
