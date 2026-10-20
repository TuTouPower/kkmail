# mail-core

Greenfield mail kernel for kkmail. Spec: [`docs/mail-core-architecture.md`](../docs/mail-core-architecture.md).

Flask (`web_outlook_app.py`) is **unchanged** and remains the default product path.

## Run API + Worker + PostgreSQL together

### 1. Dependencies

```bash
pip install -r requirements-mail-core.txt
```

### 2. PostgreSQL 16

**Option A — Docker Compose** (dev):

```bash
docker compose -f docker-compose.mail-core.yml up -d postgres
# if compose plugin missing:
# docker run -d --name kkmail-mail-core-pg \
#   -e POSTGRES_USER=kkmail -e POSTGRES_PASSWORD=kkmail \
#   -e POSTGRES_DB=kkmail_mail -p 5433:5432 postgres:16
```

**Option B — Desktop Electron child process** (stub until binaries ship):

See [`docs/mail-core-desktop.md`](../docs/mail-core-desktop.md). Data lives under
`userData/mail-core-data/` (outside the install dir). Set `KKMAIL_MAIL_CORE_PG=1`.

### 3. Environment

```bash
export MAIL_CORE_DATABASE_URL=postgresql+psycopg://kkmail:kkmail@127.0.0.1:5433/kkmail_mail

# Blob AES-GCM keyring (KKMB) — NOT the backup key
export MAIL_CORE_BLOB_KEY_V1="$(python -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())')"
export MAIL_CORE_BLOB_ACTIVE_VERSION=1

# Backup package key (KKBK) — MUST be separate from blob keys
export MAIL_CORE_BACKUP_KEY="$(python -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())')"

# Optional paths
# export MAIL_CORE_BLOB_ROOT=/var/lib/kkmail/blobs
# export MAIL_CORE_BACKUP_DIR=/var/lib/kkmail/backups
```

**Production:** place PG data + blob root on an **encrypted volume**
(OS disk encryption / LUKS / FileVault / BitLocker). A Docker named volume alone
does **not** satisfy architecture §11 / M5.

### 4. Schema

```bash
alembic -c mail_core/db/alembic.ini upgrade head
```

### 5. Start processes (three terminals)

```bash
# API (LISTEN/NOTIFY outbox fan-out starts in lifespan)
uvicorn mail_core.api.app:app --reload --host 127.0.0.1 --port 8000

# Worker (SKIP LOCKED jobs + account leases)
python -m mail_core.worker.main

# Postgres already running from step 2
```

Health: `curl -s http://127.0.0.1:8000/health`

### 6. SPA bridge (optional)

```bash
# frontend/.env.local
VITE_MAIL_CORE=1
# VITE_MAIL_CORE_BASE=http://127.0.0.1:8000
```

When the flag is off, the Flask default mail UI is unchanged.

### 7. Backup / restore stub

```bash
python -c "from mail_core.backup import create_backup_package; print(create_backup_package())"
# Restore verify: mail_core.backup.verify_backup_package(path)
```

## Layout

| Path | Role |
|---|---|
| `api/` | FastAPI (inbox, search, SSE, attachments by UUID) |
| `worker/` | Job loop |
| `sync/` | Leases, delta, IMAP/Gmail/Graph adapters |
| `blobs/` | Encrypted content-addressed store + GC |
| `backup/` | PG + blobs package with separate AES-GCM key |
| `realtime/` | Outbox + LISTEN |
| `desktop/` (repo root) | Electron PG lifecycle scaffold |

## Security notes (M5)

- Attachments: `GET /api/mail/attachments/{uuid}` only — path params rejected.
- Remote images: mail-core default **off** (`mail_core.security.REMOTE_IMAGES_DEFAULT_ON`).
- Blob digests validated as 64-hex; paths cannot escape blob root.
- Backup key ≠ blob keyring.

## Tests

```bash
pytest tests/mail_core/ -q
```

Cutover notes: [`docs/mail-core-cutover.md`](../docs/mail-core-cutover.md).
Desktop PG: [`docs/mail-core-desktop.md`](../docs/mail-core-desktop.md).
