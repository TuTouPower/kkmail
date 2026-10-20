# HTTP API

The API reference is generated from the code and is always current:

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

Mail, account, group, settings, health and login routes declare a `response_model`, so the schema documents their request and response bodies. `POST /api/auth/logout` and `POST /api/auth/password` return `{"ok": true}`. `/docs` and `/openapi.json` are served without authentication; they describe the API shape only.

## Conventions

- **Auth:** a session cookie (`kkmail_mc_session`, `HttpOnly`) from `POST /api/auth/login` (`{"password": "..."}`), or `Authorization: Bearer <key>` (keys in `MAIL_CORE_API_KEYS`). Every route except `/health`, `/ready` and login requires one of them; otherwise the response is 401. An invalid Bearer key is rejected even if a valid cookie is also sent. API keys are never accepted in the query string.
- **Login rate limit:** repeated failures from one client address return 429 with `Retry-After`.
- **CSRF:** with a cookie session, `POST/PUT/PATCH/DELETE` must send `X-CSRF-Token` (the token from login or `GET /api/auth/me`). Bearer requests are exempt.
- **Errors:** FastAPI's shape, `{"detail": "..."}`. Validation errors return 422 with a list in `detail`. A CSRF failure returns 403 with `{"detail": {"error": "...", "csrf_error": true}}`.
- **Pagination:**
  - `/api/mail/inbox` returns `next_cursor`, an opaque token. Pass it back as `?cursor=`.
  - `/api/mail/search?q=` returns hydrated message rows plus `total` and `next_offset`. Pass the latter back as `?offset=`. The server accepts a one-character `q`; the SPA starts searching at two characters.
  - `/api/accounts` uses `limit`, `offset` and `has_more`.
- **Mutations:** `POST /api/mail/messages/{id}/read` (`{"is_read": bool}`), `/flag` (`{"is_flagged": bool}`) and `/trash` apply locally and queue the remote write-back.
- **Realtime:** `GET /api/events` (SSE) carries outbox events such as `message.upserted`, `message.removed`, `folder.stats_updated`, `sync.*`, `remote_operation.updated` and `client.resync_hint`. Resume with the `Last-Event-ID` header (or `?after=`); a gap that is too large yields `client.resync_hint`. Browsers authenticate with the session cookie (`EventSource` with `withCredentials`); `EventSource` cannot send an `Authorization` header, so Bearer clients need a streaming HTTP client.
- **Attachments:** `GET /api/mail/attachments/{uuid}` streams the decrypted bytes. Path-shaped access is rejected.
