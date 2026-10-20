# Known limitations

## Product scope

- **Single user.** One login password protects the instance; there are no user accounts or roles. Bearer API keys have the same full access. Within that boundary, resource UUIDs (messages, attachments, accounts, …) are **capabilities**: knowing the UUID grants API access. They are not multi-tenant, IDOR-safe identifiers.

- **No browser extension (wontfix).** A browser extension will never ship. The old `browser-extension/` tree and `/api/extension/*` bridge are gone and must not be reintroduced.
- **No system skins.** Flask-era `data/skins/`, `docs/skins.md`, and skin `preview.png` packages are removed; appearance is limited to the SPA light/dark/system theme.

- **No sending.** Compose, reply, forward, contacts and notifications are out of scope, and the SPA has no compose UI.
- **Folders.** The SPA shows each account's inbox and the unified inbox. The backend syncs all folders, but the HTTP API exposes inbox lists only (`/api/mail/inbox`).
- **Archive, junk and move** have no API. Trash is supported: it is local-first and the remote trash is queued.
- **Flags are server-side.** `is_flagged` is stored in mail-core and written back to IMAP, Gmail and Graph via `remote_operations`. The 已标记 filter reads that field.

## Lists and search

- The list view loads the newest 100 messages per view (unified inbox or one account's inbox). Keyset pagination (`next_cursor`) is available in the API, but the SPA does not page further yet.
- Search uses the server: PostgreSQL full-text search plus trigram matching on subject and sender. The SPA starts searching at two characters (the API accepts one) and shows up to 100 results without paging.
- **Unified inbox / unread badges (client vs backend).** Architecture §12.4 targets a **backend-aggregated** unified inbox and server `folder_stats` for unread badges. **Current SPA behavior:** the list calls `/api/mail/inbox` (backend already merges inbox-role folders across accounts), but sidebar unread badges are derived from the **cached first page** of that unified list (client-8 / loaded-rows only), not from a dedicated stats endpoint. Until badges read server stats, counts can under-report beyond the loaded page. See [mail-core-architecture.md §12.4](./mail-core-architecture.md) (target) and this note (current).
- Realtime events arrive over SSE with the session cookie. Bearer-key integrations need an HTTP client that can stream and set headers; browser `EventSource` cannot.

## Desktop packaging

- **Last packaging check (docs):** 2026-10-21 — Linux `pack:linux` scaffold verified locally as soft-ok without vendored PostgreSQL (build succeeds, runtime refuses to start until `desktop/vendor/pgsql` is present). macOS/Windows unsigned paths not re-verified on that date.
- The Linux AppImage and deb include a vendored PostgreSQL (`scripts/fetch-pg-binaries.sh`) and the PyInstaller mail-core sidecar (`scripts/build-sidecar.sh`).
- macOS (dmg) and Windows (nsis) packages are unsigned builds, and their PostgreSQL binaries must be placed in `desktop/vendor/pgsql/bin` at build time (the fetch script is Linux-only). Without them the desktop app refuses to start.

## Tests

- Backend: `pytest tests` (needs PostgreSQL; `scripts/run-mail-core-tests.sh`).
- Frontend: `vitest` unit and component tests (jsdom).
- End-to-end: Playwright smoke suite in `e2e/` (covers login, mailbox list, and message reader).
