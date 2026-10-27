# PostgreSQL vendor binaries (desktop)

Place official PostgreSQL **16** binaries under `pgsql/bin/`:

```
desktop/vendor/pgsql/bin/initdb
desktop/vendor/pgsql/bin/pg_ctl
desktop/vendor/pgsql/bin/postgres
```

**Do not commit the binary tree** (see `.gitignore`).

## Linux (dev / CI)

```bash
./scripts/fetch-pg-binaries.sh
# uses theseus-rs portable builds; override with PG_VENDOR_URL=...
```

The default PostgreSQL 16.6.0 target archives use SHA-256 pins stored in the fetch script. Unpinned mirrors or versions are refused by default; a same-origin checksum fallback is only available with the explicit `--allow-unpinned` opt-in, and providing `PG_VENDOR_SHA256` to pin a custom archive explicitly is preferred.

The desktop bundle version (16.6.0) is intentionally independent of the server/test image (postgres:16.15): desktop binaries are prebuilt portable tarballs from theseus-rs, while the server runs the official Docker image. Both stay on the PostgreSQL 16 major line; patch-level drift is expected, and desktop bumps are deliberate pin-refresh changes rather than automatic tracking of server patch releases (see the header of `scripts/fetch-pg-binaries.sh`).

`PostgresManager` resolves: `KKMAIL_PG_BIN` → `desktop/vendor/pgsql/bin` → `PATH`.

## macOS / Windows (download-at-build)

The fetch script prints instructions and exits 0 for `--os macos|windows`.
Packaging / CI for those platforms should download the matching official or
EnterpriseDB / Postgres.app binaries at **build time** and unpack into
`desktop/vendor/pgsql/bin/` (or set `KKMAIL_PG_BIN`) before `electron-builder`.

Do not assume a single cross-platform tarball URL.
