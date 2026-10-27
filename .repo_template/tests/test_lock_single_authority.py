"""A33: 锁原语单一权威——ledger/integration 不得再各存一份 fcntl/msvcrt 副本。

locks.py 头注自述已「消除多处重复」；本套断言该自述与实现对齐：
两处只准 import locks.lock_fh/unlock_fh，本地副本必须消失，且锁行为
经由 locks 的实现真实可用。
"""
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from repo_task import integration, ledger, locks

pytestmark = pytest.mark.contract


def test_ledger_has_no_local_lock_copy():
    assert not hasattr(ledger, "_ledger_lock_fh")
    assert not hasattr(ledger, "_ledger_unlock_fh")


def test_integration_has_no_local_lock_copy():
    assert not hasattr(integration, "_lock_fh")


def test_ledger_and_integration_use_locks_module_functions():
    assert ledger.lock_fh is locks.lock_fh
    assert ledger.unlock_fh is locks.unlock_fh
    assert integration.lock_fh is locks.lock_fh
    assert integration.unlock_fh is locks.unlock_fh


def test_locks_roundtrip_on_real_file(tmp_path):
    fh_path = tmp_path / "probe.lock"
    with fh_path.open("a+", encoding="utf-8") as fh:
        fh.write("\0")
        fh.flush()
        locks.lock_fh(fh)
        locks.unlock_fh(fh)
