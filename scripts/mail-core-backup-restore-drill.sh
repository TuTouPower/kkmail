#!/usr/bin/env bash
# Backup → verify → decrypt dry-run restore drill (no live pg_restore by default).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/src:${PYTHONPATH:-$ROOT}"
export PATH="${ROOT}/scripts/test_pg_client:${PATH}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

OUT_RAW="${1:-/tmp/kkmail-backup-drill}"

# Validate physical path and security boundaries before creating directories or deleting
OUT="$( "$PYTHON" - "$OUT_RAW" "$ROOT" <<'PY'
import os
import re
import sys
import tempfile
from pathlib import Path

raw = sys.argv[1]
repo_root = Path(sys.argv[2]).resolve()

if not raw or raw.strip() == "":
    print("refusing empty OUT path", file=sys.stderr)
    sys.exit(2)

# Refuse dangerous root strings or path traversal sequences
if any(part in ("..", ".") for part in Path(raw).parts) or ".." in raw:
    print(f"refusing path traversal in OUT path: {raw}", file=sys.stderr)
    sys.exit(2)

base_name = Path(raw).name
if not re.match(r"^kkmail-backup-drill([a-zA-Z0-9_-]+)?$", base_name):
    print(f"OUT directory basename must match '^kkmail-backup-drill([a-zA-Z0-9_-]+)?$' (got {base_name!r})", file=sys.stderr)
    sys.exit(2)

# Allowed physical boundaries
allowed_roots = [
    repo_root,
    Path("/tmp").resolve(),
    Path(tempfile.gettempdir()).resolve(),
]

raw_path = Path(raw)
raw_parent = raw_path.parent if raw_path.parent != raw_path else Path(".")

# Check existing ancestors to prevent traversing through escaping symlinks
curr = raw_parent
while not curr.exists() and curr != curr.parent:
    curr = curr.parent

if not curr.exists():
    print(f"No existing ancestor found for {raw_parent}", file=sys.stderr)
    sys.exit(2)

curr_phys = curr.resolve()
if not any(curr_phys == r or r in curr_phys.parents for r in allowed_roots):
    print(f"Ancestor directory {curr} resolves outside allowed boundaries: {curr_phys}", file=sys.stderr)
    sys.exit(2)

# Ensure parent directory is created safely
raw_parent.mkdir(parents=True, exist_ok=True)
parent_phys = raw_parent.resolve()
if not any(parent_phys == r or r in parent_phys.parents for r in allowed_roots):
    print(f"Parent physical path {parent_phys} is outside allowed roots", file=sys.stderr)
    sys.exit(2)

target = parent_phys / base_name
# Target must not equal any allowed root or filesystem root
if target == Path("/") or any(target == r for r in allowed_roots):
    print(f"Refusing target identical to root: {target}", file=sys.stderr)
    sys.exit(2)

if target.is_symlink():
    print(f"Refusing target that is a symlink: {target}", file=sys.stderr)
    sys.exit(2)

if target.exists():
    target_real = target.resolve()
    if not any(r in target_real.parents or target_real == r for r in allowed_roots):
        print(f"Target physical path {target_real} escapes allowed boundaries", file=sys.stderr)
        sys.exit(2)

print(str(target))
PY
)"

# Pre-deletion sanity verification
if [[ -z "$OUT" || "$OUT" == "/" || -L "$OUT" ]]; then
  echo "Pre-deletion safety verification failed for OUT: '$OUT'" >&2
  exit 2
fi

case "$(basename "$OUT")" in
  kkmail-backup-drill*) ;;
  *)
    echo "Refusing deletion of unexpected directory: '$OUT'" >&2
    exit 2
    ;;
esac

rm -rf -- "$OUT"
mkdir -p "$OUT"

# Ensure backup key differs from blob key
export MAIL_CORE_BACKUP_KEY="${MAIL_CORE_BACKUP_KEY:-$( "$PYTHON" -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())')}"
export MAIL_CORE_BLOB_KEY_V1="${MAIL_CORE_BLOB_KEY_V1:-$( "$PYTHON" -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())')}"
export KKMAIL_DRILL_OUT="$OUT"

# Heredoc is single-quoted so Path is not built from untrusted shell expansion.
"$PYTHON" - <<'PY'
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
