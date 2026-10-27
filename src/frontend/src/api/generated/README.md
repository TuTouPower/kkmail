# Generated OpenAPI types

`schema.ts` is produced from `schemas/openapi.json` by `openapi-typescript`.

Do not edit by hand.

## Authoritative regeneration path (the only one)

```bash
# from repo root
scripts/gen-openapi.sh
```

This script is the single authoritative chain: it first exports the backend
OpenAPI document to `schemas/openapi.json` (`scripts/export_openapi.py`) and
then generates `schema.ts` from that JSON (`npm run openapi:gen`). Those two
commands are steps of the chain, not alternative regeneration paths — do not
run them piecemeal to "regenerate", or the JSON and the TypeScript types can
be produced from different source states and silently drift apart (A150).

Local drift checks (read-only; they verify, they do not regenerate):

```bash
python scripts/export_openapi.py --check
(cd src/frontend && npm run openapi:check)
pytest tests/mail_core/test_openapi_contract.py
```
