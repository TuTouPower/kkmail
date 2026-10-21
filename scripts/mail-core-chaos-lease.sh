#!/usr/bin/env bash
# Chaos smoke: lease steal + stale job reclaim after simulated worker kill.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi

export MAIL_CORE_DATABASE_URL="${MAIL_CORE_DATABASE_URL:-postgresql+psycopg://kkmail:kkmail@127.0.0.1:5433/kkmail_test}"
export PYTHONPATH="${ROOT}/src:${PYTHONPATH:-$ROOT}"

# Guard: require database name in MAIL_CORE_DATABASE_URL to contain 'test' or 'chaos'
DB_NAME="$("$PY" -c 'import os, urllib.parse; print(urllib.parse.urlsplit(os.environ.get("MAIL_CORE_DATABASE_URL", "")).path.lstrip("/"))')"
if [[ "$DB_NAME" != *test* && "$DB_NAME" != *chaos* ]]; then
  echo "refusing to run chaos test on non-disposable database: '$DB_NAME' (database name must contain 'test' or 'chaos')" >&2
  exit 2
fi
"$PY" -m pip install -q -r requirements-mail-core.txt
"$PY" -m alembic -c src/mail_core/db/alembic.ini upgrade head
"$PY" -m pytest tests/mail_core/test_chaos_lease_recovery.py tests/mail_core/test_sync_leases_jobs.py -q --tb=short
