#!/usr/bin/env bash
# Dependencies are installed separately; every full run owns a fresh database.
# Gate policy (T5): the default run requires the dedicated test PostgreSQL
# service (auto-start attempted once); without it the gate fails explicitly
# (exit 2) instead of silently degrading. 'unit' is an explicit quick mode
# only and never counts as a full pass. See docs/blueprint/testing.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo 'Missing .venv: run uv venv .venv and uv pip install --python .venv/bin/python -r requirements-dev.txt' >&2
    exit 2
fi
if [[ -z "${KKMAIL_TEST_PG_PASSWORD:-}" && -f "$ROOT/.env.test" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ROOT/.env.test"
    set +a
fi
KKMAIL_TEST_IMAP_REVISION="$(git -C "$ROOT" rev-parse --verify HEAD)"
export KKMAIL_TEST_IMAP_REVISION
if [[ $# -eq 0 ]]; then
    set -- run
fi
exec "$PYTHON" "$ROOT/scripts/test_pg_runtime.py" "$@"
