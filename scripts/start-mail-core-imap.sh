#!/usr/bin/env bash
# Start a lightweight IMAP L2 fixture for mail-core tests.
# Prefer docker compose service `imap` (Dovecot, profile=imap). Fallback: pymap.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${MAIL_CORE_IMAP_PORT:-1143}"
export MAIL_CORE_IMAP_HOST="${MAIL_CORE_IMAP_HOST:-127.0.0.1}"
export MAIL_CORE_IMAP_PORT="$PORT"
export MAIL_CORE_IMAP_USER="${MAIL_CORE_IMAP_USER:-alice@kkmail.test}"
export MAIL_CORE_IMAP_PASS="${MAIL_CORE_IMAP_PASS:-alice-imap-pass}"

if [[ -z "${KKMAIL_TEST_PG_PASSWORD:-}" && -f "$ROOT/.env.test" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT/.env.test"
  set +a
fi

PY="$(command -v python3 || true)"
if [[ -z "$PY" ]]; then
  PY="$(command -v python || true)"
fi

wait_for_imap_ready() {
  if [[ -z "$PY" ]]; then
    echo "Cannot verify IMAP readiness: python3/python is not available." >&2
    return 1
  fi
  "$PY" - "$MAIL_CORE_IMAP_HOST" "$PORT" <<'PY'
import socket
import sys
import time

host = sys.argv[1]
port = int(sys.argv[2])
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    try:
        with socket.create_connection((host, port), timeout=1):
            raise SystemExit(0)
    except OSError:
        time.sleep(0.25)
print(f"IMAP did not become ready at {host}:{port} within 30 seconds", file=sys.stderr)
raise SystemExit(1)
PY
}

if docker compose -p kkmail_test_pg -f config/test_pg_compose.yaml up -d imap; then
  if wait_for_imap_ready; then
    echo "Dovecot IMAP via test compose on :$PORT"
    exit 0
  fi
  exit 1
fi

if docker compose -f docker-compose.mail-core.yml --profile imap up -d imap; then
  if wait_for_imap_ready; then
    echo "Dovecot IMAP via compose (profile=imap) on :$PORT"
    exit 0
  fi
  exit 1
fi
if [[ -n "$PY" ]] && "$PY" -c "import pymap" 2>/dev/null; then
  echo "Starting pymap on :$PORT (fallback)"
  exec "$PY" -m pymap \
    --host "$MAIL_CORE_IMAP_HOST" --port "$PORT" \
    --passfile <(echo "$MAIL_CORE_IMAP_USER $MAIL_CORE_IMAP_PASS") \
    "$ROOT/tests/mail_core/fixtures/maildir"
fi

cat >&2 <<HINT
Neither docker compose imap nor pymap is available.
  docker compose -f docker-compose.mail-core.yml --profile imap up -d imap
  # or: python3 -m pip install pymap && ./scripts/start-mail-core-imap.sh
HINT
if [[ -z "${KKMAIL_TEST_PG_PASSWORD:-}" ]]; then
  echo "Hint: KKMAIL_TEST_PG_PASSWORD is not set (check .env.test on main branch/worktree if working in a git worktree)." >&2
fi
exit 1
