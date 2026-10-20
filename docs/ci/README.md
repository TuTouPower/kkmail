# CI workflow templates

GitHub Actions under `.github/workflows/` may be blocked for agents without
`workflows` scope. Keep the desired workflows here and copy them into
`.github/workflows/` in a human PR.

| Template | Purpose |
| --- | --- |
| `mail-core.workflow.yml` | Postgres service + `tests/mail_core` pytest |
| `frontend.workflow.yml` | `oxlint` + `tsc` + vitest + production build |

Local equivalents:

```bash
./scripts/run-mail-core-tests.sh
cd frontend && npm ci && npm run lint && npx tsc -b && npm test && npm run build
```
