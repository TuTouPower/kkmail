#!/usr/bin/env bash
# Migrate the mail-core schema, then run the full Python test suite against Postgres.
#
# Requires MAIL_CORE_DATABASE_URL pointing at a disposable test database, e.g.
#   export MAIL_CORE_DATABASE_URL=postgresql+psycopg://USER:PASS@127.0.0.1:5433/kkmail_test
# Keys/secrets below are generated per run when unset (test-only, never reused).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${MAIL_CORE_DATABASE_URL:?set MAIL_CORE_DATABASE_URL to a disposable test database}"
rand_b64() { python3 -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())'; }
rand_hex() { python3 -c 'import secrets; print(secrets.token_hex(32))'; }

export MAIL_CORE_BLOB_KEY_V1="${MAIL_CORE_BLOB_KEY_V1:-$(rand_b64)}"
export MAIL_CORE_BLOB_ACTIVE_VERSION="${MAIL_CORE_BLOB_ACTIVE_VERSION:-1}"
export MAIL_CORE_BACKUP_KEY="${MAIL_CORE_BACKUP_KEY:-$(rand_b64)}"
export MAIL_CORE_SECRET_KEY="${MAIL_CORE_SECRET_KEY:-$(rand_hex)}"
export MAIL_CORE_REQUIRE_DB=1

pip install -q -r requirements-mail-core.txt -r requirements-dev.txt
alembic -c mail_core/db/alembic.ini upgrade head
pytest tests -q --tb=short
