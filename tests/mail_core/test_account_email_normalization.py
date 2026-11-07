from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from mail_core.accounts.service import create_account
from mail_core.mail.storage.models import Account


def test_account_creation_normalizes_email_before_persistence(monkeypatch):
    import mail_core.accounts.connection as connection

    monkeypatch.setattr(connection, "validate_connection", lambda *_args, **_kwargs: None)

    class Session:
        def __init__(self):
            self.added = []

        def execute(self, _statement):
            return None

        def scalar(self, _statement):
            return None

        def add(self, account):
            self.added.append(account)

        def flush(self):
            return None

    session = Session()
    account = create_account(
        session,
        email="  Karson.Example@Example.COM  ",
        provider="imap",
    )

    assert account.email == "karson.example@example.com"
    assert session.added == [account]


def test_account_metadata_has_unique_lower_email_index():
    index = next(index for index in Account.__table__.indexes if index.name == "uq_accounts_email_lower")

    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    assert ddl == "CREATE UNIQUE INDEX uq_accounts_email_lower ON accounts (lower(email))"
