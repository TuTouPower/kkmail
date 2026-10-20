#!/usr/bin/env bash
# Chaos smoke: lease steal + stale job reclaim after simulated worker kill.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export MAIL_CORE_DATABASE_URL="${MAIL_CORE_DATABASE_URL:-postgresql+psycopg://kkmail:kkmail@127.0.0.1:5433/kkmail_mail}"
pip install -q -r requirements-mail-core.txt
alembic -c mail_core/db/alembic.ini upgrade head
pytest tests/mail_core/test_chaos_lease_recovery.py tests/mail_core/test_sync_leases_jobs.py -q --tb=short
