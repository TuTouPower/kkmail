# PostgreSQL vendor binaries (desktop)

Place official PostgreSQL **16** binaries under `pgsql/bin/` so Electron can start
a local server without Docker:

```
desktop/vendor/pgsql/bin/initdb
desktop/vendor/pgsql/bin/pg_ctl
desktop/vendor/pgsql/bin/postgres
…
```

## Fetch (development)

```bash
./scripts/fetch-pg-binaries.sh          # Linux x86_64 by default
./scripts/fetch-pg-binaries.sh --os macos --arch arm64
```

The script downloads a community/EnterpriseDB-style portable tarball (or documents
the manual URL when the mirror is unavailable) into `desktop/vendor/pgsql/`.

**Do not commit the binary tree** (see `desktop/vendor/.gitignore`). CI and
fresh clones stay stub-mode until this script (or `KKMAIL_PG_BIN`) is used.

## Runtime resolution order

1. `KKMAIL_PG_BIN` / `PostgresManager({ pgBinDir })`
2. `desktop/vendor/pgsql/bin`
3. System `PATH` (`initdb` / `pg_ctl`)
