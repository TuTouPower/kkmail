"""Shared classification and execution helpers for the unified-baseline migration.

Database state classification is centralized in :func:`plan_migration`: both
the startup orchestration (``mail_core.__main__.run_migrations``) and the
offline wrapper (``scripts/migrate_to_unified_baseline.py``) build a
:class:`DatabaseState` and a :class:`RevisionContext`, then act on the single
returned :class:`MigrationPlan`, so the two entries cannot disagree about which
state a database is in. Execution differs by design: the startup entry can run
``alembic upgrade head`` (and the narrow legacy conversion followed by an
upgrade), while the offline tool only verifies schema, performs supported
narrow legacy conversions and stamps; an empty database, or any no-version
database carrying unified-baseline business tables, is refused by both
entries.

Read-only checks open their own connection with a read-only transaction
(``SET TRANSACTION READ ONLY`` on PostgreSQL) plus connection and statement
timeouts. Only PostgreSQL is supported: every entry point rejects any other
backend rather than silently skipping the read-only protection. The narrow
legacy conversion runs inside one write transaction that re-verifies
everything from scratch (no precheck results are reused, closing the TOCTOU
window) under a PostgreSQL advisory lock so concurrent converters serialize.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from alembic.config import Config

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine, make_url

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
        "account_id", "folder_id", "scan_generation", "cursor"
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

_PATROL_EXPECTED_COLUMNS: dict[str, tuple[str, bool, str | None]] = {
    "folder_id": ("uuid", False, None),
    "last_status": ("json", True, None),
    "last_probe_at": ("datetime", True, None),
    "last_probe_failures": ("integer", False, "0"),
    "created_at": ("datetime", False, "now()"),
    "updated_at": ("datetime", False, "now()"),
}

_NARROW_CONVERSION_LOCK_KEY = "mail-core:narrow-legacy-conversion"

_CHECK_CONNECT_TIMEOUT_SECONDS = "10"
_CHECK_STATEMENT_TIMEOUT = "10s"


class MigrationAction(str, Enum):
    """The single classification a database migration state can fall into."""

    EMPTY_DATABASE = "empty_database"
    AT_BASELINE = "at_baseline"
    LEGACY = "legacy"
    NO_VERSION_WITH_BUSINESS_TABLES = "no_version_with_business_tables"
    UNKNOWN_REVISION = "unknown_revision"
    MULTIPLE_VERSIONS = "multiple_versions"


@dataclass(frozen=True)
class RevisionContext:
    """Revision sets the planner uses to classify a versioned database.

    Both entries build the context through :func:`revision_context`, so the
    classification inputs (not just the classification function) are single-
    sourced. The context is passed to :func:`plan_migration` as an explicit
    argument.
    """

    known_revisions: frozenset[str]
    legacy_revisions: frozenset[str]
    heads: tuple[str, ...]


@dataclass(frozen=True)
class DatabaseState:
    """Facts read from the database; classification depends only on these."""

    version_rows: tuple[str, ...]
    table_names: frozenset[str]


@dataclass(frozen=True)
class MigrationPlan:
    """The single classification result plus the facts behind its message."""

    action: MigrationAction
    current_revision: str | None = None
    version_rows: tuple[str, ...] = ()
    business_tables: tuple[str, ...] = ()
    message: str = ""


class SchemaValidationError(RuntimeError):
    """Raised when the database schema does not meet the unified baseline requirements."""


def check_connect_url(raw_url: str) -> str:
    """Return the PostgreSQL check-connection URL with a connection timeout applied.

    ``connect_timeout`` is applied via the URL query (never via engine kwargs,
    so single-argument ``create_engine(url)`` keeps working). Only PostgreSQL
    is supported; the offline tool rejects any other backend.
    """
    url = make_url(raw_url)
    if url.get_backend_name() == "postgresql" and "connect_timeout" not in url.query:
        url = url.update_query_pairs([("connect_timeout", _CHECK_CONNECT_TIMEOUT_SECONDS)])
    # NOTE: str(URL) masks the password ("***") in this SQLAlchemy version;
    # render explicitly so check engines authenticate with the real password.
    return url.render_as_string(hide_password=False)


def configure_read_only(conn: Connection, backend: str) -> None:
    """Put an already-opened check connection into read-only mode with a statement timeout.

    PostgreSQL uses a real read-only transaction (``SET TRANSACTION READ ONLY``)
    plus a statement timeout, and must be the first statement of the
    transaction. Only PostgreSQL is supported; any other backend is rejected
    instead of silently skipping the read-only protection.
    """
    if backend != "postgresql":
        raise ValueError(
            f"configure_read_only requires PostgreSQL, got {backend!r}"
        )
    conn.execute(text("SET TRANSACTION READ ONLY"))
    conn.execute(text(f"SET LOCAL statement_timeout = '{_CHECK_STATEMENT_TIMEOUT}'"))


@contextmanager
def read_only_connection(raw_url: str) -> Iterator[Connection]:
    """Yield a read-only check connection with connection and statement timeouts.

    The transaction is always rolled back and the engine disposed, so checks
    perform zero writes by construction. Only PostgreSQL is supported: a
    non-PostgreSQL URL is rejected by :func:`configure_read_only`.
    """
    backend = make_url(raw_url).get_backend_name()
    engine = create_engine(check_connect_url(raw_url))
    try:
        with engine.connect() as conn:
            configure_read_only(conn, backend)
            try:
                yield conn
            finally:
                conn.rollback()
    finally:
        engine.dispose()


def verify_database_schema(
    bind: Engine | Connection,
    *,
    exempt_tables: frozenset[str] = frozenset(),
) -> list[str]:
    """Verify that all required tables and columns exist on the target database.

    Returns a list of error messages describing missing tables or columns.
    If the returned list is empty, the schema matches the unified baseline.
    ``exempt_tables`` only waives the requirement that those tables exist: it
    is for tables the offline tool will create later (e.g. on a dry-run, where
    folder_patrol_status has not been built yet). It never waives column checks
    for a table that does exist, so an incomplete existing table is still
    reported instead of passing a dry-run and failing on apply.
    """
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    errors: list[str] = []

    missing_tables = sorted(REQUIRED_TABLES - exempt_tables - existing_tables)
    if missing_tables:
        errors.append(f"Missing required tables: {', '.join(missing_tables)}")

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


def _column_affinity(type_name: str) -> str:
    upper = (type_name or "").upper()
    if "JSON" in upper:
        return "json"
    if "UUID" in upper or "GUID" in upper:
        return "uuid"
    if "DATETIME" in upper or "TIMESTAMP" in upper:
        return "datetime"
    if "DATE" in upper:
        return "date"
    if "BOOL" in upper:
        return "boolean"
    if "INT" in upper:
        return "integer"
    if upper.startswith("FLOAT") or "REAL" in upper or "DOUBLE" in upper or "NUMERIC" in upper or "DECIMAL" in upper:
        return "number"
    if "TEXT" in upper or "CHAR" in upper or "CLOB" in upper or "STRING" in upper:
        return "string"
    if "BYTEA" in upper or "BLOB" in upper or "BINARY" in upper:
        return "binary"
    return upper.lower()


def _normalize_default(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip().lower()
    while len(text_value) >= 2 and text_value.startswith("(") and text_value.endswith(")"):
        text_value = text_value[1:-1].strip()
    cast_at = text_value.find("::")
    if cast_at != -1:
        text_value = text_value[:cast_at].strip()
    text_value = "".join(text_value.split())
    if text_value in ("current_timestamp", "currenttimestamp"):
        return "now()"
    return text_value or None


def _pk_columns(bind: Engine | Connection, table: str) -> list[str]:
    info = inspect(bind).get_pk_constraint(table) or {}
    return list(info.get("constrained_columns") or [])


def _fk_specs(bind: Engine | Connection, table: str) -> dict[tuple[str, ...], tuple[str, tuple[str, ...], str]]:
    specs: dict[tuple[str, ...], tuple[str, tuple[str, ...], str]] = {}
    for fk in inspect(bind).get_foreign_keys(table):
        cols = tuple(fk.get("constrained_columns") or [])
        referred = str(fk.get("referred_table") or "")
        referred_cols = tuple(fk.get("referred_columns") or [])
        ondelete = str((fk.get("options") or {}).get("ondelete") or "").upper()
        specs[cols] = (referred, referred_cols, ondelete)
    return specs


def _unique_specs(bind: Engine | Connection, table: str) -> set[tuple[str, ...]]:
    return {
        tuple(sorted(uq.get("column_names") or []))
        for uq in inspect(bind).get_unique_constraints(table)
    }


def verify_narrow_legacy_schema(bind: Engine | Connection) -> list[str]:
    """Deep validation for the narrow legacy conversion path.

    Beyond table names and key column names, verifies every structure the
    conversion touches: ``sync_checkpoints.cursor`` existence and JSON type,
    the full ``folder_patrol_status`` column definitions (type, nullability,
    default) when the table already exists, the related primary-key, foreign-
    key and unique constraints compared by semantics (constraint names and
    default-expression spellings are ignored), and a read-only data check over
    the cursor column. Returns error strings; empty means convertible.
    """
    errors = verify_database_schema(bind, exempt_tables=frozenset({"folder_patrol_status"}))

    inspector = inspect(bind)
    existing = set(inspector.get_table_names())

    if "sync_checkpoints" in existing:
        try:
            cols = {c["name"]: c for c in inspector.get_columns("sync_checkpoints")}
        except Exception as exc:
            errors.append(f"Table 'sync_checkpoints' columns are not introspectable: {exc}")
            cols = {}
        cursor = cols.get("cursor")
        if cursor is not None and _column_affinity(str(cursor.get("type"))) != "json":
            errors.append(
                "Table 'sync_checkpoints' column 'cursor' has type "
                f"'{cursor.get('type')}', expected a JSON/JSONB column: the patrol "
                "data migration reads and rewrites JSON cursor keys."
            )

        expected_pk = {"account_id", "folder_id"}
        actual_pk = set(_pk_columns(bind, "sync_checkpoints"))
        if actual_pk != expected_pk:
            errors.append(
                "Table 'sync_checkpoints' primary key is "
                f"({', '.join(sorted(actual_pk)) or 'none'}), expected "
                "(account_id, folder_id): the conversion addresses rows by the "
                "composite key."
            )
        expected_fks = {
            ("account_id",): ("accounts", ("id",), "CASCADE"),
            ("folder_id",): ("folders", ("id",), "CASCADE"),
        }
        actual_fks = _fk_specs(bind, "sync_checkpoints")
        for cols_key, (ref_table, ref_cols, ondelete) in expected_fks.items():
            actual = actual_fks.get(cols_key)
            if actual is None:
                errors.append(
                    f"Table 'sync_checkpoints' is missing the foreign key on "
                    f"({', '.join(cols_key)}) referencing {ref_table}."
                )
            elif actual != (ref_table, ref_cols, ondelete):
                errors.append(
                    f"Table 'sync_checkpoints' foreign key on ({', '.join(cols_key)}) "
                    f"references {actual[0]}({', '.join(actual[1])}) "
                    f"on-delete {actual[2] or 'none'}, expected "
                    f"{ref_table}({', '.join(ref_cols)}) on-delete {ondelete}."
                )

        errors.extend(_check_cursor_data(bind))

    if "folders" in existing:
        if set(_pk_columns(bind, "folders")) != {"id"}:
            errors.append(
                "Table 'folders' primary key is not (id): folder_patrol_status "
                "references folders(id) and the conversion depends on it."
            )
        if ("account_id", "remote_id") not in _unique_specs(bind, "folders"):
            errors.append(
                "Table 'folders' is missing the unique constraint on "
                "(account_id, remote_id): patrol rows cannot be attributed safely."
            )

    if "accounts" in existing and set(_pk_columns(bind, "accounts")) != {"id"}:
        errors.append(
            "Table 'accounts' primary key is not (id): the conversion joins "
            "through accounts(id)."
        )

    if "folder_patrol_status" in existing:
        try:
            patrol_cols = {c["name"]: c for c in inspector.get_columns("folder_patrol_status")}
        except Exception as exc:
            errors.append(f"Table 'folder_patrol_status' columns are not introspectable: {exc}")
            patrol_cols = {}
        for name, (affinity, nullable, default) in sorted(_PATROL_EXPECTED_COLUMNS.items()):
            col = patrol_cols.get(name)
            if col is None:
                errors.append(
                    f"Table 'folder_patrol_status' is missing required column '{name}'."
                )
                continue
            if _column_affinity(str(col.get("type"))) != affinity:
                errors.append(
                    f"Table 'folder_patrol_status' column '{name}' has type "
                    f"'{col.get('type')}', expected {affinity}."
                )
            if bool(col.get("nullable", True)) != nullable:
                errors.append(
                    f"Table 'folder_patrol_status' column '{name}' nullability is "
                    f"{col.get('nullable')}, expected {'nullable' if nullable else 'NOT NULL'}."
                )
            if _normalize_default(col.get("default")) != _normalize_default(default):
                errors.append(
                    f"Table 'folder_patrol_status' column '{name}' default is "
                    f"{col.get('default')!r}, expected {default!r}."
                )
        unexpected = sorted(set(patrol_cols) - set(_PATROL_EXPECTED_COLUMNS))
        if unexpected:
            errors.append(
                "Table 'folder_patrol_status' has unexpected columns: "
                f"{', '.join(unexpected)}."
            )
        if set(_pk_columns(bind, "folder_patrol_status")) != {"folder_id"}:
            errors.append(
                "Table 'folder_patrol_status' primary key is not (folder_id)."
            )
        patrol_fks = _fk_specs(bind, "folder_patrol_status")
        expected_patrol_fk = ("folders", ("id",), "CASCADE")
        if patrol_fks.get(("folder_id",)) != expected_patrol_fk:
            errors.append(
                "Table 'folder_patrol_status' must reference folders(id) "
                "ON DELETE CASCADE on (folder_id)."
            )

    return errors


def _check_cursor_data(bind: Engine | Connection) -> list[str]:
    """Read-only data check over ``sync_checkpoints.cursor`` on PostgreSQL.

    Every non-NULL cursor must be a JSONB object: the patrol migration only
    understands object cursors and would otherwise silently skip rows. Runs no
    writes. Only PostgreSQL is supported; any other backend is rejected.
    """
    if bind.dialect.name != "postgresql":
        raise ValueError("_check_cursor_data requires PostgreSQL")
    errors: list[str] = []
    try:
        bad = bind.execute(
            text(
                "SELECT count(*) FROM sync_checkpoints "
                "WHERE cursor IS NULL OR jsonb_typeof(cursor) <> 'object'"
            )
        ).scalar() or 0
        if bad:
            errors.append(
                f"Table 'sync_checkpoints' has {bad} row(s) whose cursor is "
                "NULL or not a JSON object: the patrol data migration cannot "
                "interpret them."
            )
    except Exception as exc:
        errors.append(f"Table 'sync_checkpoints' cursor data is not readable: {exc}")
    return errors


def _stamp_targets(current: list[str], revision: str) -> str:
    if not current:
        return "insert"
    if current == [revision]:
        return "noop"
    if all(is_legacy_revision(r) for r in current):
        return "replace"
    raise SchemaValidationError(
        f"Refusing to overwrite alembic_version {current!r} with {revision!r}: "
        "only an empty table or a recognized legacy revision may be stamped "
        "to the unified baseline."
    )


def stamp_unified_baseline(
    bind: Engine | Connection,
    *,
    revision: str = UNIFIED_BASELINE_REVISION,
    dry_run: bool = False,
) -> None:
    """Stamp the alembic_version table with the unified baseline revision."""
    if dry_run:
        _stamp_targets(_read_version_rows(bind), revision)
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
        current = _read_version_rows(conn)
        action = _stamp_targets(current, revision)
        if action == "noop":
            LOG.info("alembic_version already at %s; leaving it untouched", revision)
            return
        if action == "replace":
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


def _read_version_rows(bind: Engine | Connection) -> list[str]:
    inspector = inspect(bind)
    if "alembic_version" not in inspector.get_table_names():
        return []
    if isinstance(bind, Engine):
        with bind.connect() as conn:
            return list(conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all())
    return list(bind.execute(text("SELECT version_num FROM alembic_version")).scalars().all())


def get_current_alembic_version(bind: Connection | Engine) -> str | None:
    """Retrieve the current revision from alembic_version if present."""
    rows = _read_version_rows(bind)
    if len(rows) > 1:
        raise SchemaValidationError(
            f"alembic_version contains {len(rows)} rows; expected at most one."
        )
    return rows[0] if rows else None


def ensure_folder_patrol_status_table(bind: Connection, *, dry_run: bool = False) -> None:
    """Create folder_patrol_status table on PostgreSQL if it does not already exist.

    Only PostgreSQL is supported; any other backend is rejected instead of
    silently skipping the table creation.
    """
    if bind.dialect.name != "postgresql":
        raise ValueError("ensure_folder_patrol_status_table requires PostgreSQL")
    inspector = inspect(bind)
    if "folder_patrol_status" in inspector.get_table_names():
        return
    if dry_run:
        LOG.info("Dry-run: would create folder_patrol_status table")
        return

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
    LOG.info("Created folder_patrol_status table")


def migrate_patrol_status_data(bind: Connection, *, dry_run: bool = False) -> None:
    """Migrate legacy patrol state from sync_checkpoints.cursor to folder_patrol_status.

    Only PostgreSQL is supported; any other backend is rejected instead of
    silently skipping the migration.
    """
    if bind.dialect.name != "postgresql":
        raise ValueError("migrate_patrol_status_data requires PostgreSQL")
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "sync_checkpoints" not in tables:
        return
    if "folder_patrol_status" not in tables and not dry_run:
        return

    if dry_run:
        LOG.info("Dry-run: would migrate patrol data from sync_checkpoints.cursor to folder_patrol_status")
        return

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
    LOG.info("Migrated patrol status data and cleaned legacy cursor keys")


def apply_narrow_legacy_conversion(database_url: str) -> str:
    """Convert a validated narrow legacy database inside one write transaction.

    Re-verifies everything from scratch inside the transaction (precheck
    results are never reused, closing the TOCTOU window); any failure rolls
    back the whole conversion. Only PostgreSQL is supported: a non-PostgreSQL
    URL is rejected and the advisory lock is always taken so concurrent
    converters serialize; the loser re-reads the revision and becomes a
    no-op. Returns ``"converted"`` or ``"already-at-baseline"`` (idempotent
    re-run).
    """
    engine = create_engine(check_connect_url(database_url))
    try:
        with engine.begin() as conn:
            if conn.dialect.name != "postgresql":
                raise ValueError("narrow legacy conversion requires PostgreSQL")
            conn.execute(
                text(f"SELECT pg_advisory_xact_lock(hashtext('{_NARROW_CONVERSION_LOCK_KEY}'))")
            )
            current = _read_version_rows(conn)
            if current == [UNIFIED_BASELINE_REVISION]:
                return "already-at-baseline"
            if len(current) != 1 or not is_legacy_revision(current[0]):
                raise SchemaValidationError(
                    f"Refusing narrow legacy conversion: alembic_version is {current!r} "
                    "inside the conversion transaction; expected a single recognized "
                    "legacy revision."
                )
            errors = verify_narrow_legacy_schema(conn)
            if errors:
                detail = "\n  - ".join(errors)
                raise SchemaValidationError(
                    "Re-verification inside the conversion transaction failed; "
                    "rolling back without changes:\n  - " + detail
                )
            ensure_folder_patrol_status_table(conn)
            migrate_patrol_status_data(conn)
            stamp_unified_baseline(conn)
            return "converted"
    finally:
        engine.dispose()


def alembic_config() -> Config:
    """Build the Alembic ``Config`` for the migration tree shipped in this package.

    Single source for locating ``alembic.ini`` / the ``alembic`` directory:
    both migration entries resolve the tree through here, relative to the
    ``mail_core.db`` package, so it works from source and from a bundle.
    """
    from alembic.config import Config

    here = Path(__file__).resolve().parent
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "alembic"))
    return cfg


def revision_context(cfg: Config | None = None) -> RevisionContext:
    """Build the single :class:`RevisionContext` both migration entries classify with.

    ``known_revisions`` / ``heads`` always come from Alembic's
    ``ScriptDirectory`` over the shipped tree, never from constants: the
    moment a second revision is added to the tree, both entries see it.
    ``cfg`` is injectable only so tests can point at a temporary tree;
    production callers pass nothing (or the config they already built).
    """
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg or alembic_config())
    return RevisionContext(
        known_revisions=frozenset(r.revision for r in script.walk_revisions()),
        legacy_revisions=KNOWN_LEGACY_REVISIONS,
        heads=tuple(script.get_heads()),
    )


def read_database_state(conn: Connection) -> DatabaseState:
    """Read version rows and table names from an open read-only check connection."""
    inspector = inspect(conn)
    table_names = frozenset(inspector.get_table_names())
    if "alembic_version" in table_names:
        version_rows = tuple(
            conn.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        )
    else:
        version_rows = ()
    return DatabaseState(version_rows=version_rows, table_names=table_names)


def plan_migration(state: DatabaseState, *, context: RevisionContext) -> MigrationPlan:
    """Classify a database state once, for both migration entries.

    Both ``mail_core.__main__.run_migrations`` and ``run_migration`` build a
    :class:`DatabaseState` and a :class:`RevisionContext` and act on the single
    returned plan; classification never depends on which entry is running or
    on ``check_only``/``dry_run``. The entries then execute only the actions
    they support: startup can run ``alembic upgrade head``, the offline tool
    verifies schema and converts supported legacy databases.
    """
    version_rows = state.version_rows
    business_tables = tuple(sorted(state.table_names & REQUIRED_TABLES))

    if len(version_rows) > 1:
        return MigrationPlan(
            action=MigrationAction.MULTIPLE_VERSIONS,
            version_rows=version_rows,
            message=(
                f"alembic_version contains {len(version_rows)} rows "
                f"({', '.join(sorted(version_rows))}); expected at most one head. "
                "Resolve the duplicate version rows (restore a clean backup or stamp a "
                "single head with scripts/migrate_to_unified_baseline.py) before running "
                "migrations. The database was not modified."
            ),
        )

    if not version_rows:
        if business_tables:
            sample = ", ".join(business_tables[:5])
            return MigrationPlan(
                action=MigrationAction.NO_VERSION_WITH_BUSINESS_TABLES,
                business_tables=business_tables,
                message=(
                    "Database has business tables but no alembic_version mark "
                    f"({len(business_tables)} unified-baseline tables present, e.g. {sample}). "
                    "Its origin cannot be verified; refusing to stamp the unified "
                    "baseline blindly (creating the remaining tables could collide "
                    "with existing data). Restore a known-good backup and migrate "
                    "the data explicitly. The database was not modified."
                ),
            )
        return MigrationPlan(
            action=MigrationAction.EMPTY_DATABASE,
            message=(
                "Database is empty (no alembic_version and no unified-baseline "
                "business tables). The offline tool does not create tables or stamp "
                "an empty database: start mail-core (python -m mail_core) or run "
                "'alembic upgrade head' to initialize the unified baseline. "
                "The database was not modified."
            ),
        )

    current = version_rows[0]
    if current in context.known_revisions or current == UNIFIED_BASELINE_REVISION:
        return MigrationPlan(
            action=MigrationAction.AT_BASELINE,
            current_revision=current,
            version_rows=version_rows,
            message=(
                f"Database is at recognized revision '{current}' "
                "(current unified baseline / migration tree)."
            ),
        )

    if current in context.legacy_revisions or is_legacy_revision(current):
        return MigrationPlan(
            action=MigrationAction.LEGACY,
            current_revision=current,
            version_rows=version_rows,
            message=(
                f"Database is at known legacy revision '{current}': "
                "the narrow legacy conversion path applies."
            ),
        )

    head_text = ", ".join(context.heads) if context.heads else "(none)"
    return MigrationPlan(
        action=MigrationAction.UNKNOWN_REVISION,
        current_revision=current,
        version_rows=version_rows,
        message=(
            f"Database is at an unrecognized legacy revision '{current}' "
            f"(current heads: {head_text}). Its origin cannot be verified; restore a "
            "known-good backup and migrate the data explicitly rather than stamping "
            "or letting Alembic upgrade it. The database was not modified."
        ),
    )


def run_migration(
    database_url: str | None = None,
    *,
    dry_run: bool = False,
) -> None:
    """Perform offline schema verification, supported legacy rebuild, and baseline stamping."""
    import os

    raw_url = database_url or os.environ.get("MAIL_CORE_DATABASE_URL")
    if not raw_url:
        raise ValueError(
            "Database URL not specified and MAIL_CORE_DATABASE_URL is not set"
        )

    safe_url = make_url(raw_url).render_as_string(hide_password=True)
    LOG.info("Connecting to database at %s", safe_url)

    context = revision_context()
    with read_only_connection(raw_url) as conn:
        plan = plan_migration(read_database_state(conn), context=context)
        LOG.info(
            "Migration classification: %s (alembic_version %s)",
            plan.action.value,
            plan.current_revision,
        )

        if plan.action in (
            MigrationAction.MULTIPLE_VERSIONS,
            MigrationAction.NO_VERSION_WITH_BUSINESS_TABLES,
            MigrationAction.UNKNOWN_REVISION,
            MigrationAction.EMPTY_DATABASE,
        ):
            raise SchemaValidationError(plan.message)

        is_legacy = plan.action == MigrationAction.LEGACY
        if is_legacy:
            errors = verify_narrow_legacy_schema(conn)
        else:
            errors = verify_database_schema(conn)

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

        stamp_unified_baseline(conn, dry_run=True)

        if dry_run:
            LOG.info("Dry-run complete: no writes were performed.")
            return

    if is_legacy:
        LOG.info(
            "Detected supported legacy revision '%s'. Rebuilding folder_patrol_status "
            "from sync_checkpoints before stamping the unified baseline.",
            plan.current_revision,
        )
        apply_narrow_legacy_conversion(raw_url)
        return

    engine = create_engine(check_connect_url(raw_url))
    try:
        with engine.begin() as conn:
            stamp_unified_baseline(conn, dry_run=False)
    finally:
        engine.dispose()
