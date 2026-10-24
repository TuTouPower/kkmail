# mail-core

The kkmail backend. Spec: [`docs/blueprint/architecture.md`](../../docs/blueprint/architecture.md). Deployment: [`docs/guides/deployment.md`](../../docs/guides/deployment.md).

## Run

```bash
pip install -r requirements-dev.txt
export MAIL_CORE_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<db>
python -m mail_core --data-dir ./.kkmail-data
```

`python -m mail_core` runs the migrations, starts the worker in the same process, then starts the API with uvicorn.

|Option|Env|Default|
|---|---|---|
|`--host` / `--port`|`MAIL_CORE_HOST` / `MAIL_CORE_PORT`|`127.0.0.1` / `8000`|
|`--data-dir`|`MAIL_CORE_DATA_DIR`|(none). When set, missing secrets are generated (0600) and the blob and backup dirs are placed under it.|
|`--no-worker`|`MAIL_CORE_EMBEDDED_WORKER=0`|Embedded worker is on. To run it separately: `python -m mail_core.worker.main`.|
|`--skip-migrations`|`MAIL_CORE_SKIP_MIGRATIONS=1`|Migrations run at start.|

## Configuration

|Env|Purpose|
|---|---|
|`MAIL_CORE_DATABASE_URL`|**Required.** There is no default.|
|`MAIL_CORE_SECRET_KEY`|Session signing key. Required unless `--data-dir` is set.|
|`MAIL_CORE_LOGIN_PASSWORD_HASH` / `MAIL_CORE_LOGIN_PASSWORD`|Login password.|
|`MAIL_CORE_API_KEYS`|Bearer keys for integrations.|
|`MAIL_CORE_LOG_LEVEL`|Root log threshold (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`); defaults to `INFO`. Invalid values warn and fall back to `INFO`.|
|`MAIL_CORE_BLOB_KEY_V1` / `MAIL_CORE_BLOB_KEYS` / `MAIL_CORE_BLOB_ACTIVE_VERSION`|Blob and credential encryption keyring.|
|`MAIL_CORE_BACKUP_KEY` / `MAIL_CORE_BACKUP_KEYS`|Backup key. Must differ from the blob key.|
|`MAIL_CORE_BLOB_ROOT`, `MAIL_CORE_BACKUP_DIR`|Storage paths.|
|`MAIL_CORE_DB_POOL_SIZE`, `_MAX_OVERFLOW`, `_POOL_TIMEOUT`, `_POOL_RECYCLE`|Connection pool. Defaults: 10 / 10 / 30 s / 1800 s.|
|`MAIL_CORE_WORKER_POLL_S`, `MAIL_CORE_WORKER_MAX_IDLE_S`|Worker poll base and idle back-off ceiling.|
|`MAIL_CORE_COOKIE_SECURE`, `MAIL_CORE_COOKIE_SAMESITE`, `MAIL_CORE_SESSION_MAX_AGE`|Session cookie.|
|`MAIL_CORE_LOGIN_MAX_FAILURES`, `MAIL_CORE_LOGIN_WINDOW_S`|Failed-login limit.|
|`KKMAIL_FRONTEND_DIST`|SPA directory served at `/`.|

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
