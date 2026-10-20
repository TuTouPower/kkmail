#!/usr/bin/env bash
# Bundle the Flask backend as a single-file sidecar for the Electron shell.
# Requires PyInstaller in the active Python environment (pip install pyinstaller).
# Build the React UI first (cd frontend && npm ci && npm run build) so it is bundled too.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! python3 -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller not found. Install it first: python3 -m pip install pyinstaller" >&2
  exit 1
fi

SEP=":"
EXE=""
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) SEP=";"; EXE=".exe" ;;
esac

# Segments are exec()'d at runtime, so PyInstaller cannot see their imports.
mapfile -t HIDDEN < <(python3 - <<'PY'
import ast, pathlib
hidden = {"outlook_web.runtime", "outlook_web.windows_tray", "outlook_web.windows_update"}
for p in pathlib.Path("outlook_web/segments").glob("*.py"):
    for node in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            hidden.update(a.name for a in node.names if a.name != "__future__")
        elif isinstance(node, ast.ImportFrom) and node.module and node.module not in {"__future__", "web_outlook_app"}:
            hidden.add(node.module)
for name in sorted(hidden):
    print(name)
PY
)

ARGS=(--noconfirm --onefile --name kkmail-backend
  --add-data "templates${SEP}templates"
  --add-data "static${SEP}static"
  --add-data "outlook_web/segments${SEP}outlook_web/segments"
  --add-data "VERSION${SEP}.")
if [ -f frontend/dist/index.html ]; then
  ARGS+=(--add-data "frontend/dist${SEP}frontend/dist")
else
  echo "warning: frontend/dist missing; sidecar relies on KKMAIL_FRONTEND_DIST at runtime" >&2
fi
for mod in "${HIDDEN[@]}"; do ARGS+=(--hidden-import "$mod"); done

python3 -m PyInstaller "${ARGS[@]}" web_outlook_app.py
mkdir -p desktop/resources
cp "dist/kkmail-backend${EXE}" "desktop/resources/kkmail-backend${EXE}"
echo "sidecar: desktop/resources/kkmail-backend${EXE}"
