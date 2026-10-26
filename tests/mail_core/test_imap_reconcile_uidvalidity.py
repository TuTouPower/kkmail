"""B1 regression: IMAP reconcile must abort when UIDVALIDITY cannot be verified.

Previously a failed STATUS (UIDVALIDITY) silently left uidvalidity=0, so every
remote key was built with uv=0, the local-remote diff covered the whole folder,
and reconcile produced delete actions for all local mail in that folder.
"""

from __future__ import annotations

import pytest

from mail_core.providers.imap import ImapProvider, format_imap_remote_id


class _FakeImapClient:
    def __init__(self, status_result, search_uids=b"1 2"):
        self._status_result = status_result
        self._search_uids = search_uids

    def select(self, mailbox, readonly=False):
        return "OK", [b"2"]

    def status(self, mailbox, items):
        return self._status_result

    def uid(self, command, charset, criteria):
        assert command == "SEARCH"
        return "OK", [self._search_uids]

    def logout(self):
        return "BYE", [b"bye"]


def _provider_with_client(client) -> ImapProvider:
    provider = ImapProvider(host="imap.example.com", port=993, username="u", password="p")
    provider._connect_with_permit = lambda: (client, None)  # test seam: no network
    return provider


def test_reconcile_aborts_when_status_fails():
    client = _FakeImapClient(("NO", [b"status unavailable"]))
    provider = _provider_with_client(client)
    locals_ = [format_imap_remote_id("INBOX", 777, 1), format_imap_remote_id("INBOX", 777, 2)]
    with pytest.raises(RuntimeError, match="UIDVALIDITY"):
        provider.reconcile("INBOX", locals_)


def test_reconcile_aborts_when_status_blob_lacks_uidvalidity():
    client = _FakeImapClient(("OK", [b"INBOX (MESSAGES 2)"]))
    provider = _provider_with_client(client)
    locals_ = [format_imap_remote_id("INBOX", 777, 1)]
    with pytest.raises(RuntimeError, match="UIDVALIDITY"):
        provider.reconcile("INBOX", locals_)


def test_reconcile_with_verified_uidvalidity_still_diffs():
    client = _FakeImapClient(("OK", [b"INBOX (UIDVALIDITY 777 MESSAGES 2)"]))
    provider = _provider_with_client(client)
    locals_ = [
        format_imap_remote_id("INBOX", 777, 1),
        format_imap_remote_id("INBOX", 777, 2),
        format_imap_remote_id("INBOX", 777, 3),
    ]
    actions = provider.reconcile("INBOX", locals_)
    assert [(a.kind, a.remote_id) for a in actions] == [
        ("delete", format_imap_remote_id("INBOX", 777, 3))
    ]
