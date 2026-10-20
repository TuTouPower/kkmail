#!/usr/bin/env bash
# Download PostgreSQL binaries into desktop/vendor/pgsql for Electron.
# Linux: tries theseus-rs portable builds, then EnterpriseDB.
# macOS / Windows: prints download-at-build instructions (no silent wrong arch).
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
      echo "Override URL with PG_VENDOR_URL=..."
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

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT
ARCHIVE="$TMP/pg.tar.gz"

CANDIDATES=()
if [[ -n "${PG_VENDOR_URL:-}" ]]; then
  CANDIDATES+=("$PG_VENDOR_URL")
fi
# theseus-rs community portable builds (GitHub releases)
CANDIDATES+=("https://github.com/theseus-rs/postgresql-binaries/releases/download/${VERSION}/postgresql-${VERSION}-${THESEUS}.tar.gz")
# Legacy EDB naming (often 403 without cookies — kept as fallback)
EDB_VER_DASH="${VERSION%.*}-1"
# map 16.6.0 -> 16.6-1 loosely
MAJOR_MINOR="$(echo "$VERSION" | cut -d. -f1-2)"
CANDIDATES+=("https://get.enterprisedb.com/postgresql/postgresql-${MAJOR_MINOR}-1-${EDB_SLUG}-binaries.tar.gz")

ok=0
for URL in "${CANDIDATES[@]}"; do
  echo "Trying: $URL"
  if curl -fL --retry 3 -o "$ARCHIVE" "$URL"; then
    ok=1
    break
  fi
  echo "  failed"
done

if [[ "$ok" != 1 ]]; then
  cat >&2 <<HINT
All mirrors failed. Manual steps:
  1. Download PostgreSQL ${MAJOR_MINOR} linux/${ARCH_NORM} binaries
  2. Extract so initdb/pg_ctl/postgres live at: $DEST/bin/
  3. Or set KKMAIL_PG_BIN=/path/to/pgsql/bin
HINT
  exit 1
fi

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
  mv "$ROOT_PG" "$DEST"
fi

chmod +x "$DEST/bin"/* 2>/dev/null || true
test -x "$DEST/bin/initdb"
test -x "$DEST/bin/pg_ctl"
echo "OK: $($DEST/bin/pg_ctl --version)"
echo "PostgresManager will pick up: $DEST/bin"
