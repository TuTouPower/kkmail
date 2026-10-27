"""repo_hygiene.py 机械迁移动作的真实 git 测试。

monkeypatch 模块级路径常量到 tmp_path 构造的 git 仓库，覆盖 handoff 分段
迁移（append 保留最新）、spike/review 目录 git mv 迁移、dry-run 零写盘、
歧义与格式校验。
"""

import argparse
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import repo_hygiene as rh


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=check,
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@e.c")
    _git(root, "config", "user.name", "t")
    for name, value in {
        "REPO_ROOT": root,
        "SPIKES_DIR": root / "docs/spikes",
        "ARCHIVE_SPIKES": root / "docs/archive/spikes",
        "REVIEWS_DIR": root / "docs/reviews",
        "ARCHIVE_REVIEWS": root / "docs/archive/reviews",
        "HANDOFF": root / "docs/handoff.md",
        "ARCHIVE_HANDOFF": root / "docs/archive/handoff.md",
    }.items():
        monkeypatch.setattr(rh, name, value)
    return root


def _handoff_two_sections(repo: Path) -> None:
    (repo / "docs/handoff.md").write_text(
        "# 项目交接记录（最新）\n\n说明。\n\n"
        "## 2026-08-01T09:00:00+08:00 a → b\n\n- branch：`t001_x`\n"
        "- head_commit：`aaa111`\n\n"
        "## 2026-08-13T16:00:00+08:00 b → c\n\n- branch：`t002_y`\n"
        "- head_commit：`bbb222`\n",
        encoding="utf-8",
    )


def test_archive_handoff_moves_stale_keeps_latest(repo):
    _handoff_two_sections(repo)
    rh.cmd_archive_handoff(argparse.Namespace(write=True))
    handoff = (repo / "docs/handoff.md").read_text(encoding="utf-8")
    archive = (repo / "docs/archive/handoff.md").read_text(encoding="utf-8")
    assert "2026-08-13T16:00:00+08:00" in handoff
    assert "2026-08-01T09:00:00+08:00" not in handoff
    assert "2026-08-01T09:00:00+08:00" in archive
    assert "2026-08-13T16:00:00+08:00" not in archive
    assert "t002_y" in handoff


def test_archive_handoff_preserves_existing_archive_body(repo):
    archive = repo / "docs/archive/handoff.md"
    archive.parent.mkdir(parents=True)
    archive.write_text(
        "# 历史交接\n\n自定义备注，禁止改写。\n\n"
        "## 2026-07-01 旧段\n\n- note：keep me\n",
        encoding="utf-8",
    )
    _handoff_two_sections(repo)
    rh.cmd_archive_handoff(argparse.Namespace(write=True))
    text = archive.read_text(encoding="utf-8")
    assert "自定义备注，禁止改写。" in text
    assert "2026-07-01 旧段" in text
    assert "2026-08-01T09:00:00+08:00" in text
    assert text.index("自定义备注") < text.index("2026-08-01")


def test_archive_handoff_append_not_truncate(repo):
    _handoff_two_sections(repo)
    rh.cmd_archive_handoff(argparse.Namespace(write=True))
    # 第二轮：上一轮保留的 08-13 节 + 新 08-20 节 → 迁 08-13，追加归档不覆盖旧归档
    (repo / "docs/handoff.md").write_text(
        "# 项目交接记录（最新）\n\n说明。\n\n"
        "## 2026-08-13T16:00:00+08:00 b → c\n\n- head_commit：`bbb222`\n\n"
        "## 2026-08-20T10:00:00+08:00 c → d\n\n- head_commit：`ccc333`\n",
        encoding="utf-8",
    )
    rh.cmd_archive_handoff(argparse.Namespace(write=True))
    archive = (repo / "docs/archive/handoff.md").read_text(encoding="utf-8")
    assert "2026-08-01T09:00:00+08:00" in archive
    assert "2026-08-13T16:00:00+08:00" in archive
    assert "2026-08-20T10:00:00+08:00" not in archive  # 最新节保留在 handoff
    assert "2026-08-20T10:00:00+08:00" in (repo / "docs/handoff.md").read_text(encoding="utf-8")


def test_archive_handoff_dry_run_does_not_write(repo):
    _handoff_two_sections(repo)
    rh.cmd_archive_handoff(argparse.Namespace(write=False))
    assert not (repo / "docs/archive/handoff.md").exists()
    assert "2026-08-01T09:00:00+08:00" in (repo / "docs/handoff.md").read_text(encoding="utf-8")


def test_archive_handoff_noop_single_section(repo):
    (repo / "docs/handoff.md").write_text(
        "# 项目交接记录（最新）\n\n说明。\n\n"
        "## 2026-08-13T16:00:00+08:00 b → c\n\n- head_commit：`bbb222`\n",
        encoding="utf-8",
    )
    rh.cmd_archive_handoff(argparse.Namespace(write=True))
    assert not (repo / "docs/archive/handoff.md").exists()


def test_archive_handoff_retry_after_partial_failure_no_duplicate(repo, monkeypatch):
    """两次写之间失败（archive 已 append、handoff 重写未完成）→ 重跑幂等，不重复追加。"""
    _handoff_two_sections(repo)
    real_replace = rh._replace_text

    def flaky(path, text):
        if path == rh.HANDOFF:
            raise OSError("模拟 handoff 重写失败")
        return real_replace(path, text)

    monkeypatch.setattr(rh, "_replace_text", flaky)
    with pytest.raises(OSError):
        rh.cmd_archive_handoff(argparse.Namespace(write=True))
    archive = repo / "docs/archive/handoff.md"
    assert archive.read_text(encoding="utf-8").count("## 2026-08-01") == 1
    assert "2026-08-01" in (repo / "docs/handoff.md").read_text(encoding="utf-8")

    monkeypatch.setattr(rh, "_replace_text", real_replace)
    rh.cmd_archive_handoff(argparse.Namespace(write=True))
    text = archive.read_text(encoding="utf-8")
    assert text.count("## 2026-08-01") == 1  # 重跑不重复追加
    handoff = (repo / "docs/handoff.md").read_text(encoding="utf-8")
    assert "2026-08-13" in handoff and "2026-08-01" not in handoff


def _make_spike(repo: Path, name: str) -> None:
    d = repo / "docs/spikes" / name
    d.mkdir(parents=True)
    (d / "report.md").write_text("# report\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"feat(spike): add {name}")


def test_archive_spike_moves_dir_with_git_mv(repo):
    _make_spike(repo, "s001_uv_lock")
    rh.cmd_archive_spike(argparse.Namespace(sid="s001", write=True))
    assert not (repo / "docs/spikes/s001_uv_lock").exists()
    assert (repo / "docs/archive/spikes/s001_uv_lock/report.md").is_file()
    # git 跟踪：git ls-files 确认迁移被记录
    tracked = _git(repo, "ls-files").stdout
    assert "docs/archive/spikes/s001_uv_lock/report.md" in tracked
    assert "docs/spikes/s001_uv_lock/report.md" not in tracked


def test_archive_spike_dry_run_does_not_move(repo):
    _make_spike(repo, "s001_uv_lock")
    rh.cmd_archive_spike(argparse.Namespace(sid="s001", write=False))
    assert (repo / "docs/spikes/s001_uv_lock").is_dir()


def test_archive_spike_ambiguous_or_missing(repo):
    _make_spike(repo, "s001_uv")
    _make_spike(repo, "s001_lock")
    with pytest.raises(rh.HygieneError):
        rh.cmd_archive_spike(argparse.Namespace(sid="s001", write=True))
    with pytest.raises(rh.HygieneError):
        rh.cmd_archive_spike(argparse.Namespace(sid="s999", write=True))


def test_archive_review_moves_dir(repo):
    d = repo / "docs/reviews/review_my_check"
    d.mkdir(parents=True)
    (d / "review_general.md").write_text("PASS\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "docs(review): add my_check")
    rh.cmd_archive_review(argparse.Namespace(dir="review_my_check", write=True))
    assert (repo / "docs/archive/reviews/review_my_check/review_general.md").is_file()
    assert not (repo / "docs/reviews/review_my_check").exists()


def test_archive_review_moves_gitignore_meta(repo):
    d = repo / "docs/reviews/review_my_check"
    d.mkdir(parents=True)
    (d / "review_general.md").write_text("PASS\n", encoding="utf-8")
    meta = d / "_meta" / "notes.json"
    meta.parent.mkdir()
    meta.write_text('{"x": 1}\n', encoding="utf-8")
    (repo / ".gitignore").write_text(
        "docs/reviews/review_*/_meta/\ndocs/archive/reviews/review_*/_meta/\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "docs(review): add my_check")
    assert (d / "_meta/notes.json").is_file()
    assert "_meta" not in _git(repo, "ls-files").stdout
    rh.cmd_archive_review(argparse.Namespace(dir="review_my_check", write=True))
    dest = repo / "docs/archive/reviews/review_my_check"
    assert (dest / "review_general.md").is_file()
    assert (dest / "_meta/notes.json").is_file()
    assert not (repo / "docs/reviews/review_my_check").exists()


def test_archive_review_rejects_bad_prefix(repo):
    with pytest.raises(rh.HygieneError):
        rh.cmd_archive_review(argparse.Namespace(dir="prompts", write=True))
    with pytest.raises(rh.HygieneError):
        rh.cmd_archive_review(argparse.Namespace(dir="review_nonexistent", write=True))


# --- A155: archive-review 目录名路径校验，拒绝 ../ 穿越 ---

def test_archive_review_rejects_traversal_names(repo):
    # 穿越目标真实存在（docs/spikes/s001_x）：旧实现会越过 reviews/ 把它迁走
    spike = repo / "docs/spikes/s001_x"
    spike.mkdir(parents=True)
    # 中间目录须真实存在，否则 OS 路径解析先于校验就失败、测不到穿越
    (repo / "docs/reviews/review_x").mkdir(parents=True)
    (spike / "report.md").write_text("# r\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "feat(spike): add s001_x")
    for bad in (
        "review_x/../../spikes/s001_x",
        "review_x/../review_y",
        "review_x/sub",
        "review_../escape",
        "review_x\\..\\escape",
    ):
        with pytest.raises(rh.HygieneError):
            rh.cmd_archive_review(argparse.Namespace(dir=bad, write=True))
    assert (repo / "docs/spikes/s001_x/report.md").is_file()
    assert not (repo / "docs/archive/reviews").exists()


def test_archive_review_valid_name_still_moves(repo):
    d = repo / "docs/reviews/review_2026-01_check-2"
    d.mkdir(parents=True)
    (d / "r.md").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "docs(review): add")
    rh.cmd_archive_review(argparse.Namespace(dir="review_2026-01_check-2", write=True))
    assert (repo / "docs/archive/reviews/review_2026-01_check-2/r.md").is_file()


# --- A156: handoff 切分不把 fenced code 内的 ## 行当章节 ---

def test_split_handoff_ignores_headings_inside_fences():
    text = (
        "# 交接\n\n说明。\n\n"
        "## 第一节\n\n正文。\n\n```markdown\n## 代码里的假标题\n示例\n```\n\n续。\n\n"
        "## 第二节\n\n正文二。\n"
    )
    header, sections = rh._split_handoff(text)
    assert len(sections) == 2
    assert sections[0][0] == "## 第一节"
    assert any("## 代码里的假标题" in line for line in sections[0])
    assert sections[1][0] == "## 第二节"


def test_split_handoff_tilde_fence_and_longer_close():
    text = (
        "## 唯一节\n\n~~~\n## 假标题\n~~~\n\n正文。\n"
    )
    _, sections = rh._split_handoff(text)
    assert len(sections) == 1


def test_archive_handoff_keeps_fenced_section_intact(repo):
    (repo / "docs/handoff.md").write_text(
        "# 项目交接记录（最新）\n\n说明。\n\n"
        "## 2026-08-01 旧节\n\n- head_commit：`aaa111`\n\n"
        "## 2026-08-13 新节\n\n示例：\n\n```markdown\n## 不是新节\n内容\n```\n\n"
        "- head_commit：`bbb222`\n",
        encoding="utf-8",
    )
    rh.cmd_archive_handoff(argparse.Namespace(write=True))
    handoff = (repo / "docs/handoff.md").read_text(encoding="utf-8")
    archive = (repo / "docs/archive/handoff.md").read_text(encoding="utf-8")
    # 最新节（含 fence 内的 ## 行）完整保留，未被劈成两节误归档后半
    assert "## 2026-08-13 新节" in handoff
    assert "## 不是新节" in handoff
    assert "bbb222" in handoff
    assert "2026-08-01 旧节" in archive
    assert "不是新节" not in archive
