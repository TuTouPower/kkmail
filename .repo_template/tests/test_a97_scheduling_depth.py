"""A97: _dependency_cycle must not crash with RecursionError on deep chains."""
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from repo_task.scheduling import _dependency_cycle


def _chain(depth: int, *, cycle: bool = False) -> dict[str, list[str]]:
    deps = {f"t{i:05d}": [f"t{i + 1:05d}"] for i in range(depth)}
    deps[f"t{depth:05d}"] = ["t00000"] if cycle else []
    return deps


def test_a97_deep_acyclic_chain_beyond_recursion_limit():
    # Depth far beyond the default recursion limit (1000): the old
    # recursive DFS raised RecursionError here.
    assert _dependency_cycle(_chain(5000)) is None


def test_a97_deep_cycle_is_reported_not_crash():
    cycle = _dependency_cycle(_chain(5000, cycle=True))
    assert cycle is not None
    assert cycle[0] == cycle[-1] == "t00000"
    assert len(cycle) == 5002


def test_a97_cycle_path_semantics_unchanged():
    dependencies = {"t001": ["t003"], "t002": [], "t003": ["t005"], "t005": ["t001"]}
    assert _dependency_cycle(dependencies) == ["t001", "t003", "t005", "t001"]
