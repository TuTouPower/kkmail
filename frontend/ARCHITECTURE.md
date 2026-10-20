# Frontend Architecture

This React + TypeScript + Vite frontend is the long-term UI for the Apple Mail style client.

## Principles

- One frontend, one backend, multiple delivery targets (Electron desktop + Docker web).
- Never let React components talk directly to Flask URLs. Always go through `src/api/client.ts`.
- Design system tokens live in `src/design-system/tokens.css` and follow Apple HIG.
- Zustand holds local UI state (theme, selection, collapsed trees). TanStack Query will own server state.
- Old `templates/` and `static/` remain until the new UI covers all features, then they become optional fallback.

## Current Status

- Three-pane layout (sidebar / list / reader)
- Collapsible account groups and folders
- Dark / light theme with persistence
- Settings modal
- Demo data only — real API integration is next

## Next Steps

1. Map existing Flask routes into the typed API client.
2. Replace demo data with TanStack Query hooks.
3. Add compose, reply, forward, and batch actions.
4. Electron shell + PyInstaller sidecar for desktop packages.
5. Automated upstream sync workflow.
