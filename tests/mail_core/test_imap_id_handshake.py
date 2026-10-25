from __future__ import annotations

import imaplib
import logging
import os
import uuid
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy import select

from mail_core.mail.application.accounts import create_account_app
from mail_core.mail.domain.enums import JobType
from mail_core.mail.storage.models import WorkerJob
from mail_core.providers.imap import ImapProvider


def test_initial_sync_enqueue_failure_is_safely_logged(monkeypatch, caplog):
    import mail_core.mail.application.accounts as accounts_app

    account_id = uuid.uuid4()
    monkeypatch.setattr(
        accounts_app,
        "enqueue_account_sync",
        Mock(side_effect=RuntimeError("password=private-secret")),
    )

    with caplog.at_level(logging.WARNING, logger="mail_core.mail.application.accounts"):
        accounts_app._enqueue_initial_sync(None, account_id)

    assert str(account_id) in caplog.text
    assert "initial sync enqueue failed" in caplog.text
    assert "password=[REDACTED]" in caplog.text
    assert "private-secret" not in caplog.text


def test_imap_connect_sends_id_command():
    """AC-003: ImapProvider._connect must issue RFC 2971 ID command on connection."""
    provider = ImapProvider(
        host="imap.example.com",
        port=993,
        username="user@example.com",
        password="secretpassword",
        use_ssl=True,
    )

    mock_client = MagicMock(spec=imaplib.IMAP4_SSL)
    mock_client.sock = Mock()
    mock_client.sock.getpeername.return_value = ("8.8.8.8", 993)
    mock_client.login.return_value = ("OK", [b"LOGIN completed"])
    mock_client._simple_command.return_value = ("OK", [b"ID completed"])

    with patch("imaplib.IMAP4_SSL", return_value=mock_client):
        client = provider._connect()

    assert client is mock_client
    mock_client.login.assert_called_once_with("user@example.com", "secretpassword")
    # Use the public ID method when the Python runtime provides it; otherwise
    # retain the legacy private-command fallback.
    if callable(getattr(mock_client, "id", None)):
        mock_client.id.assert_called_once_with(
            {"name": "kkmail", "version": "3.0.20", "vendor": "kkmail"}
        )
    else:
        mock_client._simple_command.assert_called_once()
        args, _ = mock_client._simple_command.call_args
        assert args[0] == "ID"
        assert "kkmail" in args[1]


def test_imap_connect_tolerates_missing_id_support():
    """AC-004: When server does not support ID command, _connect gracefully ignores it."""
    provider = ImapProvider(
        host="imap.example.com",
        port=993,
        username="user@example.com",
        password="secretpassword",
        use_ssl=True,
    )

    mock_client = MagicMock(spec=imaplib.IMAP4_SSL)
    mock_client.sock = Mock()
    mock_client.sock.getpeername.return_value = ("8.8.8.8", 993)
    mock_client.login.return_value = ("OK", [b"LOGIN completed"])
    if callable(getattr(mock_client, "id", None)):
        mock_client.id.side_effect = imaplib.IMAP4.error("BAD command unknown: ID")
    else:
        mock_client._simple_command.side_effect = imaplib.IMAP4.error("BAD command unknown: ID")

    with patch("imaplib.IMAP4_SSL", return_value=mock_client):
        client = provider._connect()

    # Connection must succeed despite ID error
    assert client is mock_client



def test_imap_id_helper_prefers_public_method_when_available():
    from types import SimpleNamespace

    from mail_core.providers.imap import _send_imap_id

    public_method = Mock(return_value=("OK", [b"ID completed"]))
    private_method = Mock()
    client = SimpleNamespace(id=public_method, _simple_command=private_method)

    _send_imap_id(client)

    public_method.assert_called_once_with({"name": "kkmail", "version": "3.0.20", "vendor": "kkmail"})
    private_method.assert_not_called()


def test_imap_id_command_is_registered_at_module_import():
    assert imaplib.Commands["ID"] == ("AUTH", "SELECTED")

def test_imap_connect_rejects_private_peer_before_login(monkeypatch):
    monkeypatch.delenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", raising=False)
    provider = ImapProvider(
        host="imap.example.com",
        port=993,
        username="user@example.com",
        password="secretpassword",
        use_ssl=True,
    )
    mock_client = MagicMock(spec=imaplib.IMAP4_SSL)
    mock_client.sock = Mock()
    mock_client.sock.getpeername.return_value = ("10.0.0.8", 993)

    with patch("imaplib.IMAP4_SSL", return_value=mock_client):
        with pytest.raises(ValueError, match="SSRF protection"):
            provider._connect()

    mock_client.login.assert_not_called()
    mock_client.sock.close.assert_called_once()


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_create_account_app_enqueues_initial_sync():
    """AC-002: create_account_app must automatically enqueue SYNC_ACCOUNT_FOLDERS job."""
    from mail_core.db.session import get_session_factory

    email_addr = f"auto-sync-{uuid.uuid4().hex[:8]}@example.com"
    dto = create_account_app(
        email=email_addr,
        provider="imap",
        display_name="Auto Sync Test",
        config={"imap_host": "imap.example.com", "imap_port": 993, "use_ssl": True},
        credentials={"password": "pwd"},
    )
    assert dto.id is not None

    Session = get_session_factory()
    with Session() as session:
        job = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == uuid.UUID(dto.id),
                WorkerJob.job_type == JobType.SYNC_ACCOUNT_FOLDERS.value,
            )
        )
        assert job is not None
        assert job.status in ("pending", "claimed", "done")


def test_imap_connect_netease_login_error_raises_permanent_auth_error():
    """AC-003: NetEase 126/163 Login error or password error must raise PermanentAuthError."""
    from mail_core.providers.http import PermanentAuthError

    provider = ImapProvider(
        host="imap.126.com",
        port=993,
        username="user@126.com",
        password="badpassword",
        use_ssl=True,
    )

    mock_client = MagicMock(spec=imaplib.IMAP4_SSL)
    mock_client.sock = Mock()
    mock_client.sock.getpeername.return_value = ("8.8.8.8", 993)
    mock_client.login.side_effect = imaplib.IMAP4.error("LOGIN Login error or password error")

    with patch("imaplib.IMAP4_SSL", return_value=mock_client):
        with pytest.raises(PermanentAuthError, match="IMAP authentication rejected permanently"):
            provider._connect()
