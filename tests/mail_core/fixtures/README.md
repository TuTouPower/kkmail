# mail-core L2 fixtures

| Path | Role |
|---|---|
| `dovecot/` | Alpine Dovecot image + seeded Maildir (`alice@kkmail.test` / `alice-imap-pass`) |
| `maildir/` | Same mailbox layout for pymap fallback |

```bash
docker compose -f docker-compose.mail-core.yml up -d --build imap
# or
./scripts/start-mail-core-imap.sh
export MAIL_CORE_IMAP_PORT=1143
pytest tests/mail_core/test_imap_provider_live.py -q
```
