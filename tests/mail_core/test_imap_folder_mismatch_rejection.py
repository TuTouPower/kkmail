"""A185: an explicit folder that contradicts the folder embedded in a
namespaced remote_id must be rejected.

Pre-fix, ``fetch_mime`` preferred the external folder while still using the
UID/UIDVALIDITY from the remote_id, and ``apply_remote_operation`` did the
same — with equal UIDVALIDITY across folders (common) the wrong mailbox's
message was fetched or mutated.
"""

from __future__ import annotations

import pytest

from mail_core.providers.imap import ImapProvider, format_imap_remote_id

_UV = 42
_RID = format_imap_remote_id("INBOX", _UV, 7)


class _FakeClient:
    def __init__(self):
        self.selected = None

    def select(self, mailbox, readonly=False):
        self.selected = mailbox
        return "OK", [b"1"]

    def status(self, mailbox, items):
        return "OK", [f"INBOX (UIDVALIDITY {_UV})".encode()]

    def uid(self, command, *args):
        if command == "FETCH":
            # A368: apply_remote_operation verifies via FETCH (FLAGS UID);
            # fetch_mime asks for BODY.PEEK[] and needs the mime payload.
            if args and "FLAGS" in str(args[-1]):
                return "OK", [b"7 (FLAGS (\\Seen) UID 7)"]
            return "OK", [(b"7 (UID 7)", b"mime-bytes")]
        if command == "STORE":
            return "OK", [b""]
        return "NO", []

    def logout(self):
        return "BYE", [b"bye"]


def _provider(client=None) -> ImapProvider:
    provider = ImapProvider(host="h", port=993, username="u", password="p")
    provider._connect_with_permit = lambda: (client or _FakeClient(), None)
    return provider


def _provider_no_connect() -> ImapProvider:
    provider = ImapProvider(host="h", port=993, username="u", password="p")

    def _boom():
        raise AssertionError("must reject before connecting")

    provider._connect_with_permit = _boom
    return provider


def test_fetch_mime_rejects_folder_contradicting_remote_id():
    provider = _provider_no_connect()
    with pytest.raises(ValueError, match="folder"):
        provider.fetch_mime(_RID, folder_remote_id="Sent")


def test_fetch_mime_accepts_matching_folder():
    client = _FakeClient()
    provider = _provider(client)
    assert provider.fetch_mime(_RID, folder_remote_id="INBOX") == b"mime-bytes"
    assert client.selected == "INBOX"


def test_apply_rejects_folder_contradicting_remote_id():
    provider = _provider_no_connect()
    result = provider.apply_remote_operation(
        "mark_read",
        {"remote_id": _RID, "folder_remote_id": "Sent", "is_read": True},
    )
    assert result.success is False
    assert "folder" in (result.error or "")


def test_apply_accepts_matching_folder():
    provider = _provider()
    result = provider.apply_remote_operation(
        "mark_read",
        {"remote_id": _RID, "folder_remote_id": "INBOX", "is_read": True},
    )
    assert result.success is True
