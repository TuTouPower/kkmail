"""Thread scaffolding — Message-ID / In-Reply-To / References first (architecture §12.3)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import Message, Thread, ThreadMessage

_MSG_ID_RE = re.compile(r"<[^>]+>")


def normalize_subject(subject: str) -> str:
    s = subject or ""
    # Strip common reply prefixes
    while True:
        low = s.lower()
        for prefix in ("re:", "fw:", "fwd:", "回复:", "转发:"):
            if low.startswith(prefix):
                s = s[len(prefix) :].lstrip()
                break
        else:
            break
    return s.strip().lower()


@dataclass(frozen=True, slots=True)
class ThreadAssignment:
    thread_id: uuid.UUID
    created: bool


def assign_thread_for_message(
    session: Session,
    *,
    message: Message,
    in_reply_to: str | None = None,
    references: list[str] | None = None,
    provider_thread_key: str | None = None,
) -> ThreadAssignment:
    """Attach message to an existing thread or create one.

    Lookup order: provider_thread_key → In-Reply-To/References Message-ID → new thread.
    Subject+participants heuristic is intentionally not auto-merged yet (too risky).
    """
    account_id = message.account_id
    thread = None
    if provider_thread_key:
        thread = session.scalar(
            select(Thread).where(
                Thread.account_id == account_id,
                Thread.provider_thread_key == provider_thread_key,
            )
        )
    if thread is None:
        ids = []
        if in_reply_to:
            ids.extend(_MSG_ID_RE.findall(in_reply_to) or [in_reply_to.strip()])
        for ref in references or []:
            ids.extend(_MSG_ID_RE.findall(ref) or [ref.strip()])
        for mid in ids:
            parent = session.scalar(
                select(Message).where(
                    Message.account_id == account_id,
                    Message.internet_message_id == mid,
                )
            )
            if parent and parent.thread_id:
                thread = session.get(Thread, parent.thread_id)
                if thread:
                    break
    created = False
    if thread is None:
        thread = Thread(
            account_id=account_id,
            provider_thread_key=provider_thread_key,
            subject_norm=normalize_subject(message.subject),
            sort_time=message.sort_time,
        )
        session.add(thread)
        session.flush()
        created = True
    message.thread_id = thread.id
    if thread.sort_time is None or message.sort_time >= thread.sort_time:
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
    return ThreadAssignment(thread_id=thread.id, created=created)
