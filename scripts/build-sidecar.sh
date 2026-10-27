#!/usr/bin/env bash
# Bundle mail-core (`python -m mail_core`: migrations + API + embedded worker)
# as a single-file sidecar for the Electron shell.
# Strict dependency lock & build provenance enforcement.
# The React UI is shipped separately by electron-builder (extraResources frontend/dist).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/src:${PYTHONPATH:-}"

if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
elif [[ -x "$ROOT/venv/bin/python" ]]; then
  PY="$ROOT/venv/bin/python"
else
  PY="$(command -v python3)"
fi

echo "Verifying production dependency lock consistency..."
if ! "$PY" scripts/check_dep_locks.py --check; then
  echo "Dependency lock mismatch. Run '$PY scripts/check_dep_locks.py' and ensure matching environment." >&2
  exit 1
fi

if ! "$PY" -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller not found in $PY. Install it first: $PY -m pip install 'pyinstaller>=6.11.0'" >&2
  exit 1
fi

PY_VERSION="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")')"
PYINSTALLER_VERSION="$("$PY" -m PyInstaller --version)"
GIT_COMMIT="$(git rev-parse HEAD 2>/dev/null || echo "unknown")"
BUILD_TIME="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

SEP=":"
EXE=""
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) SEP=";"; EXE=".exe" ;;
esac

echo "Building kkmail-backend sidecar (Python $PY_VERSION, PyInstaller $PYINSTALLER_VERSION, commit $GIT_COMMIT)..."

"$PY" -m PyInstaller --noconfirm --onefile --name kkmail-backend \
  --paths "src" \
  --collect-submodules mail_core \
  --collect-submodules uvicorn \
  --add-data "src/mail_core/db/alembic.ini${SEP}mail_core/db" \
  --add-data "src/mail_core/db/alembic${SEP}mail_core/db/alembic" \
  src/mail_core/__main__.py

# Smoke check (A305): the frozen binary must at least start and answer
# --help (argparse exits before any server side effects) before it is
# copied into the desktop resources; a broken artifact aborts the build.
echo "Smoke-checking built sidecar..."
if ! "dist/kkmail-backend${EXE}" --help >/dev/null; then
  echo "Built sidecar failed the smoke check (--help); refusing to copy it into desktop resources." >&2
  exit 1
fi

mkdir -p src/desktop/resources
cp "dist/kkmail-backend${EXE}" "src/desktop/resources/kkmail-backend${EXE}"

cat <<EOF > src/desktop/resources/backend-build-info.json
{
  "git_commit": "$GIT_COMMIT",
  "python_version": "$PY_VERSION",
  "pyinstaller_version": "$PYINSTALLER_VERSION",
  "built_at": "$BUILD_TIME",
  "lock_file": "requirements-mail-core.lock"
}
EOF

echo "sidecar built: src/desktop/resources/kkmail-backend${EXE}"
echo "build provenance: src/desktop/resources/backend-build-info.json"
