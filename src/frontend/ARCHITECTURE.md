# Frontend architecture (kkmail SPA)

React + TypeScript + Vite SPA for kkmail. Served same-origin by mail-core (`/`), or loaded by the Electron desktop shell.

## Principles

- **One client, one backend.** All HTTP goes through `src/api/client.ts` (cookie session + CSRF + timeout). Mail list/detail/SSE live in `src/api/mailCore.ts`. Do not call provider APIs from the browser.
- **Generated OpenAPI types.** `src/api/generated/schema.ts` is produced from `schemas/openapi.json` (`npm run openapi:gen`). Hand-written DTOs in `schemaTypes.ts` / `queries.ts` wrap those shapes for the UI. Keep them in sync with `npm run openapi:check` (also run by `npm test`).
- **Server state vs UI state.** TanStack Query owns accounts, groups, inbox, search, and message detail. Zustand (`src/store/mailStore.ts`) owns theme, selection, sidebar/list widths, mobile view, and settings open.
- **Design tokens.** Layout and theme tokens live in `src/design-system/tokens.css` (see `assets/DESIGN.md`). Prefer tokens over ad-hoc colors.
- **No compose / send.** Product scope excludes compose, reply, forward, contacts, and notifications. Do not reintroduce those UI surfaces.

## Layout

Three-pane shell in `App.tsx`: `Sidebar` · `MessageList` · `MessageReader`, with `ColumnResize` tracks on wide viewports. Below `MOBILE_MAX_WIDTH` (760px, `src/lib/viewport.ts`) the sidebar becomes a drawer and list/reader swap via `data-mobile-view`. Settings replaces the list+reader tracks when open (`SettingsModal.tsx`).

## Realtime

`useMailCoreRealtime` opens cookie-authenticated SSE at `/api/events` and invalidates Query caches on named events. Browser `EventSource` cannot send Authorization headers, so the stream relies on the session cookie.

## Scripts

|Script|Purpose|
|---|---|
|`npm run dev`|Vite dev server; proxies `/api` to mail-core|
|`npm run build`|`tsc -b` + production bundle → `frontend/dist`|
|`npm test`|Vitest + `openapi:check`|
|`npm run openapi:gen`|Regenerate `src/api/generated/schema.ts`|

## Out of scope (do not resurrect)

- Flask `templates/` / `static/`, browser extension, system skins / `docs/skins.md`
- Feature flags that dual-run Flask and mail-core
