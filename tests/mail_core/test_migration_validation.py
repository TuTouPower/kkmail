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

from mail_core.db import baseline
from mail_core.db.baseline import (
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


# --- AC-006: Narrow legacy conversion guarantees on real PostgreSQL ------------

# Frozen literal: the 0030-era schema, transcribed from the deleted
# incremental migrations (same frozen text as
# tests/mail_core/test_startup_migrations.py::_DDL_0030_TABLES, duplicated
# here so each suite stays independent). Never generated from
# REQUIRED_COLUMNS.
_PG_0030_DDL: tuple[str, ...] = (
    "CREATE TABLE account_groups (id UUID NOT NULL, name VARCHAR(128), color VARCHAR(32), sort_order INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_account_groups PRIMARY KEY (id), CONSTRAINT uq_account_groups_name UNIQUE (name))",
    "CREATE TABLE credential_secrets (ref TEXT NOT NULL, key_version INTEGER NOT NULL, nonce BYTEA NOT NULL, ciphertext BYTEA NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_credential_secrets PRIMARY KEY (ref))",
    "CREATE TABLE app_settings (key VARCHAR(128) NOT NULL, value TEXT NOT NULL DEFAULT '', updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_app_settings PRIMARY KEY (key))",
    "CREATE TABLE auth_credentials (id VARCHAR(64) NOT NULL, login_password_hash VARCHAR(255), session_epoch INTEGER NOT NULL DEFAULT 1, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_auth_credentials PRIMARY KEY (id))",
    "CREATE TABLE accounts (id UUID NOT NULL, email VARCHAR(320) NOT NULL, provider VARCHAR(32) NOT NULL, display_name VARCHAR(255), credential_ref VARCHAR(512), group_id UUID, master_order INTEGER, group_order INTEGER, sync_enabled BOOLEAN NOT NULL DEFAULT true, sync_status VARCHAR(32) NOT NULL DEFAULT 'idle', config JSONB NOT NULL DEFAULT '{}', recipient_addresses JSONB NOT NULL DEFAULT '[]', created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_accounts PRIMARY KEY (id), CONSTRAINT uq_accounts_email UNIQUE (email), CONSTRAINT fk_accounts_group_id FOREIGN KEY (group_id) REFERENCES account_groups (id) ON DELETE SET NULL)",
    "CREATE TABLE account_sync_leases (account_id UUID NOT NULL, owner_id VARCHAR(128) NOT NULL, lease_expires_at TIMESTAMPTZ NOT NULL, heartbeat_at TIMESTAMPTZ NOT NULL, fencing_token BIGINT NOT NULL DEFAULT 0, CONSTRAINT pk_account_sync_leases PRIMARY KEY (account_id), CONSTRAINT fk_leases_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE)",
    "CREATE TABLE account_sync_activity (account_id UUID NOT NULL, last_foreground_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL, CONSTRAINT pk_account_sync_activity PRIMARY KEY (account_id), CONSTRAINT fk_activity_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE)",
    "CREATE TABLE folders (id UUID NOT NULL, account_id UUID NOT NULL, remote_id VARCHAR(512) NOT NULL, name VARCHAR(512) NOT NULL, role VARCHAR(32) NOT NULL DEFAULT 'other', parent_remote_id VARCHAR(512), sync_status VARCHAR(32) NOT NULL DEFAULT 'idle', created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_folders PRIMARY KEY (id), CONSTRAINT uq_folders_account_remote UNIQUE (account_id, remote_id), CONSTRAINT fk_folders_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE)",
    "CREATE TABLE threads (id UUID NOT NULL, account_id UUID NOT NULL, provider_thread_key VARCHAR(512), subject_norm VARCHAR(998), sort_time TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_threads PRIMARY KEY (id), CONSTRAINT uq_threads_account_provider_key UNIQUE (account_id, provider_thread_key), CONSTRAINT fk_threads_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE)",
    "CREATE TABLE messages (id UUID NOT NULL, account_id UUID NOT NULL, remote_id VARCHAR(512), internet_message_id VARCHAR(998), thread_id UUID, subject TEXT NOT NULL DEFAULT '', from_address VARCHAR(320) NOT NULL DEFAULT '', from_name VARCHAR(255), to_addresses JSONB NOT NULL DEFAULT '[]', cc_addresses JSONB NOT NULL DEFAULT '[]', sort_time TIMESTAMPTZ, is_read BOOLEAN, is_flagged BOOLEAN, has_attachments BOOLEAN, snippet TEXT, size_bytes BIGINT, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_messages PRIMARY KEY (id), CONSTRAINT uq_messages_account_remote UNIQUE (account_id, remote_id), CONSTRAINT fk_messages_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE, CONSTRAINT fk_messages_thread FOREIGN KEY (thread_id) REFERENCES threads (id) ON DELETE SET NULL)",
    "CREATE TABLE message_locations (id UUID NOT NULL, message_id UUID NOT NULL, folder_id UUID NOT NULL, uid BIGINT, CONSTRAINT pk_message_locations PRIMARY KEY (id), CONSTRAINT uq_message_locations UNIQUE (message_id, folder_id), CONSTRAINT fk_locations_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE, CONSTRAINT fk_locations_folder FOREIGN KEY (folder_id) REFERENCES folders (id) ON DELETE CASCADE)",
    "CREATE TABLE message_bodies (message_id UUID NOT NULL, text_plain TEXT, text_html TEXT, parse_error TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_message_bodies PRIMARY KEY (message_id), CONSTRAINT fk_bodies_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE)",
    "CREATE TABLE message_blobs (id UUID NOT NULL, content_sha256 VARCHAR(64) NOT NULL, key_version INTEGER NOT NULL DEFAULT 1, size_bytes BIGINT NOT NULL, storage_path VARCHAR(1024) NOT NULL, ref_count INTEGER NOT NULL DEFAULT 1, gc_eligible_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_message_blobs PRIMARY KEY (id), CONSTRAINT uq_message_blobs_hash_key UNIQUE (content_sha256, key_version), CONSTRAINT ck_message_blobs_ref_count_nonnegative CHECK (ref_count >= 0))",
    "CREATE TABLE message_blob_links (message_id UUID NOT NULL, blob_id UUID NOT NULL, CONSTRAINT pk_message_blob_links PRIMARY KEY (message_id), CONSTRAINT fk_links_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE, CONSTRAINT fk_links_blob FOREIGN KEY (blob_id) REFERENCES message_blobs (id) ON DELETE RESTRICT)",
    "CREATE TABLE attachments (id UUID NOT NULL, message_id UUID NOT NULL, blob_id UUID, part_id VARCHAR(64), filename VARCHAR(512) NOT NULL, content_type VARCHAR(255), size_bytes BIGINT, content_id VARCHAR(255), is_inline BOOLEAN NOT NULL DEFAULT false, CONSTRAINT pk_attachments PRIMARY KEY (id), CONSTRAINT uq_attachments_message_part UNIQUE (message_id, part_id), CONSTRAINT fk_attachments_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE, CONSTRAINT fk_attachments_blob FOREIGN KEY (blob_id) REFERENCES message_blobs (id) ON DELETE SET NULL)",
    "CREATE TABLE thread_messages (id UUID NOT NULL, thread_id UUID NOT NULL, message_id UUID NOT NULL, position INTEGER NOT NULL DEFAULT 0, CONSTRAINT pk_thread_messages PRIMARY KEY (id), CONSTRAINT uq_thread_messages UNIQUE (thread_id, message_id), CONSTRAINT fk_tm_thread FOREIGN KEY (thread_id) REFERENCES threads (id) ON DELETE CASCADE, CONSTRAINT fk_tm_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE)",
    "CREATE TABLE sync_checkpoints (account_id UUID NOT NULL, folder_id UUID NOT NULL, cursor JSONB NOT NULL DEFAULT '{}', uidvalidity BIGINT, modseq BIGINT, history_id VARCHAR(128), delta_link TEXT, full_scan_complete BOOLEAN NOT NULL DEFAULT false, scan_generation UUID, fencing_token BIGINT NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_sync_checkpoints PRIMARY KEY (account_id, folder_id), CONSTRAINT fk_checkpoints_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE, CONSTRAINT fk_checkpoints_folder FOREIGN KEY (folder_id) REFERENCES folders (id) ON DELETE CASCADE)",
    "CREATE TABLE sync_runs (id UUID NOT NULL, account_id UUID NOT NULL, folder_id UUID, phase VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL, stats JSONB NOT NULL DEFAULT '{}', error TEXT, fencing_token BIGINT, started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TIMESTAMPTZ, CONSTRAINT pk_sync_runs PRIMARY KEY (id), CONSTRAINT fk_runs_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE, CONSTRAINT fk_runs_folder FOREIGN KEY (folder_id) REFERENCES folders (id) ON DELETE SET NULL)",
    "CREATE TABLE remote_operations (id UUID NOT NULL, account_id UUID NOT NULL, entity_key VARCHAR(512) NOT NULL, op_type VARCHAR(64) NOT NULL, desired_state JSONB NOT NULL DEFAULT '{}', status VARCHAR(32) NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, next_attempt_at TIMESTAMPTZ, idempotency_key VARCHAR(128), created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_remote_operations PRIMARY KEY (id), CONSTRAINT uq_remote_operations_idempotency UNIQUE (idempotency_key), CONSTRAINT fk_remote_ops_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE)",
    "CREATE TABLE folder_stats (folder_id UUID NOT NULL, total_count INTEGER NOT NULL DEFAULT 0, unread_count INTEGER, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_folder_stats PRIMARY KEY (folder_id), CONSTRAINT fk_stats_folder FOREIGN KEY (folder_id) REFERENCES folders (id) ON DELETE CASCADE)",
    "CREATE TABLE outbox_publication_state (id INTEGER NOT NULL, epoch UUID NOT NULL, next_seq BIGINT NOT NULL DEFAULT 1, pruned_through_seq BIGINT NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_outbox_publication_state PRIMARY KEY (id), CONSTRAINT ck_outbox_publication_state_singleton CHECK (id = 1))",
    "CREATE TABLE outbox (id BIGINT NOT NULL, event_type VARCHAR(64) NOT NULL, account_id UUID, payload JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, publication_seq BIGINT, published_at TIMESTAMPTZ, CONSTRAINT pk_outbox PRIMARY KEY (id), CONSTRAINT fk_outbox_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE SET NULL)",
    "CREATE TABLE message_archive_state (message_id UUID NOT NULL, claim_revision BIGINT NOT NULL DEFAULT 0, state VARCHAR(32) NOT NULL DEFAULT 'metadata_synced', priority INTEGER NOT NULL DEFAULT 2, retry_count INTEGER NOT NULL DEFAULT 0, pause_reason VARCHAR(255), last_error TEXT, claimed_by VARCHAR(128), claimed_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_message_archive_state PRIMARY KEY (message_id), CONSTRAINT fk_archive_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE, CONSTRAINT ck_message_archive_state_state_valid CHECK (state IN ('metadata_synced', 'archive_pending', 'archive_in_progress', 'archive_paused_quota', 'archive_failed', 'archive_complete')))",
    "CREATE TABLE worker_jobs (id UUID NOT NULL, execution_generation UUID NOT NULL, job_type VARCHAR(64) NOT NULL, account_id UUID, dedupe_key VARCHAR(128), payload JSONB NOT NULL DEFAULT '{}', status VARCHAR(32) NOT NULL DEFAULT 'pending', priority INTEGER NOT NULL DEFAULT 100, run_after TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, attempts INTEGER NOT NULL DEFAULT 0, failure_attempts INTEGER NOT NULL DEFAULT 0, locked_by VARCHAR(128), locked_at TIMESTAMPTZ, last_error TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_worker_jobs PRIMARY KEY (id), CONSTRAINT uq_worker_jobs_execution_generation UNIQUE (execution_generation), CONSTRAINT fk_jobs_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE)",
    "CREATE TABLE message_search (message_id UUID NOT NULL, account_id UUID NOT NULL, subject TEXT NOT NULL DEFAULT '', from_text TEXT NOT NULL DEFAULT '', to_text TEXT NOT NULL DEFAULT '', body_text TEXT NOT NULL DEFAULT '', document TEXT NOT NULL DEFAULT '', updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_message_search PRIMARY KEY (message_id), CONSTRAINT fk_search_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE, CONSTRAINT fk_search_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE)",
    "CREATE TABLE blob_quota_reservations (id UUID NOT NULL, worker_id VARCHAR(128) NOT NULL, message_id UUID, reserved_bytes BIGINT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, expires_at TIMESTAMPTZ NOT NULL, CONSTRAINT pk_blob_quota PRIMARY KEY (id), CONSTRAINT fk_quota_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE, CONSTRAINT ck_blob_quota_reservations_reserved_bytes_positive CHECK (reserved_bytes > 0))",
    "CREATE TABLE sync_requests (id UUID NOT NULL, client_request_id VARCHAR(64) NOT NULL, mode VARCHAR(32) NOT NULL, trigger VARCHAR(32) NOT NULL, state VARCHAR(32) NOT NULL DEFAULT 'queued', scope JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TIMESTAMPTZ, CONSTRAINT pk_sync_requests PRIMARY KEY (id), CONSTRAINT uq_sync_requests_client UNIQUE (client_request_id))",
    "CREATE TABLE sync_request_targets (id UUID NOT NULL, request_id UUID NOT NULL, account_id UUID, folder_id UUID, current_job_id UUID, target_key VARCHAR(255) NOT NULL, requested_generation UUID NOT NULL, state VARCHAR(32) NOT NULL DEFAULT 'queued', error_code VARCHAR(64), safe_error VARCHAR(500), created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TIMESTAMPTZ, CONSTRAINT pk_sync_request_targets PRIMARY KEY (id), CONSTRAINT uq_sync_targets_request_key UNIQUE (request_id, target_key), CONSTRAINT fk_targets_request FOREIGN KEY (request_id) REFERENCES sync_requests (id) ON DELETE CASCADE, CONSTRAINT fk_targets_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE SET NULL, CONSTRAINT fk_targets_folder FOREIGN KEY (folder_id) REFERENCES folders (id) ON DELETE SET NULL, CONSTRAINT fk_targets_job FOREIGN KEY (current_job_id) REFERENCES worker_jobs (id) ON DELETE SET NULL)",
    "CREATE TABLE sync_request_target_jobs (id UUID NOT NULL, target_id UUID NOT NULL, execution_generation UUID NOT NULL, job_id UUID, phase VARCHAR(64) NOT NULL DEFAULT 'sync', folder_id UUID, status VARCHAR(32) NOT NULL DEFAULT 'queued', error_code VARCHAR(64), safe_error VARCHAR(500), created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, finished_at TIMESTAMPTZ, CONSTRAINT pk_sync_request_target_jobs PRIMARY KEY (id), CONSTRAINT uq_sync_target_jobs_target_generation UNIQUE (target_id, execution_generation), CONSTRAINT fk_target_jobs_target FOREIGN KEY (target_id) REFERENCES sync_request_targets (id) ON DELETE CASCADE, CONSTRAINT fk_target_jobs_job FOREIGN KEY (job_id) REFERENCES worker_jobs (id) ON DELETE SET NULL, CONSTRAINT fk_target_jobs_folder FOREIGN KEY (folder_id) REFERENCES folders (id) ON DELETE SET NULL)",
    "CREATE TABLE message_remote_image_allows (message_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_message_remote_image_allows PRIMARY KEY (message_id), CONSTRAINT fk_mria_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE)",
    "CREATE TABLE sender_remote_image_allows (id UUID NOT NULL, from_address VARCHAR(320) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_sender_remote_image_allows PRIMARY KEY (id), CONSTRAINT uq_sender_remote_image_allows_from_address UNIQUE (from_address))",
)

_PG_0030_EXTRA_TABLES = ("folder_patrol_status",)


def _pg_build_0030_shape(engine) -> tuple[uuid.UUID, uuid.UUID]:
    """Create the frozen 0030 schema plus one patrol-bearing checkpoint row on PostgreSQL."""
    account_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    cursor_value = {
        "last_status": {"folder_path": "/Inbox", "uidvalidity": 12345},
        "last_probe_at": 1700000000,
        "last_probe_failures": 3,
        "delta_token": "token-xyz",
    }
    with engine.begin() as conn:
        for stmt in _PG_0030_DDL:
            conn.execute(text(stmt))
        conn.execute(text("DELETE FROM alembic_version"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('20261031_0030')"))
        conn.execute(
            text("INSERT INTO accounts (id, email, provider) VALUES (:acc, 'legacy@example.com', 'imap')"),
            {"acc": account_id},
        )
        conn.execute(
            text(
                "INSERT INTO folders (id, account_id, remote_id, name) "
                "VALUES (:folder, :acc, 'INBOX', 'Inbox')"
            ),
            {"folder": folder_id, "acc": account_id},
        )
        conn.execute(
            text(
                "INSERT INTO sync_checkpoints (account_id, folder_id, cursor) "
                "VALUES (:acc, :folder, CAST(:cur AS jsonb))"
            ),
            {"acc": account_id, "folder": folder_id, "cur": json.dumps(cursor_value)},
        )
    return account_id, folder_id


def _pg_restore_head(cfg, engine) -> None:
    """Drop the synthetic 0030 shape and rebuild the real head schema."""
    tables = (
        "account_groups credential_secrets app_settings auth_credentials accounts "
        "account_sync_leases account_sync_activity folders threads messages "
        "message_locations message_bodies message_blobs message_blob_links attachments "
        "thread_messages sync_checkpoints sync_runs remote_operations folder_stats "
        "folder_patrol_status outbox_publication_state outbox message_archive_state "
        "worker_jobs message_search blob_quota_reservations sync_requests "
        "sync_request_targets sync_request_target_jobs message_remote_image_allows "
        "sender_remote_image_allows"
    )
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {tables.replace(' ', ', ')} CASCADE"))
        conn.execute(text("DELETE FROM alembic_version"))
    with engine.connect() as conn:
        command.upgrade(cfg, "head")


def test_narrow_conversion_failure_rolls_back_on_postgres(monkeypatch):
    """A mid-conversion failure on PostgreSQL rolls back DDL, data, and revision."""
    cfg = _get_alembic_config()
    engine = get_engine()
    db_url = os.environ["MAIL_CORE_DATABASE_URL"]

    with engine.connect() as conn:
        command.downgrade(cfg, "base")

    try:
        account_id, folder_id = _pg_build_0030_shape(engine)

        real_migrate = baseline.migrate_patrol_status_data

        def _boom(bind, *, dry_run: bool = False):
            real_migrate(bind, dry_run=dry_run)
            raise RuntimeError("injected mid-conversion failure")

        monkeypatch.setattr(baseline, "migrate_patrol_status_data", _boom)
        with pytest.raises(RuntimeError, match="injected mid-conversion failure"):
            baseline.apply_narrow_legacy_conversion(db_url)

        with engine.connect() as conn:
            assert "folder_patrol_status" not in set(inspect(conn).get_table_names())
            cursor = conn.execute(
                text("SELECT cursor FROM sync_checkpoints WHERE folder_id = :folder"),
                {"folder": folder_id},
            ).scalar_one()
            assert cursor == {
                "last_status": {"folder_path": "/Inbox", "uidvalidity": 12345},
                "last_probe_at": 1700000000,
                "last_probe_failures": 3,
                "delta_token": "token-xyz",
            }
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars().all() == ["20261031_0030"]
    finally:
        monkeypatch.undo()
        _pg_restore_head(cfg, engine)


def test_check_connection_is_read_only_on_postgres():
    """The check connection refuses writes on PostgreSQL without modifying the database."""
    engine = get_engine()
    db_url = os.environ["MAIL_CORE_DATABASE_URL"]
    before = set(inspect(engine).get_table_names())

    with baseline.read_only_connection(db_url) as conn:
        with pytest.raises(Exception, match="(?i)read.only"):
            conn.execute(text("CREATE TABLE _should_never_exist (id INTEGER PRIMARY KEY)"))

    with engine.connect() as conn:
        assert "_should_never_exist" not in set(inspect(conn).get_table_names())
        assert set(inspect(conn).get_table_names()) == before


def test_concurrent_narrow_conversion_is_serialized_on_postgres():
    """Two concurrent converters serialize: one converts, the other becomes a no-op."""
    import threading

    cfg = _get_alembic_config()
    engine = get_engine()
    db_url = os.environ["MAIL_CORE_DATABASE_URL"]

    with engine.connect() as conn:
        command.downgrade(cfg, "base")

    try:
        _account_id, folder_id = _pg_build_0030_shape(engine)

        outcomes: list = []

        def _worker() -> None:
            try:
                outcomes.append(baseline.apply_narrow_legacy_conversion(db_url))
            except Exception as exc:  # pragma: no cover - serialized path must not fail
                outcomes.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)

        assert sorted(str(outcome) for outcome in outcomes) == [
            "already-at-baseline",
            "converted",
        ]

        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars().all() == [UNIFIED_BASELINE_REVISION]
            rows = conn.execute(
                text(
                    "SELECT folder_id, last_status, last_probe_failures "
                    "FROM folder_patrol_status"
                )
            ).all()
            assert len(rows) == 1
            assert rows[0][0] == folder_id
            assert rows[0][1] == {"folder_path": "/Inbox", "uidvalidity": 12345}
            assert rows[0][2] == 3
            remaining = conn.execute(
                text("SELECT cursor FROM sync_checkpoints WHERE folder_id = :folder"),
                {"folder": folder_id},
            ).scalar_one()
            assert remaining == {"delta_token": "token-xyz"}
    finally:
        _pg_restore_head(cfg, engine)
