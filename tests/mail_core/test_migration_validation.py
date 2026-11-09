"""Database Migration & Schema Integrity Validation Tests (adoption A17).

Verifies single unified Alembic baseline migration, clean empty database
upgrade, reversible downgrade base to upgrade head cycles, relational
constraints/indexes/FTS, zero ORM schema drift, and offline baseline stamp tool
against real PostgreSQL.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, String, inspect, text
from sqlalchemy.exc import IntegrityError

from mail_core.db.session import get_engine, get_session_factory
from mail_core.mail.domain.enums import ArchiveState
from mail_core.mail.storage.models import (
    Account,
    AccountGroup,
    Attachment,
    Base,
    BlobQuotaReservation,
    Folder,
    FolderPatrolStatus,
    Message,
    MessageArchiveState,
    MessageBlob,
    MessageBlobLink,
    MessageBody,
    MessageLocation,
    MessageRemoteImageAllow,
    OutboxEvent,
    SenderRemoteImageAllow,
    WorkerJob,
)

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = str(ROOT / "src/mail_core/db/alembic.ini")
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from migrate_to_unified_baseline import (
    REQUIRED_TABLES,
    UNIFIED_BASELINE_REVISION,
    SchemaValidationError,
    migrate_patrol_status_data,
    run_migration,
    stamp_unified_baseline,
    verify_database_schema,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _get_alembic_config() -> Config:
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option("script_location", str(ROOT / "src/mail_core/db/alembic"))
    safe_url = os.environ["MAIL_CORE_DATABASE_URL"].replace("%", "%%")
    cfg.set_main_option("sqlalchemy.url", safe_url)
    return cfg


# --- AC-001: Single unified baseline migration without forks ----------------------


def test_alembic_chain_has_single_head():
    """Adoption A17: Migration history is squashed to a single unified baseline."""
    script = ScriptDirectory.from_config(_get_alembic_config())
    assert script.get_heads() == [UNIFIED_BASELINE_REVISION]

    current = script.get_revision(UNIFIED_BASELINE_REVISION)
    assert current is not None
    assert current.down_revision is None

    visited = []
    while current is not None:
        visited.append(current.revision)
        down = current.down_revision
        if down is None:
            break
        assert isinstance(down, str), f"Fork at {current.revision}"
        current = script.get_revision(down)

    assert len(visited) == 1
    assert visited == [UNIFIED_BASELINE_REVISION]


# --- AC-002: Empty database upgrade & reversible downgrade cycle -------------------


def test_clean_upgrade_head_creates_all_tables_and_seeds():
    """Empty database upgrade head creates all tables and initialized seeds."""
    cfg = _get_alembic_config()
    engine = get_engine()

    try:
        with engine.connect() as conn:
            command.downgrade(cfg, "base")

        table_names = set(inspect(engine).get_table_names())
        assert table_names <= {"alembic_version"}

        with engine.connect() as conn:
            command.upgrade(cfg, "head")

        table_names_after = set(inspect(engine).get_table_names())
        assert REQUIRED_TABLES <= table_names_after

        # Verify publication state singleton was seeded
        with engine.connect() as conn:
            pub_state = conn.execute(
                text("SELECT id, next_seq, pruned_through_seq FROM outbox_publication_state WHERE id = 1")
            ).one()
            assert pub_state[0] == 1
            assert pub_state[1] == 1
            assert pub_state[2] == 0
    finally:
        with engine.connect() as conn:
            command.upgrade(cfg, "head")


def test_revertible_downgrade_base_and_upgrade_head_cycle():
    """Verifies reversible downgrade base and upgrade head cycle against real PostgreSQL."""
    cfg = _get_alembic_config()
    engine = get_engine()
    Session = get_session_factory()

    try:
        # 1. Downgrade to base
        with engine.connect() as conn:
            command.downgrade(cfg, "base")

        tables_at_base = set(inspect(engine).get_table_names())
        assert tables_at_base <= {"alembic_version"}

        # 2. Upgrade back to head
        with engine.connect() as conn:
            command.upgrade(cfg, "head")

        tables_at_head = set(inspect(engine).get_table_names())
        assert REQUIRED_TABLES <= tables_at_head

        # 3. Insert and verify data
        with Session() as session:
            account = Account(
                email=f"cycle-{uuid.uuid4().hex[:8]}@example.com",
                provider="imap",
            )
            session.add(account)
            session.commit()
            acc_id = account.id

            folder = Folder(
                account_id=acc_id,
                remote_id="INBOX",
                name="Inbox",
                role="inbox",
            )
            session.add(folder)
            session.commit()

            msg = Message(
                account_id=acc_id,
                remote_id="msg-cycle-01",
                subject="Test cycle",
                from_address="sender@example.com",
                sort_time=datetime.now(timezone.utc),
            )
            session.add(msg)
            session.commit()

            assert session.get(Message, msg.id) is not None
    finally:
        # Guarantee database stays at head
        with engine.connect() as conn:
            command.upgrade(cfg, "head")


# --- AC-003: Relational Constraints, Indexes, CHECK constraints & FTS -------------


def test_schema_constraints_indexes_and_fts_semantics():
    """Verifies relational integrity, CHECK constraints, indexes, keyset order and FTS."""
    Session = get_session_factory()
    test_email = f"constraints-{uuid.uuid4().hex[:8]}@example.com"
    with Session() as session:
        acc = Account(email=test_email, provider="imap")
        session.add(acc)
        session.commit()
        acc_id = acc.id

    with Session() as session:
        msg = Message(
            account_id=acc_id,
            remote_id="remote-unique-1",
            subject="Searchable Subject Keyword",
            from_address="author@example.com",
            sort_time=datetime.now(timezone.utc),
        )
        session.add(msg)
        session.commit()

        # 1. Unique constraint: duplicate (account_id, remote_id) must be rejected
        dup_msg = Message(
            account_id=acc_id,
            remote_id="remote-unique-1",
            subject="Duplicate Remote ID",
            from_address="author@example.com",
            sort_time=datetime.now(timezone.utc),
        )
        session.add(dup_msg)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        # 2. Case-insensitive email unique index on accounts
        dup_acc = Account(email=test_email.upper(), provider="graph")
        session.add(dup_acc)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        # 3. Foreign Key: invalid account_id must be rejected
        ghost_msg = Message(
            account_id=uuid.uuid4(),
            remote_id="ghost-1",
            subject="Ghost",
            from_address="a@b.c",
            sort_time=datetime.now(timezone.utc),
        )
        session.add(ghost_msg)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        # 4. MessageBlob foreign key RESTRICT: cannot delete blob referenced by links
        blob = MessageBlob(
            content_sha256=uuid.uuid4().hex * 2,
            size_bytes=512,
            storage_path="path/test",
            ref_count=1,
        )
        session.add(blob)
        session.flush()

        msg_ref = Message(
            account_id=acc_id,
            remote_id="msg-blob-ref",
            subject="Blob Ref",
            from_address="a@b.c",
            sort_time=datetime.now(timezone.utc),
        )
        session.add(msg_ref)
        session.flush()

        link = MessageBlobLink(message_id=msg_ref.id, blob_id=blob.id)
        session.add(link)
        session.flush()

        session.delete(blob)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        # 5. CHECK constraint: blob ref_count >= 0
        invalid_blob = MessageBlob(
            content_sha256=uuid.uuid4().hex * 2,
            size_bytes=512,
            storage_path="path/invalid",
            ref_count=-1,
        )
        session.add(invalid_blob)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        # 6. CHECK constraint: blob quota reserved_bytes > 0
        invalid_res = BlobQuotaReservation(
            worker_id="test-worker",
            reserved_bytes=0,
            expires_at=datetime.now(timezone.utc),
        )
        session.add(invalid_res)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        # 7. CHECK constraint: archive state valid enum value
        invalid_state = MessageArchiveState(
            message_id=msg.id,
            state="invalid_state_xyz",
        )
        session.add(invalid_state)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

        # 8. Keyset order and FTS trigram index availability
        from mail_core.search.index import upsert_message_search

        upsert_message_search(session, message_id=msg.id)
        session.commit()
        engine = get_engine()
        with engine.connect() as conn:
            res = conn.execute(text("SELECT count(*) FROM message_search")).scalar()
            assert res is not None and res >= 1
            hit_ids = conn.execute(
                text(
                    "SELECT message_id FROM message_search "
                    "WHERE document @@ plainto_tsquery('simple', :q)"
                ),
                {"q": "Searchable"},
            ).scalars().all()
            assert msg.id in hit_ids

            # Verify keyset indexes exist
            indexes = inspect(engine).get_indexes("messages")
            idx_names = {idx["name"] for idx in indexes}
            assert "ix_messages_sort_id" in idx_names
            assert "uq_messages_account_remote" in idx_names
            assert "ix_messages_account_internet_id" in idx_names


# --- AC-004: ORM Schema Drift & Negative Detection ---------------------------------


def test_orm_schema_drift_and_negative_detection():
    """Asserts zero drift between SQLAlchemy models and PostgreSQL database catalog."""
    engine = get_engine()

    # 1. Explicit catalog assertions for PostgreSQL-specific generated column and GIN indexes
    search_cols = {c["name"] for c in inspect(engine).get_columns("message_search")}
    assert "document" in search_cols, "Expected PostgreSQL tsvector document column in message_search"

    search_idx = {i["name"] for i in inspect(engine).get_indexes("message_search")}
    assert "ix_message_search_account" in search_idx
    assert "ix_message_search_document" in search_idx
    assert "ix_message_search_from_trgm" in search_idx
    assert "ix_message_search_subject_trgm" in search_idx

    rem_idx = {i["name"] for i in inspect(engine).get_indexes("remote_operations")}
    assert "ix_remote_operations_retry" in rem_idx

    registered_pg_objects = {
        "document",
        "ix_message_search_account",
        "ix_message_search_document",
        "ix_message_search_from_trgm",
        "ix_message_search_subject_trgm",
        "ix_remote_operations_retry",
    }

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        diffs = compare_metadata(ctx, Base.metadata)

        real_diffs = []
        for d in diffs:
            # Check if this diff corresponds to one of our explicitly registered PG DDL objects
            obj_name = None
            if d[0] == "remove_index":
                obj_name = getattr(d[1], "name", None)
            elif d[0] == "remove_column":
                col = d[3]
                obj_name = getattr(col, "name", None)
            if obj_name in registered_pg_objects:
                continue
            real_diffs.append(d)
        assert real_diffs == [], f"Schema drift detected between Base.metadata and database: {real_diffs}"

    # Negative test: artificially introduce an unmigrated column to in-memory metadata
    fake_col = Column("unmigrated_test_column_xyz", String(64))
    Account.__table__.append_column(fake_col)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            drift_detected = compare_metadata(ctx, Base.metadata)
            assert len(drift_detected) >= 1
            assert any(
                d[0] == "add_column" and getattr(d[3], "name", None) == "unmigrated_test_column_xyz"
                for d in drift_detected
            ), f"Expected drift for unmigrated column, got {drift_detected}"
    finally:
        Account.__table__._columns.remove(fake_col)


# --- AC-005: Live Database Verification with Offline Tool --------------------------


def test_offline_migration_tool_verifies_and_stamps_live_db():
    """Verify that migrate_to_unified_baseline tool accepts the live database."""
    engine = get_engine()
    with engine.connect() as conn:
        errors = verify_database_schema(conn)
        assert errors == []

        stamp_unified_baseline(conn, dry_run=False)
        conn.commit()

        cur_rev = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        assert cur_rev == UNIFIED_BASELINE_REVISION


def test_offline_tool_refuses_legacy_schema_without_side_effects_on_postgres():
    """A legacy/incomplete PostgreSQL schema is rejected before any write.

    Adoption A17 keeps the explicit-refusal decision: the offline tool has no
    general legacy upgrade path. Reducing a real PostgreSQL database to an
    incomplete legacy schema must be refused without leaving a
    folder_patrol_status table, rewriting sync_checkpoints.cursor, or changing
    alembic_version.
    """
    cfg = _get_alembic_config()
    engine = get_engine()
    db_url = os.environ["MAIL_CORE_DATABASE_URL"]
    legacy_cursor = json.dumps(
        {"last_status": "idle", "last_probe_failures": 7, "delta_token": "keep-me"}
    )
    folder_id = uuid.uuid4()

    with engine.connect() as conn:
        command.downgrade(cfg, "base")

    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES ('20261027_0029')")
            )
            conn.execute(text("CREATE TABLE folders (id UUID PRIMARY KEY)"))
            conn.execute(
                text(
                    "CREATE TABLE sync_checkpoints ("
                    "folder_id UUID PRIMARY KEY, cursor JSONB NOT NULL)"
                )
            )
            conn.execute(
                text("INSERT INTO folders (id) VALUES (:fid)"),
                {"fid": folder_id},
            )
            conn.execute(
                text(
                    "INSERT INTO sync_checkpoints (folder_id, cursor) "
                    "VALUES (:fid, CAST(:cur AS jsonb))"
                ),
                {"fid": folder_id, "cur": legacy_cursor},
            )

        with pytest.raises(SchemaValidationError, match="not supported") as excinfo:
            run_migration(db_url)
        assert "Restore the pre-upgrade sealed backup" in str(excinfo.value)

        with engine.connect() as conn:
            assert "folder_patrol_status" not in set(inspect(conn).get_table_names())
            cursor = conn.execute(
                text("SELECT cursor FROM sync_checkpoints WHERE folder_id = :fid"),
                {"fid": folder_id},
            ).scalar_one()
            assert cursor == json.loads(legacy_cursor)
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars().all() == ["20261027_0029"]
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS sync_checkpoints"))
            conn.execute(text("DROP TABLE IF EXISTS folders"))
            conn.execute(text("DELETE FROM alembic_version"))
        with engine.connect() as conn:
            command.upgrade(cfg, "head")


def test_stamp_unified_baseline_executes_real_insert_on_postgres():
    """stamp_unified_baseline performs a real INSERT on PostgreSQL.

    The head database is already stamped, so alembic_version is cleared first
    to force the INSERT branch to run against real DDL instead of a no-op.
    """
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM alembic_version"))

    with engine.connect() as conn:
        stamp_unified_baseline(conn, dry_run=False)
        conn.commit()
        versions = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalars().all()
    assert versions == [UNIFIED_BASELINE_REVISION]


def test_patrol_status_migration_executes_on_real_postgres():
    """The patrol data migration runs against a real JSONB PostgreSQL column.

    The unit suite only asserts the emitted SQL strings; here the INSERT ...
    ON CONFLICT and cursor-minus-ARRAY statements actually execute, and the
    migrated row and cleaned cursor are read back from the database. No legacy
    schema upgrade is performed.
    """
    engine = get_engine()
    Session = get_session_factory()
    with Session() as session:
        account = Account(
            email=f"patrol-{uuid.uuid4().hex[:8]}@example.com",
            provider="imap",
        )
        session.add(account)
        session.commit()
        account_id = account.id
        folder = Folder(
            account_id=account_id,
            remote_id="INBOX",
            name="Inbox",
            role="inbox",
        )
        session.add(folder)
        session.commit()
        folder_id = folder.id

    cursor_value = {
        "last_status": {"folder_path": "/Inbox", "uidvalidity": 12345},
        "last_probe_at": 1700000000,
        "last_probe_failures": 3,
        "delta_token": "token-xyz",
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sync_checkpoints (account_id, folder_id, cursor) "
                "VALUES (:acc, :folder, CAST(:cur AS jsonb))"
            ),
            {"acc": account_id, "folder": folder_id, "cur": json.dumps(cursor_value)},
        )

    with engine.connect() as conn:
        migrate_patrol_status_data(conn, dry_run=False)
        conn.commit()

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT last_status, last_probe_at, last_probe_failures "
                "FROM folder_patrol_status WHERE folder_id = :folder"
            ),
            {"folder": folder_id},
        ).one()
        assert row[0] == {"folder_path": "/Inbox", "uidvalidity": 12345}
        assert row[1] is not None
        assert row[2] == 3
        remaining = conn.execute(
            text("SELECT cursor FROM sync_checkpoints WHERE folder_id = :folder"),
            {"folder": folder_id},
        ).scalar_one()
        assert remaining == {"delta_token": "token-xyz"}
