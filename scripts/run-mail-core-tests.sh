#!/usr/bin/env bash
# Local / CI smoke: migrate mail-core schema then pytest tests/mail_core.
# Expects Postgres reachable via MAIL_CORE_DATABASE_URL (default :5433).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export MAIL_CORE_DATABASE_URL="${MAIL_CORE_DATABASE_URL:-postgresql+psycopg://kkmail:kkmail@127.0.0.1:5433/kkmail_mail}"
export MAIL_CORE_BLOB_KEY_V1="${MAIL_CORE_BLOB_KEY_V1:-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=}"
export MAIL_CORE_BLOB_ACTIVE_VERSION="${MAIL_CORE_BLOB_ACTIVE_VERSION:-1}"
export MAIL_CORE_BACKUP_KEY="${MAIL_CORE_BACKUP_KEY:-BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=}"

pip install -q -r requirements-mail-core.txt
alembic -c mail_core/db/alembic.ini upgrade head
pytest tests/mail_core -q --tb=line
