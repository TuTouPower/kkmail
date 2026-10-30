"""Application service for remote image allowlists (t066)."""

from __future__ import annotations

import re
import uuid
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import (
    Message,
    MessageRemoteImageAllow,
    SenderRemoteImageAllow,
)

# Strict RFC 5322 compatible email validation pattern.
_EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)


class InvalidSenderEmailError(ValueError):
    """Raised when a sender email address is invalid, empty, or multi-address."""


def normalize_sender_email(address: str | None) -> str:
    """Normalize and validate a sender email address (trim whitespace, lowercase).

    Rejects empty strings, multiple addresses, control characters, CRLF, dot-syntax defects, and invalid syntax.
    """
    if not address or not isinstance(address, str):
        raise InvalidSenderEmailError("Sender address is required")

    # Reject control characters and line breaks on the RAW unstripped string first
    if any(ord(c) < 32 or ord(c) == 127 for c in address):
        raise InvalidSenderEmailError("Sender address contains illegal control characters")

    trimmed = address.strip()
    if not trimmed:
        raise InvalidSenderEmailError("Sender address cannot be empty or whitespace only")

    if len(trimmed) > 320:
        raise InvalidSenderEmailError("Sender address exceeds maximum length of 320 characters")

    # Reject multiple addresses (commas or semicolons)
    if "," in trimmed or ";" in trimmed:
        raise InvalidSenderEmailError("Multiple addresses are not supported in sender allowlist")

    # Reject angle brackets if raw header was passed unparsed
    if "<" in trimmed or ">" in trimmed:
        raise InvalidSenderEmailError("Sender address must be a raw email, not display text with angle brackets")

    lower = trimmed.lower()
    if lower.count("@") != 1:
        raise InvalidSenderEmailError("Sender address must contain exactly one '@'")

    local_part, _, domain_part = lower.partition("@")
    if not local_part or not domain_part:
        raise InvalidSenderEmailError("Sender address local and domain parts cannot be empty")

    if local_part.startswith(".") or local_part.endswith(".") or ".." in local_part:
        raise InvalidSenderEmailError("Local part cannot start/end with dot or contain consecutive dots")

    if domain_part.startswith(".") or domain_part.endswith(".") or ".." in domain_part:
        raise InvalidSenderEmailError("Domain part cannot start/end with dot or contain consecutive dots")

    if not _EMAIL_REGEX.match(lower):
        raise InvalidSenderEmailError(f"Invalid email address format: {address!r}")

    return lower


def is_remote_images_allowed(
    session: Session,
    message_id: uuid.UUID,
    from_address: str | None,
) -> bool:
    """Return True if remote images are allowed for the message or its sender."""
    # 1. Check single-message allow
    msg_allowed = session.scalar(
        select(MessageRemoteImageAllow.message_id).where(
            MessageRemoteImageAllow.message_id == message_id
        )
    )
    if msg_allowed is not None:
        return True

    # 2. Check sender-level allow
    if from_address:
        try:
            norm_addr = normalize_sender_email(from_address)
            sender_allowed = session.scalar(
                select(SenderRemoteImageAllow.id).where(
                    SenderRemoteImageAllow.from_address == norm_addr
                )
            )
            if sender_allowed is not None:
                return True
        except InvalidSenderEmailError:
            pass

    return False


def allow_message_remote_images(session: Session, message_id: uuid.UUID) -> bool:
    """Persist single-message remote image allow record (atomic idempotent ON CONFLICT)."""
    msg = session.get(Message, message_id)
    if msg is None:
        raise LookupError(f"Message {message_id} not found")

    stmt = (
        pg_insert(MessageRemoteImageAllow)
        .values(message_id=message_id)
        .on_conflict_do_nothing(index_elements=["message_id"])
    )
    session.execute(stmt)
    session.flush()
    return True


def allow_sender_remote_images(
    session: Session,
    from_address: str,
) -> SenderRemoteImageAllow:
    """Persist global sender remote image allow record (atomic idempotent ON CONFLICT)."""
    norm_addr = normalize_sender_email(from_address)

    stmt = (
        pg_insert(SenderRemoteImageAllow)
        .values(from_address=norm_addr)
        .on_conflict_do_nothing(index_elements=["from_address"])
    )
    session.execute(stmt)
    session.flush()

    record = session.scalar(
        select(SenderRemoteImageAllow).where(
            SenderRemoteImageAllow.from_address == norm_addr
        )
    )
    assert record is not None
    return record


def list_allowed_senders(session: Session) -> list[SenderRemoteImageAllow]:
    """Return all allowed sender records ordered by creation date descending."""
    return list(
        session.scalars(
            select(SenderRemoteImageAllow).order_by(
                SenderRemoteImageAllow.created_at.desc()
            )
        ).all()
    )


def remove_allowed_sender(session: Session, sender_id: uuid.UUID) -> bool:
    """Remove a sender allowlist record by ID. Return True if deleted, False if not found."""
    record = session.get(SenderRemoteImageAllow, sender_id)
    if record is None:
        return False
    session.delete(record)
    session.flush()
    return True
