# Known limitations

Recorded so unfinished product rules are not silently dropped.

## Flagged mail

The design system requires a Flagged filter and a flag action. Upstream `assast/outlookEmail` does not provide a server-side flagged or starred field on `/api/emails` or `/api/email`.

Current behavior:

- Flagging a message stores the key in local UI state.
- The Flagged filter only sees that local state.
- Flags are not written to Graph, IMAP, or SQLite.

Revisit when the backend exposes a flag API. Do not remove the Flagged control from the design without approval.

## Apple Mail demo alignment

The new interface follows `DESIGN.md` and the earlier Apple Mail demo:

- Three-column workspace, collapsible sidebar, settings only at bottom left.
- List toolbar has search, clear search, All/Unread/Flagged, Mark All as Read, sort.
- Reader toolbar has reply, reply all, forward, mark read, archive, trash, junk, move, flag.
- Mobile uses a drawer and a back control.

Archive, junk, and move are present for design parity. Upstream mail routes still only support inbox, junk, and trash as live folders, and there is no move API. Trash is wired to delete (with confirmation). The other three buttons are rendered `disabled` until a backend move API exists.

The unified "所有收件箱" view fetches at most 8 accounts (one request per account) and shows a notice when more accounts exist.

## Packaging status

Verified in this development environment:

- Linux AppImage and deb build with `cd desktop && npm run dist:linux`.
- Windows unpacked app and zip build with signing disabled. NSIS installer needs Wine on Linux.
- PyInstaller sidecar builds with `./scripts/build-sidecar.sh` and, with `KKMAIL_SIDECAR=1`, serves the bundled SPA without opening a tray or browser.
- Linux unpacked Electron app starts the bundled sidecar, generates a per-install `secret_key.txt`, and stops the sidecar on SIGTERM.
- Browser login into the React shell was verified against a local Flask server.
- Backend test suite: full `pytest` passes; frontend `oxlint --deny-warnings`, `vitest`, and `vite build` pass.

Blocked here:

- No Docker daemon, so the multi-stage image was not run.
- Windows NSIS installer requires Wine when built on Linux.
- macOS packages must be built on macOS.

CI workflows are in `.github/workflows/desktop.yml` and `.github/workflows/tests.yml`.

## Remaining product gaps

- OAuth, forwarding, projects, temporary mail, and WebDAV backup are reachable from Settings, but the old `/legacy` UI still holds the complete advanced flows.
- End-to-end browser tests are not yet in place.


## Mail list cache

The React SPA keeps mail lists in `@tanstack/react-query` memory:

- `staleTime` is 5 minutes (`MAIL_STALE_TIME_MS`); within that window navigation reuses the cache.
- Soft refresh (toolbar 刷新) calls `invalidateQueries` and keeps showing the previous list via `placeholderData` while refetching.
- There is still no durable IndexedDB/SQLite mail cache; a full page reload re-fetches from IMAP/Graph.
