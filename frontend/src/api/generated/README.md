# Generated OpenAPI types

`schema.ts` is produced from `docs/openapi.json` by `openapi-typescript`.

Do not edit by hand. Regenerate:

```bash
# from repo root
scripts/gen-openapi.sh
# or
python scripts/export_openapi.py
cd frontend && npm run openapi:gen
```

Local drift checks (no GitHub CI):

```bash
python scripts/export_openapi.py --check
cd frontend && npm run openapi:check
pytest tests/mail_core/test_openapi_contract.py
```
