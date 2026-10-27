# kkmail frontend

React + TypeScript + Vite SPA for the kkmail mail-core backend.

## Setup

```bash
# from repo root: mail-core must be listening (default 127.0.0.1:8000)
cd src/frontend
npm ci
npm run dev          # http://127.0.0.1:5173 — /api proxied to mail-core
npm run build        # output: dist/ (also copied/served by mail-core in production images)
npm test             # vitest + OpenAPI drift check
```

Optional: set `VITE_API_BASE` (or runtime `__KKMAIL_CONFIG__.apiBase`) when the API origin differs from the page origin. Same-origin is the default and preferred.

## Layout of `src/`

|Path|Role|
|---|---|
|`api/`|HTTP client, mail-core helpers, OpenAPI-generated types|
|`components/`|Sidebar, MessageList, MessageReader, Settings, Login|
|`hooks/`|SSE realtime (`useMailCoreRealtime`), scope sync + authoritative polling (`use_scope_sync`)|
|`public/theme_bootstrap.js`|Pre-render theme bootstrap loaded by `index.html` before the app mounts|
|`store/`|Zustand UI state|
|`design-system/`|CSS tokens|
|`lib/`|mailKey, sanitize/srcdoc, viewport breakpoint, helpers|

See [ARCHITECTURE.md](./ARCHITECTURE.md) for boundaries and product scope. Root docs: [docs/guides/deployment.md](../../docs/guides/deployment.md), [schemas/openapi.json](../../schemas/openapi.json), [assets/DESIGN.md](../../assets/DESIGN.md).
