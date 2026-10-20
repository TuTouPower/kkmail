"""Maintain message_search rows for FTS + trigram."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import Message, MessageBody, MessageSearch


def upsert_message_search(
    session: Session,
    *,
    message_id: uuid.UUID,
    body_text: str | None = None,
) -> MessageSearch:
    msg = session.get(Message, message_id)
    if msg is None:
        raise ValueError(f"message {message_id} not found")
    if body_text is None:
        body = session.get(MessageBody, message_id)
        body_text = (body.text_plain if body else None) or msg.snippet or ""
    from_text = " ".join(x for x in [msg.from_name, msg.from_address] if x)
    row = session.get(MessageSearch, message_id)
    if row is None:
        row = MessageSearch(message_id=message_id, account_id=msg.account_id)
        session.add(row)
    row.account_id = msg.account_id
    row.subject = msg.subject or ""
    row.from_text = from_text
    row.body_text = body_text or ""
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
    return row


def search_messages(
    session: Session,
    *,
    account_ids: list[uuid.UUID] | None,
    query: str,
    limit: int = 50,
) -> list[uuid.UUID]:
    """Return message ids ranked by FTS, with trigram fallback on from_text."""
    from sqlalchemy import text as sql_text

    if not query.strip():
        return []
    params: dict = {"q": query, "limit": limit}
    account_filter = ""
    if account_ids:
        account_filter = "AND account_id = ANY(:account_ids)"
        params["account_ids"] = account_ids
    # Prefer FTS; also allow fuzzy from_text via %
    rows = session.execute(
        sql_text(
            f"""
            SELECT message_id
            FROM message_search
            WHERE (
                document @@ plainto_tsquery('simple', :q)
                OR from_text ILIKE '%' || :q || '%'
                OR subject ILIKE '%' || :q || '%'
                OR similarity(from_text, :q) > 0.3
            )
            {account_filter}
            ORDER BY ts_rank(document, plainto_tsquery('simple', :q)) DESC, updated_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).all()
    return [r[0] for r in rows]
