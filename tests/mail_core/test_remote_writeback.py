"""Provider writeback: Memory + IMAP shapes + Graph injectable transports."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from mail_core.providers.base import RemoteFolder, RemoteMessageMeta
from mail_core.providers.graph import GraphProvider
from mail_core.providers.imap import ImapProvider, format_imap_remote_id
from mail_core.providers.remote_writeback import normalize_op_type
from mail_core.providers.stub_memory import MemoryProvider


def _meta(rid: str, *, read: bool = False) -> RemoteMessageMeta:
    return RemoteMessageMeta(
        remote_id=rid,
        subject="s",
        from_address="a@b.c",
        from_name=None,
        sort_time=datetime.now(timezone.utc),
        is_read=read,
        has_attachments=False,
        uid=int(rid) if rid.isdigit() else None,
    )


def test_normalize_aliases():
    assert normalize_op_type("set_read") == "mark_read"
    assert normalize_op_type("flag") == "set_flag"
    assert normalize_op_type("delete") == "trash"


def test_memory_set_read_flag_move_trash():
    p = MemoryProvider(
        folders=[
            RemoteFolder("INBOX", "INBOX", "inbox"),
            RemoteFolder("Archive", "Archive", "archive"),
            RemoteFolder("Trash", "Trash", "trash"),
        ]
    )
    p.seed("INBOX", [_meta("1"), _meta("2"), _meta("3")])

    assert p.apply_remote_operation("set_read", {"remote_id": "1", "folder_remote_id": "INBOX", "is_read": True}).success
    assert p.messages["INBOX"][0].is_read is True

    assert p.apply_remote_operation("flag", {"remote_id": "2", "folder_remote_id": "INBOX", "is_flagged": True}).success
    assert "2" in p.flagged

    assert p.apply_remote_operation(
        "move",
        {"remote_id": "2", "folder_remote_id": "INBOX", "dest_folder_remote_id": "Archive"},
    ).success
    assert all(m.remote_id != "2" for m in p.messages["INBOX"])
    assert any(m.remote_id == "2" for m in p.messages["Archive"])

    assert p.apply_remote_operation("trash", {"remote_id": "3", "folder_remote_id": "INBOX"}).success
    assert any(m.remote_id == "3" for m in p.messages["Trash"])
    assert all(m.remote_id != "3" for m in p.messages["INBOX"])


def test_imap_writeback_uses_uid_store_and_move():
    calls: list[tuple] = []

    class FakeIMAP:
        # A368: the provider verifies UID existence and STORE results via
        # FETCH (FLAGS UID), so the fake keeps real flag state for UID 10.
        def __init__(self):
            self._flags: set[str] = set()

        def select(self, folder, readonly=False):
            calls.append(("select", folder))
            return ("OK", [b"1"])

        def uid(self, cmd, *args):
            calls.append(("uid", cmd, args))
            if cmd == "FETCH":
                flags = " ".join(sorted(self._flags))
                return ("OK", [f"1 (FLAGS ({flags}) UID 10)".encode()])
            if cmd == "STORE":
                flag = args[2].strip("()")
                if args[1] == "+FLAGS":
                    self._flags.add(flag)
                else:
                    self._flags.discard(flag)
                return ("OK", [b""])
            if cmd == "MOVE":
                return ("OK", [b""])
            return ("OK", [b""])

        def response(self, code):
            if code == "COPYUID":
                return ("COPYUID", [b"42 10 12"])
            return (code, None)

        def expunge(self):
            calls.append(("expunge",))
            return ("OK", [b""])

        def logout(self):
            calls.append(("logout",))
            return ("OK", [b""])

    provider = ImapProvider(host="127.0.0.1", port=1143, username="u", password="p", use_ssl=False)
    provider._connect = MagicMock(return_value=FakeIMAP())  # type: ignore[method-assign]

    r = provider.apply_remote_operation("mark_read", {"remote_id": "10", "folder_remote_id": "INBOX", "is_read": True})
    assert r.success
    assert ("uid", "STORE", ("10", "+FLAGS", r"(\Seen)")) in calls

    calls.clear()
    r = provider.apply_remote_operation("set_flag", {"remote_id": "10", "folder_remote_id": "INBOX", "is_flagged": True})
    assert r.success
    assert any(c[0] == "uid" and c[1] == "STORE" and r"(\Flagged)" in c[2] for c in calls)

    calls.clear()
    r = provider.apply_remote_operation(
        "move",
        {"remote_id": "10", "folder_remote_id": "INBOX", "dest_folder_remote_id": "Archive"},
    )
    assert r.success
    assert ("uid", "MOVE", ("10", "Archive")) in calls
    assert r.remote_state == {
        "folder_remote_id": "Archive",
        "remote_id": format_imap_remote_id("Archive", 42, 12),
        "uid": 12,
    }

    calls.clear()
    r = provider.apply_remote_operation("trash", {"remote_id": "10", "folder_remote_id": "INBOX", "trash_folder_remote_id": "Trash"})
    assert r.success
    assert ("uid", "MOVE", ("10", "Trash")) in calls
    assert r.remote_state == {
        "folder_remote_id": "Trash",
        "remote_id": format_imap_remote_id("Trash", 42, 12),
        "uid": 12,
    }


def test_imap_move_trash_refuse_unsafe_expunge():
    calls = []

    class FakeIMAPFailMove:
        def select(self, folder):
            calls.append(("select", folder))
            return ("OK", [b"1"])

        def uid(self, cmd, *args):
            calls.append(("uid", cmd, args))
            if cmd == "FETCH":
                # A368 existence check: UID 10 exists in this fake.
                return ("OK", [b"1 (FLAGS () UID 10)"])
            if cmd == "MOVE":
                return ("NO", [b"MOVE not supported"])
            return ("OK", [b""])

        def expunge(self):
            calls.append(("expunge",))
            return ("OK", [b""])

        def logout(self):
            calls.append(("logout",))
            return ("OK", [b""])

    provider = ImapProvider(host="127.0.0.1", port=1143, username="u", password="p", use_ssl=False)
    provider._connect = MagicMock(return_value=FakeIMAPFailMove())  # type: ignore[method-assign]

    # OP_MOVE fails without expunge/Deleted
    r_move = provider.apply_remote_operation(
        "move",
        {"remote_id": "10", "folder_remote_id": "INBOX", "dest_folder_remote_id": "Archive"},
    )
    assert not r_move.success
    assert "IMAP server does not support atomic MOVE/delete" in (r_move.error or "")
    assert not any(c[0] == "expunge" for c in calls)
    assert not any(c[0] == "uid" and c[1] == "STORE" for c in calls)

    calls.clear()
    # OP_TRASH fails without expunge/Deleted
    r_trash = provider.apply_remote_operation(
        "trash",
        {"remote_id": "10", "folder_remote_id": "INBOX", "trash_folder_remote_id": "Trash"},
    )
    assert not r_trash.success
    assert "IMAP server does not support atomic MOVE/delete" in (r_trash.error or "")
    assert not any(c[0] == "expunge" for c in calls)
    assert not any(c[0] == "uid" and c[1] == "STORE" for c in calls)


# 旧测试 test_graph_writeback_via_transport_mocks 已整体删除：
# t064 将 Graph 远程写回升级为 $batch 批量管道，单端点独立调用的旧契约已废弃。
# 现行 Graph 批量写回规范由 tests/mail_core/test_t064_batched_remote_writeback.py (AC-013) 权威覆盖。

