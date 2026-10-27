"""track_worktree.py hook 尾部读取与 tid 提取测试（A135/A344）。"""

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import track_worktree as tw


def _ledger_line(tid, event, **kw):
    rec = {"tid": tid, "event": event, **kw}
    return json.dumps(rec, ensure_ascii=False) + "\n"


def _make_project(tmp_path, ledger_text):
    project = tmp_path / "proj"
    (project / "docs" / "runtime").mkdir(parents=True)
    (project / "docs" / "runtime" / "dispatch_ledger.jsonl").write_text(
        ledger_text, encoding="utf-8"
    )
    return project


def test_resolve_worktree_reads_tail_events(tmp_path, monkeypatch):
    monkeypatch.setattr(tw, "TAIL_READ_BYTES", 4096)
    filler = "".join(
        _ledger_line("t999", "note", pad="x" * 50) for _ in range(20)
    )
    ledger = filler + _ledger_line(
        "t001", "start", worktree="wt/t001"
    )
    project = _make_project(tmp_path, ledger)
    assert tw.resolve_worktree(str(project), "t001") == str(
        Path(str(project)) / "wt" / "t001"
    )


def test_resolve_worktree_tail_window_misses_old_events(tmp_path, monkeypatch):
    """A135：只取尾部事件——tid 的 start 已滑出尾窗时不再整表回溯。"""
    monkeypatch.setattr(tw, "TAIL_READ_BYTES", 512)
    ledger = _ledger_line("t001", "start", worktree="wt/t001")
    ledger += "".join(
        _ledger_line("t999", "note", pad="x" * 100) for _ in range(30)
    )
    project = _make_project(tmp_path, ledger)
    assert tw.resolve_worktree(str(project), "t001") == ""


def test_resolve_worktree_terminal_in_tail_closes_window(tmp_path):
    ledger = _ledger_line("t001", "start", worktree="wt/t001")
    ledger += _ledger_line("t001", "report")
    project = _make_project(tmp_path, ledger)
    assert tw.resolve_worktree(str(project), "t001") == ""


def test_append_record_dedups_against_last_line_only(tmp_path):
    path = tmp_path / ".scratch" / "statusline_workdir.jsonl"
    path.parent.mkdir(parents=True)
    record = {"agent": "a", "tid": "t001"}
    tw.append_record(str(path), record)
    tw.append_record(str(path), record)  # 与最后一行相同 → 去重
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    other = {"agent": "a", "tid": "t002"}
    tw.append_record(str(path), other)
    tw.append_record(str(path), record)  # 与最后一行不同 → 追加
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_append_record_large_file_still_dedups(tmp_path, monkeypatch):
    monkeypatch.setattr(tw, "TAIL_READ_BYTES", 1024)
    path = tmp_path / "statusline_workdir.jsonl"
    filler = [
        json.dumps({"agent": "x", "pad": "y" * 80, "i": i}) for i in range(100)
    ]
    last = json.dumps({"agent": "a", "tid": "t001"}, ensure_ascii=False)
    path.write_text("\n".join(filler + [last]) + "\n", encoding="utf-8")
    tw.append_record(str(path), {"agent": "a", "tid": "t001"})
    assert path.read_text(encoding="utf-8").count('"tid": "t001"') == 1


# --- A344: extract_tid 只在命令真的调用 track_worktree.py / task.py 时提取 ---

def test_extract_tid_from_track_worktree_command():
    cmd = "python3 .repo_template/scripts/track_worktree.py --tid t113"
    assert tw.extract_tid(cmd, "") == "t113"
    cmd2 = "python3 .repo_template/scripts/track_worktree.py --tid=t042"
    assert tw.extract_tid(cmd2, "") == "t042"


def test_extract_tid_from_task_py_start():
    cmd = "python3 .repo_template/scripts/task.py start t007"
    assert tw.extract_tid(cmd, "") == "t007"


def test_extract_tid_ignores_unrelated_commands():
    # 其它工具的 --tid 参数、字符串字面量里的 start tNNN 不得误命中
    assert tw.extract_tid("some_tool --tid t999", "t001") == "t001"
    assert tw.extract_tid("echo 'start t123'", "") == ""
    assert tw.extract_tid("grep --tid t555 file.txt", "") == ""
    assert tw.extract_tid("echo start t321", "t002") == "t002"


def test_extract_tid_fallback_when_script_command_has_no_tid():
    assert tw.extract_tid("python3 .repo_template/scripts/task.py view", "t009") == "t009"
