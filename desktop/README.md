# Desktop

Electron shell for the React UI and the mail-core backend.

```bash
cd desktop
npm install
npm start
```

Startup sequence (`main.js`):

1. `PostgresManager` starts a loopback-only PostgreSQL cluster under `userData/mail-core-data/` (outside the install dir; per-install random password, `scram-sha-256`). Missing PG binaries are a fatal error — see `docs/mail-core-desktop.md`.
2. Spawns mail-core with `--data-dir <userData>/mail-core-data`: in development `python3 -m mail_core` from the repo, packaged builds the PyInstaller sidecar `resources/backend/kkmail-backend` (build with `./scripts/build-sidecar.sh`). A packaged app without the sidecar refuses to start.
3. mail-core generates per-install secrets (session key, blob key, backup key) in `mail-core-data/secrets/` (0600), runs migrations, starts the API and an embedded worker on `127.0.0.1`.
4. After `/health` answers, the window opens. On first run the generated initial login password is shown once; it disappears after you change it in Settings.

External links open in the system browser only for `http(s):`/`mailto:`; other navigation away from the local origin is blocked. Never expose the local port beyond `127.0.0.1`.

`npm test` checks sidecar paths, packaging config, and the PostgreSQL manager.
