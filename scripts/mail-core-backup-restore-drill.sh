#!/usr/bin/env bash
# Backup → verify → decrypt dry-run restore drill (no live pg_restore by default).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${PYTHONPATH:-$ROOT}"
OUT="${1:-/tmp/kkmail-backup-drill}"
rm -rf "$OUT"
mkdir -p "$OUT"

# Ensure backup key differs from blob key
export MAIL_CORE_BACKUP_KEY="${MAIL_CORE_BACKUP_KEY:-$(python -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())')}"
export MAIL_CORE_BLOB_KEY_V1="${MAIL_CORE_BLOB_KEY_V1:-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=}"

python - <<PY
from pathlib import Path
from mail_core.backup.package import create_backup_package, verify_backup_package
out = Path("$OUT")
# encrypt=True; may stub dump if pg_dump/DB unreachable — package still seals
path = create_backup_package(out, include_blobs=True, encrypt=True,
    database_url_override="postgresql://nobody:nope@127.0.0.1:1/none")
print("created", path)
vr = verify_backup_package(path)
print("verify", vr)
assert vr.ok, vr.errors
print("DRILL_OK")
PY
