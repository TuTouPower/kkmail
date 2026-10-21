#!/usr/bin/env bash
# Local helper checks for fetch-pg-binaries.sh (no network).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Path-traversal members must be rejected by the same logic as the script.
cat > "$TMP/check_tar_safe.sh" <<'INNER'
set -euo pipefail
assert_tar_safe() {
  local archive="$1"
  local member
  while IFS= read -r member; do
    case "$member" in
      "" ) continue ;;
      /* | *../* | */../* | */.. | .. | ../* | *.. )
        echo "unsafe:$member"
        exit 1
        ;;
    esac
  done < <(tar -tzf "$archive")
}
assert_tar_safe "$1"
INNER

# Safe archive
mkdir -p "$TMP/safe/bin"
echo x > "$TMP/safe/bin/pg_ctl"
tar -czf "$TMP/safe.tgz" -C "$TMP/safe" .
bash "$TMP/check_tar_safe.sh" "$TMP/safe.tgz"

# Traversal archive (member name contains ..)
mkdir -p "$TMP/evil"
python3 -c '
import tarfile, io, sys
with tarfile.open(sys.argv[1], "w:gz") as tar:
    ti = tarfile.TarInfo(name="../evil_bin")
    ti.size = 1
    tar.addfile(ti, io.BytesIO(b"x"))
' "$TMP/evil.tgz"
if bash "$TMP/check_tar_safe.sh" "$TMP/evil.tgz" 2>/dev/null; then
  echo "expected traversal reject" >&2
  exit 1
fi

# Allowlist patterns (inline)
url_allowed() {
  local u="$1"
  case "$u" in
    https://github.com/theseus-rs/postgresql-binaries/releases/download/*) return 0 ;;
    https://get.enterprisedb.com/postgresql/*) return 0 ;;
    *) return 1 ;;
  esac
}
url_allowed "https://github.com/theseus-rs/postgresql-binaries/releases/download/16.6.0/postgresql-16.6.0-x86_64-unknown-linux-gnu.tar.gz"
url_allowed "https://github.com/theseus-rs/postgresql-binaries/releases/download/16.6.0/postgresql-16.6.0-aarch64-apple-darwin.tar.gz"
url_allowed "https://github.com/theseus-rs/postgresql-binaries/releases/download/16.6.0/postgresql-16.6.0-x86_64-pc-windows-msvc.tar.gz"
url_allowed "https://get.enterprisedb.com/postgresql/postgresql-16.6-1-linux-x64-binaries.tar.gz"
url_allowed "https://get.enterprisedb.com/postgresql/postgresql-16.6-1-osx-binaries.zip"
url_allowed "https://get.enterprisedb.com/postgresql/postgresql-16.6-1-windows-x64-binaries.zip"
if url_allowed "https://evil.example/postgresql.tar.gz"; then
  echo "evil URL should fail" >&2
  exit 1
fi
if url_allowed "http://github.com/theseus-rs/postgresql-binaries/releases/download/x/y.tar.gz"; then
  echo "http should fail" >&2
  exit 1
fi

echo "test_fetch_pg_binaries_helpers: ok"
