# Known limitations

## Product scope

- **Single user.** One login password protects the instance; there are no user accounts or roles. Bearer API keys have the same full access.

- **No sending.** Compose, reply, forward, contacts and notifications are out of scope, and the SPA has no compose UI.
- **Folders.** The SPA shows each account's inbox and the unified inbox. The backend syncs all folders, but the HTTP API exposes inbox lists only (`/api/mail/inbox`).
- **Archive, junk and move** have no API. Trash is supported: it is local-first and the remote trash is queued.
- **Flags are server-side.** `is_flagged` is stored in mail-core and written back to IMAP, Gmail and Graph via `remote_operations`. The 已标记 filter reads that field.

## Lists and search

- The list view loads the newest 100 messages per view (unified inbox or one account's inbox). Keyset pagination (`next_cursor`) is available in the API, but the SPA does not page further yet.
- Search uses the server: PostgreSQL full-text search plus trigram matching on subject and sender. The SPA starts searching at two characters (the API accepts one) and shows up to 100 results without paging.
- Sidebar unread badges come from the cached unified-inbox page, so they count unread messages among the loaded rows only.
- Realtime events arrive over SSE with the session cookie. Bearer-key integrations need an HTTP client that can stream and set headers; browser `EventSource` cannot.

## Desktop packaging

- The Linux AppImage and deb include a vendored PostgreSQL (`scripts/fetch-pg-binaries.sh`) and the PyInstaller mail-core sidecar (`scripts/build-sidecar.sh`).
- macOS (dmg) and Windows (nsis) packages are unsigned builds, and their PostgreSQL binaries must be placed in `desktop/vendor/pgsql/bin` at build time (the fetch script is Linux-only). Without them the desktop app refuses to start.

## Tests

- Backend: `pytest tests` (needs PostgreSQL; `scripts/run-mail-core-tests.sh`).
- Frontend: `vitest` unit and component tests (jsdom).
- There is no browser end-to-end suite.
