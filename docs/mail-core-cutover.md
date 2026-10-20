# mail-core cutover plan (early phases)

Legacy Flask (`web_outlook_app.py`) remains the runnable product UI/API on
`:5000` / Docker `:5080` until mail-core reaches M1 local-authority.

| Phase | Legacy | mail-core |
|---|---|---|
| Skeleton / schema | Unchanged; keep shipping | New `mail_core/` package + `docker-compose.mail-core.yml` (PG :5433) |
| Sync / providers | Still owns live IMAP/Graph reads | Builds greenfield PG + blob; no dual-write of old cache |
| Cutover | Retire mail-list paths | SPA points at FastAPI; accounts/settings migrated at high level only |

Do **not** treat the old SQLite mail cache as a source of truth.
