#!/usr/bin/env bash
# Start a lightweight IMAP L2 fixture for mail-core tests.
# Prefer docker compose service `imap` (Dovecot). Fallback: pymap if installed.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${MAIL_CORE_IMAP_PORT:-1143}"
export MAIL_CORE_IMAP_HOST="${MAIL_CORE_IMAP_HOST:-127.0.0.1}"
export MAIL_CORE_IMAP_PORT="$PORT"
export MAIL_CORE_IMAP_USER="${MAIL_CORE_IMAP_USER:-alice@kkmail.test}"
export MAIL_CORE_IMAP_PASS="${MAIL_CORE_IMAP_PASS:-alice-imap-pass}"

if docker compose -f docker-compose.mail-core.yml up -d imap 2>/dev/null; then
  echo "Dovecot IMAP via compose on :$PORT"
  exit 0
fi

if python -c "import pymap" 2>/dev/null; then
  echo "Starting pymap on :$PORT (fallback)"
  exec python -m pymap \
    --host "$MAIL_CORE_IMAP_HOST" --port "$PORT" \
    --passfile <(echo "$MAIL_CORE_IMAP_USER $MAIL_CORE_IMAP_PASS") \
    "$ROOT/tests/mail_core/fixtures/maildir"
fi

cat >&2 <<HINT
Neither docker compose imap nor pymap is available.
  docker compose -f docker-compose.mail-core.yml up -d imap
  # or: pip install pymap && ./scripts/start-mail-core-imap.sh
HINT
exit 1
