# mail-core implementation status

Spec: [mail-core-architecture.md](./mail-core-architecture.md). This page is a **checklist against that spec**, not a claim that every milestone (M1–M6) is fully met on every packaging path. Product-scope gaps: [known-limitations.md](./known-limitations.md).

| Area | Status |
| --- | --- |
| Schema | Alembic migrations through `20261021_0009`. `/health` reports the code head and `/ready` checks that the database matches it. |
| Auth | Cookie session, Bearer API keys, CSRF on unsafe methods, and a per-client failed-login limit. All secrets are required; `--data-dir` generates them per install. |
| Sync | IMAP (TLS by default), Gmail and Graph providers, with leases and fencing tokens. Metadata pages are applied in batches. Delta pages use last-change-wins. Rate limits re-queue the job with backoff. Provider depth and edge cases still tracked in code/tests, not “done forever”. |
| Jobs | `SKIP LOCKED` claim, dedupe keys, exponential backoff, and bounded reclaim of stale claims. The worker poll adapts to queue depth. |
| Remote write-back | Read, flag and trash go through idempotent `remote_operations` with reconciliation. |
| Storage | Content-addressed blobs in the streaming AES-GCM `KKMS` format, verified on read. Key rotation re-wraps blobs. Garbage collection is reference-counted. |
| Credentials | `credential_secrets` table, encrypted with a key derived from the blob keyring. `env:` refs are read-only. |
| Realtime | Transactional outbox, LISTEN/NOTIFY, a single dispatcher, and SSE fan-out. |
| Read API | Unified inbox (opaque cursor), hydrated search with a total, message detail, and streamed attachments. Contract: [`docs/openapi.json`](./openapi.json) / [api.md](./api.md). |
| Backup | `KKBK` packages under a separate backup key. A restore drill script is provided. |
| Desktop orchestration | When PostgreSQL binaries exist (vendor or `PATH`), Electron starts PG → `python -m mail_core --data-dir` (migrate + API + embedded worker) on loopback with per-install secrets. Without binaries the app refuses to start (`stub` is fatal). |
| Desktop packaging (M6) | **Partial.** Linux AppImage/deb scaffold + vendored PG fetch script exist. macOS/Windows packages are unsigned and need build-time PG binaries (see known-limitations). Not notarized / store-ready. |
| OpenAPI → TS | Implemented: `docs/openapi.json` + `frontend/src/api/generated/`. Drift checked **locally** (`openapi:check` / pytest); **no** GitHub CI. |
| Tests | `tests/mail_core/` (pytest, PostgreSQL) and `frontend/src/**/*.test.ts(x)` (vitest). No browser end-to-end suite. **No GitHub Actions** in this repository — run locally per `AGENTS.md`. |
