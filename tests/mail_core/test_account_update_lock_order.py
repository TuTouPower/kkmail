"""R16 regression: account updates must take the sidebar (organization)
advisory lock BEFORE the Account row lock.

Review evidence (review_20261026_commits, R16): ``update_account_app`` used
to read ``prior_sync_enabled`` with ``SELECT ... FOR UPDATE`` on the Account
row before anything else. A combined PATCH (sync preference + group move)
then tried to take the sidebar advisory lock inside ``update_account``,
while layout/organization transactions take sidebar -> Account. The two
orders deadlock on real PostgreSQL (SQLSTATE 40P01).

The unit tests below run the real application service
(``update_account_app``) and the real account service (``update_account``)
against an instrumented session at the DB boundary: the session records
the order in which the production code executes the advisory-lock
statement and the ``FOR UPDATE`` account query. The invariant that
prevents the deadlock is that the first sidebar advisory acquisition
precedes the first Account row lock; later advisory executions in the
same transaction are re-acquisitions of a lock the session already holds
and cannot block.

The PG test at the bottom reproduces the original two-transaction
competition against a real database and only runs under the project's
PG test runtime (it skips in unit mode, where no PostgreSQL is available).
"""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest

from mail_core.accounts import service as account_service
from mail_core.mail.application import accounts as accounts_app
from mail_core.mail.storage.models import Account


class _ScalarsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class InstrumentedSession:
    """Session test double that records lock acquisition order.

    It implements just the surface ``update_account_app`` /
    ``update_account`` use, dispatching ``scalar`` on the real SQL the
    production code builds so the real service logic runs end to end.
    """

    def __init__(self, account: Account, group_id: uuid.UUID | None = None):
        self.account = account
        self.group = SimpleNamespace(id=group_id) if group_id is not None else None
        self.events: list[str] = []
        self.added: list[object] = []
        self.committed = False
        self.rolled_back = False

    # context-manager protocol used by the application services
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, *args, **kwargs):
        if "pg_advisory_xact_lock" in str(statement):
            self.events.append("sidebar_advisory_lock")
        return SimpleNamespace(first=lambda: None, scalar=lambda: None)

    def scalar(self, statement, *args, **kwargs):
        sql = str(statement).lower()
        if "from account_groups" in sql and "for update" in sql:
            self.events.append("group_row_lock")
            return self.group
        if "from accounts" in sql and "for update" in sql:
            self.events.append("account_row_lock")
            return self.account
        if "max(" in sql:
            return None
        return None

    def scalars(self, statement, *args, **kwargs):
        return _ScalarsResult([])

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _account(*, sync_enabled: bool = True) -> Account:
    return Account(
        id=uuid.uuid4(),
        email="lock-order@example.test",
        provider="graph",
        display_name="Lock Order",
        credential_ref=None,
        group_id=None,
        master_order=None,
        group_order=None,
        sync_enabled=sync_enabled,
        sync_status="idle",
        config={},
    )


def _install_session(monkeypatch, session: InstrumentedSession) -> None:
    monkeypatch.setattr(accounts_app, "get_session_factory", lambda: lambda: session)


def _assert_sidebar_before_account(session: InstrumentedSession) -> None:
    assert "sidebar_advisory_lock" in session.events, session.events
    assert "account_row_lock" in session.events, session.events
    first_sidebar = session.events.index("sidebar_advisory_lock")
    first_account = session.events.index("account_row_lock")
    assert first_sidebar < first_account, session.events


def test_combined_sync_and_group_update_locks_sidebar_before_account(monkeypatch):
    group_id = uuid.uuid4()
    session = InstrumentedSession(_account(sync_enabled=True), group_id=group_id)
    _install_session(monkeypatch, session)

    dto = accounts_app.update_account_app(
        session.account.id,
        sync_enabled=False,
        group_id=group_id,
    )

    _assert_sidebar_before_account(session)
    # prior_sync_enabled must be read inside the locked transaction: the
    # True -> False flip is what produces the ACCOUNT_UPDATED outbox event.
    assert dto.sync_enabled is False
    assert dto.group_id == str(group_id)
    outbox_events = [obj for obj in session.added if obj.__class__.__name__ == "OutboxEvent"]
    assert len(outbox_events) == 1
    assert outbox_events[0].payload == {"sync_enabled": False}
    assert session.committed is True


def test_sync_preference_only_update_locks_sidebar_before_prior_read(monkeypatch):
    session = InstrumentedSession(_account(sync_enabled=True))
    _install_session(monkeypatch, session)

    dto = accounts_app.update_account_app(session.account.id, sync_enabled=False)

    # Even without any organization change, the entry must not grab the
    # Account row lock for the prior_sync_enabled snapshot before the
    # sidebar advisory lock (R16 / repair design section 10).
    _assert_sidebar_before_account(session)
    assert dto.sync_enabled is False
    outbox_events = [obj for obj in session.added if obj.__class__.__name__ == "OutboxEvent"]
    assert len(outbox_events) == 1
    assert outbox_events[0].payload == {"sync_enabled": False}


def test_oauth_update_locks_sidebar_then_account_then_flow(monkeypatch):
    from mail_core.accounts import oauth_flow

    group_id = uuid.uuid4()
    session = InstrumentedSession(_account(sync_enabled=True), group_id=group_id)
    _install_session(monkeypatch, session)

    def fake_consume(sess, *, account, flow_id, principal, config_patch, group_id):
        session.events.append("oauth_consume")
        assert account is session.account
        return {}

    monkeypatch.setattr(oauth_flow, "consume_oauth_flow_for_reauthorize", fake_consume)

    dto = accounts_app.update_account_app(
        session.account.id,
        sync_enabled=False,
        group_id=group_id,
        oauth_flow_id="flow-1",
        principal=None,
    )

    _assert_sidebar_before_account(session)
    assert session.events.index("account_row_lock") < session.events.index("oauth_consume")
    assert dto.sync_enabled is False
    assert session.committed is True


def test_service_update_account_locks_sidebar_before_account_without_group_change():
    session = InstrumentedSession(_account(sync_enabled=True))

    acc = account_service.update_account(session, session.account.id, sync_enabled=False)

    _assert_sidebar_before_account(session)
    assert acc.sync_enabled is False


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set (PG lock-order competition requires real PostgreSQL)",
)
def test_combined_patch_vs_sidebar_first_transaction_no_deadlock_pg(monkeypatch):
    """Real-PG competition: combined PATCH vs a sidebar -> Account txn.

    The competing transaction uses the exact lock sequence of
    ``save_sidebar_layout`` (sidebar advisory lock, then Account row).
    On the pre-fix code the combined PATCH held the Account row (from the
    prior_sync_enabled read) while waiting for the sidebar lock, so
    PostgreSQL aborted one side with SQLSTATE 40P01.
    """
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from sqlalchemy import select

    from mail_core.accounts.service import lock_sidebar_layout
    from mail_core.db.session import get_session_factory

    account = accounts_app.create_account_app(
        email=f"lock-order-{uuid.uuid4().hex[:8]}@example.test",
        provider="graph",
        config={"oauth_client_type": "public"},
        credentials={"client_id": "cid", "refresh_token": "rt"},
    )
    group = accounts_app.create_group_app(name=f"lock-order-{uuid.uuid4().hex[:8]}")
    account_id = uuid.UUID(account.id)
    group_id = uuid.UUID(group.id)

    original_update = accounts_app.update_account
    entered_service = Event()
    release_service = Event()

    def gated_update(*args, **kwargs):
        entered_service.set()
        assert release_service.wait(10)
        return original_update(*args, **kwargs)

    monkeypatch.setattr(accounts_app, "update_account", gated_update)

    def combined_patch():
        try:
            accounts_app.update_account_app(account_id, sync_enabled=False, group_id=group_id)
            return "ok"
        except Exception as exc:  # deadlock surfaces as an exception name
            return f"{type(exc).__name__}: {exc}".splitlines()[0]

    def sidebar_first_transaction():
        try:
            Session = get_session_factory()
            with Session() as session:
                lock_sidebar_layout(session)
                row = session.scalar(
                    select(Account).where(Account.id == account_id).with_for_update()
                )
                assert row is not None
                session.commit()
            return "ok"
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}".splitlines()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        patch_future = pool.submit(combined_patch)
        assert entered_service.wait(10)
        sidebar_future = pool.submit(sidebar_first_transaction)
        # Give the competing transaction time to reach its blocking lock,
        # then let the PATCH proceed into update_account.
        time.sleep(2)
        release_service.set()
        results = [patch_future.result(20), sidebar_future.result(20)]

    assert results == ["ok", "ok"], results
    Session = get_session_factory()
    with Session() as session:
        row = session.get(Account, account_id)
        assert row is not None
        assert row.group_id == group_id
        assert row.sync_enabled is False
