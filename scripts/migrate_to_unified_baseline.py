#!/usr/bin/env python3
"""Offline migration entrypoint for the unified baseline (adoption A17).

Thin wrapper: all judgement and execution logic lives in
``mail_core.db.baseline`` (shared with the ``python -m mail_core``
startup orchestration). This script only parses CLI arguments and maps
outcomes to exit codes: 0 success, 1 schema validation failure,
2 any other failure (including a missing database URL).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SRC = ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mail_core.db.baseline import SchemaValidationError, run_migration

LOG = logging.getLogger("migrate_to_unified_baseline")


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
