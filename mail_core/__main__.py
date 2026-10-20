"""python -m mail_core — print how to run API + worker (primary entrypoints)."""

from __future__ import annotations


def main() -> None:
    print(
        "kkmail mail-core\n"
        "  API:    uvicorn mail_core.api.app:app --host 127.0.0.1 --port 8000\n"
        "  Worker: python -m mail_core.worker.main\n"
        "Required env: MAIL_CORE_SECRET_KEY, MAIL_CORE_LOGIN_PASSWORD_HASH|LOGIN_PASSWORD,\n"
        "              MAIL_CORE_BLOB_KEY_V1|MAIL_CORE_BLOB_KEYS, MAIL_CORE_DATABASE_URL\n"
        "See docs/mail-core-architecture.md and docker-compose.mail-core.yml."
    )


if __name__ == "__main__":
    main()
