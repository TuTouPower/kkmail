"""A293: the scan-generation staleness check must be an existence query.

The old ``_assert_scan_generation_current`` ran a GROUP BY over ALL of
the account's full-scan targets (every generation, sorted by the
grouping) on every checkpoint commit that carried a generation. The
pinned shape: fetch this generation's birth once, then ask "does a
newer-born sibling generation exist?" with a LIMIT 1 existence query --
no GROUP BY anywhere.

SQLite + hand DDL following test_sync_checkpoint_generation_order.py;
``assert_fencing`` is patched out.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from mail_core.mail.storage.models import SyncRequest, SyncRequestTarget
from mail_core.sync import checkpoints as checkpoints_mod
from mail_core.sync.checkpoints import (
    ScanGenerationMismatch,
    begin_scan_generation,
    commit_checkpoint,
)

_DDL = [
    """
    CREATE TABLE sync_requests (
        id CHAR(36) PRIMARY KEY,
        client_request_id VARCHAR(64) NOT NULL UNIQUE,
        mode VARCHAR(32) NOT NULL,
        "trigger" VARCHAR(32) NOT NULL,
        state VARCHAR(32) NOT NULL DEFAULT 'queued',
        scope JSON NOT NULL DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        finished_at DATETIME
    )
    """,
    """
    CREATE TABLE sync_request_targets (
        id CHAR(36) PRIMARY KEY,
        request_id CHAR(36) NOT NULL,
        account_id CHAR(36),
        folder_id CHAR(36),
        target_key VARCHAR(255) NOT NULL,
        requested_generation CHAR(36) NOT NULL,
        state VARCHAR(32) NOT NULL DEFAULT 'queued',
        error_code VARCHAR(64),
        safe_error VARCHAR(500),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        finished_at DATETIME
    )
    """,
    """
    CREATE TABLE sync_checkpoints (
        account_id CHAR(36) NOT NULL,
        folder_id CHAR(36) NOT NULL,
        cursor JSON NOT NULL DEFAULT '{}',
        uidvalidity BIGINT,
        modseq BIGINT,
        history_id VARCHAR(128),
        delta_link TEXT,
        full_scan_complete BOOLEAN NOT NULL DEFAULT 0,
        scan_generation CHAR(36),
        fencing_token INTEGER NOT NULL DEFAULT 0,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        PRIMARY KEY (account_id, folder_id)
    )
    """,
]

_T0 = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
_ACCOUNT = uuid.UUID("00000000-0000-0000-0000-00000000acc0")
_FOLDER = uuid.UUID("00000000-0000-0000-0000-00000000f01d")


@pytest.fixture(autouse=True)
def _no_fencing():
    with patch.object(checkpoints_mod, "assert_fencing", lambda *_a, **_k: None):
        yield


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
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    Session = sessionmaker(bind=engine)
    gen_old, gen_new = uuid.uuid4(), uuid.uuid4()

    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    with Session() as session:
        _seed(session, gen_old, born_at=_T0)
        _seed(session, gen_new, born_at=_T0 + timedelta(minutes=5))
        session.commit()

        statements.clear()
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
