# mail-core cutover

**Status (2026-10): complete for the product shell.**

- Sole backend: `mail_core` (FastAPI).
- SPA is served from mail-core (`frontend/dist`) on the same origin.
- Auth: Cookie Session + Bearer API Key + CSRF (mail-core).
- Flask segments, legacy `static/js` dual UI, and upstream compose image path are removed.

## Run

See root `README.md` and `docker-compose.mail-core.yml`.

## SPA → API map

| SPA | mail-core |
| --- | --- |
| login / session | `POST /api/auth/login`, `GET /api/auth/me` |
| accounts | `GET/POST/PATCH/DELETE /api/accounts` |
| groups | `GET/POST/DELETE /api/groups` |
| settings | `GET/POST /api/settings` (no secrets) |
| password | `POST /api/auth/password` |
| sync | `POST /api/accounts/sync-all`, `POST /api/accounts/{id}/sync` |
| mail list/detail | `/api/mail/*` + SSE `/api/events` |
| trash | `POST /api/mail/messages/{id}/trash` |

Send / forwarding / temp-mail / shares are out of scope (501 / removed).
