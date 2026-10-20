#!/usr/bin/env bash
# Download PostgreSQL binaries into desktop/vendor/pgsql for Electron.
# Linux: tries theseus-rs portable builds, then EnterpriseDB.
# macOS / Windows: prints download-at-build instructions (no silent wrong arch).
#
# Security: URL allowlist, mandatory SHA-256 verification, path-traversal-safe extract.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/desktop/vendor"
DEST="$VENDOR/pgsql"
OS="linux"
ARCH="$(uname -m)"
VERSION="${PG_VERSION:-16.6.0}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --os) OS="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--os linux|macos|windows] [--arch x86_64|arm64] [--version 16.6.0]"
      echo "Override URL with PG_VENDOR_URL=... (must be an allowlisted HTTPS host)"
      echo "Require checksum via PG_VENDOR_SHA256=... or a sidecar .sha256 / SHA256SUMS fetch"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$VENDOR"

if [[ -x "$DEST/bin/pg_ctl" && -x "$DEST/bin/initdb" ]]; then
  echo "Already present: $DEST/bin — skipping download (rm -rf $DEST to refresh)"
  "$DEST/bin/pg_ctl" --version || true
  exit 0
fi

case "$OS" in
  macos|darwin|windows|win)
    cat <<HINT
download-at-build ($OS / $ARCH):
  Official portable Postgres is not auto-fetched for $OS in this script
  (signing / arch variants differ per release channel).

  Build pipeline should:
    1. Download PostgreSQL ${VERSION%%.*}.x binaries for $OS/$ARCH
       (EnterpriseDB, Postgres.app, or official installers).
    2. Place initdb/pg_ctl/postgres under:
         desktop/vendor/pgsql/bin/
    3. Or set KKMAIL_PG_BIN=/path/to/pgsql/bin at runtime.

  Linux CI/dev boxes: re-run with --os linux
HINT
    exit 0
    ;;
esac

# Normalize arch
case "$ARCH" in
  x86_64|amd64) ARCH_NORM=x86_64; THESEUS=x86_64-unknown-linux-gnu; EDB_SLUG=linux-x64 ;;
  aarch64|arm64) ARCH_NORM=arm64; THESEUS=aarch64-unknown-linux-gnu; EDB_SLUG=linux-arm64 ;;
  *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;;
esac

# Allowlisted download hosts (SSRF / supply-chain).
url_allowed() {
  local u="$1"
  case "$u" in
    https://github.com/theseus-rs/postgresql-binaries/releases/download/*) return 0 ;;
    https://get.enterprisedb.com/postgresql/*) return 0 ;;
    *) return 1 ;;
  esac
}

assert_url_allowed() {
  local u="$1"
  if ! url_allowed "$u"; then
    echo "URL not on PG vendor allowlist: $u" >&2
    echo "Allowed: github.com/theseus-rs/postgresql-binaries/... or get.enterprisedb.com/postgresql/..." >&2
    exit 1
  fi
}

verify_archive_sha256() {
  local archive="$1"
  local url="$2"
  local expected=""
  if [[ -n "${PG_VENDOR_SHA256:-}" ]]; then
    expected="$(echo "$PG_VENDOR_SHA256" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  else
    local side="$archive.sha256"
    if curl -fsSL --retry 2 -o "$side" "${url}.sha256" 2>/dev/null; then
      expected="$(awk '{print tolower($1)}' "$side" | head -1)"
    elif curl -fsSL --retry 2 -o "$TMP/SHA256SUMS" "$(dirname "$url")/SHA256SUMS" 2>/dev/null; then
      local base
      base="$(basename "$url")"
      expected="$(awk -v b="$base" 'tolower($2)==tolower(b) || tolower($2)==tolower("*" b) {print tolower($1); exit}' "$TMP/SHA256SUMS")"
    fi
  fi
  if [[ -z "$expected" || ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
    echo "No usable SHA-256 for $url" >&2
    echo "Set PG_VENDOR_SHA256=<64-hex> (required when the mirror has no sidecar checksum)." >&2
    return 1
  fi
  local actual
  actual="$(sha256sum "$archive" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "SHA-256 mismatch for PostgreSQL archive" >&2
    echo "  expected: $expected" >&2
    echo "  actual:   $actual" >&2
    return 1
  fi
  echo "SHA-256 OK ($actual)"
}

# Reject absolute paths and .. components before extract (path traversal).
assert_tar_safe() {
  local archive="$1"
  local member
  while IFS= read -r member; do
    case "$member" in
      "" ) continue ;;
      /* | *../* | */../* | */.. | .. | ../* | *.. )
        echo "Refusing archive member with unsafe path: $member" >&2
        exit 1
        ;;
    esac
  done < <(tar -tzf "$archive")
}

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT
ARCHIVE="$TMP/pg.tar.gz"

CANDIDATES=()
if [[ -n "${PG_VENDOR_URL:-}" ]]; then
  assert_url_allowed "$PG_VENDOR_URL"
  CANDIDATES+=("$PG_VENDOR_URL")
fi
# theseus-rs community portable builds (GitHub releases)
CANDIDATES+=("https://github.com/theseus-rs/postgresql-binaries/releases/download/${VERSION}/postgresql-${VERSION}-${THESEUS}.tar.gz")
# Legacy EDB naming (often 403 without cookies — kept as fallback)
MAJOR_MINOR="$(echo "$VERSION" | cut -d. -f1-2)"
CANDIDATES+=("https://get.enterprisedb.com/postgresql/postgresql-${MAJOR_MINOR}-1-${EDB_SLUG}-binaries.tar.gz")

ok=0
USED_URL=""
for URL in "${CANDIDATES[@]}"; do
  assert_url_allowed "$URL"
  echo "Trying: $URL"
  if curl -fL --retry 3 -o "$ARCHIVE" "$URL"; then
    if verify_archive_sha256 "$ARCHIVE" "$URL"; then
      ok=1
      USED_URL="$URL"
      break
    fi
  fi
  echo "  failed"
done

if [[ "$ok" != 1 ]]; then
  cat >&2 <<HINT
All mirrors failed (download or checksum). Manual steps:
  1. Download PostgreSQL ${MAJOR_MINOR} linux/${ARCH_NORM} binaries
  2. Verify SHA-256, then extract so initdb/pg_ctl/postgres live at: $DEST/bin/
  3. Or set KKMAIL_PG_BIN=/path/to/pgsql/bin
  4. For a custom URL: PG_VENDOR_URL=... PG_VENDOR_SHA256=...
HINT
  exit 1
fi

assert_tar_safe "$ARCHIVE"

rm -rf "$DEST"
mkdir -p "$VENDOR"
tar -xzf "$ARCHIVE" -C "$TMP"
if [[ -d "$TMP/pgsql/bin" ]]; then
  mv "$TMP/pgsql" "$DEST"
elif [[ -x "$TMP/bin/pg_ctl" ]]; then
  mkdir -p "$DEST"
  # theseus layout: archive root has bin/, lib/, share/
  for d in bin lib share include; do
    [[ -d "$TMP/$d" ]] && mv "$TMP/$d" "$DEST/"
  done
  # sometimes nested postgresql-VERSION-triple/
  if [[ ! -x "$DEST/bin/pg_ctl" ]]; then
    FOUND="$(find "$TMP" -type f -name pg_ctl | head -1 || true)"
    if [[ -n "$FOUND" ]]; then
      ROOT_BIN="$(dirname "$FOUND")"
      ROOT_PG="$(dirname "$ROOT_BIN")"
      # Ensure resolved path stays under TMP (no symlink escape).
      ROOT_PG_REAL="$(cd "$ROOT_PG" && pwd)"
      case "$ROOT_PG_REAL" in
        "$TMP"/*) ;;
        *) echo "Extracted tree escaped temp dir: $ROOT_PG_REAL" >&2; exit 1 ;;
      esac
      rm -rf "$DEST"
      mv "$ROOT_PG" "$DEST"
    fi
  fi
else
  FOUND="$(find "$TMP" -type f -name pg_ctl | head -1 || true)"
  if [[ -z "$FOUND" ]]; then
    echo "Could not locate pg_ctl in archive" >&2
    exit 1
  fi
  ROOT_PG="$(dirname "$(dirname "$FOUND")")"
  ROOT_PG_REAL="$(cd "$ROOT_PG" && pwd)"
  case "$ROOT_PG_REAL" in
    "$TMP"/*) ;;
    *) echo "Extracted tree escaped temp dir: $ROOT_PG_REAL" >&2; exit 1 ;;
  esac
  mv "$ROOT_PG" "$DEST"
fi

chmod +x "$DEST/bin"/* 2>/dev/null || true
test -x "$DEST/bin/initdb"
test -x "$DEST/bin/pg_ctl"
echo "OK: $($DEST/bin/pg_ctl --version) (from $USED_URL)"
echo "PostgresManager will pick up: $DEST/bin"
