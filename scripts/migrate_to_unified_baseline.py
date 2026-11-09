#!/usr/bin/env python3
"""Offline schema validation and Alembic baseline stamp utility (adoption A17).

Connects to an existing database, verifies required tables and columns for the
unified baseline (20261107_0001), and stamps the alembic_version table once
verified. Aborts with an error if schema requirements are not met.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    func,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import Connection, Engine, make_url

ROOT = Path(__file__).resolve().parents[1]
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

LOG = logging.getLogger("migrate_to_unified_baseline")

UNIFIED_BASELINE_REVISION = "20261107_0001"

CORE_CRITICAL_TABLES: frozenset[str] = frozenset({
    "accounts",
    "folders",
    "messages",
    "sync_checkpoints",
    "worker_jobs",
})

KNOWN_LEGACY_REVISIONS: frozenset[str] = frozenset({
    "20261020_0001",
    "f5f312751c77",
    "20261021_0003",
    "20261021_0004",
    "20261021_0005",
    "20261021_0006",
    "20261021_0007",
    "20261021_0008",
    "20261021_0009",
    "20261021_0010",
    "20261021_0011",
    "20261021_0012",
    "20261021_0013",
    "20261022_0014",
    "20261022_0015",
    "20261023_0016",
    "20261023_0017",
    "20261023_0018",
    "20261023_0019",
    "20261025_0020",
    "20261025_0021",
    "20261026_0022",
    "20261026_0023",
    "20261026_0024",
    "20261026_0025",
    "20261026_0026",
    "20261027_0027",
    "20261027_0028",
    "20261027_0029",
    "20261031_0030",
    "20261107_0031",
})


def is_legacy_revision(rev: str | None) -> bool:
    """Return True if rev represents a recognized migration prior to unified baseline."""
    if not rev:
        return False
    if rev in KNOWN_LEGACY_REVISIONS:
        return True
    return (
        len(rev) == len(UNIFIED_BASELINE_REVISION)
        and rev[:8].isdigit()
        and rev[8] == "_"
        and rev[9:].isdigit()
        and rev < UNIFIED_BASELINE_REVISION
    )

REQUIRED_TABLES: frozenset[str] = frozenset({
    "account_groups",
    "credential_secrets",
    "app_settings",
    "auth_credentials",
    "accounts",
    "account_sync_leases",
    "account_sync_activity",
    "folders",
    "threads",
    "messages",
    "message_locations",
    "message_bodies",
    "message_blobs",
    "message_blob_links",
    "attachments",
    "thread_messages",
    "sync_checkpoints",
    "sync_runs",
    "remote_operations",
    "folder_stats",
    "folder_patrol_status",
    "outbox_publication_state",
    "outbox",
    "message_archive_state",
    "worker_jobs",
    "message_search",
    "blob_quota_reservations",
    "sync_requests",
    "sync_request_targets",
    "sync_request_target_jobs",
    "message_remote_image_allows",
    "sender_remote_image_allows",
})

REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "accounts": frozenset({
        "id", "email", "provider", "group_id", "master_order", "group_order", "recipient_addresses"
    }),
    "messages": frozenset({
        "id", "account_id", "sort_time", "remote_id", "is_read", "is_flagged", "has_attachments"
    }),
    "message_blobs": frozenset({
        "id", "content_sha256", "key_version", "gc_eligible_at", "ref_count"
    }),
    "attachments": frozenset({
        "id", "message_id", "part_id"
    }),
    "worker_jobs": frozenset({
        "id", "execution_generation", "dedupe_key", "failure_attempts"
    }),
    "sync_checkpoints": frozenset({
        "account_id", "folder_id", "scan_generation"
    }),
    "sync_requests": frozenset({
        "id", "client_request_id"
    }),
    "sync_request_targets": frozenset({
        "id", "request_id", "target_key"
    }),
    "sync_request_target_jobs": frozenset({
        "id", "target_id", "execution_generation"
    }),
    "folder_patrol_status": frozenset({
        "folder_id", "last_status", "last_probe_failures"
    }),
    "outbox_publication_state": frozenset({
        "id", "epoch", "next_seq", "pruned_through_seq"
    }),
    "outbox": frozenset({
        "id", "publication_seq", "published_at"
    }),
    "message_archive_state": frozenset({
        "message_id", "claim_revision", "state"
    }),
    "remote_operations": frozenset({
        "id", "next_attempt_at"
    }),
    "message_search": frozenset({
        "message_id", "to_text", "document"
    }),
}


class SchemaValidationError(RuntimeError):
    """Raised when the database schema does not meet the unified baseline requirements."""


def verify_database_schema(
    bind: Engine | Connection,
    *,
    exempt_tables: frozenset[str] = frozenset(),
) -> list[str]:
    """Verify that all required tables and columns exist on the target database.

    Returns a list of error messages describing missing tables or columns.
    If the returned list is empty, the schema matches the unified baseline.
    ``exempt_tables`` excludes tables the offline tool will create later, so
    a dry-run skips exactly those tables without masking other missing ones.
    """
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    errors: list[str] = []

    missing_tables = sorted(REQUIRED_TABLES - exempt_tables - existing_tables)
    if missing_tables:
        errors.append(f"Missing required tables: {', '.join(missing_tables)}")

    # Check columns for present tables
    for table_name, req_cols in sorted(REQUIRED_COLUMNS.items()):
        if table_name in exempt_tables or table_name not in existing_tables:
            continue
        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        missing_cols = sorted(req_cols - existing_cols)
        if missing_cols:
            errors.append(
                f"Table '{table_name}' is missing required columns: {', '.join(missing_cols)}"
            )

    return errors


def stamp_unified_baseline(
    bind: Engine | Connection,
    *,
    revision: str = UNIFIED_BASELINE_REVISION,
    dry_run: bool = False,
) -> None:
    """Stamp the alembic_version table with the unified baseline revision."""
    if dry_run:
        LOG.info("Dry-run: would stamp alembic_version to %s", revision)
        return

    def _execute(conn: Connection) -> None:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS alembic_version (
                    version_num VARCHAR(32) NOT NULL,
                    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
                )
                """
            )
        )
        current = conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        if not current:
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                {"rev": revision},
            )
        elif current == [revision]:
            LOG.info("alembic_version already at %s; leaving it untouched", revision)
        elif all(is_legacy_revision(r) for r in current):
            conn.execute(text("DELETE FROM alembic_version"))
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                {"rev": revision},
            )
        else:
            raise SchemaValidationError(
                f"Refusing to overwrite alembic_version {current!r} with {revision!r}: "
                "only an empty table or a recognized legacy revision may be stamped "
                "to the unified baseline."
            )

    if isinstance(bind, Engine):
        with bind.begin() as conn:
            _execute(conn)
    else:
        _execute(bind)

    LOG.info("Successfully stamped alembic_version to %s", revision)


def get_current_alembic_version(bind: Connection | Engine) -> str | None:
    """Retrieve the current revision from alembic_version if present."""
    inspector = inspect(bind)
    if "alembic_version" not in inspector.get_table_names():
        return None
    if isinstance(bind, Engine):
        with bind.connect() as conn:
            return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    return bind.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def ensure_folder_patrol_status_table(bind: Connection, *, dry_run: bool = False) -> None:
    """Create folder_patrol_status table if it does not already exist."""
    inspector = inspect(bind)
    if "folder_patrol_status" in inspector.get_table_names():
        return
    if dry_run:
        LOG.info("Dry-run: would create folder_patrol_status table")
        return

    if bind.dialect.name == "postgresql":
        bind.execute(
            text(
                """
                CREATE TABLE folder_patrol_status (
                    folder_id UUID NOT NULL,
                    last_status JSONB,
                    last_probe_at TIMESTAMP WITH TIME ZONE,
                    last_probe_failures INTEGER DEFAULT 0 NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
                    CONSTRAINT pk_folder_patrol_status PRIMARY KEY (folder_id),
                    CONSTRAINT fk_folder_patrol_status_folder_id_folders FOREIGN KEY (folder_id) REFERENCES folders (id) ON DELETE CASCADE
                )
                """
            )
        )
    else:
        meta = MetaData()
        Table("folders", meta, Column("id", String(64), primary_key=True))
        t = Table(
            "folder_patrol_status",
            meta,
            Column(
                "folder_id",
                UUID(as_uuid=True),
                ForeignKey("folders.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
            Column("last_status", JSONB, nullable=True),
            Column("last_probe_at", DateTime(timezone=True), nullable=True),
            Column("last_probe_failures", Integer, nullable=False, server_default=text("0")),
            Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
            Column("updated_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
        )
        t.create(bind)
    LOG.info("Created folder_patrol_status table")


def _migrate_patrol_status_data_generic(bind: Connection) -> None:
    rows = bind.execute(text("SELECT folder_id, cursor FROM sync_checkpoints")).fetchall()
    now_dt = datetime.now(timezone.utc)
    patrol_keys = {"last_status", "last_probe_at", "last_probe_failures"}

    for fid, raw_cursor in rows:
        if raw_cursor is None:
            continue
        if isinstance(raw_cursor, str):
            try:
                cur = json.loads(raw_cursor)
            except Exception:
                continue
        elif isinstance(raw_cursor, dict):
            cur = dict(raw_cursor)
        else:
            continue

        if not isinstance(cur, dict) or not any(k in cur for k in patrol_keys):
            continue

        status = cur.get("last_status")
        probe_at_raw = cur.get("last_probe_at")
        failures_raw = cur.get("last_probe_failures", 0)

        probe_at_dt = None
        if probe_at_raw is not None:
            try:
                if isinstance(probe_at_raw, (int, float)):
                    probe_at_dt = datetime.fromtimestamp(float(probe_at_raw), tz=timezone.utc)
                elif isinstance(probe_at_raw, str):
                    try:
                        probe_at_dt = datetime.fromtimestamp(float(probe_at_raw), tz=timezone.utc)
                    except ValueError:
                        probe_at_dt = datetime.fromisoformat(probe_at_raw)
            except Exception:
                probe_at_dt = None

        failures = 0
        if failures_raw is not None:
            try:
                failures = int(failures_raw)
            except Exception:
                failures = 0

        status_val = json.dumps(status) if isinstance(status, (dict, list)) else status

        existing = bind.execute(
            text("SELECT 1 FROM folder_patrol_status WHERE folder_id = :fid"),
            {"fid": str(fid)},
        ).scalar()
        if existing:
            bind.execute(
                text(
                    """
                    UPDATE folder_patrol_status
                    SET last_status = :status,
                        last_probe_at = :probe_at,
                        last_probe_failures = :failures,
                        updated_at = :now
                    WHERE folder_id = :fid
                    """
                ),
                {
                    "status": status_val,
                    "probe_at": probe_at_dt,
                    "failures": failures,
                    "now": now_dt,
                    "fid": str(fid),
                },
            )
        else:
            bind.execute(
                text(
                    """
                    INSERT INTO folder_patrol_status (
                        folder_id, last_status, last_probe_at, last_probe_failures, created_at, updated_at
                    ) VALUES (
                        :fid, :status, :probe_at, :failures, :now, :now
                    )
                    """
                ),
                {
                    "fid": str(fid),
                    "status": status_val,
                    "probe_at": probe_at_dt,
                    "failures": failures,
                    "now": now_dt,
                },
            )

        new_cur = {k: v for k, v in cur.items() if k not in patrol_keys}
        new_cur_val = json.dumps(new_cur) if isinstance(raw_cursor, str) else new_cur
        bind.execute(
            text("UPDATE sync_checkpoints SET cursor = :c WHERE folder_id = :fid"),
            {"c": new_cur_val, "fid": str(fid)},
        )


def migrate_patrol_status_data(bind: Connection, *, dry_run: bool = False) -> None:
    """Migrate legacy patrol state from sync_checkpoints.cursor to folder_patrol_status."""
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "sync_checkpoints" not in tables:
        return
    if "folder_patrol_status" not in tables and not dry_run:
        return

    if dry_run:
        LOG.info("Dry-run: would migrate patrol data from sync_checkpoints.cursor to folder_patrol_status")
        return

    if bind.dialect.name == "postgresql":
        bind.execute(
            text(
                """
                INSERT INTO folder_patrol_status (
                    folder_id,
                    last_status,
                    last_probe_at,
                    last_probe_failures,
                    created_at,
                    updated_at
                )
                SELECT
                    folder_id,
                    CASE WHEN cursor ? 'last_status' THEN cursor->'last_status' ELSE NULL END,
                    CASE
                        WHEN cursor ? 'last_probe_at' AND (cursor->>'last_probe_at') ~ '^-?[0-9]+(\\.[0-9]+)?$'
                        THEN to_timestamp((cursor->>'last_probe_at')::double precision)
                        ELSE NULL
                    END,
                    CASE
                        WHEN cursor ? 'last_probe_failures' AND (cursor->>'last_probe_failures') ~ '^[0-9]+$'
                        THEN (cursor->>'last_probe_failures')::integer
                        ELSE 0
                    END,
                    now(),
                    now()
                FROM sync_checkpoints
                WHERE cursor ? 'last_status' OR cursor ? 'last_probe_at' OR cursor ? 'last_probe_failures'
                ON CONFLICT (folder_id) DO UPDATE SET
                    last_status = EXCLUDED.last_status,
                    last_probe_at = EXCLUDED.last_probe_at,
                    last_probe_failures = EXCLUDED.last_probe_failures,
                    updated_at = EXCLUDED.updated_at;
                """
            )
        )
        bind.execute(
            text(
                """
                UPDATE sync_checkpoints
                SET cursor = cursor - ARRAY['last_status', 'last_probe_at', 'last_probe_failures']
                WHERE cursor ? 'last_status' OR cursor ? 'last_probe_at' OR cursor ? 'last_probe_failures';
                """
            )
        )
    else:
        _migrate_patrol_status_data_generic(bind)

    LOG.info("Migrated patrol status data and cleaned legacy cursor keys")


def run_migration(
    database_url: str | None = None,
    *,
    dry_run: bool = False,
) -> None:
    """Perform offline schema verification, legacy upgrade, and baseline stamping."""
    raw_url = database_url or os.environ.get("MAIL_CORE_DATABASE_URL")
    if not raw_url:
        raise ValueError(
            "Database URL not specified and MAIL_CORE_DATABASE_URL is not set"
        )

    safe_url = make_url(raw_url).render_as_string(hide_password=True)
    LOG.info("Connecting to database at %s", safe_url)

    engine = create_engine(raw_url)
    with engine.connect() as conn:
        current_rev = get_current_alembic_version(conn)
        LOG.info("Current alembic_version: %s", current_rev)

        is_legacy = is_legacy_revision(current_rev)

        if is_legacy:
            LOG.info(
                "Detected legacy revision '%s'. Running automated upgrade to unified baseline...",
                current_rev,
            )
            ensure_folder_patrol_status_table(conn, dry_run=dry_run)
            migrate_patrol_status_data(conn, dry_run=dry_run)
        else:
            inspector = inspect(conn)
            existing = set(inspector.get_table_names())
            missing_critical = sorted(CORE_CRITICAL_TABLES - existing)
            if missing_critical:
                if current_rev is not None and current_rev != UNIFIED_BASELINE_REVISION:
                    raise SchemaValidationError(
                        f"Database schema verification failed for unified baseline: database is at unknown "
                        f"revision '{current_rev}' and missing critical tables ({', '.join(missing_critical)}). "
                        "Refusing to stamp unified baseline."
                    )
                elif current_rev is None:
                    raise SchemaValidationError(
                        f"Database schema verification failed for unified baseline: database has no alembic_version "
                        f"and is missing critical tables ({', '.join(missing_critical)}). "
                        "Refusing to stamp unified baseline."
                    )

        exempt_tables = (
            frozenset({"folder_patrol_status"}) if (dry_run and is_legacy) else frozenset()
        )
        errors = verify_database_schema(conn, exempt_tables=exempt_tables)

        if errors:
            detail = "\n  - ".join(errors)
            if is_legacy:
                raise SchemaValidationError(
                    "Automatic upgrade of this legacy database to the unified baseline is "
                    "not supported: its schema is missing tables or columns that the offline "
                    "tool cannot reconstruct (the alembic versions tree ships only the unified "
                    "baseline, so incremental migrations cannot be replayed). Restore the "
                    "pre-upgrade sealed backup into a fresh deployment instead.\n  - " + detail
                )
            raise SchemaValidationError(
                "Database schema verification failed for unified baseline:\n  - " + detail
            )

        LOG.info("Database schema verification passed. All tables and columns present.")
        stamp_unified_baseline(conn, dry_run=dry_run)
        if not dry_run:
            conn.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        help="Database connection URL (defaults to MAIL_CORE_DATABASE_URL)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only verify schema without updating alembic_version",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        run_migration(args.database_url, dry_run=args.dry_run)
        return 0
    except SchemaValidationError as exc:
        LOG.error("%s", exc)
        return 1
    except Exception as exc:
        LOG.exception("Migration failed: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
