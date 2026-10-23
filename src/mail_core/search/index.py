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


_MATCH = """
    (
        document @@ plainto_tsquery('simple', :q)
        OR from_text ILIKE '%' || :q || '%'
        OR subject ILIKE '%' || :q || '%'
        OR from_text % :q
    )
"""


def _filters(query: str, account_ids: list[uuid.UUID] | None, folder_id: uuid.UUID | None) -> tuple[str, dict]:
    params: dict = {"q": query}
    filters: list[str] = []
    if account_ids is not None:
        filters.append("account_id = ANY(:account_ids)")
        params["account_ids"] = account_ids
    if folder_id is not None:
        filters.append(
            "EXISTS (SELECT 1 FROM message_locations ml "
            "WHERE ml.message_id = message_search.message_id AND ml.folder_id = :folder_id)"
        )
        params["folder_id"] = folder_id
    where_clause = "AND " + " AND ".join(filters) if filters else ""
    return where_clause, params


def search_messages(
    session: Session,
    *,
    account_ids: list[uuid.UUID] | None,
    query: str,
    folder_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[uuid.UUID]:
    """Message ids ranked by FTS, with trigram/ILIKE fallback on subject + from_text.

    Subject/from ILIKE are served by GIN trigram indexes (migration 0006).
    """
    from sqlalchemy import text as sql_text

    if not query.strip():
        return []
    scope_filter, params = _filters(query, account_ids, folder_id)
    params.update(limit=limit, offset=max(0, offset))
    rows = session.execute(
        sql_text(
            f"""
            SELECT message_id
            FROM message_search
            WHERE {_MATCH}
            {scope_filter}
            ORDER BY ts_rank(document, plainto_tsquery('simple', :q)) DESC, updated_at DESC, message_id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).all()
    return [r[0] for r in rows]


def count_messages(
    session: Session,
    *,
    account_ids: list[uuid.UUID] | None,
    query: str,
    folder_id: uuid.UUID | None = None,
) -> int:
    from sqlalchemy import text as sql_text

    if not query.strip():
        return 0
    scope_filter, params = _filters(query, account_ids, folder_id)
    return int(
        session.execute(
            sql_text(f"SELECT count(*) FROM message_search WHERE {_MATCH} {scope_filter}"),
            params,
        ).scalar()
        or 0
    )
