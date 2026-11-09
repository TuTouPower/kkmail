"""A13: real-PostgreSQL, two-process session-revocation verification.

Two genuinely independent OS processes (``subprocess`` -> ``python -c``) each
build their own SQLAlchemy engine / session factory via the real production
path ``mail_core.db.session.get_session_factory()`` and share only
``MAIL_CORE_DATABASE_URL``. Process B issues and validates a session, process A
commits ``invalidate_all_sessions()`` (real DB epoch increment), and process B
then re-validates the *same* cookie. No NOTIFY/LISTEN channel is ever opened by
B, and the orchestrating parent only writes a barrier file that carries no
epoch, session, or auth state, so B's rejection is driven solely by
``read_session()`` re-querying the authoritative DB epoch.

Covered here:
  * NOTIFY lost (suppressed entirely) -> REST still rejects;
  * NOTIFY duplicated / out of order / repeated invalidations -> REST still rejects;
  * SSE disconnected (B starts no listener and no SSE subscription; A's local
    dispatcher has no subscribers, so local stream closing is a no-op);
  * DB unavailable -> fail-closed, never falling back to the in-process epoch.

Lesson from the previous A13 batch (implementation commit 7a010f21): an
existing assertion was flipped in place inside the implementation commit
instead of adding a separate test for the new semantics. That violates this
repo's TDD rule: when an implementation change invalidates an old test's
semantics, ADD a new independent test for the new semantics and either keep
the old test untouched or delete it wholesale with a written retirement
reason -- NEVER edit the old expectation in place. This module therefore adds
only NEW tests over the real production path (mail_core.security.auth); the old
FakeSession-based impersonation of cross-process revocation is retired (not
rewritten) in test_auth_plan_a_db.py.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = str(REPO_ROOT / "src")

# Deliberately different from reset_auth_caches()'s in-process default of 1:
# proves issue_session()/read_session() consult the real DB epoch, not a local
# constant or a cached value.
_SEED_EPOCH = 7
_DEFAULT_SESSION_MAX_AGE = str(60 * 60 * 24 * 30)

# Scripts are top-level strings executed via ``python -c`` in fresh processes;
# they are indented at column 0 on purpose. A13_SRC_DIR is inserted into
# sys.path so a child never depends on the parent's cwd.
_B_PROCESS_SCRIPT = r'''
import json
import os
import sys
import time

sys.path.insert(0, os.environ["A13_SRC_DIR"])

from mail_core.realtime import listener as listener_module
from mail_core.security.auth import (
    get_session_epoch,
    issue_session,
    read_session,
    reset_auth_caches,
)

phase1_path = os.environ["A13_PHASE1_PATH"]
flag_path = os.environ["A13_REVOKE_FLAG_PATH"]
result_path = os.environ["A13_RESULT_PATH"]
seed_epoch = int(os.environ["A13_SEED_EPOCH"])
deadline_s = float(os.environ["A13_DEADLINE_S"])

reset_auth_caches()

# Constructive proof that B receives no revocation notice: it starts no
# LISTEN/NOTIFY listener and no SSE subscription at all.
assert getattr(listener_module, "_listener", None) is None, (
    "process B must not run an outbox/revocation listener"
)

cookie, csrf = issue_session()
first = read_session(cookie)
assert first is not None, "freshly issued session must validate before revocation"
assert first["epoch"] == seed_epoch, first
assert first["csrf"] == csrf, first

with open(phase1_path, "w", encoding="utf-8") as handle:
    json.dump({"cookie": cookie, "first_epoch": first["epoch"]}, handle)

# The flag is only a test barrier; it carries no epoch/session/auth state and B
# never reads its contents. While waiting, B holds no NOTIFY channel and no
# local epoch cache that could be "notified".
deadline = time.monotonic() + deadline_s
while not os.path.exists(flag_path):
    if time.monotonic() > deadline:
        raise SystemExit("process B timed out waiting for the revocation barrier")
    time.sleep(0.02)

second = read_session(cookie)
epoch_after = get_session_epoch()
with open(result_path, "w", encoding="utf-8") as handle:
    json.dump({"second": second, "epoch_after": epoch_after}, handle)
'''

_A_NO_NOTIFY_SCRIPT = r'''
import os
import sys

sys.path.insert(0, os.environ["A13_SRC_DIR"])

from unittest.mock import patch

from mail_core.security.auth import invalidate_all_sessions, reset_auth_caches

reset_auth_caches()

# Simulate a completely lost NOTIFY: the real production path still commits the
# authoritative epoch increment, but pg_notify is suppressed entirely. B has no
# listener either way, so REST rejection must come only from re-reading the DB.
with patch(
    "mail_core.realtime.notify.try_notify_session_revocation",
    lambda session, epoch: None,
):
    invalidate_all_sessions()
'''

_A_DUPLICATE_OUT_OF_ORDER_SCRIPT = r'''
import os
import sys

sys.path.insert(0, os.environ["A13_SRC_DIR"])

from unittest.mock import patch

from mail_core.realtime import notify as notify_module
from mail_core.security.auth import invalidate_all_sessions, reset_auth_caches

reset_auth_caches()
real_notify = notify_module.try_notify_session_revocation


def noisy_notify(session, epoch):
    # Deliberately duplicated and out-of-order payloads on the same channel.
    for payload in (999, 1, epoch, epoch, 2):
        notify_module.notify_session_revocation(session, payload)
    return real_notify(session, epoch)


with patch(
    "mail_core.realtime.notify.try_notify_session_revocation", noisy_notify
):
    # Two invalidations: repeated revocations / repeated notifications.
    invalidate_all_sessions()
    invalidate_all_sessions()
'''

_DB_FAILURE_SCRIPT = r'''
import os
import sys

sys.path.insert(0, os.environ["A13_SRC_DIR"])

from mail_core.security.auth import (
    AuthConfigError,
    get_session_epoch,
    read_session,
    reset_auth_caches,
)

cookie = os.environ["A13_COOKIE"]

reset_auth_caches()
# reset_auth_caches() sets the in-process _session_epoch to 1, which is exactly
# the epoch embedded in `cookie`. If the implementation wrongly fell back to
# that cached value when the DB query fails, BOTH assertions below would fail.
try:
    value = get_session_epoch()
except AuthConfigError:
    pass
else:
    raise AssertionError("DB failure must fail closed, not return epoch %r" % (value,))

assert read_session(cookie) is None, (
    "DB failure must not fall back to the in-process epoch and admit the old cookie"
)
'''


def _child_env(overrides: dict | None = None) -> dict:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.environ.get("PYTHONPATH") or SRC_DIR,
        "MAIL_CORE_DATABASE_URL": os.environ["MAIL_CORE_DATABASE_URL"],
        "MAIL_CORE_SECRET_KEY": os.environ.get(
            "MAIL_CORE_SECRET_KEY", "a13-multiprocess-test-secret-key"
        ),
        "MAIL_CORE_SESSION_MAX_AGE": os.environ.get(
            "MAIL_CORE_SESSION_MAX_AGE", _DEFAULT_SESSION_MAX_AGE
        ),
        "A13_SRC_DIR": SRC_DIR,
        "A13_DEADLINE_S": "30",
    }
    if overrides:
        env.update(overrides)
    return env


def _seed_credential(epoch: int) -> None:
    """Write only the single 'default' row this suite owns; never TRUNCATE."""
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage.models import AuthCredential

    Session = get_session_factory()
    with Session() as session:
        cred = session.get(AuthCredential, "default")
        if cred is None:
            session.add(
                AuthCredential(
                    id="default",
                    login_password_hash="a13-multiprocess-seed-hash",
                    session_epoch=epoch,
                )
            )
        else:
            cred.login_password_hash = "a13-multiprocess-seed-hash"
            cred.session_epoch = epoch
        session.commit()


def _db_epoch() -> int:
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage.models import AuthCredential

    Session = get_session_factory()
    with Session() as session:
        cred = session.get(AuthCredential, "default")
        assert cred is not None
        return int(cred.session_epoch)


def _wait_for_file(path: Path, process=None, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process is not None and process.poll() is not None:
            _, stderr = process.communicate()
            raise AssertionError(
                f"child exited before writing {path.name}: {stderr}"
            )
        time.sleep(0.02)
    raise AssertionError(f"timed out waiting for {path.name}")


def _run_two_process_scenario(
    tmp_path: Path, a_script: str, expected_epoch: int
) -> str:
    """Orchestrate B (long-lived) and A (short-lived) as independent processes.

    The parent never participates in authentication; it only seeds the DB,
    launches the two children, and writes a barrier file. Returns B's cookie.
    """
    phase1 = tmp_path / "phase1.json"
    flag = tmp_path / "revoked.flag"
    result = tmp_path / "result.json"
    env = _child_env(
        {
            "A13_PHASE1_PATH": str(phase1),
            "A13_REVOKE_FLAG_PATH": str(flag),
            "A13_RESULT_PATH": str(result),
            "A13_SEED_EPOCH": str(_SEED_EPOCH),
        }
    )

    _seed_credential(_SEED_EPOCH)
    assert _db_epoch() == _SEED_EPOCH

    process_b = subprocess.Popen(
        [sys.executable, "-c", _B_PROCESS_SCRIPT],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_file(phase1, process_b)
        phase1_data = json.loads(phase1.read_text(encoding="utf-8"))
        assert phase1_data["first_epoch"] == _SEED_EPOCH

        process_a = subprocess.run(
            [sys.executable, "-c", a_script],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert process_a.returncode == 0, process_a.stderr

        # Barrier only: carries no epoch/session/auth state; B never reads it.
        flag.write_text("continue", encoding="utf-8")

        _wait_for_file(result, process_b)
        _, stderr = process_b.communicate(timeout=30)
        assert process_b.returncode == 0, stderr
        data = json.loads(result.read_text(encoding="utf-8"))
        assert data["second"] is None
        assert data["epoch_after"] == expected_epoch
        assert _db_epoch() == expected_epoch
        return phase1_data["cookie"]
    finally:
        if process_b.poll() is None:
            process_b.terminate()
            try:
                process_b.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process_b.kill()
                process_b.communicate(timeout=5)


def test_cross_process_revocation_rejects_without_any_notify(tmp_path):
    """A13 core: A commits epoch increment with NOTIFY fully suppressed;
    B, holding an already-validated cookie and no listener, must reject it."""
    cookie = _run_two_process_scenario(
        tmp_path, _A_NO_NOTIFY_SCRIPT, expected_epoch=_SEED_EPOCH + 1
    )
    from mail_core.security.auth import read_session

    # A third, independent view (the orchestrating process) also sees the
    # revoked session, confirming the DB epoch is the sole authority.
    assert read_session(cookie) is None


def test_duplicate_and_out_of_order_notify_does_not_change_rest_rejection(tmp_path):
    """Repeated/out-of-order/repeated-invalidation NOTIFY noise never weakens
    REST rejection; only the committed DB epoch matters."""
    _run_two_process_scenario(
        tmp_path,
        _A_DUPLICATE_OUT_OF_ORDER_SCRIPT,
        expected_epoch=_SEED_EPOCH + 2,
    )


def test_db_failure_fails_closed_without_falling_back_to_in_process_epoch():
    """DB unavailable must fail closed, never admit a cookie via the cached
    in-process epoch (which is deliberately equal to the cookie's epoch)."""
    from mail_core.security.auth import issue_session, reset_auth_caches

    _seed_credential(1)
    reset_auth_caches()
    cookie, _ = issue_session()

    dead_url = (
        "postgresql+psycopg://kkmail:kkmail@127.0.0.1:1/"
        "kkmail_test_dead?connect_timeout=2"
    )
    env = _child_env(
        {
            "A13_COOKIE": cookie,
            "MAIL_CORE_DATABASE_URL": dead_url,
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", _DB_FAILURE_SCRIPT],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
