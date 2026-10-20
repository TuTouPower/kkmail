# Cutover note (2026-10): mail-core is the sole mail backend; Flask is retiring.

# mail-core cutover

Legacy Flask (`web_outlook_app.py`) remains the runnable product shell on
`:5000` / Docker `:5080` (login, settings, compose/send until those move).

mail-core FastAPI (`:8000`) is the local-authoritative mail kernel.

## Prefer mail-core for list/reader

| Mechanism | Effect |
|---|---|
| `VITE_MAIL_CORE=1` | Build-time: SPA uses mail-core inbox + detail |
| `VITE_MAIL_CORE_DEFAULT=1` | Build-time cutover default (same UX) |
| `MAIL_CORE_DEFAULT=1` | Runtime: Flask injects `window.__KKMAIL_CONFIG__` into SPA `index.html` (no rebuild). Login routes unchanged. |
| `VITE_MAIL_CORE=0` | Force Flask-only list/reader even if runtime default is on |
| `MAIL_CORE_PUBLIC_BASE` | Optional public base for mail-core (default `/mail-core`) |

When mail-core is preferred but the API errors, **MessageList falls back to Flask**
list endpoints. MessageReader uses mail-core for `id_mode=mail_core` rows (remote
images off); non-mail_core ids keep Flask detail.

## Phases

| Phase | Legacy | mail-core |
|---|---|---|
| Skeleton / schema | Unchanged; keep shipping | `mail_core/` + compose PG :5433 |
| Sync / providers | Still owns live product reads until cutover | PG + blob; OAuth transports for Gmail/Graph |
| Cutover (current) | Login + send + settings; Flask list as fallback | SPA list/reader prefer mail-core when flagged |
| Later | Retire mail-list paths | Full local authority |

Do **not** treat the old SQLite mail cache as a source of truth.


## Dev defaults

`docker-compose.mail-core.yml` sets `MAIL_CORE_DEFAULT=1` and
`MAIL_CORE_PUBLIC_BASE=http://127.0.0.1:8000` on the API service so a local
SPA can prefer mail-core. Flask login/send remain on the product compose.

Frontend builds may set `VITE_MAIL_CORE_DEFAULT=1` (see `frontend/.env.example`).
Use `VITE_MAIL_CORE=0` to force the Flask list/reader path.
