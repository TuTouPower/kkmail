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


## SPA bridge (optional)

Enable the experimental mail-core inbox panel in the React SPA:

```bash
# frontend/.env.local
VITE_MAIL_CORE=1
# optional absolute base; default uses Vite proxy /mail-core → :8000
# VITE_MAIL_CORE_BASE=http://127.0.0.1:8000
```

Flask default mail UI remains unchanged when the flag is off.
