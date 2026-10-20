# Desktop

Electron shell for the React UI and the mail-core backend.

## Setup

```bash
cd desktop
npm ci          # prefer ci (lockfile) over npm install
npm start
```

Host Node ≥ 22.12 is recommended (Electron 44 engines range). See also `docs/mail-core-desktop.md`.

### Environment variables

| Variable | Who | Purpose |
|---|---|---|
| `KKMAIL_PG_BIN` | Electron / PostgresManager | Override path to `initdb`/`pg_ctl` bin dir |
| `KKMAIL_PG_PORT` | PostgresManager | Loopback PG port (integer 1–65535) |
| `KKMAIL_FRONTEND_DIST` | mail-core API | Optional path to built SPA (`frontend/dist`) |
| `MAIL_CORE_*` | mail-core child | Set by `startup.js` (DB URL, blob keys, data dir, …) — not inherited from the parent shell |
| `PG*` | pg_ctl / createdb | Allowlisted by `scrubEnv` when spawning Postgres |

Packaging: macOS DMG/ZIP artifacts are named **`kkmail.dmg`** / **`kkmail.zip`** (`build.mac.artifactName`).

## Startup sequence (`main.js`)

1. `PostgresManager` starts a loopback-only PostgreSQL cluster under `userData/mail-core-data/` (outside the install dir; per-install random password, `scram-sha-256`). Missing PG binaries are a fatal error — see `docs/mail-core-desktop.md`.
2. Spawns mail-core with `--data-dir <userData>/mail-core-data`: in development `python3 -m mail_core` from the repo, packaged builds the PyInstaller sidecar `resources/backend/kkmail-backend` (build with `./scripts/build-sidecar.sh`). A packaged app without the sidecar refuses to start.
3. mail-core generates per-install secrets (session key, blob key, backup key) in `mail-core-data/secrets/` (0600), runs migrations, starts the API and an embedded worker on `127.0.0.1`.
4. After `/health` answers, the window opens. On first run the generated initial login password is shown once; it disappears after you change it in Settings.

External links open in the system browser only for `http(s):`/`mailto:`; other navigation away from the local origin is blocked. Never expose the local port beyond `127.0.0.1`.

## Session hardening (`hardening.js`)

- `will-attach-webview` always prevented (`webviewTag: false`)
- permission request/check handlers deny all prompts
- restrictive Content-Security-Policy on every response (`default-src 'self'`, no `object`/`frame-ancestors`, connect only to self)

## Tests (`npm test`)

| File | Coverage |
|---|---|
| `paths.test.js` | Sidecar path + `extraResources` filter matches `kkmail-backend` |
| `hardening.test.js` | CSP / webview / permission deny helpers |
| `postgresManager.test.js` | Data root, pwfile 0600, port validation, stop idempotency, binary cache |
| `startup.test.js` | `scrubEnv` allowlist, log redaction, process-tree kill helpers |

## Child-process hardening (`startup.js` / `postgresManager.js`)

- mail-core and `pg_ctl`/`createdb` get an **allowlisted** env (`scrubEnv`) plus explicit `MAIL_CORE_*` / `PG*` extras — parent secrets are not inherited
- backend **stdio is piped** to `mail-core-data/mail-core.log` with password / DB-URL redaction (no `inherit`)
- shutdown is **single-flight**: SIGTERM the process group (Unix) or the child, escalate to SIGKILL / `taskkill /T /F` after 4s; `PostgresManager.stop()` is idempotent
- PG binary probes are **cached** with a spawn timeout; `KKMAIL_PG_PORT` must be an integer 1–65535 before writing `postgresql.conf`
- initdb `--pwfile` lives under `secrets/` mode `0600` and is unlinked in `finally` (legacy `.pgpass-init` cleaned on start)
- data root prefers Electron `userData`, else `~/.kkmail`, else `XDG_DATA_HOME` / per-uid tmp — never shared `/tmp/.kkmail`
