"""Locked JSONL storage primitives for task execution events.

Growth / archiving strategy (A206): the ledger is append-only and every
parse is O(n). Two mitigations keep long ledgers usable:

- Within one process, ``ledger_read()`` reuses the snapshot taken under
  the lock while the file is unchanged (size + mtime_ns), so a command
  that consults the ledger repeatedly parses it once. Writes through
  this module invalidate the snapshot.
- Archiving: once the ledger passes ``LEDGER_ARCHIVE_THRESHOLD_EVENTS``
  events and no attempt is still in flight (``task.py ps`` empty), the
  operator may rotate it manually: move ``dispatch_ledger.jsonl`` to
  ``dispatch_ledger.<YYYYMMDD>.jsonl`` in the same runtime directory
  and let the next write start a fresh file. Attempt numbering restarts
  from the fresh file, so rotation is only safe with no in-flight
  attempts; archived files are evidence and are never rewritten.
"""

import json
import os
import sys
from datetime import datetime
from typing import Callable

import repo_task.context as ctx

from .locks import lock_fh, unlock_fh


def _sanitize(event: dict) -> dict:
    final = {
        key: value.replace("\n", " ").replace("\r", " ")
        if isinstance(value, str) else value
        for key, value in event.items()
    }
    final["ts"] = datetime.now(ctx.TZ_CN).isoformat(timespec="seconds")
    return final


def _read_unlocked() -> list[dict]:
    if not ctx.LEDGER_PATH.is_file():
        return []
    events = []
    for line_no, line in enumerate(
        ctx.LEDGER_PATH.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as e:
            # fail-closed：损坏行跳过会让后续事件基于缺失事件续写，导致
            # attempt 号复用或 current identity 误判。拒绝继续，提示手动修复。
            raise ctx.TaskDataError(
                f"调度账本 {ctx._rel(ctx.LEDGER_PATH)} 第 {line_no} 行损坏（{e}）；"
                "拒绝继续以防 attempt 号复用。请手动修复该行后重试"
            ) from None
        if not isinstance(value, dict):
            raise ctx.TaskDataError(
                f"调度账本 {ctx._rel(ctx.LEDGER_PATH)} 第 {line_no} 行非 JSON 对象；拒绝继续"
            )
        events.append(value)
    return events


LEDGER_ARCHIVE_THRESHOLD_EVENTS = 10_000

# A206: process-local ledger_read() snapshot:
# (path, st_size, st_mtime_ns, events). Only ledger_read() uses it; the
# write path always re-reads under the lock. The path is part of the key
# so tests that repoint LEDGER_PATH never see another file's snapshot.
_read_cache: tuple[str, int, int, tuple[dict, ...]] | None = None


def _append_many_unlocked(events: list[dict]) -> list[dict]:
    finals = [_sanitize(event) for event in events]
    if not finals:
        return []
    payload = "".join(
        json.dumps(event, ensure_ascii=False) + "\n" for event in finals
    )
    # 无换行尾行（截断残留）会被新事件直接拼接；先补换行把坏尾行隔离为独立行
    if ctx.LEDGER_PATH.is_file() and ctx.LEDGER_PATH.stat().st_size > 0:
        with ctx.LEDGER_PATH.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(-1, os.SEEK_END)
            if stream.read(1) != b"\n":
                with ctx.LEDGER_PATH.open("ab") as fix:
                    fix.write(b"\n")
    with ctx.LEDGER_PATH.open("a", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    global _read_cache
    _read_cache = None
    return finals


def _append_unlocked(event: dict) -> dict:
    return _append_many_unlocked([event])[0]


def _with_lock(callback):
    ctx.LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = ctx.LEDGER_PATH.with_suffix(".lock")
    with lock_path.open("a+", encoding="utf-8") as fh:
        # 空 lock 文件上 Windows msvcrt.locking(1 字节) 会失败，先写入 1 字节。
        # 注意：锁是 CLI 单进程独占使用，非线程安全（msvcrt 进程级、fcntl 描述符级）。
        if fh.tell() == 0:
            fh.write("\0")
            fh.flush()
        lock_fh(fh)
        try:
            return callback()
        finally:
            unlock_fh(fh)


def _read_cached_unlocked() -> list[dict]:
    """_read_unlocked with the A206 process-local snapshot reuse.

    Runs under the ledger lock, so the stat key and the parse are
    consistent with respect to cooperating writers.
    """
    global _read_cache
    path_key = str(ctx.LEDGER_PATH)
    if ctx.LEDGER_PATH.is_file():
        stat = ctx.LEDGER_PATH.stat()
        key = (path_key, stat.st_size, stat.st_mtime_ns)
    else:
        key = (path_key, 0, 0)
    if _read_cache is not None and _read_cache[:3] == key:
        return [dict(event) for event in _read_cache[3]]
    events = _read_unlocked()
    if ctx.LEDGER_PATH.is_file():
        stat = ctx.LEDGER_PATH.stat()
        key = (path_key, stat.st_size, stat.st_mtime_ns)
    _read_cache = (key[0], key[1], key[2], tuple(dict(event) for event in events))
    return events


def ledger_read() -> list[dict]:
    """Read all valid JSON object events while holding the ledger lock.

    Repeated calls within one process reuse a single parse while the
    file is unchanged (A206); see the module docstring for the ledger
    archiving strategy once the file grows past the threshold.
    """
    return _with_lock(_read_cached_unlocked)


def ledger_append(event: dict) -> dict:
    """Append one sanitized event while holding the ledger lock."""
    return _with_lock(lambda: _append_unlocked(event))


def ledger_locked_append(builder: Callable[[list[dict]], dict]) -> dict:
    """Build and append one event against a fresh locked ledger snapshot."""
    def update():
        events = _read_unlocked()
        return _append_unlocked(builder(events))

    return _with_lock(update)


def ledger_locked_append_many(
    builder: Callable[[list[dict]], list[dict]],
) -> list[dict]:
    """Preflight and append a complete event batch under one ledger lock."""
    def update():
        events = _read_unlocked()
        return _append_many_unlocked(builder(events))

    return _with_lock(update)


def ledger_next_attempt(tid: str, events: list[dict]) -> int:
    attempts = [
        event.get("attempt") for event in events
        if event.get("tid") == tid
        and isinstance(event.get("attempt"), int)
        and not isinstance(event.get("attempt"), bool)
        and event.get("attempt") > 0
    ]
    return max(attempts, default=0) + 1


def ledger_allocate_attempt(
    tid: str,
    builder: Callable[[int, list[dict]], dict],
) -> dict:
    """Atomically allocate the next integer attempt and append its event."""
    def allocate(events: list[dict]) -> dict:
        attempt = ledger_next_attempt(tid, events)
        event = builder(attempt, events)
        event["tid"] = tid
        event["attempt"] = attempt
        return event

    return ledger_locked_append(allocate)


def _ledger_append_safely(event: dict) -> None:
    """Best-effort append for topology and integration events."""
    try:
        if not ctx.LEDGER_PATH.resolve().is_relative_to(ctx.REPO_ROOT.resolve()):
            return
        ledger_append(event)
    except (OSError, ctx.TaskDataError) as error:
        # TaskDataError：ledger 损坏 fail-closed；写失败也不阻断主流程，仅记录。
        # 事件上下文（tid/attempt/execution_id）进 WARNING，便于事后定位缺口（F34）
        print(
            f"WARNING: 调度账本写入失败（{error}）；"
            f"event={event.get('event')} tid={event.get('tid')} "
            f"attempt={event.get('attempt')} "
            f"execution_id={event.get('execution_id')} 事件未记录",
            file=sys.stderr,
        )
