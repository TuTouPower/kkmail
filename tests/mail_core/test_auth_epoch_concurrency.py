"""R02 regression: concurrent session-epoch increments must never lose one.

_persist_db_password_hash (password change) and invalidate_all_sessions
(logout) both do a read-modify-write of AuthCredential.session_epoch. The
review reproduced on real PostgreSQL: password change reads epoch=N, a
logout commits epoch=N+1 and a session is issued against it, then the
password change writes its stale N+1 — the pre-change session stays valid
after the password changed. Both paths now take the credential row lock
(with_for_update) so increments serialize.

The interleave is made deterministic by gating try_notify_session_revocation,
which both functions call after computing the new epoch but before commit:
the first caller parks there holding its transaction open while the second
increment runs.
"""

from __future__ import annotations

import os
import threading

import pytest

from mail_core.security import auth as auth_mod

DATABASE_URL = os.environ.get("MAIL_CORE_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="MAIL_CORE_DATABASE_URL not set")

_SEED_EPOCH = 10


@pytest.fixture(autouse=True)
def _seed_credential():
    auth_mod.reset_auth_caches()
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage.models import AuthCredential

    Session = get_session_factory()
    with Session() as session:
        cred = session.get(AuthCredential, "default")
        if cred is None:
            session.add(
                AuthCredential(id="default", login_password_hash="seed", session_epoch=_SEED_EPOCH)
            )
        else:
            cred.login_password_hash = "seed"
            cred.session_epoch = _SEED_EPOCH
        session.commit()
    yield
    auth_mod.reset_auth_caches()


def _db_epoch() -> int:
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage.models import AuthCredential

    Session = get_session_factory()
    with Session() as session:
        cred = session.get(AuthCredential, "default")
        assert cred is not None
        return int(cred.session_epoch)


class _NotifyGate:
    """Park the first notify caller until released; pass the rest through."""

    def __init__(self, monkeypatch):
        self.entered = threading.Event()
        self.release = threading.Event()
        self._count = 0
        self._lock = threading.Lock()
        from mail_core.realtime.notify import try_notify_session_revocation as real_notify

        self._real = real_notify

        def gated(session, epoch):
            with self._lock:
                self._count += 1
                first = self._count == 1
            if first:
                self.entered.set()
                assert self.release.wait(timeout=30), "test gate timed out"
            return self._real(session, epoch)

        monkeypatch.setattr(
            "mail_core.realtime.notify.try_notify_session_revocation", gated
        )


def _run_interleaved(monkeypatch, first, second):
    gate = _NotifyGate(monkeypatch)
    errors: list[BaseException] = []

    def run(fn):
        try:
            fn()
        except BaseException as exc:  # surfaced by assertions below
            errors.append(exc)

    t1 = threading.Thread(target=run, args=(first,))
    t1.start()
    assert gate.entered.wait(timeout=30), "first increment never reached notify"
    t2 = threading.Thread(target=run, args=(second,))
    t2.start()
    # Give the second increment time to either finish (pre-fix) or block on
    # the credential row lock (post-fix), then let the first one commit.
    t2.join(timeout=1.0)
    gate.release.set()
    t1.join(timeout=30)
    t2.join(timeout=30)
    assert not t1.is_alive() and not t2.is_alive(), "increment threads did not finish"
    assert not errors, f"increment raised: {errors!r}"


def test_password_change_and_logout_do_not_lose_epoch_increment(monkeypatch):
    _run_interleaved(
        monkeypatch,
        first=lambda: auth_mod._persist_db_password_hash("new-hash", increment_epoch=True),
        second=lambda: auth_mod.invalidate_all_sessions(),
    )
    assert _db_epoch() == _SEED_EPOCH + 2


def test_two_logouts_do_not_lose_epoch_increment(monkeypatch):
    _run_interleaved(
        monkeypatch,
        first=lambda: auth_mod.invalidate_all_sessions(),
        second=lambda: auth_mod.invalidate_all_sessions(),
    )
    assert _db_epoch() == _SEED_EPOCH + 2
