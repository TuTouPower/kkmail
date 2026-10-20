# Known limitations

## Product scope

- **No sending.** Compose, reply, forward, contacts and notifications are out of scope, and the SPA has no compose UI.
- **Folders.** The SPA shows each account's inbox and the unified inbox. The backend syncs all folders, but the HTTP API exposes inbox lists only (`/api/mail/inbox`).
- **Archive, junk and move** have no API. Trash is supported: it is local-first and the remote trash is queued.
- **Flags are server-side.** `is_flagged` is stored in mail-core and written back to IMAP, Gmail and Graph via `remote_operations`. The 已标记 filter reads that field.

## Lists and search

- The list view loads the newest 100 messages per view. Keyset pagination (`next_cursor`) is available in the API, but the SPA does not page further yet.
- Search uses the server: PostgreSQL full-text search plus trigram matching on subject and sender. It starts from two characters.
- Sidebar unread badges come from the cached unified-inbox page, so they count unread messages among the loaded rows only.

## Desktop packaging

- The Linux AppImage and deb include a vendored PostgreSQL (`scripts/fetch-pg-binaries.sh`) and the PyInstaller mail-core sidecar (`scripts/build-sidecar.sh`).
- macOS and Windows packages are unsigned builds.

## Tests

- Backend: `pytest tests` (needs PostgreSQL; `scripts/run-mail-core-tests.sh`).
- Frontend: `vitest` unit and component tests (jsdom).
- There is no browser end-to-end suite.
