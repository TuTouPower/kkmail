"""A117: IMAP login-phase failures must not leak the socket, and
``_close_client`` must fall back to closing the client/socket when
``logout()`` itself fails.
"""

from __future__ import annotations

import imaplib
from types import SimpleNamespace

import pytest

from mail_core.providers.imap import ImapProvider


class _FakeSock:
    def __init__(self):
        self.closed = False

    def getpeername(self):
        return ("8.8.8.8", 993)

    def close(self):
        self.closed = True


def _provider_with_fake_client(monkeypatch, login_exc):
    sock = _FakeSock()

    class FakeIMAP:
        def __init__(self, *a, **k):
            self.sock = sock

        def login(self, *a):
            raise login_exc

    monkeypatch.setattr("mail_core.providers.imap.imaplib.IMAP4_SSL", FakeIMAP)
    provider = ImapProvider(host="h", port=993, username="u", password="p")
    return provider, sock


def test_connect_closes_socket_when_login_raises_oserror(monkeypatch):
    provider, sock = _provider_with_fake_client(monkeypatch, OSError("connection reset"))
    with pytest.raises(OSError, match="connection reset"):
        provider._connect()
    assert sock.closed is True


def test_connect_closes_socket_when_login_raises_imap_error(monkeypatch):
    provider, sock = _provider_with_fake_client(
        monkeypatch, imaplib.IMAP4.error("authentication failed")
    )
    with pytest.raises(imaplib.IMAP4.error):
        provider._connect()
    assert sock.closed is True


class _Permit:
    def __init__(self):
        self.released = False

    def release(self):
        self.released = True


def test_close_client_falls_back_to_close_and_socket_when_logout_fails():
    sock = _FakeSock()
    calls = {"close": False}

    class BadLogoutClient:
        def __init__(self):
            self.sock = sock

        def logout(self):
            raise OSError("logout blew up")

        def close(self):
            calls["close"] = True

    permit = _Permit()
    ImapProvider._close_client(BadLogoutClient(), permit)
    assert calls["close"] is True
    assert sock.closed is True
    assert permit.released is True


def test_close_client_still_releases_permit_and_closes_socket_when_close_also_fails():
    sock = _FakeSock()

    class WorseClient:
        def __init__(self):
            self.sock = sock

        def logout(self):
            raise OSError("logout blew up")

        def close(self):
            raise OSError("close blew up too")

    permit = _Permit()
    ImapProvider._close_client(WorseClient(), permit)
    assert sock.closed is True
    assert permit.released is True
