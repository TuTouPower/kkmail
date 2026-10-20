#!/usr/bin/env bash
# Bundle mail-core (`python -m mail_core`: migrations + API + embedded worker)
# as a single-file sidecar for the Electron shell.
# Requires PyInstaller: prefer .venv, else python3 -m pip install pyinstaller
# The React UI is shipped separately by electron-builder (extraResources frontend/dist).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/venv/bin/python" ]]; then
  PY="$ROOT/venv/bin/python"
else
  PY="$(command -v python3)"
fi

if ! "$PY" -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller not found. Install it first: $PY -m pip install pyinstaller" >&2
  exit 1
fi

SEP=":"
EXE=""
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) SEP=";"; EXE=".exe" ;;
esac

"$PY" -m PyInstaller --noconfirm --onefile --name kkmail-backend \
  --collect-submodules mail_core \
  --collect-submodules uvicorn \
  --add-data "mail_core/db/alembic.ini${SEP}mail_core/db" \
  --add-data "mail_core/db/alembic${SEP}mail_core/db/alembic" \
  mail_core/__main__.py
mkdir -p desktop/resources
cp "dist/kkmail-backend${EXE}" "desktop/resources/kkmail-backend${EXE}"
echo "sidecar: desktop/resources/kkmail-backend${EXE}"
