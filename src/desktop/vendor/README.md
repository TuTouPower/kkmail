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

The default PostgreSQL 16.6.0 target archives use SHA-256 pins stored in the fetch script. Unpinned mirrors or versions may use a same-origin checksum only as a warned fallback; provide `PG_VENDOR_SHA256` to pin a custom archive explicitly.

`PostgresManager` resolves: `KKMAIL_PG_BIN` → `desktop/vendor/pgsql/bin` → `PATH`.

## macOS / Windows (download-at-build)

The fetch script prints instructions and exits 0 for `--os macos|windows`.
Packaging / CI for those platforms should download the matching official or
EnterpriseDB / Postgres.app binaries at **build time** and unpack into
`desktop/vendor/pgsql/bin/` (or set `KKMAIL_PG_BIN`) before `electron-builder`.

Do not assume a single cross-platform tarball URL.
