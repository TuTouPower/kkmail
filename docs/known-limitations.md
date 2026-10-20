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

- Electron has packaging scripts, but Windows, macOS, and Linux installers are not yet produced as release artifacts.
- The Python backend is not yet bundled as a PyInstaller sidecar.
- Docker multi-stage build is defined, but this development environment has no Docker daemon.
- OAuth, forwarding, projects, temporary mail, and WebDAV backup are reachable from Settings, but the old `/legacy` UI still holds the complete advanced flows.
- End-to-end browser tests are not yet in place.

Sidecar build verified locally: desktop/resources/outlookemail-backend
