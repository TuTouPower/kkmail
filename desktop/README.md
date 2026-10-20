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

The Python backend is still started from the repo in development. A release build should bundle a PyInstaller sidecar and point `main.js` at that binary. Do not expose the local Flask port beyond `127.0.0.1`.
