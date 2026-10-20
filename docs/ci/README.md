# CI workflow templates

| Template | Install as | Job | Runs |
| --- | --- | --- | --- |
| `mail-core.workflow.yml` | `.github/workflows/tests.yml` | `mail-core` | PostgreSQL 16 service, a Dovecot IMAP fixture, and `scripts/run-mail-core-tests.sh` (generates per-run keys, `alembic upgrade head`, then the full `pytest tests` with `MAIL_CORE_REQUIRE_DB=1`, so DB-backed tests error instead of skipping) |
| `frontend.workflow.yml` | `.github/workflows/frontend.yml` | `check` | `npm ci`, `oxlint --deny-warnings`, `tsc -b`, `vitest` (unit and jsdom component tests), and `vite build` |

Copy a template to its install path unchanged; keep the two copies identical when either changes.

To run the same checks locally:

```bash
export MAIL_CORE_DATABASE_URL=postgresql+psycopg://<user>:<pass>@127.0.0.1:5433/<test-db>
./scripts/run-mail-core-tests.sh
cd frontend && npm ci && npm run lint && npx tsc -b && npm test && npm run build
```
