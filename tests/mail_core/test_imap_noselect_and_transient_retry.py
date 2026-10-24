"""Tests for IMAP \\Noselect mailbox filtering and Graph/HTTP transient retries."""

from __future__ import annotations

import io
import json
import ssl
import urllib.error
from unittest.mock import MagicMock, Mock, patch

import pytest

from mail_core.providers.base import RemoteFolder
from mail_core.providers.http import ProviderHttpError
from mail_core.providers.imap import ImapProvider
from mail_core.providers.oauth import urllib_json_request


# --- 1. IMAP \\Noselect and \\NonExistent filtering ---


def test_imap_list_folders_filters_noselect_and_nonexistent(monkeypatch):
    class FakeIMAPWithNoselect:
        def list(self):
            return "OK", [
                b'(\\HasNoChildren) "/" "INBOX"',
                '(\\HasChildren \\Noselect) "/" "其他文件夹"'.encode("utf-8"),
                b'(\\Noselect \\HasChildren) "/" "Other Folders"',
                b'(\\NonExistent) "/" "VirtualFolder"',
                b'(\\HasNoChildren \\Sent) "/" "Sent Messages"',
                '(\\HasNoChildren) "/" "其他文件夹/子文件夹"'.encode("utf-8"),
            ]

        def logout(self):
            return "OK", []

    prov = ImapProvider("imap.example.com", 993, "user", "pass", use_ssl=False)
    monkeypatch.setattr(prov, "_connect", lambda: FakeIMAPWithNoselect())
    folders = prov.list_folders()

    folder_names = [f.name for f in folders]
    remote_ids = [f.remote_id for f in folders]

    assert "INBOX" in folder_names
    assert "Sent Messages" in folder_names
    assert "其他文件夹/子文件夹" in folder_names

    # \\Noselect and \\NonExistent must be filtered out
    assert "其他文件夹" not in folder_names
    assert "Other Folders" not in folder_names
    assert "VirtualFolder" not in folder_names
    assert "其他文件夹" not in remote_ids
    assert "Other Folders" not in remote_ids
    assert "VirtualFolder" not in remote_ids


def test_imap_folder_catalog_keeps_noselect_parent_as_nonselectable_node(monkeypatch):
    class FakeIMAPFolderCatalog:
        def list(self):
            return "OK", [
                b'(\\HasNoChildren) "/" "INBOX"',
                '(\\Noselect \\HasChildren) "/" "其他文件夹"'.encode("utf-8"),
                '(\\HasNoChildren) "/" "其他文件夹/QQ邮件订阅"'.encode("utf-8"),
            ]

        def logout(self):
            return "OK", []

    provider = ImapProvider("imap.example.com", 993, "user", "pass", use_ssl=False)
    monkeypatch.setattr(provider, "_connect", lambda: FakeIMAPFolderCatalog())

    catalog = {folder.remote_id: folder for folder in provider.list_folder_catalog()}

    assert catalog["其他文件夹"].selectable is False
    assert catalog["其他文件夹/QQ邮件订阅"].selectable is True
    assert catalog["其他文件夹/QQ邮件订阅"].parent_remote_id == "其他文件夹"
    assert "其他文件夹" not in {folder.remote_id for folder in provider.list_folders()}


def test_imap_fetch_metadata_page_safe_on_noselect_mailbox(monkeypatch):
    class FakeIMAPNoselectSearchFail:
        def select(self, mailbox, readonly=True):
            return "OK", [b"0"]

        def status(self, mailbox, spec):
            return "NO", [b"status failed"]

        def uid(self, cmd, *args):
            if cmd == "SEARCH":
                return "NO", [b"UID SEARCH failed"]
            return "OK", []

        def list(self, ref, mailbox):
            return "OK", ['(\\Noselect) "/" "其他文件夹"'.encode("utf-8")]

        def logout(self):
            return "OK", []

    prov = ImapProvider("imap.example.com", 993, "user", "pass", use_ssl=False)
    monkeypatch.setattr(prov, "_connect", lambda: FakeIMAPNoselectSearchFail())

    page = prov.fetch_metadata_page("其他文件夹", None)
    assert page.items == []
    assert page.next_cursor is None
    assert page.exhausted is True


def test_imap_delta_changes_safe_on_noselect_mailbox(monkeypatch):
    class FakeIMAPNoselect:
        def __init__(self):
            self.list_calls = 0

        def select(self, mailbox, readonly=True):
            return "NO", [b"cannot select"]

        def list(self, ref, mailbox):
            self.list_calls += 1
            return "OK", [b'(\\Noselect) "/" "Other Folders"']

        def logout(self):
            return "OK", []

    client = FakeIMAPNoselect()
    provider = ImapProvider("imap.example.com", 993, "user", "pass", use_ssl=False)
    monkeypatch.setattr(provider, "_connect", lambda: client)
    cursor = {"uid_next": 25, "modseq": 4}

    page = provider.delta_changes("Other Folders", cursor)

    assert page.changes == ()
    assert page.next_cursor == cursor
    assert page.exhausted is True
    assert client.list_calls == 1


def test_imap_delta_changes_preserves_ordinary_select_errors(monkeypatch):
    class FakeIMAPSelectFail:
        def select(self, mailbox, readonly=True):
            return "NO", [b"temporary failure"]

        def list(self, ref, mailbox):
            return "OK", [b'(\\HasChildren) "/" "Other Folders"']

        def logout(self):
            return "OK", []

    provider = ImapProvider("imap.example.com", 993, "user", "pass", use_ssl=False)
    monkeypatch.setattr(provider, "_connect", lambda: FakeIMAPSelectFail())

    with pytest.raises(RuntimeError, match="select Other Folders failed"):
        provider.delta_changes("Other Folders", {"uid_next": 25})


# --- 2. HTTP 503 and TLS EOF / Network Disconnect Transient Retries ---


def test_urllib_json_request_retries_on_503_and_succeeds(monkeypatch):
    calls = []
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    class FakeHTTPResponse:
        def __init__(self, data_dict):
            self.data = json.dumps(data_dict).encode("utf-8")
            self.headers = {"Content-Type": "application/json"}

        def read(self):
            return self.data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeHTTP503Error(urllib.error.HTTPError):
        def __init__(self):
            fp = io.BytesIO(b'{"error": "service unavailable"}')
            super().__init__("https://graph.microsoft.com/v1.0/me", 503, "Service Unavailable", {"Retry-After": "2"}, fp)

    def fake_urlopen(req, timeout=60):
        calls.append(req)
        if len(calls) < 3:
            raise FakeHTTP503Error()
        return FakeHTTPResponse({"status": "ok"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    res = urllib_json_request("GET", "https://graph.microsoft.com/v1.0/me", _sleep_fn=fake_sleep)
    assert res == {"status": "ok"}
    assert len(calls) == 3
    assert len(sleeps) == 2
    assert sleeps[0] == 2.0
    assert sleeps[1] == 2.0


def test_urllib_json_request_retries_on_tls_eof_and_succeeds(monkeypatch):
    calls = []
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    class FakeHTTPResponse:
        def __init__(self, data_dict):
            self.data = json.dumps(data_dict).encode("utf-8")
            self.headers = {"Content-Type": "application/json"}

        def read(self):
            return self.data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def fake_urlopen(req, timeout=60):
        calls.append(req)
        if len(calls) == 1:
            raise urllib.error.URLError(ssl.SSLEOFError("EOF occurred in violation of protocol"))
        return FakeHTTPResponse({"status": "connected"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    res = urllib_json_request("GET", "https://graph.microsoft.com/v1.0/me", _sleep_fn=fake_sleep)
    assert res == {"status": "connected"}
    assert len(calls) == 2
    assert len(sleeps) == 1
    assert sleeps[0] >= 0.5


def test_urllib_json_request_raises_after_retry_exhausted(monkeypatch):
    calls = []
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)

    class FakeHTTP503Error(urllib.error.HTTPError):
        def __init__(self):
            fp = io.BytesIO(b'{"error": "service unavailable"}')
            super().__init__("https://graph.microsoft.com/v1.0/me", 503, "Service Unavailable", {}, fp)

    def fake_urlopen(req, timeout=60):
        calls.append(req)
        raise FakeHTTP503Error()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(ProviderHttpError) as exc_info:
        urllib_json_request("GET", "https://graph.microsoft.com/v1.0/me", _sleep_fn=fake_sleep)

    assert exc_info.value.status == 503
    # Initial + 3 retries = 4 calls total
    assert len(calls) == 4
    assert len(sleeps) == 3
