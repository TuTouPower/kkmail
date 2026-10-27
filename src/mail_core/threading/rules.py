"""Thread linking — Message-ID / In-Reply-To / References (architecture §12.3)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import Message, Thread, ThreadMessage

# Capture angle-bracket Message-IDs and bare tokens that look like message-ids.
_ANGLE_RE = re.compile(r"<([^<>@\s]+@[^<>\s]+)>")
_BARE_RE = re.compile(r"([^\s<>]+@[^\s<>]+)")

# Thread.subject_norm is String(998) while Message.subject is unbounded
# Text; every Thread creation goes through normalize_subject, so the
# column bound is enforced here (A12).
SUBJECT_NORM_MAX_LENGTH = 998


def normalize_subject(subject: str) -> str:
    s = subject or ""
    while True:
        low = s.lower()
        stripped = False
        for prefix in ("re:", "fw:", "fwd:", "回复:", "转发:", "aw:", "sv:"):
            if low.startswith(prefix):
                s = s[len(prefix) :].lstrip()
                stripped = True
                break
        if not stripped:
            break
    return s.strip().lower()[:SUBJECT_NORM_MAX_LENGTH]


def normalize_message_id(value: str | None) -> str | None:
    """Return canonical Message-ID including angle brackets, or None."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    m = _ANGLE_RE.search(value)
    if m:
        return f"<{m.group(1)}>"
    m = _BARE_RE.search(value)
    if m:
        return f"<{m.group(1)}>"
    if value.startswith("<") and value.endswith(">"):
        return value
    return None


def extract_message_ids(*parts: str | None) -> list[str]:
    """Ordered unique Message-IDs; later headers override earlier duplicates."""
    found: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        for m in _ANGLE_RE.findall(part):
            mid = f"<{m}>"
            if mid not in seen:
                seen.add(mid)
                found.append(mid)
        # Only use bare match if no angle form in this segment
        if "<" not in part:
            for m in _BARE_RE.findall(part):
                mid = f"<{m}>"
                if mid not in seen:
                    seen.add(mid)
                    found.append(mid)
    return found


@dataclass(frozen=True, slots=True)
class ThreadAssignment:
    thread_id: uuid.UUID
    created: bool
    linked_via: str  # provider_key | in_reply_to | references | existing | new


def _ensure_thread_for_parent(session: Session, parent: Message) -> Thread:
    if parent.thread_id:
        thread = session.get(Thread, parent.thread_id)
        if thread:
            return thread
    thread = Thread(
        account_id=parent.account_id,
        subject_norm=normalize_subject(parent.subject),
        sort_time=parent.sort_time,
    )
    session.add(thread)
    session.flush()
    parent.thread_id = thread.id
    if session.scalar(
        select(ThreadMessage).where(
            ThreadMessage.thread_id == thread.id,
            ThreadMessage.message_id == parent.id,
        )
    ) is None:
        session.add(ThreadMessage(thread_id=thread.id, message_id=parent.id))
    session.flush()
    return thread


def assign_thread_for_message(
    session: Session,
    *,
    message: Message,
    in_reply_to: str | None = None,
    references: str | list[str] | None = None,
    provider_thread_key: str | None = None,
) -> ThreadAssignment:
    """Attach message to an existing thread or create one.

    Lookup order:
    1. provider_thread_key
    2. In-Reply-To Message-ID (parent must exist locally)
    3. References, newest → oldest
    4. New thread

    If a parent message exists but has no thread yet, a thread is created and
    both parent and child are attached.
    """
    account_id = message.account_id
    # Canonicalize this message's own internet_message_id when present.
    if message.internet_message_id:
        message.internet_message_id = normalize_message_id(message.internet_message_id) or message.internet_message_id

    thread: Thread | None = None
    linked_via = "new"

    if provider_thread_key:
        thread = session.scalar(
            select(Thread).where(
                Thread.account_id == account_id,
                Thread.provider_thread_key == provider_thread_key,
            )
        )
        if thread:
            linked_via = "provider_key"

    ref_blob = references
    if isinstance(references, list):
        ref_blob = " ".join(references)

    if thread is None:
        for mid in extract_message_ids(in_reply_to):
            parent = session.scalar(
                select(Message).where(
                    Message.account_id == account_id,
                    Message.internet_message_id == mid,
                )
            )
            if parent is not None:
                thread = _ensure_thread_for_parent(session, parent)
                linked_via = "in_reply_to"
                break

    if thread is None:
        # References: walk from right (nearest ancestor) to left
        refs = extract_message_ids(ref_blob if isinstance(ref_blob, str) else None)
        for mid in reversed(refs):
            parent = session.scalar(
                select(Message).where(
                    Message.account_id == account_id,
                    Message.internet_message_id == mid,
                )
            )
            if parent is not None:
                thread = _ensure_thread_for_parent(session, parent)
                linked_via = "references"
                break

    if thread is None and message.thread_id:
        thread = session.get(Thread, message.thread_id)
        if thread is not None:
            linked_via = "existing"

    created = False
    if thread is None:
        try:
            with session.begin_nested():
                thread = Thread(
                    account_id=account_id,
                    provider_thread_key=provider_thread_key,
                    subject_norm=normalize_subject(message.subject),
                    sort_time=message.sort_time,
                )
                session.add(thread)
                session.flush()
                created = True
                linked_via = "new"
        except IntegrityError:
            if provider_thread_key:
                thread = session.scalar(
                    select(Thread).where(
                        Thread.account_id == account_id,
                        Thread.provider_thread_key == provider_thread_key,
                    )
                )
            if thread is None:
                raise
    elif provider_thread_key and not thread.provider_thread_key:
        thread.provider_thread_key = provider_thread_key

    previous_thread_id = message.thread_id
    message.thread_id = thread.id
    if previous_thread_id is not None and previous_thread_id != thread.id:
        session.execute(
            delete(ThreadMessage).where(
                ThreadMessage.message_id == message.id,
                ThreadMessage.thread_id != thread.id,
            )
        )
    if message.sort_time is not None and (thread.sort_time is None or message.sort_time >= thread.sort_time):
        thread.sort_time = message.sort_time
    existing = session.scalar(
        select(ThreadMessage).where(
            ThreadMessage.thread_id == thread.id,
            ThreadMessage.message_id == message.id,
        )
    )
    if existing is None:
        session.add(ThreadMessage(thread_id=thread.id, message_id=message.id))
    session.flush()
    return ThreadAssignment(thread_id=thread.id, created=created, linked_via=linked_via)
