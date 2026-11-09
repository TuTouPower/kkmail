"""Startup migration orchestration tests (single guarded entry).

Covers ``mail_core.__main__.run_migrations`` and the ``--migrate-only`` /
``--check-migrations`` flags against file-backed SQLite databases. The 0030
fixture DDL below is a frozen literal transcribed from the historical
migrations (20261020_0002 base plus the incremental adds through
20261031_0030); it is deliberately NOT generated from
``REQUIRED_COLUMNS`` so the tests cannot pass trivially.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text

from mail_core import __main__ as main_module
from mail_core.db import baseline
from mail_core.db.baseline import SchemaValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = str(REPO_ROOT / "src")

# Frozen literal: the 0030-era schema (unified baseline minus the
# folder_patrol_status table added by 0031), transcribed from the deleted
# incremental migrations. PG-style type names are intentional: SQLite stores
# them as declared and SQLAlchemy reports them back, so the same literal
# exercises the semantic type/nullable/default/constraint comparison on both
# backends.
_DDL_0030_TABLES: tuple[str, ...] = (
    "CREATE TABLE account_groups (id UUID NOT NULL, name VARCHAR(128) NOT NULL, color VARCHAR(32), sort_order INTEGER NOT NULL DEFAULT 0, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_account_groups PRIMARY KEY (id), CONSTRAINT uq_account_groups_name UNIQUE (name))",
    "CREATE TABLE credential_secrets (ref TEXT NOT NULL, key_version INTEGER NOT NULL, nonce BYTEA NOT NULL, ciphertext BYTEA NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_credential_secrets PRIMARY KEY (ref))",
    "CREATE TABLE app_settings (key VARCHAR(128) NOT NULL, value TEXT NOT NULL DEFAULT '', updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_app_settings PRIMARY KEY (key))",
    "CREATE TABLE auth_credentials (id VARCHAR(64) NOT NULL, login_password_hash VARCHAR(255), session_epoch INTEGER NOT NULL DEFAULT 1, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_auth_credentials PRIMARY KEY (id))",
    "CREATE TABLE accounts (id UUID NOT NULL, email VARCHAR(320) NOT NULL, provider VARCHAR(32) NOT NULL, display_name VARCHAR(255), credential_ref VARCHAR(512), group_id UUID, master_order INTEGER, group_order INTEGER, sync_enabled BOOLEAN NOT NULL DEFAULT 1, sync_status VARCHAR(32) NOT NULL DEFAULT 'idle', config JSONB NOT NULL DEFAULT '{}', recipient_addresses JSONB NOT NULL DEFAULT '[]', created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_accounts PRIMARY KEY (id), CONSTRAINT uq_accounts_email UNIQUE (email), CONSTRAINT fk_accounts_group_id FOREIGN KEY (group_id) REFERENCES account_groups (id) ON DELETE SET NULL)",
    "CREATE TABLE account_sync_leases (account_id UUID NOT NULL, owner_id VARCHAR(128) NOT NULL, lease_expires_at TIMESTAMPTZ NOT NULL, heartbeat_at TIMESTAMPTZ NOT NULL, fencing_token BIGINT NOT NULL DEFAULT 0, CONSTRAINT pk_account_sync_leases PRIMARY KEY (account_id), CONSTRAINT fk_leases_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE)",
    "CREATE TABLE account_sync_activity (account_id UUID NOT NULL, last_foreground_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ NOT NULL, CONSTRAINT pk_account_sync_activity PRIMARY KEY (account_id), CONSTRAINT fk_activity_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE)",
    "CREATE TABLE folders (id UUID NOT NULL, account_id UUID NOT NULL, remote_id VARCHAR(512) NOT NULL, name VARCHAR(512) NOT NULL, role VARCHAR(32) NOT NULL DEFAULT 'other', parent_remote_id VARCHAR(512), sync_status VARCHAR(32) NOT NULL DEFAULT 'idle', created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_folders PRIMARY KEY (id), CONSTRAINT uq_folders_account_remote UNIQUE (account_id, remote_id), CONSTRAINT fk_folders_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE)",
    "CREATE TABLE threads (id UUID NOT NULL, account_id UUID NOT NULL, provider_thread_key VARCHAR(512), subject_norm VARCHAR(998), sort_time TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_threads PRIMARY KEY (id), CONSTRAINT uq_threads_account_provider_key UNIQUE (account_id, provider_thread_key), CONSTRAINT fk_threads_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE)",
    "CREATE TABLE messages (id UUID NOT NULL, account_id UUID NOT NULL, remote_id VARCHAR(512), internet_message_id VARCHAR(998), thread_id UUID, subject TEXT NOT NULL DEFAULT '', from_address VARCHAR(320) NOT NULL DEFAULT '', from_name VARCHAR(255), to_addresses JSONB NOT NULL DEFAULT '[]', cc_addresses JSONB NOT NULL DEFAULT '[]', sort_time TIMESTAMPTZ, is_read BOOLEAN, is_flagged BOOLEAN, has_attachments BOOLEAN, snippet TEXT, size_bytes BIGINT, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_messages PRIMARY KEY (id), CONSTRAINT uq_messages_account_remote UNIQUE (account_id, remote_id), CONSTRAINT fk_messages_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE, CONSTRAINT fk_messages_thread FOREIGN KEY (thread_id) REFERENCES threads (id) ON DELETE SET NULL)",
    "CREATE TABLE message_locations (id UUID NOT NULL, message_id UUID NOT NULL, folder_id UUID NOT NULL, uid BIGINT, CONSTRAINT pk_message_locations PRIMARY KEY (id), CONSTRAINT uq_message_locations UNIQUE (message_id, folder_id), CONSTRAINT fk_locations_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE, CONSTRAINT fk_locations_folder FOREIGN KEY (folder_id) REFERENCES folders (id) ON DELETE CASCADE)",
    "CREATE TABLE message_bodies (message_id UUID NOT NULL, text_plain TEXT, text_html TEXT, parse_error TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_message_bodies PRIMARY KEY (message_id), CONSTRAINT fk_bodies_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE)",
    "CREATE TABLE message_blobs (id UUID NOT NULL, content_sha256 VARCHAR(64) NOT NULL, key_version INTEGER NOT NULL DEFAULT 1, size_bytes BIGINT NOT NULL, storage_path VARCHAR(1024) NOT NULL, ref_count INTEGER NOT NULL DEFAULT 1, gc_eligible_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_message_blobs PRIMARY KEY (id), CONSTRAINT uq_message_blobs_hash_key UNIQUE (content_sha256, key_version), CONSTRAINT ck_message_blobs_ref_count_nonnegative CHECK (ref_count >= 0))",
    "CREATE TABLE message_blob_links (message_id UUID NOT NULL, blob_id UUID NOT NULL, CONSTRAINT pk_message_blob_links PRIMARY KEY (message_id), CONSTRAINT fk_links_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE, CONSTRAINT fk_links_blob FOREIGN KEY (blob_id) REFERENCES message_blobs (id) ON DELETE RESTRICT)",
    "CREATE TABLE attachments (id UUID NOT NULL, message_id UUID NOT NULL, blob_id UUID, part_id VARCHAR(64), filename VARCHAR(512) NOT NULL, content_type VARCHAR(255), size_bytes BIGINT, content_id VARCHAR(255), is_inline BOOLEAN NOT NULL DEFAULT 0, CONSTRAINT pk_attachments PRIMARY KEY (id), CONSTRAINT uq_attachments_message_part UNIQUE (message_id, part_id), CONSTRAINT fk_attachments_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE, CONSTRAINT fk_attachments_blob FOREIGN KEY (blob_id) REFERENCES message_blobs (id) ON DELETE SET NULL)",
    "CREATE TABLE thread_messages (id UUID NOT NULL, thread_id UUID NOT NULL, message_id UUID NOT NULL, position INTEGER NOT NULL DEFAULT 0, CONSTRAINT pk_thread_messages PRIMARY KEY (id), CONSTRAINT uq_thread_messages UNIQUE (thread_id, message_id), CONSTRAINT fk_tm_thread FOREIGN KEY (thread_id) REFERENCES threads (id) ON DELETE CASCADE, CONSTRAINT fk_tm_message FOREIGN KEY (message_id) REFERENCES messages (id) ON DELETE CASCADE)",
    "CREATE TABLE sync_checkpoints (account_id UUID NOT NULL, folder_id UUID NOT NULL, cursor JSONB NOT NULL DEFAULT '{}', uidvalidity BIGINT, modseq BIGINT, history_id VARCHAR(128), delta_link TEXT, full_scan_complete BOOLEAN NOT NULL DEFAULT 0, scan_generation UUID, fencing_token BIGINT NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP, CONSTRAINT pk_sync_checkpoints PRIMARY KEY (account_id, folder_id), CONSTRAINT fk_checkpoints_account FOREIGN KEY (account_id) REFERENCES accounts (id) ON DELETE CASCADE, CONSTRAINT fk_checkpoints_folder FOREIGN KEY (folder_id) REFERENCES folders (id) ON DELETE CASCADE)",
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

_ACCOUNT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_FOLDER_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"

_LEGACY_CURSOR = {
    "last_status": {"folder_path": "/Inbox", "uidvalidity": 12345},
    "last_probe_at": 1700000000.0,
    "last_probe_failures": 3,
    "delta_token": "token-xyz",
}


def _make_0030_db(path: Path, *, revision: str = "20261031_0030") -> str:
    db_url = f"sqlite:///{path}"
    engine = create_engine(db_url)
    try:
        with engine.begin() as conn:
            for stmt in _DDL_0030_TABLES:
                conn.execute(text(stmt))
            conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                {"rev": revision},
            )
            conn.execute(
                text(
                    "INSERT INTO accounts (id, email, provider, recipient_addresses) "
                    "VALUES (:acc, 'legacy@example.com', 'imap', '[]')"
                ),
                {"acc": _ACCOUNT_ID},
            )
            conn.execute(
                text(
                    "INSERT INTO folders (id, account_id, remote_id, name) "
                    "VALUES (:folder, :acc, 'INBOX', 'Inbox')"
                ),
                {"folder": _FOLDER_ID, "acc": _ACCOUNT_ID},
            )
            conn.execute(
                text(
                    "INSERT INTO sync_checkpoints (account_id, folder_id, cursor) "
                    "VALUES (:acc, :folder, :cur)"
                ),
                {"acc": _ACCOUNT_ID, "folder": _FOLDER_ID, "cur": json.dumps(_LEGACY_CURSOR)},
            )
    finally:
        engine.dispose()
    return db_url


def _snapshot(db_url: str) -> dict:
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            tables = sorted(inspect(conn).get_table_names())
            revs: list[str] = []
            if "alembic_version" in tables:
                revs = sorted(
                    row[0] for row in conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
                )
            patrol: list[tuple] = []
            if "folder_patrol_status" in tables:
                try:
                    patrol = [
                        tuple(row)
                        for row in conn.execute(
                            text(
                                "SELECT folder_id, last_status, last_probe_failures "
                                "FROM folder_patrol_status ORDER BY folder_id"
                            )
                        ).fetchall()
                    ]
                except Exception:
                    patrol = [("<unreadable>",)]
            cursors: list[tuple] = []
            if "sync_checkpoints" in tables:
                cursors = sorted(
                    (row[0], row[1])
                    for row in conn.execute(text("SELECT folder_id, cursor FROM sync_checkpoints")).fetchall()
                )
            return {"tables": tables, "revs": revs, "patrol": patrol, "cursors": cursors}
    finally:
        engine.dispose()


def _mock_upgrade(monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr("alembic.command.upgrade", lambda cfg, rev: calls.append(rev))
    return calls


def test_t1_narrow_legacy_converts_inline(tmp_path, monkeypatch):
    """T1: narrow legacy (0030) converts inline through the startup path."""
    db_url = _make_0030_db(tmp_path / "narrow.db")
    upgrades = _mock_upgrade(monkeypatch)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)

    main_module.run_migrations()

    assert upgrades == ["head"]
    state = _snapshot(db_url)
    assert state["revs"] == [baseline.UNIFIED_BASELINE_REVISION]
    assert "folder_patrol_status" in state["tables"]
    assert len(state["patrol"]) == 1
    folder_id, last_status, failures = state["patrol"][0]
    assert folder_id == _FOLDER_ID
    assert json.loads(last_status) == {"folder_path": "/Inbox", "uidvalidity": 12345}
    assert failures == 3
    assert state["cursors"] == [(_FOLDER_ID, json.dumps({"delta_token": "token-xyz"}))]


def test_t2_unsupported_legacy_rejected_with_zero_changes(tmp_path, monkeypatch):
    """T2: legacy revision with missing tables is refused; tables/data/revision untouched."""
    db_file = tmp_path / "unsupported.db"
    db_url = f"sqlite:///{db_file}"
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('20261027_0029')"))
        conn.execute(text("CREATE TABLE folders (id VARCHAR(64) PRIMARY KEY)"))
        conn.execute(
            text("CREATE TABLE sync_checkpoints (folder_id VARCHAR(64) PRIMARY KEY, cursor TEXT)")
        )
        conn.execute(
            text("INSERT INTO sync_checkpoints (folder_id, cursor) VALUES ('f-1', '{\"a\": 1}')")
        )
    engine.dispose()
    before = _snapshot(db_url)
    upgrades = _mock_upgrade(monkeypatch)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)

    with pytest.raises(RuntimeError) as excinfo:
        main_module.run_migrations()

    message = str(excinfo.value)
    assert "20261027_0029" in message
    assert "not supported" in message
    assert "Restore the pre-upgrade sealed backup" in message
    assert "do not re-run" in message
    assert _snapshot(db_url) == before
    assert upgrades == []


def test_t3_dry_run_and_check_reject_without_writes(tmp_path, monkeypatch):
    """T3: dry-run and --check paths refuse unknown revisions and incomplete structure; zero writes."""
    unknown_file = tmp_path / "unknown.db"
    unknown_url = f"sqlite:///{unknown_file}"
    engine = create_engine(unknown_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('unknown_rev_9999')"))
    engine.dispose()
    before_unknown = _snapshot(unknown_url)
    with pytest.raises(SchemaValidationError):
        baseline.run_migration(unknown_url, dry_run=True)
    assert _snapshot(unknown_url) == before_unknown

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", unknown_url)
    with pytest.raises(RuntimeError) as excinfo:
        main_module.run_migrations(check_only=True)
    assert "not modified" in str(excinfo.value)
    assert _snapshot(unknown_url) == before_unknown

    incomplete_url = _make_0030_db(tmp_path / "incomplete.db")
    engine = create_engine(incomplete_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE folder_patrol_status (folder_id VARCHAR(64) PRIMARY KEY)"))
    engine.dispose()
    before_incomplete = _snapshot(incomplete_url)
    with pytest.raises(SchemaValidationError, match="missing required columns"):
        baseline.run_migration(incomplete_url, dry_run=True)
    assert _snapshot(incomplete_url) == before_incomplete


def test_t4_failed_conversion_rolls_back_and_rerun_is_idempotent(tmp_path, monkeypatch):
    """T4: a mid-conversion failure rolls back data and revision; success then re-run is a no-op.

    SQLite (test-only backend) autocommits DDL outside the implicit DML
    transaction, so the created-but-never-committed patrol table shell can
    survive while every row change is undone. Full DDL rollback is a
    PostgreSQL property and is proven against real PG in
    tests/mail_core/test_migration_validation.py.
    """
    db_url = _make_0030_db(tmp_path / "rollback.db")
    upgrades = _mock_upgrade(monkeypatch)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)
    before = _snapshot(db_url)

    real_migrate = baseline.migrate_patrol_status_data

    def _boom(bind, *, dry_run: bool = False):
        real_migrate(bind, dry_run=dry_run)
        raise RuntimeError("injected mid-conversion failure")

    monkeypatch.setattr("mail_core.db.baseline.migrate_patrol_status_data", _boom)
    with pytest.raises(RuntimeError, match="injected mid-conversion failure"):
        main_module.run_migrations()
    after_failure = _snapshot(db_url)
    assert after_failure["revs"] == before["revs"]
    assert after_failure["cursors"] == before["cursors"]
    assert after_failure["patrol"] == []
    assert upgrades == []

    # On PostgreSQL the whole conversion transaction (including the CREATE
    # TABLE) rolls back; emulate that here because SQLite autocommits DDL.
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE folder_patrol_status"))
    engine.dispose()

    monkeypatch.setattr("mail_core.db.baseline.migrate_patrol_status_data", real_migrate)
    main_module.run_migrations()
    assert upgrades == ["head"]
    after_success = _snapshot(db_url)
    assert after_success["revs"] == [baseline.UNIFIED_BASELINE_REVISION]

    main_module.run_migrations()
    assert upgrades == ["head", "head"]
    assert _snapshot(db_url) == after_success


def test_t5_empty_head_and_incremental_never_stamp(tmp_path, monkeypatch):
    """T5: empty DB initializes via upgrade; at-head/normal revisions never stamp; versioned-with-tables refused."""
    empty_url = f"sqlite:///{tmp_path / 'empty.db'}"
    upgrades = _mock_upgrade(monkeypatch)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", empty_url)
    main_module.run_migrations()
    assert upgrades == ["head"]
    assert _snapshot(empty_url)["tables"] == []

    head_file = tmp_path / "head.db"
    head_url = f"sqlite:///{head_file}"
    engine = create_engine(head_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        conn.execute(
            text("INSERT INTO alembic_version VALUES (:rev)"),
            {"rev": baseline.UNIFIED_BASELINE_REVISION},
        )
    engine.dispose()
    before_head = _snapshot(head_url)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", head_url)
    main_module.run_migrations()
    assert upgrades == ["head", "head"]
    assert _snapshot(head_url) == before_head

    class _FakeScript:
        def get_heads(self):
            return ["20261108_0002"]

        def walk_revisions(self):
            return iter([
                SimpleNamespace(revision="20261108_0002"),
                SimpleNamespace(revision=baseline.UNIFIED_BASELINE_REVISION),
            ])

    monkeypatch.setattr(
        "alembic.script.ScriptDirectory",
        SimpleNamespace(from_config=staticmethod(lambda cfg: _FakeScript())),
    )
    main_module.run_migrations()
    assert upgrades == ["head", "head", "head"]
    assert _snapshot(head_url) == before_head

    orphans_file = tmp_path / "orphans.db"
    orphans_url = f"sqlite:///{orphans_file}"
    engine = create_engine(orphans_url)
    with engine.begin() as conn:
        conn.execute(text(_DDL_0030_TABLES[0]))
    engine.dispose()
    before_orphans = _snapshot(orphans_url)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", orphans_url)
    with pytest.raises(RuntimeError, match="no alembic_version mark"):
        main_module.run_migrations()
    assert _snapshot(orphans_url) == before_orphans
    assert upgrades == ["head", "head", "head"]


def test_t6_migrate_only_runs_without_server_or_worker(tmp_path, monkeypatch):
    """T6: --migrate-only executes even with SKIP_MIGRATIONS=1 and never starts server/worker."""
    db_url = f"sqlite:///{tmp_path / 'gate.db'}"
    monkeypatch.delenv("MAIL_CORE_DATABASE_URL", raising=False)
    monkeypatch.delenv("MAIL_CORE_PORT", raising=False)
    monkeypatch.delenv("MAIL_CORE_HOST", raising=False)
    monkeypatch.delenv("KKMAIL_SIDECAR", raising=False)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", db_url)
    monkeypatch.setenv("MAIL_CORE_SKIP_MIGRATIONS", "1")

    calls: list = []
    monkeypatch.setattr(
        "mail_core.__main__.run_migrations",
        lambda *, check_only=False: calls.append(check_only),
    )

    import threading as threading_module

    def _no_thread(*args, **kwargs):
        raise AssertionError("worker thread must not start for --migrate-only")

    monkeypatch.setattr(threading_module, "Thread", _no_thread)

    import sys as _sys
    from types import ModuleType

    bomb = ModuleType("uvicorn")
    def _bomb_getattr(name):
        raise AssertionError("uvicorn must not be touched for --migrate-only")
    bomb.__getattr__ = _bomb_getattr  # type: ignore[attr-defined]
    monkeypatch.setitem(_sys.modules, "uvicorn", bomb)

    assert main_module.main(["--migrate-only"]) == 0
    assert calls == [False]


def test_t6_migrate_only_and_check_are_mutually_exclusive():
    """T6: argparse rejects combining both gate flags without touching any database."""
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": SRC_DIR,
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    proc = subprocess.run(
        [sys.executable, "-m", "mail_core", "--migrate-only", "--check-migrations"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 2


def test_t7_check_migrations_exit_codes_and_zero_writes(tmp_path, monkeypatch):
    """T7: --check-migrations reports pass/fail for the same fixtures with zero writes."""
    good_url = _make_0030_db(tmp_path / "check-good.db")
    before_good = _snapshot(good_url)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", good_url)
    assert main_module.main(["--check-migrations"]) == 0
    assert _snapshot(good_url) == before_good

    bad_file = tmp_path / "check-bad.db"
    bad_url = f"sqlite:///{bad_file}"
    engine = create_engine(bad_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"))
        conn.execute(text("INSERT INTO alembic_version VALUES ('unknown_rev_9999')"))
    engine.dispose()
    before_bad = _snapshot(bad_url)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", bad_url)
    with pytest.raises(RuntimeError):
        main_module.main(["--check-migrations"])
    assert _snapshot(bad_url) == before_bad


def test_t7_check_migrations_clean_subprocess_zero_writes(tmp_path):
    """T7: --check-migrations in a clean subprocess env (only DATABASE_URL + SKIP=1) exits 0 with zero writes."""
    db_file = tmp_path / "clean.db"
    db_url = f"sqlite:///{db_file}"
    env = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": SRC_DIR,
        "HOME": os.environ.get("HOME", "/tmp"),
        "MAIL_CORE_DATABASE_URL": db_url,
        "MAIL_CORE_SKIP_MIGRATIONS": "1",
    }
    proc = subprocess.run(
        [sys.executable, "-m", "mail_core", "--check-migrations"],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    engine = create_engine(db_url)
    try:
        with engine.connect() as conn:
            assert inspect(conn).get_table_names() == []
    finally:
        engine.dispose()


def test_both_entries_delegate_to_single_planner(tmp_path, monkeypatch):
    """Both entries classify through baseline.plan_migration, not their own judgement."""
    empty_url = f"sqlite:///{tmp_path / 'delegate.db'}"
    calls: list[object] = []
    real_plan = baseline.plan_migration

    def _spy(*args, **kwargs):
        calls.append(kwargs.get("context"))
        return real_plan(*args, **kwargs)

    monkeypatch.setattr("mail_core.db.baseline.plan_migration", _spy)
    upgrades = _mock_upgrade(monkeypatch)
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", empty_url)

    main_module.run_migrations()
    with pytest.raises(baseline.SchemaValidationError):
        baseline.run_migration(empty_url, dry_run=True)

    assert len(calls) == 2
    assert upgrades == ["head"]
