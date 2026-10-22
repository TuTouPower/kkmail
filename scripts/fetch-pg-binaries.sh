#!/usr/bin/env bash
# Download PostgreSQL binaries into desktop/vendor/pgsql for Electron.
# Supports cross-platform targets: darwin-arm64, darwin-x64, linux-x64, linux-arm64, win-x64.
# Sources: theseus-rs portable builds (primary), EnterpriseDB (fallback).
#
# Security: URL allowlist, mandatory SHA-256 verification, path-traversal-safe extract.
set -euo pipefail

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
    return 1
  fi
}

calc_sha256() {
  local target_file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$target_file" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$target_file" | awk '{print $1}'
  else
    python3 -c "import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], 'rb').read()).hexdigest())" "$target_file"
  fi
}

verify_archive_sha256() {
  local archive="$1"
  local url="$2"
  local tmp_dir="${3:-$(dirname "$archive")}"
  local expected=""
  if [[ -n "${PG_VENDOR_SHA256:-}" ]]; then
    expected="$(echo "$PG_VENDOR_SHA256" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
  else
    local side="$archive.sha256"
    if curl -fsSL --connect-timeout 15 --max-time 300 --retry 2 --retry-delay 2 --retry-max-time 60 -o "$side" "${url}.sha256" 2>/dev/null; then
      expected="$(awk '{print tolower($1)}' "$side" | head -1)"
    elif curl -fsSL --connect-timeout 15 --max-time 300 --retry 2 --retry-delay 2 --retry-max-time 60 -o "$tmp_dir/SHA256SUMS" "$(dirname "$url")/SHA256SUMS" 2>/dev/null; then
      local base
      base="$(basename "$url")"
      expected="$(awk -v b="$base" 'tolower($2)==tolower(b) || tolower($2)==tolower("*" b) {print tolower($1); exit}' "$tmp_dir/SHA256SUMS")"
    fi
  fi
  if [[ -z "$expected" || ! "$expected" =~ ^[0-9a-f]{64}$ ]]; then
    echo "No usable SHA-256 for $url" >&2
    echo "Set PG_VENDOR_SHA256=<64-hex> (required when the mirror has no sidecar checksum)." >&2
    return 1
  fi
  local actual
  actual="$(calc_sha256 "$archive")"
  if [[ "$actual" != "$expected" ]]; then
    echo "SHA-256 mismatch for PostgreSQL archive" >&2
    echo "  expected: $expected" >&2
    echo "  actual:   $actual" >&2
    return 1
  fi
  echo "SHA-256 OK ($actual)"
}

assert_tar_safe() {
  local archive="$1"
  local member
  while IFS= read -r member; do
    case "$member" in
      "" ) continue ;;
      /* | *../* | */../* | */.. | .. | ../* | *.. )
        echo "Refusing archive member with unsafe path: $member" >&2
        return 1
        ;;
    esac
  done < <(tar -tzf "$archive")
}

assert_zip_safe() {
  local archive="$1"
  local member
  while IFS= read -r member; do
    case "$member" in
      "" ) continue ;;
      /* | *../* | */../* | */.. | .. | ../* | *.. )
        echo "Refusing zip member with unsafe path: $member" >&2
        return 1
        ;;
    esac
  done < <(unzip -Z1 "$archive")
}

fix_macos_rpath() {
  local target_dir="$1"
  if ! command -v install_name_tool >/dev/null 2>&1 || ! command -v otool >/dev/null 2>&1; then
    echo "install_name_tool or otool not available, skipping rpath adjustment" >&2
    return 0
  fi
  echo "Adjusting macOS dependency and rpath settings with install_name_tool..."

  # 1. Patch executable binaries in bin/
  if [[ -d "$target_dir/bin" ]]; then
    for b in "$target_dir/bin"/*; do
      [[ -f "$b" ]] || continue
      for rp in "@executable_path/../lib" "@loader_path/../lib" "/opt/homebrew/lib" "/usr/local/lib" "/opt/homebrew/opt/openssl@3/lib" "/usr/local/opt/openssl@3/lib"; do
        install_name_tool -add_rpath "$rp" "$b" 2>/dev/null || true
      done
      while IFS= read -r line; do
        local dep
        dep="$(echo "$line" | awk '{print $1}')"
        [[ -z "$dep" ]] && continue
        local dep_base
        dep_base="$(basename "$dep")"
        if [[ ("$dep" == *"/lib/"* && "$dep" != "/usr/lib/"*) || "$dep" == *runner* ]]; then
          if [[ -f "$target_dir/lib/$dep_base" ]]; then
            install_name_tool -change "$dep" "@executable_path/../lib/$dep_base" "$b" 2>/dev/null || true
          fi
        fi
      done < <(otool -L "$b" 2>/dev/null | tail -n +2)
    done
  fi

  # 2. Patch shared libraries in lib/
  if [[ -d "$target_dir/lib" ]]; then
    while IFS= read -r d; do
      [[ -f "$d" ]] || continue
      local d_base
      d_base="$(basename "$d")"
      install_name_tool -id "@loader_path/$d_base" "$d" 2>/dev/null || true
      for rp in "@loader_path" "/opt/homebrew/lib" "/usr/local/lib" "/opt/homebrew/opt/openssl@3/lib" "/usr/local/opt/openssl@3/lib"; do
        install_name_tool -add_rpath "$rp" "$d" 2>/dev/null || true
      done
      while IFS= read -r line; do
        local dep
        dep="$(echo "$line" | awk '{print $1}')"
        [[ -z "$dep" ]] && continue
        local dep_base
        dep_base="$(basename "$dep")"
        if [[ ("$dep" == *"/lib/"* && "$dep" != "/usr/lib/"*) || "$dep" == *runner* ]]; then
          if [[ -f "$target_dir/lib/$dep_base" ]]; then
            install_name_tool -change "$dep" "@loader_path/$dep_base" "$d" 2>/dev/null || true
          fi
        fi
      done < <(otool -L "$d" 2>/dev/null | tail -n +2)
    done < <(find "$target_dir/lib" -type f -name "*.dylib" 2>/dev/null || true)
  fi
}

main() {
  local ROOT VENDOR DEST DETECTED_OS DETECTED_ARCH OS ARCH VERSION
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  VENDOR="$ROOT/src/desktop/vendor"
  DEST="$VENDOR/pgsql"

  DETECTED_OS="$(uname -s 2>/dev/null | tr '[:upper:]' '[:lower:]' || echo "linux")"
  DETECTED_ARCH="$(uname -m 2>/dev/null || echo "x86_64")"

  OS=""
  ARCH=""
  VERSION="${PG_VERSION:-16.6.0}"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --os) OS="$2"; shift 2 ;;
      --arch) ARCH="$2"; shift 2 ;;
      --version) VERSION="$2"; shift 2 ;;
      -h|--help)
        echo "Usage: $0 [--os darwin|linux|windows] [--arch arm64|x64|x86_64] [--version 16.6.0]"
        echo "Supported targets: darwin-arm64, darwin-x64, linux-x64, linux-arm64, win-x64"
        echo "Override URL with PG_VENDOR_URL=... (must be an allowlisted HTTPS host)"
        echo "Require checksum via PG_VENDOR_SHA256=... or a sidecar .sha256 / SHA256SUMS fetch"
        exit 0
        ;;
      *) echo "Unknown arg: $1" >&2; exit 2 ;;
    esac
  done

  if [[ -z "$OS" ]]; then
    case "$DETECTED_OS" in
      darwin*) OS="darwin" ;;
      linux*) OS="linux" ;;
      msys*|mingw*|cygwin*|windows*) OS="windows" ;;
      *) OS="linux" ;;
    esac
  fi

  if [[ -z "$ARCH" ]]; then
    ARCH="$DETECTED_ARCH"
  fi

  local OS_NORM ARCH_NORM TARGET THESEUS EDB_SLUG
  # Normalize OS
  case "$(echo "$OS" | tr '[:upper:]' '[:lower:]')" in
    darwin|macos|osx) OS_NORM="darwin" ;;
    linux) OS_NORM="linux" ;;
    windows|win|win32|win64) OS_NORM="windows" ;;
    *) echo "Unsupported OS: $OS" >&2; exit 1 ;;
  esac

  # Normalize ARCH
  case "$(echo "$ARCH" | tr '[:upper:]' '[:lower:]')" in
    arm64|aarch64) ARCH_NORM="arm64" ;;
    x86_64|amd64|x64) ARCH_NORM="x64" ;;
    *) echo "Unsupported arch: $ARCH" >&2; exit 1 ;;
  esac

  # Canonical target resolution
  case "${OS_NORM}-${ARCH_NORM}" in
    darwin-arm64)
      TARGET="darwin-arm64"
      THESEUS="aarch64-apple-darwin"
      EDB_SLUG="osx"
      ;;
    darwin-x64)
      TARGET="darwin-x64"
      THESEUS="x86_64-apple-darwin"
      EDB_SLUG="osx"
      ;;
    linux-x64)
      TARGET="linux-x64"
      THESEUS="x86_64-unknown-linux-gnu"
      EDB_SLUG="linux-x64"
      ;;
    linux-arm64)
      TARGET="linux-arm64"
      THESEUS="aarch64-unknown-linux-gnu"
      EDB_SLUG="linux-arm64"
      ;;
    windows-x64)
      TARGET="win-x64"
      THESEUS="x86_64-pc-windows-msvc"
      EDB_SLUG="windows-x64"
      ;;
    *)
      echo "Unsupported target combination: ${OS_NORM}-${ARCH_NORM}" >&2
      echo "Supported targets: darwin-arm64, darwin-x64, linux-x64, linux-arm64, win-x64" >&2
      exit 1
      ;;
  esac

  mkdir -p "$VENDOR"

  if [[ "$OS_NORM" == "windows" ]]; then
    if [[ -f "$DEST/bin/pg_ctl.exe" && -f "$DEST/bin/initdb.exe" ]]; then
      echo "Already present: $DEST/bin — skipping download (rm -rf $DEST to refresh)"
      exit 0
    fi
  else
    if [[ -x "$DEST/bin/pg_ctl" && -x "$DEST/bin/initdb" ]]; then
      echo "Already present: $DEST/bin — skipping download (rm -rf $DEST to refresh)"
      "$DEST/bin/pg_ctl" --version 2>/dev/null || true
      exit 0
    fi
  fi

  local TMP ARCHIVE CANDIDATES
  TMP="$(mktemp -d)"
  cleanup() { rm -rf "$TMP"; }
  trap cleanup EXIT
  ARCHIVE="$TMP/pg.archive"

  CANDIDATES=()
  if [[ -n "${PG_VENDOR_URL:-}" ]]; then
    assert_url_allowed "$PG_VENDOR_URL" || exit 1
    CANDIDATES+=("$PG_VENDOR_URL")
  fi

  # theseus-rs community portable builds (primary)
  CANDIDATES+=("https://github.com/theseus-rs/postgresql-binaries/releases/download/${VERSION}/postgresql-${VERSION}-${THESEUS}.tar.gz")

  # EnterpriseDB portable fallback builds
  local MAJOR_MINOR
  MAJOR_MINOR="$(echo "$VERSION" | cut -d. -f1-2)"
  if [[ "$TARGET" == "win-x64" ]]; then
    CANDIDATES+=("https://get.enterprisedb.com/postgresql/postgresql-${MAJOR_MINOR}-1-windows-x64-binaries.zip")
  elif [[ "$TARGET" == darwin-* ]]; then
    CANDIDATES+=("https://get.enterprisedb.com/postgresql/postgresql-${MAJOR_MINOR}-1-osx-binaries.zip")
  else
    CANDIDATES+=("https://get.enterprisedb.com/postgresql/postgresql-${MAJOR_MINOR}-1-${EDB_SLUG}-binaries.tar.gz")
  fi

  local ok=0 USED_URL=""
  for URL in "${CANDIDATES[@]}"; do
    assert_url_allowed "$URL" || exit 1
    echo "Trying: $URL"
    if curl -fL --connect-timeout 15 --max-time 300 --retry 3 --retry-delay 2 --retry-max-time 600 -o "$ARCHIVE" "$URL"; then
      if verify_archive_sha256 "$ARCHIVE" "$URL" "$TMP"; then
        ok=1
        USED_URL="$URL"
        break
      fi
    fi
    echo "  failed"
  done

  if [[ "$ok" != 1 ]]; then
    cat >&2 <<HINT
All mirrors failed for target: $TARGET (download or checksum). Manual steps:
  1. Download PostgreSQL ${MAJOR_MINOR} for $TARGET
  2. Verify SHA-256, then extract so initdb/pg_ctl/postgres live at: $DEST/bin/
  3. Or set KKMAIL_PG_BIN=/path/to/pgsql/bin
  4. For a custom URL: PG_VENDOR_URL=... PG_VENDOR_SHA256=...
HINT
    exit 1
  fi

  local EXTRACT_DIR="$TMP/extracted"
  mkdir -p "$EXTRACT_DIR"

  if [[ "$USED_URL" == *.zip ]]; then
    assert_zip_safe "$ARCHIVE" || exit 1
    unzip -q "$ARCHIVE" -d "$EXTRACT_DIR"
  else
    assert_tar_safe "$ARCHIVE" || exit 1
    tar -xzf "$ARCHIVE" -C "$EXTRACT_DIR"
  fi

  local FOUND
  FOUND="$(find "$EXTRACT_DIR" -type f \( -name initdb -o -name initdb.exe \) | head -1 || true)"
  if [[ -z "$FOUND" ]]; then
    echo "Could not locate initdb in extracted archive" >&2
    exit 1
  fi

  local ROOT_BIN ROOT_PG ROOT_PG_REAL
  ROOT_BIN="$(dirname "$FOUND")"
  ROOT_PG="$(dirname "$ROOT_BIN")"
  ROOT_PG_REAL="$(cd "$ROOT_PG" && pwd)"
  case "$ROOT_PG_REAL" in
    "$TMP"/*) ;;
    *) echo "Extracted tree escaped temp dir: $ROOT_PG_REAL" >&2; exit 1 ;;
  esac

  rm -rf "$DEST"
  mkdir -p "$VENDOR"
  mv "$ROOT_PG" "$DEST"

  # Trim redundant files (headers, documentation, unneeded binaries)
  echo "Trimming redundant files (headers, doc, unneeded CLI tools)..."
  rm -rf "$DEST/include" "$DEST/doc" "$DEST/man" "$DEST/share/doc" "$DEST/share/man"
  find "$DEST" -type f \( -name "*.a" -o -name "*.pdb" -o -name "*.dSYM" \) -delete 2>/dev/null || true

  # Retain only required core binaries (initdb, pg_ctl, postgres) and runtime libraries
  if [[ -d "$DEST/bin" ]]; then
    for f in "$DEST/bin"/*; do
      [[ -f "$f" ]] || continue
      local base
      base="$(basename "$f")"
      case "$base" in
        initdb|initdb.exe|pg_ctl|pg_ctl.exe|postgres|postgres.exe|createdb|createdb.exe|*.dll)
          ;;
        *)
          rm -f "$f"
          ;;
      esac
    done
  fi

  # On macOS, adjust dynamic link dependencies and rpaths
  if [[ "$OS_NORM" == "darwin" ]]; then
    fix_macos_rpath "$DEST"
  fi

  # Verification
  if [[ "$OS_NORM" != "windows" ]]; then
    chmod +x "$DEST/bin"/* 2>/dev/null || true
    test -x "$DEST/bin/initdb"
    test -x "$DEST/bin/pg_ctl"
  else
    test -f "$DEST/bin/initdb.exe"
    test -f "$DEST/bin/pg_ctl.exe"
  fi

  echo "OK: PostgreSQL binaries ready at $DEST/bin for target: $TARGET (from $USED_URL)"
  if [[ "$OS_NORM" == "darwin" && "$TARGET" == "darwin-arm64" && "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
    "$DEST/bin/pg_ctl" --version || true
  elif [[ "$OS_NORM" == "linux" && "$(uname -s)" == "Linux" ]]; then
    "$DEST/bin/pg_ctl" --version || true
  fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
