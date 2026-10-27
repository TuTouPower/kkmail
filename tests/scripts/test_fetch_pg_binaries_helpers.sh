#!/usr/bin/env bash
# Local helper checks for fetch-pg-binaries.sh (no network).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Source production helper functions without running main
source "$ROOT/scripts/fetch-pg-binaries.sh"

# Safe archive
mkdir -p "$TMP/safe/bin"
echo x > "$TMP/safe/bin/pg_ctl"
tar -czf "$TMP/safe.tgz" -C "$TMP/safe" .
assert_tar_safe "$TMP/safe.tgz"

# Traversal archive (member name contains ..)
mkdir -p "$TMP/evil"
python3 -c '
import tarfile, io, sys
with tarfile.open(sys.argv[1], "w:gz") as tar:
    ti = tarfile.TarInfo(name="../evil_bin")
    ti.size = 1
    tar.addfile(ti, io.BytesIO(b"x"))
' "$TMP/evil.tgz"
if assert_tar_safe "$TMP/evil.tgz" 2>/dev/null; then
  echo "expected traversal reject" >&2
  exit 1
fi

# A safe-looking name can still escape through a symlink member.
python3 -c '
import io, sys, tarfile
with tarfile.open(sys.argv[1], "w:gz") as tar:
    link = tarfile.TarInfo(name="redirect")
    link.type = tarfile.SYMTYPE
    link.linkname = "../../outside"
    tar.addfile(link)
    child = tarfile.TarInfo(name="redirect/escaped")
    child.size = 1
    tar.addfile(child, io.BytesIO(b"x"))
' "$TMP/link.tgz"
if assert_tar_safe "$TMP/link.tgz" 2>/dev/null; then
  echo "expected symlink member reject" >&2
  exit 1
fi
python3 -c '
import sys, tarfile
with tarfile.open(sys.argv[1], "w:gz") as tar:
    link = tarfile.TarInfo(name="hardlink")
    link.type = tarfile.LNKTYPE
    link.linkname = "../../outside"
    tar.addfile(link)
' "$TMP/hardlink.tgz"
if assert_tar_safe "$TMP/hardlink.tgz" 2>/dev/null; then
  echo "expected hardlink member reject" >&2
  exit 1
fi

# Allowlist patterns (calling production url_allowed)
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

# Default 16.6.0 target pins are version-, target- and filename-specific.
[[ "$(pinned_archive_sha256 16.6.0 darwin-arm64 https://github.com/theseus-rs/postgresql-binaries/releases/download/16.6.0/postgresql-16.6.0-aarch64-apple-darwin.tar.gz)" == "e0507eda29922276ea1c34baf826d4cdfa72b945cde5c8add7b4f344eec79ff9" ]]
[[ "$(pinned_archive_sha256 16.6.0 darwin-x64 https://github.com/theseus-rs/postgresql-binaries/releases/download/16.6.0/postgresql-16.6.0-x86_64-apple-darwin.tar.gz)" == "364b891d4445e691aba8fddc4428efcfd81c044656153536088ebf8f711bb08b" ]]
[[ "$(pinned_archive_sha256 16.6.0 linux-x64 https://github.com/theseus-rs/postgresql-binaries/releases/download/16.6.0/postgresql-16.6.0-x86_64-unknown-linux-gnu.tar.gz)" == "f05dc63d918eac05a5dff7f8e0c5a72f89176efda87e1556a6ec1758046c1987" ]]
[[ "$(pinned_archive_sha256 16.6.0 linux-arm64 https://github.com/theseus-rs/postgresql-binaries/releases/download/16.6.0/postgresql-16.6.0-aarch64-unknown-linux-gnu.tar.gz)" == "ae3e4bd7f3907ecf464c9ea50e924106cc5ebe1fe5eb70a1554f6e14fcd59d06" ]]
[[ "$(pinned_archive_sha256 16.6.0 win-x64 https://github.com/theseus-rs/postgresql-binaries/releases/download/16.6.0/postgresql-16.6.0-x86_64-pc-windows-msvc.tar.gz)" == "08ce689d6b24b80be69315b30da82c01456b09af3f5d4f769e81564c1f0ace9b" ]]
if pinned_archive_sha256 16.7.0 linux-x64 https://github.com/theseus-rs/postgresql-binaries/releases/download/16.7.0/unknown.tar.gz >/dev/null 2>&1; then
  echo "unknown version unexpectedly has a repository pin" >&2
  exit 1
fi

# Verify fallback handling without network: unpinned same-origin sidecars are
# refused by default (A99), only an explicit --allow-unpinned / ALLOW_UNPINNED=1
# opt-in allows them, explicit hashes bypass sidecars, and mismatched explicit
# hashes fail closed.
printf 'test archive bytes\n' > "$TMP/fallback.archive"
FALLBACK_SHA="$(calc_sha256 "$TMP/fallback.archive")"
curl_calls=0
curl() {
  local output="" request_url=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -o) output="$2"; shift 2 ;;
      *) request_url="$1"; shift ;;
    esac
  done
  curl_calls=$((curl_calls + 1))
  if [[ "$request_url" == *.sha256 ]]; then
    printf 'SHA256 hash of fallback archive:\n%s\nCertUtil completed successfully.\n' "$FALLBACK_SHA" > "$output"
    return 0
  fi
  return 22
}
# A99: no pin and no explicit opt-in -> refuse before fetching any checksum.
if verify_archive_sha256 "$TMP/fallback.archive" "https://get.enterprisedb.com/postgresql/fallback.tar.gz" "$TMP" "16.6.0" "linux-x64" > "$TMP/unpinned.log" 2>&1; then
  echo "unpinned same-origin fallback should be refused by default" >&2
  exit 1
fi
grep -q "allow-unpinned" "$TMP/unpinned.log"
[[ "$curl_calls" -eq 0 ]]
"$ROOT/scripts/fetch-pg-binaries.sh" --help | grep -q -- "--allow-unpinned"
# A99: explicit opt-in re-enables the (still warned) same-origin fallback.
curl_calls=0
if ! ALLOW_UNPINNED=1 verify_archive_sha256 "$TMP/fallback.archive" "https://get.enterprisedb.com/postgresql/fallback.tar.gz" "$TMP" "16.6.0" "linux-x64" > "$TMP/fallback.log" 2>&1; then
  cat "$TMP/fallback.log" >&2
  echo "sidecar fallback should accept matching archive hash" >&2
  exit 1
fi
grep -q "WARNING: no repository-pinned SHA-256" "$TMP/fallback.log"
[[ "$curl_calls" -eq 1 ]]

curl_calls=0
PG_VENDOR_SHA256="$FALLBACK_SHA" verify_archive_sha256 "$TMP/fallback.archive" "https://get.enterprisedb.com/postgresql/fallback.tar.gz" "$TMP" "16.6.0" "linux-x64" >/dev/null
[[ "$curl_calls" -eq 0 ]]

BAD_SHA="$(printf '%064d' 0)"
if PG_VENDOR_SHA256="$BAD_SHA" verify_archive_sha256 "$TMP/fallback.archive" "https://get.enterprisedb.com/postgresql/fallback.tar.gz" "$TMP" "16.6.0" "linux-x64" >/dev/null 2>&1; then
  echo "mismatched explicit checksum should fail" >&2
  exit 1
fi

# SHA256SUMS fallback must select the exact archive name, not the first entry.
curl() {
  local output="" request_url=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -o) output="$2"; shift 2 ;;
      *) request_url="$1"; shift ;;
    esac
  done
  if [[ "$request_url" == *.sha256 ]]; then return 22; fi
  printf '%s  other.tar.gz\n%s  *fallback.tar.gz\n' "$BAD_SHA" "$FALLBACK_SHA" > "$output"
}
if ! ALLOW_UNPINNED=1 verify_archive_sha256 "$TMP/fallback.archive" "https://get.enterprisedb.com/postgresql/fallback.tar.gz" "$TMP" "16.7.0" "linux-x64" > "$TMP/manifest.log" 2>&1; then
  cat "$TMP/manifest.log" >&2
  echo "SHA256SUMS fallback should select matching archive name" >&2
  exit 1
fi
grep -q "SHA-256 OK ($FALLBACK_SHA)" "$TMP/manifest.log"

# A131: reusing existing binaries requires a pg_ctl --version match (and no
# obvious architecture mismatch); a stale tree must be refused, not skipped.
mkdir -p "$TMP/existing/bin"
for tool in pg_ctl initdb psql; do
  printf '#!/bin/sh\necho "pg_ctl (PostgreSQL) 16.6.0"\n' > "$TMP/existing/bin/$tool"
  chmod +x "$TMP/existing/bin/$tool"
done
check_existing_binaries "$TMP/existing" "16.6.0" "linux-x64"
printf '#!/bin/sh\necho "pg_ctl (PostgreSQL) 15.4"\n' > "$TMP/existing/bin/pg_ctl"
chmod +x "$TMP/existing/bin/pg_ctl"
if check_existing_binaries "$TMP/existing" "16.6.0" "linux-x64" > "$TMP/ver.log" 2>&1; then
  echo "stale 15.4 tree should be refused for expected 16.6.0" >&2
  exit 1
fi
grep -q "rm -rf" "$TMP/ver.log"
printf '#!/bin/sh\necho "pg_ctl (PostgreSQL) 16.6.0"\n' > "$TMP/existing/bin/pg_ctl"
chmod +x "$TMP/existing/bin/pg_ctl"
rm "$TMP/existing/bin/psql"
if check_existing_binaries "$TMP/existing" "16.6.0" "linux-x64" >/dev/null 2>&1; then
  echo "incomplete tree (missing psql) should be refused" >&2
  exit 1
fi

# Also test zip helper with a safe zip if unzip and zip are available
if command -v zip >/dev/null 2>&1 && command -v unzip >/dev/null 2>&1; then
  (cd "$TMP/safe" && zip -q "$TMP/safe.zip" bin/pg_ctl)
  assert_zip_safe "$TMP/safe.zip"

  python3 - "$TMP/evil.zip" "$TMP/link.zip" <<'PYZIP'
import stat, sys, zipfile
with zipfile.ZipFile(sys.argv[1], "w") as archive:
    archive.writestr("../evil_bin", "x")
with zipfile.ZipFile(sys.argv[2], "w") as archive:
    link = zipfile.ZipInfo("redirect")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive.writestr(link, "../../outside")
    archive.writestr("redirect/escaped", "x")
PYZIP
  if assert_zip_safe "$TMP/evil.zip" 2>/dev/null; then
    echo "expected zip traversal reject" >&2
    exit 1
  fi
  if assert_zip_safe "$TMP/link.zip" 2>/dev/null; then
    echo "expected zip symlink reject" >&2
    exit 1
  fi
fi

echo "test_fetch_pg_binaries_helpers: ok"
