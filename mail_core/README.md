# mail-core

Greenfield mail kernel for kkmail. Spec: [`docs/mail-core-architecture.md`](../docs/mail-core-architecture.md).

## Dev quick start

```bash
pip install -r requirements-mail-core.txt
docker compose -f docker-compose.mail-core.yml up -d postgres
export MAIL_CORE_DATABASE_URL=postgresql+psycopg://kkmail:kkmail@127.0.0.1:5433/kkmail_mail
alembic -c mail_core/db/alembic.ini upgrade head
uvicorn mail_core.api.app:app --reload --port 8000
python -m mail_core.worker.main
```

Legacy Flask app is unchanged; see `docs/mail-core-cutover.md`.
