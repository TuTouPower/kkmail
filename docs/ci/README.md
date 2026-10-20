# CI workflows

| Workflow | Job | Runs |
| --- | --- | --- |
| `.github/workflows/tests.yml` | `mail-core` | PostgreSQL 16 service, a Dovecot IMAP fixture, and `scripts/run-mail-core-tests.sh` (migrate, then the full `pytest tests` with `MAIL_CORE_REQUIRE_DB=1`) |
| `.github/workflows/frontend.yml` | `check` | `oxlint`, `tsc -b`, `vitest` (unit and jsdom component tests), and `vite build` |

The `*.workflow.yml` files in this directory mirror the `.github/workflows` files above. Change them together.

To run the same checks locally:

```bash
export MAIL_CORE_DATABASE_URL=postgresql+psycopg://<user>:<pass>@127.0.0.1:5433/<test-db>
./scripts/run-mail-core-tests.sh
cd frontend && npm ci && npm run lint && npx tsc -b && npm test && npm run build
```
