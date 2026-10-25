"""Maintain message_search rows for FTS + trigram."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

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


def upsert_message_search_batch(session: Session, *, messages: Sequence[Message]) -> None:
    """Update a page of search rows with one body lookup and one index lookup."""
    by_id = {message.id: message for message in messages}
    if not by_id:
        return
    message_ids = list(by_id)

    bodies = {
        body.message_id: body
        for body in session.scalars(
            select(MessageBody).where(MessageBody.message_id.in_(message_ids))
        )
    }
    search_rows = {
        row.message_id: row
        for row in session.scalars(
            select(MessageSearch).where(MessageSearch.message_id.in_(message_ids))
        )
    }
    for pending in session.new:
        if isinstance(pending, MessageBody) and pending.message_id in by_id:
            bodies[pending.message_id] = pending
        elif isinstance(pending, MessageSearch) and pending.message_id in by_id:
            search_rows[pending.message_id] = pending

    now = datetime.now(timezone.utc)
    for message in by_id.values():
        body = bodies.get(message.id)
        body_text = (body.text_plain if body else None) or message.snippet or ""
        row = search_rows.get(message.id)
        if row is None:
            row = MessageSearch(message_id=message.id, account_id=message.account_id)
            search_rows[message.id] = row
            session.add(row)
        row.account_id = message.account_id
        row.subject = message.subject or ""
        row.from_text = " ".join(x for x in [message.from_name, message.from_address] if x)
        row.body_text = body_text
        row.updated_at = now
    session.flush()


_MATCH = """
    (
        document @@ plainto_tsquery('simple', :q)
        OR from_text ILIKE '%' || :like_q || '%' ESCAPE E'\\\\'
        OR subject ILIKE '%' || :like_q || '%' ESCAPE E'\\\\'
        OR from_text % :q
    )
"""


def _escape_like_literal(query: str) -> str:
    """Escape LIKE metacharacters while retaining literal query semantics."""
    return query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clamp_search_limit(limit: int) -> int:
    return min(200, max(1, int(limit)))


def _filters(query: str, account_ids: list[uuid.UUID] | None, folder_id: uuid.UUID | None) -> tuple[str, dict]:
    params: dict = {"q": query, "like_q": _escape_like_literal(query)}
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
    params.update(limit=_clamp_search_limit(limit), offset=max(0, offset))
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


def search_messages_with_total(
    session: Session,
    *,
    account_ids: list[uuid.UUID] | None,
    query: str,
    folder_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[uuid.UUID], int]:
    """Return one ranked page and its total using a single FTS query when rows exist."""
    from sqlalchemy import text as sql_text

    if not query.strip():
        return [], 0
    scope_filter, params = _filters(query, account_ids, folder_id)
    params.update(limit=_clamp_search_limit(limit), offset=max(0, offset))
    rows = session.execute(
        sql_text(
            f"""
            SELECT message_id, count(*) OVER () AS total_count
            FROM message_search
            WHERE {_MATCH}
            {scope_filter}
            ORDER BY ts_rank(document, plainto_tsquery('simple', :q)) DESC, updated_at DESC, message_id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).all()
    if not rows:
        # Window counts have no row to carry the total for an out-of-range offset.
        total = count_messages(session, account_ids=account_ids, query=query, folder_id=folder_id) if offset else 0
        return [], total
    return [row[0] for row in rows], int(rows[0][1] or 0)
