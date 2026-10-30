"""Tests for remote image allowlists service and email normalization (t066)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.application.remote_images import (
    InvalidSenderEmailError,
    allow_message_remote_images,
    allow_sender_remote_images,
    is_remote_images_allowed,
    list_allowed_senders,
    normalize_sender_email,
    remove_allowed_sender,
)
from mail_core.mail.storage.models import (
    Account,
    Message,
    MessageRemoteImageAllow,
    SenderRemoteImageAllow,
)


def test_normalize_sender_email_valid():
    assert normalize_sender_email("user@example.com") == "user@example.com"
    assert normalize_sender_email("  User.Name+Tag@Sub.EXAMPLE.COM  ") == "user.name+tag@sub.example.com"
    assert normalize_sender_email("customer_service@company.co.uk") == "customer_service@company.co.uk"


def test_normalize_sender_email_invalid():
    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("")

    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("   ")

    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email(None)

    # Control characters and CRLF (including leading and trailing)
    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("user@example.com\r\ninjected: header")

    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("\r\nuser@example.com\r\n")

    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("user\0@example.com")

    # Dot syntax defects
    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email(".user@example.com")

    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("user..name@example.com")

    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("user@.domain.com")

    # Exceeding 320 chars
    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("a" * 315 + "@example.com")

    # Multi-address
    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("a@b.com, c@d.com")

    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("a@b.com; c@d.com")

    # Unparsed display name
    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("Alice <alice@example.com>")

    # Missing domain or user
    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("plainaddress")

    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("@nodomain.com")

    with pytest.raises(InvalidSenderEmailError):
        normalize_sender_email("user@")


# --- DB Integrated tests ---

_db_required = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_message(from_address: str = "newsletter@source.com") -> uuid.UUID:
    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            email=f"account-{uuid.uuid4().hex[:8]}@test.local",
            provider="stub",
            credential_ref="cred_ref",
        )
        session.add(acc)
        session.flush()

        msg = Message(
            account_id=acc.id,
            remote_id=f"remote-{uuid.uuid4().hex[:8]}",
            subject="Test Remote Images",
            from_address=from_address,
            from_name="Test Source",
            to_addresses=["me@test.local"],
            cc_addresses=[],
            sort_time=datetime.now(timezone.utc),
            is_read=False,
            is_flagged=False,
            has_attachments=False,
            snippet="",
        )
        session.add(msg)
        session.commit()
        return msg.id


@_db_required
def test_message_and_sender_allow_truth_table():
    msg_id = _seed_message(from_address="allowed-sender@partner.org")
    Session = get_session_factory()

    with Session() as session:
        # Initially: not allowed
        assert not is_remote_images_allowed(session, msg_id, "allowed-sender@partner.org")

        # Case 1: Single message allow
        assert allow_message_remote_images(session, msg_id)
        session.commit()

        assert is_remote_images_allowed(session, msg_id, "other@domain.com")

        # Idempotent re-allow message
        assert allow_message_remote_images(session, msg_id)
        session.commit()

    # Case 2: Sender allow
    msg_id_2 = _seed_message(from_address="  ALLOWED-SENDER@partner.org  ")
    with Session() as session:
        # Before sender allow: msg_id_2 not allowed
        assert not is_remote_images_allowed(session, msg_id_2, "allowed-sender@partner.org")

        record = allow_sender_remote_images(session, "allowed-sender@partner.org")
        session.commit()
        assert record.from_address == "allowed-sender@partner.org"

        # Now msg_id_2 is allowed by sender match
        assert is_remote_images_allowed(session, msg_id_2, "  ALLOWED-SENDER@partner.org  ")

        # Idempotent re-allow sender
        rec2 = allow_sender_remote_images(session, "Allowed-Sender@Partner.Org")
        session.commit()
        assert rec2.id == record.id

        # Listing allowed senders
        senders = list_allowed_senders(session)
        assert any(s.from_address == "allowed-sender@partner.org" for s in senders)

        # Remove allowed sender
        assert remove_allowed_sender(session, record.id)
        session.commit()

        # After removing sender: msg_id_2 is no longer allowed, but msg_id is still allowed by single message record
        assert not is_remote_images_allowed(session, msg_id_2, "allowed-sender@partner.org")
        assert is_remote_images_allowed(session, msg_id, "allowed-sender@partner.org")


@_db_required
def test_cascade_delete_message_cleans_single_allow():
    msg_id = _seed_message(from_address="news@corp.com")
    Session = get_session_factory()

    with Session() as session:
        allow_message_remote_images(session, msg_id)
        session.commit()

    with Session() as session:
        allow_row = session.get(MessageRemoteImageAllow, msg_id)
        assert allow_row is not None

        # Seed sender allow for this address
        sender_row = allow_sender_remote_images(session, "news@corp.com")
        session.commit()
        sender_id = sender_row.id

        # Delete message
        msg = session.get(Message, msg_id)
        session.delete(msg)
        session.commit()

    with Session() as session:
        # Message allow cascaded, but sender allow strictly retained (AC-008)
        assert session.get(MessageRemoteImageAllow, msg_id) is None
        assert session.get(SenderRemoteImageAllow, sender_id) is not None


@_db_required
def test_sender_allow_cross_accounts():
    """Verify sender allowlist applies globally across different recipient accounts (AC-012)."""
    Session = get_session_factory()
    with Session() as session:
        acc1 = Account(email=f"acc1-{uuid.uuid4().hex[:8]}@test.local", provider="stub", credential_ref="r1")
        acc2 = Account(email=f"acc2-{uuid.uuid4().hex[:8]}@test.local", provider="stub", credential_ref="r2")
        session.add_all([acc1, acc2])
        session.flush()

        msg1 = Message(
            account_id=acc1.id,
            remote_id=f"r-{uuid.uuid4().hex[:8]}",
            subject="Mail on Account 1",
            from_address="partner@cross-account.org",
            to_addresses=[acc1.email],
            sort_time=datetime.now(timezone.utc),
        )
        msg2 = Message(
            account_id=acc2.id,
            remote_id=f"r-{uuid.uuid4().hex[:8]}",
            subject="Mail on Account 2",
            from_address="PARTNER@cross-account.org",
            to_addresses=[acc2.email],
            sort_time=datetime.now(timezone.utc),
        )
        session.add_all([msg1, msg2])
        session.commit()
        m1_id, m2_id = msg1.id, msg2.id

    with Session() as session:
        assert not is_remote_images_allowed(session, m1_id, "partner@cross-account.org")
        assert not is_remote_images_allowed(session, m2_id, "PARTNER@cross-account.org")

        # Allow on account 1's email
        allow_sender_remote_images(session, "partner@cross-account.org")
        session.commit()

        # Both account 1 and account 2 messages now allowed
        assert is_remote_images_allowed(session, m1_id, "partner@cross-account.org")
        assert is_remote_images_allowed(session, m2_id, "PARTNER@cross-account.org")
