#!/usr/bin/env bash
# Download official PostgreSQL binaries into desktop/vendor/pgsql for Electron.
# Default: Linux x86_64 PostgreSQL 16 from the EnterpriseDB community binaries
# mirror pattern. Override with PG_VENDOR_URL if the default 404s.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENDOR="$ROOT/desktop/vendor"
DEST="$VENDOR/pgsql"
OS="linux"
ARCH="x86_64"
VERSION="${PG_VERSION:-16.6-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --os) OS="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    -h|--help)
      echo "Usage: $0 [--os linux|macos|windows] [--arch x86_64|arm64] [--version 16.6-1]"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$VENDOR"
TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

# EnterpriseDB binary bundles (common Electron packaging source).
# Example: postgresql-16.6-1-linux-x64-binaries.tar.gz
case "$OS-$ARCH" in
  linux-x86_64|linux-amd64) SLUG="linux-x64" ;;
  linux-arm64|linux-aarch64) SLUG="linux-arm64" ;;
  macos-x86_64|macos-amd64) SLUG="osx" ;;
  macos-arm64) SLUG="osx" ;; # EDB may ship universal; document manual if missing
  windows-x86_64) SLUG="windows-x64" ;;
  *) echo "Unsupported os/arch: $OS $ARCH" >&2; exit 1 ;;
esac

NAME="postgresql-${VERSION%-*}-${VERSION##*-}-${SLUG}-binaries.tar.gz"
# Prefer explicit override
URL="${PG_VENDOR_URL:-https://get.enterprisedb.com/postgresql/${NAME}}"

echo "Fetching PostgreSQL vendor binaries"
echo "  URL:  $URL"
echo "  Dest: $DEST"

if [[ -x "$DEST/bin/pg_ctl" && -x "$DEST/bin/initdb" ]]; then
  echo "Already present: $DEST/bin — skipping download (rm -rf $DEST to refresh)"
  "$DEST/bin/pg_ctl" --version || true
  exit 0
fi

ARCHIVE="$TMP/pg.tar.gz"
if ! curl -fL --retry 3 -o "$ARCHIVE" "$URL"; then
  cat >&2 <<HINT

Download failed (mirror may have moved). Manual steps:
  1. Obtain PostgreSQL ${VERSION%%-*} binary bundle for ${OS}/${ARCH}
     from https://www.postgresql.org/download/ or EnterpriseDB.
  2. Extract so that initdb/pg_ctl/postgres live at:
       $DEST/bin/
  3. Or set KKMAIL_PG_BIN=/path/to/pgsql/bin

HINT
  exit 1
fi

rm -rf "$DEST"
mkdir -p "$VENDOR"
tar -xzf "$ARCHIVE" -C "$TMP"
# EDB layout is usually pgsql/ under the archive
if [[ -d "$TMP/pgsql/bin" ]]; then
  mv "$TMP/pgsql" "$DEST"
elif [[ -d "$TMP/pgsql" ]]; then
  mv "$TMP/pgsql" "$DEST"
else
  FOUND="$(find "$TMP" -type d -name bin | head -1 || true)"
  if [[ -z "$FOUND" ]]; then
    echo "Could not locate bin/ in archive" >&2
    exit 1
  fi
  mv "$(dirname "$FOUND")" "$DEST"
fi

chmod +x "$DEST/bin"/* 2>/dev/null || true
test -x "$DEST/bin/initdb"
test -x "$DEST/bin/pg_ctl"
echo "OK: $($DEST/bin/pg_ctl --version)"
echo "PostgresManager will pick up: $DEST/bin"
