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

# Guard: strictly parse and validate target database URL before any setup, migrations, or tests
TARGET_INFO="$(python3 - <<'PY'
import os, re, sys, urllib.parse

raw_url = os.environ.get("MAIL_CORE_DATABASE_URL", "")
if not raw_url:
    print("MAIL_CORE_DATABASE_URL is unset or empty", file=sys.stderr)
    sys.exit(2)

try:
    parsed = urllib.parse.urlsplit(raw_url)
except Exception as exc:
    print(f"Failed to parse MAIL_CORE_DATABASE_URL: {exc}", file=sys.stderr)
    sys.exit(2)

if not parsed.scheme or not parsed.scheme.startswith("postgresql"):
    print(f"refusing non-PostgreSQL scheme in MAIL_CORE_DATABASE_URL: {parsed.scheme!r}", file=sys.stderr)
    sys.exit(2)

db_name = parsed.path.lstrip("/")
if not db_name:
    print("refusing empty database name in MAIL_CORE_DATABASE_URL", file=sys.stderr)
    sys.exit(2)

pattern = r"^kkmail_test(_[a-zA-Z0-9_-]+)?$"
if not re.match(pattern, db_name):
    print(
        f"refusing non-test database: {db_name!r}. "
        f"Database name must match pattern '{pattern}' (e.g. kkmail_test, kkmail_test_ci)",
        file=sys.stderr,
    )
    sys.exit(2)

host = parsed.hostname or "localhost"
port = parsed.port or 5432
print(f"{host}:{port}/{db_name}")
PY
)"
echo "Verified disposable test database target: $TARGET_INFO"
rand_b64() { python3 -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())'; }
rand_hex() { python3 -c 'import secrets; print(secrets.token_hex(32))'; }

export MAIL_CORE_BLOB_KEY_V1="${MAIL_CORE_BLOB_KEY_V1:-$(rand_b64)}"
export MAIL_CORE_BLOB_ACTIVE_VERSION="${MAIL_CORE_BLOB_ACTIVE_VERSION:-1}"
export MAIL_CORE_BACKUP_KEY="${MAIL_CORE_BACKUP_KEY:-$(rand_b64)}"
export MAIL_CORE_SECRET_KEY="${MAIL_CORE_SECRET_KEY:-$(rand_hex)}"
export MAIL_CORE_REQUIRE_DB=1
export PYTHONPATH=src

pip install -q -r requirements-mail-core.txt -r requirements-dev.txt
alembic -c src/mail_core/db/alembic.ini upgrade head
pytest tests -q --tb=short
