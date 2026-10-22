#!/usr/bin/env bash
# Dependencies are installed separately; every full run owns a fresh database.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo 'Missing .venv: run uv venv .venv and uv pip install --python .venv/bin/python -r requirements-dev.txt' >&2
    exit 2
fi
if [[ $# -eq 0 ]]; then
    set -- run
fi
exec "$PYTHON" "$ROOT/scripts/test_pg_runtime.py" "$@"
