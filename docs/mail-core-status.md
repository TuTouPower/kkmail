# mail-core implementation status

Spec: [mail-core-architecture.md](./mail-core-architecture.md). This page lists what is implemented against that spec. Product-scope gaps are in [known-limitations.md](./known-limitations.md).

| Area | Status |
| --- | --- |
| Schema | Alembic migrations through `20261021_0007`. `/health` reports the code head and `/ready` checks that the database matches it. |
| Auth | Cookie session, Bearer API keys, CSRF on unsafe methods, and a per-client failed-login limit. All secrets are required; `--data-dir` generates them per install. |
| Sync | IMAP (TLS by default), Gmail and Graph providers, with leases and fencing tokens. Metadata pages are applied in batches. Delta pages use last-change-wins. Rate limits re-queue the job with backoff. |
| Jobs | `SKIP LOCKED` claim, dedupe keys, exponential backoff, and bounded reclaim of stale claims. The worker poll adapts to queue depth. |
| Remote write-back | Read, flag and trash go through idempotent `remote_operations` with reconciliation. |
| Storage | Content-addressed blobs in the streaming AES-GCM `KKMS` format, verified on read. Key rotation re-wraps blobs. Garbage collection is reference-counted. |
| Credentials | `credential_secrets` table, encrypted with a key derived from the blob keyring. `env:` refs are read-only. |
| Realtime | Transactional outbox, LISTEN/NOTIFY, a single dispatcher, and SSE fan-out. |
| Read API | Unified inbox (opaque cursor), hydrated search with a total, message detail, and streamed attachments. |
| Backup | `KKBK` packages under a separate backup key. A restore drill script is provided. |
| Desktop | Electron starts a loopback PostgreSQL (SCRAM, random password) and the `python -m mail_core` sidecar, with per-install secrets. |
| CI templates | `docs/ci/*.workflow.yml`: PostgreSQL-backed pytest with no DB skips, and frontend lint, `tsc -b`, vitest and build. |
| Tests | `tests/mail_core/` (pytest, PostgreSQL) and `frontend/src/**/*.test.ts(x)` (vitest, including jsdom component tests). No browser end-to-end suite. |
