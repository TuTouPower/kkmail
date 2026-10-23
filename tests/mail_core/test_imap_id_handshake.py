from __future__ import annotations

import imaplib
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from mail_core.mail.application.accounts import create_account_app
from mail_core.mail.domain.enums import JobType
from mail_core.mail.storage.models import WorkerJob
from mail_core.providers.imap import ImapProvider


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
    mock_client.login.return_value = ("OK", [b"LOGIN completed"])
    mock_client._simple_command.return_value = ("OK", [b"ID completed"])

    with patch("imaplib.IMAP4_SSL", return_value=mock_client):
        client = provider._connect()

    assert client is mock_client
    mock_client.login.assert_called_once_with("user@example.com", "secretpassword")
    # Verify ID command was issued
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
    mock_client.login.return_value = ("OK", [b"LOGIN completed"])
    mock_client._simple_command.side_effect = imaplib.IMAP4.error("BAD command unknown: ID")

    with patch("imaplib.IMAP4_SSL", return_value=mock_client):
        client = provider._connect()

    # Connection must succeed despite ID error
    assert client is mock_client


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
    mock_client.login.side_effect = imaplib.IMAP4.error("LOGIN Login error or password error")

    with patch("imaplib.IMAP4_SSL", return_value=mock_client):
        with pytest.raises(PermanentAuthError, match="IMAP authentication rejected permanently"):
            provider._connect()
