"""Application-layer search (routes must not call search.index directly)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from mail_core.search.index import search_messages as _search_messages


def search_message_ids(
    session: Session,
    *,
    query: str,
    account_ids: list[uuid.UUID] | None = None,
    limit: int = 50,
) -> list[uuid.UUID]:
    return _search_messages(session, account_ids=account_ids, query=query, limit=limit)
