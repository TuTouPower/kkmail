"""A130: current attempt is decided by ledger order of attempt_reserved,
not by (attempt, execution_id) lexicographic sorting."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from repo_task.attempts import attempts_for_tid, current_attempt_record, current_identity


def _reserved(attempt, exec_id):
    return {"event": "attempt_reserved", "tid": "t001", "attempt": attempt,
            "execution_id": exec_id, "executor": "inline", "state": "running"}


def test_current_is_last_reserved_when_hex_order_disagrees():
    # Same attempt number, two identities: lexicographically larger id ("f...")
    # is reserved first, smaller id ("0...") last. Current must be the last
    # reserved in ledger order, not the lexicographic maximum.
    events = [_reserved(1, "f" * 32), _reserved(1, "0" * 32)]
    assert current_identity("t001", events) == (1, "0" * 32)
    assert [r["execution_id"] for r in attempts_for_tid("t001", events)] == ["f" * 32, "0" * 32]


def test_current_follows_reserved_order_across_attempt_numbers():
    # attempt 2 reserved before attempt 1 in the ledger (corrupt/reordered
    # history): current follows the last attempt_reserved position.
    events = [_reserved(2, "a" * 32), _reserved(1, "b" * 32)]
    record = current_attempt_record("t001", events)
    assert record is not None and record["attempt"] == 1
    assert [r["attempt"] for r in attempts_for_tid("t001", events)] == [2, 1]
