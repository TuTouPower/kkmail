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
# No hardcoded fixture password (A227): the Dovecot images carry their own
# seeded credential, so this value is only consumed by the pymap fallback
# passfile below — and that path refuses to start when it is unset.
export MAIL_CORE_IMAP_PASS="${MAIL_CORE_IMAP_PASS:-}"
IMAP_PASSFILE=""

cleanup_imap_passfile() {
  if [[ -n "$IMAP_PASSFILE" ]]; then
    rm -f -- "$IMAP_PASSFILE" || echo "Could not remove temporary IMAP passfile." >&2
  fi
}
trap cleanup_imap_passfile EXIT

if [[ -z "${KKMAIL_TEST_PG_PASSWORD:-}" && -f "$ROOT/.env.test" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT/.env.test"
  set +a
fi
KKMAIL_TEST_IMAP_REVISION="$(git -C "$ROOT" rev-parse --verify HEAD)"
export KKMAIL_TEST_IMAP_REVISION

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
  if [[ -z "$MAIL_CORE_IMAP_PASS" ]]; then
    echo "Refusing to start the pymap fallback: MAIL_CORE_IMAP_PASS is not set and there is no default fixture password. Set MAIL_CORE_IMAP_PASS explicitly (e.g. in .env.test) and re-run." >&2
    exit 1
  fi
  echo "Starting pymap on :$PORT (fallback)"
  mkdir -p "$ROOT/.scratch"
  IMAP_PASSFILE="$(mktemp "$ROOT/.scratch/imap-pass.XXXXXX")"
  chmod 600 "$IMAP_PASSFILE"
  printf '%s %s\n' "$MAIL_CORE_IMAP_USER" "$MAIL_CORE_IMAP_PASS" > "$IMAP_PASSFILE"
  if "$PY" -m pymap \
      --host "$MAIL_CORE_IMAP_HOST" --port "$PORT" \
      --passfile "$IMAP_PASSFILE" \
      "$ROOT/tests/mail_core/fixtures/maildir"; then
    exit 0
  else
    exit "$?"
  fi
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
