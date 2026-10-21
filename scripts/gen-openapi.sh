#!/usr/bin/env bash
# Regenerate schemas/openapi.json and src/frontend/src/api/generated/schema.ts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ -f .venv/bin/activate ]]; then
  # shellcheck source=/dev/null
  source .venv/bin/activate
fi
python scripts/export_openapi.py
(cd src/frontend && npm run openapi:gen)
echo "OpenAPI + TS types regenerated."
