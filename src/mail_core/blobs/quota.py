"""Disk quota helpers for MIME archive backpressure."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class QuotaStatus:
    used_bytes: int
    soft_limit_bytes: int | None
    hard_limit_bytes: int | None
    soft_exceeded: bool
    hard_exceeded: bool


def dir_size_bytes(root: Path) -> int:
    total = 0
    if not root.exists():
        return 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
    return total


def check_quota(
    root: Path,
    *,
    soft_limit_bytes: int | None = None,
    hard_limit_bytes: int | None = None,
) -> QuotaStatus:
    used = dir_size_bytes(root)
    soft = soft_limit_bytes
    hard = hard_limit_bytes
    return QuotaStatus(
        used_bytes=used,
        soft_limit_bytes=soft,
        hard_limit_bytes=hard,
        soft_exceeded=soft is not None and used >= soft,
        hard_exceeded=hard is not None and used >= hard,
    )
