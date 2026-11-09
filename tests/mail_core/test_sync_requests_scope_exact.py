"""DEFECT 5: list_recent_sync_requests must match scopes exactly.

Before the fix the list matcher kept a request iff every *provided* query
filter equalled the request's canonical scope value. A query that omitted
a scope key therefore matched requests carrying that key: the global
(all-accounts) recovery query returned a single account's in-flight
request, and the frontend hook (use_scope_sync) adopted it under the
global scope key, displaying the account's progress on the global sync
button and blocking a real global sync.

Stored canonical scope shapes (create_sync_request call sites):
- full sync-all (POST /api/accounts/sync-all): ``{"all": True}``
- full single account (POST /api/accounts/{id}/sync): ``{"account_id": X}``
- delta global inbox (frontend allInbox view): ``{"folder_role": "inbox"}``
- delta single account: ``{"account_id": X, "folder_role": "inbox"}``
- delta group: ``{"group_id": G, "folder_role": R}``
- delta folder: ``{"account_id": X, "folder_id": F, "folder_role": R}``

These tests seed SyncRequest rows directly with those stored shapes into
the real PostgreSQL schema created by ``alembic upgrade head`` (JSONB
scope) and call the application function. No existing test is modified
by this file.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

from mail_core.db.session import get_session_factory
from mail_core.mail.application.sync_requests import list_recent_sync_requests
from mail_core.mail.storage.models import SyncRequest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


def _seed(Session, *, scope: dict, state: str) -> uuid.UUID:
    request_id = uuid.uuid4()
    with Session() as session:
        session.add(
            SyncRequest(
                id=request_id,
                client_request_id=f"defect5-{uuid.uuid4().hex}",
                mode="full" if scope.get("all") or set(scope) == {"account_id"} else "delta",
                trigger="manual",
                state=state,
                scope=scope,
                created_at=_NOW,
            )
        )
        session.commit()
    return request_id


def _ids(reports) -> set[str]:
    return {r.id for r in reports}


def test_recent_sync_requests_no_filter_returns_only_global_and_account_filter_only_account():
    """Required regression: one global + one single-account request, both
    unfinished. The unfiltered (global) query returns ONLY the global one;
    the account-filtered query returns ONLY the account one."""
    Session = get_session_factory()
    account_id = uuid.uuid4()
    global_id = _seed(Session, scope={"all": True}, state="queued")
    account_req_id = _seed(Session, scope={"account_id": str(account_id)}, state="running")

    with Session() as session:
        unfiltered = list_recent_sync_requests(session)
        assert _ids(unfiltered) == {str(global_id)}

        account_filtered = list_recent_sync_requests(session, account_id=account_id)
        assert _ids(account_filtered) == {str(account_req_id)}


def test_recent_sync_requests_delta_global_query_never_adopts_account_request():
    """The actual frontend leak: the global inbox view queries with only
    folder_role=inbox; a single-account delta request carries that same
    role plus an account_id and must never match it (and vice versa)."""
    Session = get_session_factory()
    account_id = uuid.uuid4()
    group_id = uuid.uuid4()
    delta_global_id = _seed(Session, scope={"folder_role": "inbox"}, state="queued")
    delta_account_id = _seed(
        Session, scope={"account_id": str(account_id), "folder_role": "inbox"}, state="running"
    )
    delta_group_id = _seed(
        Session, scope={"group_id": str(group_id), "folder_role": "inbox"}, state="queued"
    )

    with Session() as session:
        reports = list_recent_sync_requests(session, folder_role="inbox")
        assert _ids(reports) == {str(delta_global_id)}

        reports = list_recent_sync_requests(session, account_id=account_id, folder_role="inbox")
        assert _ids(reports) == {str(delta_account_id)}
        reports = list_recent_sync_requests(session, account_id=account_id)
        assert _ids(reports) == {str(delta_account_id)}

        reports = list_recent_sync_requests(session, group_id=group_id, folder_role="inbox")
        assert _ids(reports) == {str(delta_group_id)}

        reports = list_recent_sync_requests(session, account_id=uuid.uuid4())
        assert reports == []
