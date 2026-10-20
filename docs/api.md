# HTTP API

The API reference is generated from the code and is always current:

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

Every route declares a `response_model`, so the schema documents request and response bodies.

## Conventions

- **Auth:** a session cookie from `POST /api/auth/login`, or `Authorization: Bearer <key>` (keys in `MAIL_CORE_API_KEYS`). Every route except `/health`, `/ready` and login requires one of them.
- **CSRF:** with a cookie session, `POST/PUT/PATCH/DELETE` must send `X-CSRF-Token` (the token from login or `GET /api/auth/me`). Bearer requests are exempt.
- **Errors:** FastAPI's shape, `{"detail": "..."}`. Validation errors return 422 with a list in `detail`. A CSRF failure returns 403 with `{"detail": {"error": "...", "csrf_error": true}}`.
- **Pagination:**
  - `/api/mail/inbox` returns `next_cursor`, an opaque token. Pass it back as `?cursor=`.
  - `/api/mail/search` returns `total` and `next_offset`. Pass the latter back as `?offset=`.
  - `/api/accounts` uses `limit`, `offset` and `has_more`.
- **Realtime:** `GET /api/events` (SSE) carries outbox events such as `message.upserted`, `message.removed`, `folder.stats_updated` and `client.resync_hint`.
- **Attachments:** `GET /api/mail/attachments/{uuid}` streams the decrypted bytes. Path-shaped access is rejected.
