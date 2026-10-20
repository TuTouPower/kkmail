#!/usr/bin/env bash
# Backup → verify → decrypt dry-run restore drill (no live pg_restore by default).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${PYTHONPATH:-$ROOT}"

OUT_RAW="${1:-[REDACTED]backup-drill}"
# Refuse empty / filesystem roots / path traversal before any rm -rf.
case "$OUT_RAW" in
  ""|"/"|"/tmp"|"/var"|"/home"|"/usr"|"/etc"|"/root"|*".."*)
    echo "refusing unsafe OUT path: $OUT_RAW" >&2
    exit 2
    ;;
esac
# Resolve to an absolute path; parent must already exist (or be creatable under /tmp).
OUT_PARENT="$(dirname -- "$OUT_RAW")"
OUT_BASE="$(basename -- "$OUT_RAW")"
mkdir -p "$OUT_PARENT"
OUT="$(cd "$OUT_PARENT" && pwd)/$OUT_BASE"
case "$OUT" in
  /tmp/*|"$ROOT"/*)
    ;;
  *)
    echo "OUT must be under /tmp or the repo root (got $OUT)" >&2
    exit 2
    ;;
esac
rm -rf -- "$OUT"
mkdir -p "$OUT"

# Ensure backup key differs from blob key
export MAIL_CORE_BACKUP_KEY="${MAIL_CORE_BACKUP_KEY:-$(python -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())')}"
export MAIL_CORE_BLOB_KEY_V1="${MAIL_CORE_BLOB_KEY_V1:-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=}"
export KKMAIL_DRILL_OUT="$OUT"

# Heredoc is single-quoted so Path is not built from untrusted shell expansion.
python - <<'PY'
import os
from pathlib import Path

from mail_core.backup.package import create_backup_package, verify_backup_package

out = Path(os.environ["KKMAIL_DRILL_OUT"])
url = "postgresql://nobody:nope@127.0.0.1:1/none"
try:
    path = create_backup_package(
        out, include_blobs=True, encrypt=True, database_url_override=url
    )
    vr = verify_backup_package(path)
    assert vr.ok, vr.errors
    print("created", path)
    print("verify", vr)
except RuntimeError as exc:
    # Offline drill: explicit stub dump must NOT verify clean without allow_stub.
    print("pg_dump unavailable (", exc, "); crypto-only stub drill")
    path = create_backup_package(
        out,
        include_blobs=True,
        encrypt=True,
        database_url_override=url,
        allow_dump_stub=True,
    )
    vr_fail = verify_backup_package(path)
    assert not vr_fail.ok, "sql_stub must not verify as restoreable"
    assert any("sql_stub" in e for e in vr_fail.errors), vr_fail.errors
    vr = verify_backup_package(path, allow_stub=True)
    assert vr.ok, vr.errors
    print("created", path)
    print("verify_reject_stub", vr_fail.errors)
    print("verify_allow_stub", vr)
print("DRILL_OK")
PY
