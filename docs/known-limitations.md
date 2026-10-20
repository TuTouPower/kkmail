# Known limitations

Recorded so unfinished product rules are not silently dropped.

## Flagged mail

The design system requires a Flagged filter and a flag action. Upstream `assast/outlookEmail` does not provide a server-side flagged or starred field on `/api/emails` or `/api/email`.

Current behavior:

- Flagging a message stores the key in local UI state.
- The Flagged filter only sees that local state.
- Flags are not written to Graph, IMAP, or SQLite.

Revisit when the backend exposes a flag API. Do not remove the Flagged control from the design without approval.

## Move and archive

The design system includes move and archive actions. Upstream mail routes support inbox, junk, trash, and all. There is no dedicated move-to-folder API. Archive is therefore not wired to a server folder. Move destinations that exist are limited to the folders the live API already supports.

## Packaging status

Verified in this development environment:

- Linux AppImage and deb build with `cd desktop && npm run dist:linux`.
- Windows unpacked app and zip build with signing disabled. NSIS installer needs Wine on Linux.
- PyInstaller sidecar builds with `./scripts/build-sidecar.sh`.
- Browser login into the React shell was verified against a local Flask server.
- Backend test suite: 756 passed.

Blocked here:

- No Docker daemon, so the multi-stage image was not run.
- Windows NSIS installer requires Wine when built on Linux.
- macOS packages must be built on macOS.

CI workflows are in `.github/workflows/desktop.yml` and `.github/workflows/tests.yml`.

## Remaining product gaps

- OAuth, forwarding, projects, temporary mail, and WebDAV backup are reachable from Settings, but the old `/legacy` UI still holds the complete advanced flows.
- End-to-end browser tests are not yet in place.
