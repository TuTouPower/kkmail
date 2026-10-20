# Desktop

Electron shell for the shared React UI and Flask backend.

```bash
cd desktop
npm install
npm start
```

`npm start` launches Python on `127.0.0.1`, waits for `/login`, then opens the window with `contextIsolation` enabled.

Packaging:

```bash
npm run dist:linux
npm run dist:win
npm run dist:mac
```

In development `main.js` runs `python3 web_outlook_app.py` from the repo. Packaged builds run the PyInstaller sidecar from `resources/backend/kkmail-backend` (`.exe` on Windows); build it first with `./scripts/build-sidecar.sh`. A packaged app without the sidecar refuses to start instead of falling back to Python.

The shell passes `KKMAIL_SIDECAR=1` (no tray, no auto-opened browser) and `KKMAIL_FRONTEND_DIST`. It does not inject `SECRET_KEY` or `LOGIN_PASSWORD`: the backend generates a per-install secret in its data dir. External links open in the system browser only for `http(s):`/`mailto:`; any other navigation away from the local origin is blocked.

`npm test` checks the sidecar path and packaging config. Do not expose the local Flask port beyond `127.0.0.1`.
