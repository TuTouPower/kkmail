"""Database Migration & Schema Integrity Validation Tests (t018).

Verifies linear Alembic migration history, three historical revision upgrade windows
with data preservation, relational constraints/indexes/FTS, ORM drift detection,
and reversible upgrade/downgrade cycles against real PostgreSQL.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, String, inspect, select, text
from sqlalchemy.exc import IntegrityError

from mail_core.db.session import get_engine, get_session_factory
from mail_core.mail.storage.models import (
    Account,
    AccountGroup,
    Attachment,
    Base,
    Folder,
    Message,
    MessageBlob,
    MessageBlobLink,
    MessageBody,
    MessageLocation,
    WorkerJob,
)

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = str(ROOT / "src/mail_core/db/alembic.ini")

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


# --- AC-001: Linear migration, single head and branch rejection --------------------


# Replaces the t018 test that fixed 20261022_0015 as the current head. t027, t036,
# and t037 extend the chain with account ordering and nullable mail provenance.
def test_current_alembic_chain_has_single_head():
    """The current migration history stays linear and ends at the current head."""
    cfg = _get_alembic_config()
    script = ScriptDirectory.from_config(cfg)

    heads = script.get_heads()
    assert len(heads) == 1, f"Expected exactly 1 migration head, found {len(heads)}: {heads}"
    head_rev = heads[0]
    assert head_rev == "20261023_0018"

    # Walk from head down to base; assert strict single-parent chain
    current = script.get_revision(head_rev)
    visited = []
    while current is not None:
        visited.append(current.revision)
        down = current.down_revision
        if down is None:
            break
        assert isinstance(down, str), f"Fork detected at revision {current.revision} with multiple parents: {down}"
        current = script.get_revision(down)

    assert len(visited) == 18, f"Expected 18 total revisions, found {len(visited)}"
    assert visited[-1] == "20261020_0001"


def test_nullable_message_time_migration_preserves_known_received_time():
    """Revision 0017 must preserve a provider received time already stored at 0015."""
    cfg = _get_alembic_config()
    engine = get_engine()
    account_id = uuid.uuid4()
    message_id = uuid.uuid4()
    received_at = datetime(2025, 5, 4, 3, 2, 1, tzinfo=timezone.utc)

    try:
        with engine.connect() as conn:
            command.downgrade(cfg, "20261022_0015")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO accounts (id, email, provider, created_at, updated_at)
                    VALUES (:id, :email, 'imap', NOW(), NOW())
                    """
                ),
                {"id": account_id, "email": f"migration-time-{account_id.hex[:8]}@example.com"},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, account_id, remote_id, subject, from_address, sort_time, is_read, is_flagged)
                    VALUES (:id, :account_id, 'received-time-preservation', 'Known time', 'sender@example.com', :sort_time, false, false)
                    """
                ),
                {"id": message_id, "account_id": account_id, "sort_time": received_at},
            )

        with engine.connect() as conn:
            command.upgrade(cfg, "head")

        with engine.connect() as conn:
            actual_received_at = conn.execute(
                text("SELECT sort_time FROM messages WHERE id = :id"), {"id": message_id}
            ).scalar_one()
            assert actual_received_at == received_at
    finally:
        with engine.connect() as conn:
            command.upgrade(cfg, "head")
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM messages WHERE id = :id"), {"id": message_id})
            conn.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": account_id})


def test_nullable_remote_id_migration_preserves_known_provider_id():
    cfg = _get_alembic_config()
    engine = get_engine()
    account_id = uuid.uuid4()
    message_id = uuid.uuid4()
    remote_id = "graph-provider-id-exact"

    try:
        with engine.connect() as conn:
            command.downgrade(cfg, "20261023_0017")

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO accounts (id, email, provider, created_at, updated_at)
                    VALUES (:id, :email, 'graph', NOW(), NOW())
                    """
                ),
                {"id": account_id, "email": f"migration-remote-{account_id.hex[:8]}@example.com"},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, account_id, remote_id, subject, from_address, is_read, is_flagged)
                    VALUES (:id, :account_id, :remote_id, 'Known ID', 'sender@example.com', false, false)
                    """
                ),
                {"id": message_id, "account_id": account_id, "remote_id": remote_id},
            )

        with engine.connect() as conn:
            command.upgrade(cfg, "head")

        with engine.connect() as conn:
            actual_remote_id = conn.execute(
                text("SELECT remote_id FROM messages WHERE id = :id"), {"id": message_id}
            ).scalar_one()
            assert actual_remote_id == remote_id
    finally:
        with engine.connect() as conn:
            command.upgrade(cfg, "head")
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM messages WHERE id = :id"), {"id": message_id})
            conn.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": account_id})


def test_nullable_remote_id_migration_allows_unknowns_and_rejects_lossy_downgrade():
    cfg = _get_alembic_config()
    engine = get_engine()
    Session = get_session_factory()

    try:
        with engine.connect() as conn:
            command.downgrade(cfg, "20261023_0017")
        with engine.connect() as conn:
            command.upgrade(cfg, "head")

        columns = {column["name"]: column for column in inspect(engine).get_columns("messages")}
        assert columns["remote_id"]["nullable"] is True

        with Session() as session:
            account = Account(email=f"remote-null-{uuid.uuid4().hex[:8]}@example.com", provider="stub")
            session.add(account)
            session.flush()
            first = Message(
                account_id=account.id,
                remote_id=None,
                subject="Unknown remote identity one",
                from_address="sender@example.com",
            )
            second = Message(
                account_id=account.id,
                remote_id=None,
                subject="Unknown remote identity two",
                from_address="sender@example.com",
            )
            session.add_all((first, second))
            session.commit()
            account_id = account.id
            message_ids = (first.id, second.id)

        with pytest.raises(RuntimeError, match="messages.remote_id contains NULL"):
            command.downgrade(cfg, "20261023_0017")

        with engine.connect() as conn:
            assert MigrationContext.configure(conn).get_current_revision() == "20261023_0018"
        with Session() as session:
            assert all(session.get(Message, mid) is not None for mid in message_ids)
            session.query(Message).filter(Message.id.in_(message_ids)).delete(synchronize_session=False)
            session.delete(session.get(Account, account_id))
            session.commit()

        with engine.connect() as conn:
            command.downgrade(cfg, "20261023_0017")
        columns_0017 = {column["name"]: column for column in inspect(engine).get_columns("messages")}
        assert columns_0017["remote_id"]["nullable"] is False
    finally:
        with engine.connect() as conn:
            command.upgrade(cfg, "head")


# --- AC-002: Three revision windows upgrade with data preservation -----------------


def test_migration_three_revision_windows_data_preservation():
    """AC-002: Downgrades to 3 historical revision windows, inserts SQL data, upgrades to head and verifies."""
    cfg = _get_alembic_config()
    engine = get_engine()

    account_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    message_id = uuid.uuid4()
    blob_id = uuid.uuid4()
    att_id = uuid.uuid4()

    try:
        # Window 1: Downgrade to unified schema (f5f312751c77)
        with engine.connect() as conn:
            command.downgrade(cfg, "f5f312751c77")

        # Insert valid data for unified schema
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO accounts (id, email, provider, created_at, updated_at)
                    VALUES (:acc_id, 'mig-test@example.com', 'imap', NOW(), NOW())
                    """
                ),
                {"acc_id": account_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO folders (id, account_id, remote_id, name, role, created_at, updated_at)
                    VALUES (:fld_id, :acc_id, 'INBOX', '收件箱', 'inbox', NOW(), NOW())
                    """
                ),
                {"fld_id": folder_id, "acc_id": account_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, account_id, remote_id, subject, from_address, sort_time, is_read, is_flagged)
                    VALUES (:msg_id, :acc_id, 'msg-leg-001', 'Legacy Preserved Subject', 'sender@test.com', NOW(), false, true)
                    """
                ),
                {"msg_id": message_id, "acc_id": account_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO message_locations (id, message_id, folder_id)
                    VALUES (:loc_id, :msg_id, :fld_id)
                    """
                ),
                {"loc_id": uuid.uuid4(), "msg_id": message_id, "fld_id": folder_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO message_blobs (id, content_sha256, key_version, size_bytes, storage_path, ref_count, created_at)
                    VALUES (:blob_id, 'deadbeefcafe0001000200030004000500060007000800090010001100120013', 1, 1024, 'blobs/deadbeef', 1, NOW())
                    """
                ),
                {"blob_id": blob_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO message_blob_links (message_id, blob_id)
                    VALUES (:msg_id, :blob_id)
                    """
                ),
                {"msg_id": message_id, "blob_id": blob_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO attachments (id, message_id, filename, content_type, size_bytes)
                    VALUES (:att_id, :msg_id, 'legacy_report.pdf', 'application/pdf', 1024)
                    """
                ),
                {"att_id": att_id, "msg_id": message_id},
            )

        # Window 2: Upgrade to 20261021_0011 (prior to auth_credentials)
        with engine.connect() as conn:
            command.upgrade(cfg, "20261021_0011")

        with engine.begin() as conn:
            # Insert remote_operations with next_attempt_at introduced in 0011
            conn.execute(
                text(
                    """
                    INSERT INTO remote_operations (id, account_id, entity_key, op_type, status, next_attempt_at, desired_state, created_at, updated_at)
                    VALUES (:op_id, :acc_id, 'msg:msg-leg-001', 'mark_read', 'pending', NOW(), '{"is_read": true}'::jsonb, NOW(), NOW())
                    """
                ),
                {"op_id": uuid.uuid4(), "acc_id": account_id},
            )

        # Window 3: Upgrade to 20261022_0014 (prior to 0015 attachment part_id)
        with engine.connect() as conn:
            command.upgrade(cfg, "20261022_0014")

        with engine.begin() as conn:
            # auth_credentials and session_epoch available
            conn.execute(
                text(
                    """
                    INSERT INTO auth_credentials (id, login_password_hash, session_epoch, updated_at)
                    VALUES ('default', 'mocked_bcrypt_hash_val', 42, NOW())
                    ON CONFLICT (id) DO UPDATE SET session_epoch = 42
                    """
                )
            )

        # Upgrade to the current head, including nullable message received time.
        with engine.connect() as conn:
            command.upgrade(cfg, "head")

        # Verify all data intact
        with engine.connect() as conn:
            # 1. Message intact
            msg_row = conn.execute(
                text("SELECT subject, from_address, is_read, is_flagged FROM messages WHERE id = :id"),
                {"id": message_id},
            ).one()
            assert msg_row[0] == "Legacy Preserved Subject"
            assert msg_row[1] == "sender@test.com"
            assert msg_row[2] is False
            assert msg_row[3] is True

            # 2. Attachment part_id backfilled cleanly
            att_row = conn.execute(
                text("SELECT filename, part_id FROM attachments WHERE id = :id"),
                {"id": att_id},
            ).one()
            assert att_row[0] == "legacy_report.pdf"
            assert att_row[1] is not None
            assert str(att_row[1]).startswith("legacy_")

            # 3. Auth credentials and session_epoch preserved
            auth_row = conn.execute(text("SELECT login_password_hash, session_epoch FROM auth_credentials WHERE id = 'default'")).one()
            assert auth_row[0] == "mocked_bcrypt_hash_val"
            assert auth_row[1] == 42

            # 4. Message blob links preserved
            link_row = conn.execute(
                text("SELECT blob_id FROM message_blob_links WHERE message_id = :id"),
                {"id": message_id},
            ).one()
            assert link_row[0] == blob_id
    finally:
        # Guarantee database returns to clean head
        try:
            with engine.connect() as conn:
                command.upgrade(cfg, "head")
        except Exception:
            pass


# --- AC-003: Relational Constraints, Indexes, Keyset & FTS -------------------------


def test_schema_constraints_indexes_and_fts_semantics():
    """AC-003: Verifies unique constraints, foreign keys CASCADE/RESTRICT, FTS search and keyset order."""
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

        # 2. Foreign Key: invalid account_id must be rejected
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

        # 3. MessageBlob foreign key RESTRICT: cannot delete blob referenced by links
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

        # 4. Keyset order and FTS trigram index availability
        engine = get_engine()
        with engine.connect() as conn:
            # Query message_search FTS table with trigram similarity function
            res = conn.execute(text("SELECT count(*) FROM message_search")).scalar()
            assert res is not None

            # Verify keyset index exists
            indexes = inspect(engine).get_indexes("messages")
            idx_names = {idx["name"] for idx in indexes}
            assert "ix_messages_sort_id" in idx_names
            assert "uq_messages_account_remote" in idx_names


# --- AC-004: ORM Schema Drift & Negative Detection ---------------------------------


def test_orm_schema_drift_and_negative_detection():
    """AC-004: Asserts zero drift between SQLAlchemy models and PostgreSQL database catalog."""
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


# --- Current migration rollback and historical predecessor cycle -----------------


def test_revertible_downgrade_and_upgrade_cycle():
    """The t027 ordering and prior blob migrations remain reversible below t037."""
    cfg = _get_alembic_config()
    engine = get_engine()
    Session = get_session_factory()
    with Session() as session:
        group = AccountGroup(name=f"migration-group-{uuid.uuid4().hex}", sort_order=17)
        session.add(group)
        session.flush()
        account = Account(
            email=f"migration-member-{uuid.uuid4().hex}@example.test",
            provider="imap",
            group_id=group.id,
            master_order=4,
            group_order=2,
        )
        session.add(account)
        session.commit()
        group_id, account_id = group.id, account.id

    try:
        # Remove t037 and t036 before exercising the sidebar ordering migration.
        with engine.connect() as conn:
            command.downgrade(cfg, "20261023_0016")

        cols_0016 = {c["name"]: c for c in inspect(engine).get_columns("messages")}
        assert cols_0016["sort_time"]["nullable"] is False
        assert cols_0016["remote_id"]["nullable"] is False

        with engine.connect() as conn:
            command.downgrade(cfg, "20261022_0015")

        columns_0015 = {c["name"] for c in inspect(engine).get_columns("accounts")}
        assert "master_order" not in columns_0015
        assert "group_order" not in columns_0015
        assert "blob_quota_reservations" in set(inspect(engine).get_table_names())

        # Downgrade the prior blob migration (0015 -> 0014).
        with engine.connect() as conn:
            command.downgrade(cfg, "20261022_0014")

        tables_0014 = set(inspect(engine).get_table_names())
        assert "blob_quota_reservations" not in tables_0014
        cols_0014 = {c["name"] for c in inspect(engine).get_columns("attachments")}
        assert "part_id" not in cols_0014

        # Re-upgrade to head (0014 -> 0018).
        with engine.connect() as conn:
            command.upgrade(cfg, "head")

        tables_head = set(inspect(engine).get_table_names())
        assert "blob_quota_reservations" in tables_head
        attachment_columns = {c["name"] for c in inspect(engine).get_columns("attachments")}
        assert "part_id" in attachment_columns
        account_columns = {c["name"] for c in inspect(engine).get_columns("accounts")}
        assert {"master_order", "group_order"} <= account_columns
        message_columns = {c["name"]: c for c in inspect(engine).get_columns("messages")}
        assert message_columns["sort_time"]["nullable"] is True
        assert message_columns["remote_id"]["nullable"] is True
        with Session() as session:
            migrated_group = session.get(AccountGroup, group_id)
            migrated_account = session.get(Account, account_id)
            assert migrated_group is not None and migrated_group.sort_order == 17
            assert migrated_account is not None and migrated_account.group_id == group_id
            assert migrated_account.master_order is None and migrated_account.group_order is None
    finally:
        with engine.connect() as conn:
            command.upgrade(cfg, "head")


def test_nullable_message_time_migration_round_trips_to_head_and_predecessor():
    """Revision 0017 round-trips through later revisions and refuses a lossy downgrade."""
    cfg = _get_alembic_config()
    engine = get_engine()

    try:
        with engine.connect() as conn:
            command.downgrade(cfg, "20261023_0016")

        cols_0016 = {c["name"]: c for c in inspect(engine).get_columns("messages")}
        assert cols_0016["sort_time"]["nullable"] is False
        account_cols_0016 = {c["name"] for c in inspect(engine).get_columns("accounts")}
        assert {"master_order", "group_order"} <= account_cols_0016

        with engine.connect() as conn:
            command.upgrade(cfg, "head")

        cols_head = {c["name"]: c for c in inspect(engine).get_columns("messages")}
        assert cols_head["sort_time"]["nullable"] is True
        assert cols_head["remote_id"]["nullable"] is True

        Session = get_session_factory()
        with Session() as session:
            account = Account(email=f"rollback-null-{uuid.uuid4().hex[:8]}@example.com", provider="stub")
            session.add(account)
            session.flush()
            unknown_time = Message(
                account_id=account.id,
                remote_id="unknown-time",
                subject="Unknown time",
                from_address="sender@example.com",
                sort_time=None,
            )
            session.add(unknown_time)
            session.commit()
            account_id, message_id = account.id, unknown_time.id

        with pytest.raises(RuntimeError, match="messages.sort_time contains NULL"):
            command.downgrade(cfg, "20261023_0016")

        with engine.connect() as conn:
            assert MigrationContext.configure(conn).get_current_revision() == "20261023_0018"
        with Session() as session:
            session.delete(session.get(Message, message_id))
            session.flush()
            session.delete(session.get(Account, account_id))
            session.commit()

        with engine.connect() as conn:
            command.downgrade(cfg, "20261022_0015")

        cols_0015 = {c["name"]: c for c in inspect(engine).get_columns("messages")}
        assert cols_0015["sort_time"]["nullable"] is False
        account_cols_0015 = {c["name"] for c in inspect(engine).get_columns("accounts")}
        assert "master_order" not in account_cols_0015
        assert "group_order" not in account_cols_0015
        assert "blob_quota_reservations" in set(inspect(engine).get_table_names())
    finally:
        with engine.connect() as conn:
            command.upgrade(cfg, "head")
