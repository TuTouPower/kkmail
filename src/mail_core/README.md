# mail-core

The kkmail backend. Spec: [`docs/blueprint/architecture.md`](../../docs/blueprint/architecture.md). Deployment: [`docs/guides/deployment.md`](../../docs/guides/deployment.md).

## Run

```bash
pip install -r requirements-dev.txt
export MAIL_CORE_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<db>
python -m mail_core --data-dir ./.kkmail-data
```

`python -m mail_core` runs the migrations, starts the worker in the same process, then starts the API with uvicorn.

|Option|Environment|Default / behavior|
|---|---|---|
|`--host`|`MAIL_CORE_HOST`|`127.0.0.1`|
|`--port`|`MAIL_CORE_PORT`|`8000`|
|`--data-dir`|`MAIL_CORE_DATA_DIR`|Unset. When set, missing per-install secrets and storage paths are bootstrapped under this directory.|
|`--no-worker`|`MAIL_CORE_EMBEDDED_WORKER=0`|Embedded worker is enabled by default. To run it separately: `python -m mail_core.worker.main`.|
|`--skip-migrations`|`MAIL_CORE_SKIP_MIGRATIONS=1`|Migrations run at startup by default.|
|`--proxy-headers`|`MAIL_CORE_PROXY_HEADERS`|Requests proxy-header handling. Requires `--forwarded-allow-ips` or `MAIL_CORE_FORWARDED_ALLOW_IPS`; without trusted hosts, logs a warning and leaves forwarded headers disabled.|
|`--forwarded-allow-ips`|`MAIL_CORE_FORWARDED_ALLOW_IPS`|Unset. Comma-separated trusted proxy IPs/CIDRs; enables `X-Forwarded-*` handling for those peers.|

When data-dir bootstrap must create a login credential, it writes a random initial password to `<data-dir>/initial-password.txt` and its bcrypt hash to `<data-dir>/secrets/login-password.bcrypt` (both mode `0600`). The plaintext file remains until the user changes the login password in Settings; then it is removed. With a database configured, `auth_credentials.login_password_hash` is authoritative after bootstrap.

## Configuration

|Env|Purpose|
|---|---|
|`MAIL_CORE_DATABASE_URL`|**Required.** There is no default.|
|`MAIL_CORE_SECRET_KEY`|Session signing key. Required without `--data-dir`; data-dir bootstrap creates and persists one.|
|`MAIL_CORE_LOGIN_PASSWORD_HASH`, `MAIL_CORE_LOGIN_PASSWORD`, `MAIL_CORE_PASSWORD_HASH_PATH`|Login bootstrap sources. The database credential row is authoritative once populated.|
|`MAIL_CORE_API_KEYS`|Bearer keys for integrations.|
|`MAIL_CORE_LOG_LEVEL`|Root log threshold; defaults to `INFO`. Invalid values warn and fall back to `INFO`.|
|`MAIL_CORE_COOKIE_SECURE`, `MAIL_CORE_COOKIE_SAMESITE`, `MAIL_CORE_SESSION_MAX_AGE`|Session cookie controls: secure follows HTTPS when unset, SameSite defaults to `lax`, and max age defaults to 30 days.|
|`MAIL_CORE_LOGIN_MAX_FAILURES`, `MAIL_CORE_LOGIN_WINDOW_S`|Failed-login rate limit; defaults to 10 failures per 300 seconds.|
|`MAIL_CORE_SSE_MAX_CONNECTIONS`|Maximum concurrent SSE streams per process; defaults to 128.|
|`MAIL_CORE_FORWARDED_ALLOW_IPS`|Trusted proxy IPs/CIDRs; unset disables forwarded-header middleware.|
|`MAIL_CORE_PUBLIC_ORIGIN`, `MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN`|Web OAuth origin and opt-in loopback HTTP for local testing; loopback allowance defaults off.|
|`MAIL_CORE_ALLOW_PRIVATE_HOSTS`|Allows IMAP connections to private/loopback hosts; defaults off.|
|`KKMAIL_SIDECAR`, `KKMAIL_INSTANCE_TOKEN`|Desktop-only runtime marker and `/health` handshake token; do not configure for web deployments.|
|`KKMAIL_FRONTEND_DIST`|Optional SPA directory served at `/`.|
|`MAIL_CORE_BLOB_KEY_V1`, `MAIL_CORE_BLOB_KEYS`, `MAIL_CORE_BLOB_KEY_VERSION`, `MAIL_CORE_BLOB_ACTIVE_VERSION`|Blob and credential keyring. Supply one base64 32-byte key or a JSON version map; the active version defaults to the highest configured version.|
|`MAIL_CORE_BLOB_ROOT`, `MAIL_CORE_BLOB_SOFT_BYTES`, `MAIL_CORE_BLOB_HARD_BYTES`|Blob storage path and optional soft/hard quota limits. Root defaults to `[REDACTED]mail-core-blobs` without data-dir.|
|`MAIL_CORE_BACKUP_KEY`, `MAIL_CORE_BACKUP_KEYS`, `MAIL_CORE_BACKUP_KEY_VERSION`|Backup keyring; keys must differ from blob keys. Active version defaults to the highest configured version.|
|`MAIL_CORE_BACKUP_DIR`|Backup output directory; defaults to `<data-dir>/backups` or `[REDACTED]mail-core-backup`.|
|`MAIL_CORE_DB_POOL_SIZE`, `MAIL_CORE_DB_MAX_OVERFLOW`, `MAIL_CORE_DB_POOL_TIMEOUT`, `MAIL_CORE_DB_POOL_RECYCLE`|SQLAlchemy pool settings. Defaults: 10 / 10 / 30 seconds / 1800 seconds.|
|`MAIL_CORE_EMBEDDED_WORKER`, `MAIL_CORE_WORKER_ID`, `MAIL_CORE_WORKER_POLL_S`, `MAIL_CORE_WORKER_MAX_IDLE_S`|Embedded worker and identity/poll controls. Embedded worker defaults on, poll defaults to 2 seconds, max idle defaults to `max(poll, 10)`; worker ID is generated when unset.|
|`MAIL_CORE_RECLAIM_STALE_SECONDS`, `MAIL_CORE_JOB_MAX_ATTEMPTS`, `MAIL_CORE_ARCHIVE_BATCH`|Worker reclaim/retry/archive limits. Defaults: 300 seconds / 8 attempts / 20 messages per archive batch.|
|`MAIL_CORE_PG_CONNECT_TIMEOUT`, `MAIL_CORE_PG_DUMP_TIMEOUT`, `MAIL_CORE_PG_RESTORE_TIMEOUT`|Backup PostgreSQL connection/dump/restore timeouts. Defaults: 10 / 300 / 300 seconds.|
|`MAIL_CORE_PROXY_HEADERS`|When enabled, requests proxy-header handling; requires trusted `MAIL_CORE_FORWARDED_ALLOW_IPS`, otherwise warns and leaves forwarded headers disabled.|

## Layout

|Path|Role|
|---|---|
|`api/`|FastAPI routers: `auth_routes`, `accounts`, `mail`, `sse`. Routes call the application layer only.|
|`mail/application/`|Read models, search, mutations, remote operations, attachments.|
|`mail/domain/`, `mail/storage/`|Enums, the archive FSM, ORM models, folder stats.|
|`accounts/`|Accounts, groups, settings, and credential stores (DB-encrypted, `env:` read-only, `keyring:`).|
|`sync/`|Leases and fencing, jobs, metadata and delta apply, the engine.|
|`providers/`|IMAP, Gmail and Graph providers, OAuth, remote write-back.|
|`worker/`|Job loop and handlers.|
|`blobs/`|KKMS streaming AEAD store, archive scheduler, GC, key rotation.|
|`backup/`|KKBK backup packages.|
|`realtime/`|Outbox dispatcher and LISTEN/NOTIFY.|
|`security/`|Auth, redaction, login rate limit.|
|`runtime/`|`--data-dir` secret bootstrap.|

## Tests

```bash
export MAIL_CORE_DATABASE_URL=...   # disposable database
scripts/run-mail-core-tests.sh      # migrate + full pytest; DB-backed tests are not allowed to skip
```
