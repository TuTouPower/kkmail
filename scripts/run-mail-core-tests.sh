#!/usr/bin/env bash
# Local / CI smoke: migrate mail-core schema then pytest tests/mail_core.
# Expects Postgres reachable via MAIL_CORE_DATABASE_URL (default :5433).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export MAIL_CORE_DATABASE_URL="${MAIL_CORE_DATABASE_URL:-postgresql+psycopg://kkmail:kkmail@127.0.0.1:5433/kkmail_mail}"
if [[ -z "${MAIL_CORE_BLOB_KEY_V1:-}" ]]; then
  export MAIL_CORE_BLOB_KEY_V1="$(python3 -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())')"
fi
export MAIL_CORE_BLOB_ACTIVE_VERSION="${MAIL_CORE_BLOB_ACTIVE_VERSION:-1}"
if [[ -z "${MAIL_CORE_BACKUP_KEY:-}" ]]; then
  export MAIL_CORE_BACKUP_KEY="$(python3 -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())')"
fi
export MAIL_CORE_SECRET_KEY="${MAIL_CORE_SECRET_KEY:-test-mail-core-secret-key-ci-only}"
export MAIL_CORE_LOGIN_PASSWORD="${MAIL_CORE_LOGIN_PASSWORD:-test-login-password}"
export MAIL_CORE_API_KEYS="${MAIL_CORE_API_KEYS:-test-api-key-for-pytest}"

pip install -q -r requirements-mail-core.txt
alembic -c mail_core/db/alembic.ini upgrade head
pytest tests/mail_core -q --tb=line
