"""A293: the scan-generation staleness check must be an existence query.

The old ``_assert_scan_generation_current`` ran a GROUP BY over ALL of
the account's full-scan targets (every generation, sorted by the
grouping) on every checkpoint commit that carried a generation. The
pinned shape: fetch this generation's birth once, then ask "does a
newer-born sibling generation exist?" with a LIMIT 1 existence query --
no GROUP BY anywhere.

Runs against the real PostgreSQL schema built by Alembic. Foreign-key
parent rows (Account/Folder) are seeded because the real schema enforces
them; ``assert_fencing`` is patched out so no lease row is needed.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import event

from mail_core.db.session import get_engine, get_session_factory
from mail_core.mail.storage.models import Account, Folder, SyncRequest, SyncRequestTarget
from mail_core.sync import checkpoints as checkpoints_mod
from mail_core.sync.checkpoints import (
    ScanGenerationMismatch,
    begin_scan_generation,
    commit_checkpoint,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_T0 = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
_ACCOUNT = uuid.UUID("00000000-0000-0000-0000-00000000acc0")
_FOLDER = uuid.UUID("00000000-0000-0000-0000-00000000f01d")


@pytest.fixture(autouse=True)
def _no_fencing():
    with patch.object(checkpoints_mod, "assert_fencing", lambda *_a, **_k: None):
        yield


def _capture_sql():
    engine = get_engine()
    statements: list[str] = []

    def _record(_conn, _cursor, statement, _params, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    return statements, lambda: event.remove(engine, "before_cursor_execute", _record)


def _seed_fk_parents(Session):
    with Session() as session:
        session.add(Account(id=_ACCOUNT, email="a293-fk@example.test",
                            provider="imap", sync_enabled=True))
        session.add(Folder(id=_FOLDER, account_id=_ACCOUNT, remote_id="INBOX",
                           name="INBOX", role="inbox"))
        session.commit()


def _seed(session, generation, *, born_at):
    request_id = uuid.uuid4()
    session.add(
        SyncRequest(
            id=request_id,
            client_request_id=f"a293-{uuid.uuid4().hex}",
            mode="full",
            trigger="manual",
            state="queued",
            scope={},
            created_at=born_at,
        )
    )
    session.add(
        SyncRequestTarget(
            id=uuid.uuid4(),
            request_id=request_id,
            account_id=_ACCOUNT,
            folder_id=_FOLDER,
            target_key=f"account:{_ACCOUNT}:folder:{_FOLDER}:role:inbox",
            requested_generation=generation,
            state="queued",
            created_at=born_at,
        )
    )
    session.flush()


def test_generation_check_is_limit1_existence_without_group_by():
    Session = get_session_factory()
    _seed_fk_parents(Session)
    gen_old, gen_new = uuid.uuid4(), uuid.uuid4()

    with Session() as session:
        _seed(session, gen_old, born_at=_T0)
        _seed(session, gen_new, born_at=_T0 + timedelta(minutes=5))
        session.commit()

        statements, stop_capture = _capture_sql()
        try:
            with pytest.raises(ScanGenerationMismatch):
                commit_checkpoint(
                    session,
                    account_id=_ACCOUNT,
                    folder_id=_FOLDER,
                    fencing_token=7,
                    cursor={"uid_next": 1},
                    scan_generation=gen_old,
                )
            session.rollback()
        finally:
            stop_capture()

    generation_queries = [s for s in statements if "sync_request_targets" in s]
    assert generation_queries, "generation check issued no target query"
    assert not any("GROUP BY" in s.upper() for s in generation_queries), generation_queries
    assert any("LIMIT" in s.upper() for s in generation_queries), generation_queries

    # The newest generation still commits cleanly under the new shape.
    with Session() as session:
        begin_scan_generation(
            session,
            account_id=_ACCOUNT,
            folder_id=_FOLDER,
            fencing_token=7,
            scan_generation=gen_new,
        )
        row = commit_checkpoint(
            session,
            account_id=_ACCOUNT,
            folder_id=_FOLDER,
            fencing_token=7,
            cursor={"uid_next": 2},
            scan_generation=gen_new,
        )
        assert row.cursor == {"uid_next": 2}
        session.commit()
