#!/usr/bin/env python3
"""Offline schema validation and Alembic baseline stamp utility (adoption A17).

Connects to an existing database, verifies required tables and columns for the
unified baseline (20261107_0001), and stamps the alembic_version table once
verified. Aborts with an error if schema requirements are not met.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine

ROOT = Path(__file__).resolve().parents[1]
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

LOG = logging.getLogger("migrate_to_unified_baseline")

UNIFIED_BASELINE_REVISION = "20261107_0001"

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


def verify_database_schema(bind: Engine | Connection) -> list[str]:
    """Verify that all required tables and columns exist on the target database.

    Returns a list of error messages describing missing tables or columns.
    If the returned list is empty, the schema matches the unified baseline.
    """
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    errors: list[str] = []

    missing_tables = sorted(REQUIRED_TABLES - existing_tables)
    if missing_tables:
        errors.append(f"Missing required tables: {', '.join(missing_tables)}")

    # Check columns for present tables
    for table_name, req_cols in sorted(REQUIRED_COLUMNS.items()):
        if table_name not in existing_tables:
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
        elif current != [revision]:
            conn.execute(text("DELETE FROM alembic_version"))
            conn.execute(
                text("INSERT INTO alembic_version (version_num) VALUES (:rev)"),
                {"rev": revision},
            )

    if isinstance(bind, Engine):
        with bind.begin() as conn:
            _execute(conn)
    else:
        _execute(bind)

    LOG.info("Successfully stamped alembic_version to %s", revision)


def run_migration(
    database_url: str | None = None,
    *,
    dry_run: bool = False,
) -> None:
    """Perform offline schema verification and baseline stamping."""
    url = database_url or os.environ.get("MAIL_CORE_DATABASE_URL")
    if not url:
        raise ValueError(
            "Database URL not specified and MAIL_CORE_DATABASE_URL is not set"
        )

    engine = create_engine(url)
    with engine.connect() as conn:
        errors = verify_database_schema(conn)
        if errors:
            raise SchemaValidationError(
                "Database schema verification failed for unified baseline:\n  - "
                + "\n  - ".join(errors)
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
