"""A74: sync-core SKILL step 6 must match repo_sync.py cmd_apply behaviour.

Implementation (and test_repo_sync's contract-failure test) says a contract
test failure triggers a FULL rollback of the apply writes and does not
advance state. The skill previously claimed the opposite (files kept, no
automatic rollback).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".repo_template/skills/repo-template-sync-core/SKILL.md"
USAGE = ROOT / ".repo_template/docs/usage.md"


def test_a74_skill_no_longer_claims_files_are_kept_on_test_failure():
    text = SKILL.read_text(encoding="utf-8")
    assert "保留已写入文件，不能声称已自动回滚" not in text
    assert "保留已写入文件" not in text


def test_a74_skill_states_full_rollback_on_test_failure():
    text = SKILL.read_text(encoding="utf-8")
    assert "完整回滚" in text, "skill step 6 must state the full-rollback behaviour"
    assert "repo_sync_rollback" in text


def test_a74_usage_md_synced_with_same_behaviour():
    text = USAGE.read_text(encoding="utf-8")
    assert "完整回滚" in text and "repo_sync_rollback" in text, (
        "usage.md must document the same test-failure rollback behaviour"
    )
