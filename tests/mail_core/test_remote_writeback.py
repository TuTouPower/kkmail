"""Provider writeback: Memory + IMAP shapes + Gmail/Graph injectable transports."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from mail_core.providers.base import RemoteFolder, RemoteMessageMeta
from mail_core.providers.gmail import GmailProvider
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
        def select(self, folder, readonly=False):
            calls.append(("select", folder))
            return ("OK", [b"1"])

        def uid(self, cmd, *args):
            calls.append(("uid", cmd, args))
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


def test_gmail_writeback_via_transport_mocks():
    seen: list[tuple] = []

    def transport(method, path, params):
        seen.append((method, path, dict(params or {})))
        if path.endswith("/modify"):
            return {"id": "m1", "labelIds": ["INBOX", "STARRED"]}
        if path.endswith("/trash"):
            return {"id": "m1", "labelIds": ["TRASH"]}
        return {"success": True}

    p = GmailProvider(credential_ref="x", transport=transport)
    assert p.apply_remote_operation("set_read", {"remote_id": "m1", "is_read": True}).success
    assert seen[0][0] == "POST" and seen[0][1].endswith("/messages/m1/modify")
    assert seen[0][2].get("removeLabelIds") == ["UNREAD"]

    seen.clear()
    assert p.apply_remote_operation("flag", {"remote_id": "m1", "is_flagged": True}).success
    assert seen[0][2].get("addLabelIds") == ["STARRED"]

    seen.clear()
    assert p.apply_remote_operation(
        "move",
        {"remote_id": "m1", "folder_remote_id": "INBOX", "dest_folder_remote_id": "Label_2"},
    ).success
    assert seen[0][2]["addLabelIds"] == ["Label_2"]
    assert seen[0][2]["removeLabelIds"] == ["INBOX"]

    seen.clear()
    assert p.apply_remote_operation("trash", {"remote_id": "m1"}).success
    assert seen[0][1].endswith("/messages/m1/trash")


def test_graph_writeback_via_transport_mocks():
    seen: list[tuple] = []

    def transport(method, path, params):
        seen.append((method, path, dict(params or {})))
        if method == "PATCH":
            return {"id": "g1", "isRead": params.get("isRead"), "flag": params.get("flag")}
        if path.endswith("/move"):
            return {"id": "g2", "parentFolderId": params.get("destinationId")}
        if method == "DELETE":
            return {}
        return {"success": True}

    p = GraphProvider(credential_ref="x", transport=transport)
    assert p.apply_remote_operation("mark_read", {"remote_id": "g1", "is_read": False}).success
    assert seen[0][0] == "PATCH" and seen[0][2]["isRead"] is False

    seen.clear()
    assert p.apply_remote_operation("set_flag", {"remote_id": "g1", "is_flagged": True}).success
    assert seen[0][2]["flag"]["flagStatus"] == "flagged"

    seen.clear()
    moved = p.apply_remote_operation(
        "move",
        {"remote_id": "g1", "dest_folder_remote_id": "archive-id"},
    )
    assert moved.success
    assert seen[0][0] == "POST" and seen[0][1].endswith("/move")
    assert moved.remote_state == {"folder_remote_id": "archive-id", "id": "g2"}

    seen.clear()
    trashed = p.apply_remote_operation("trash", {"remote_id": "g1"})
    assert trashed.success
    assert seen[0][1].endswith("/move")
    assert trashed.remote_state == {"folder_remote_id": "deleteditems", "id": "g2"}
