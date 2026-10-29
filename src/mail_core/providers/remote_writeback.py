"""Normalize remote_operation op_types and desired_state for providers."""

from __future__ import annotations

from typing import Any


# Canonical op names used by providers after normalization.
OP_MARK_READ = "mark_read"
OP_SET_FLAG = "set_flag"
OP_MOVE = "move"
OP_TRASH = "trash"


def normalize_op_type(op_type: str) -> str:
    t = (op_type or "").strip().lower()
    aliases = {
        "mark_read": OP_MARK_READ,
        "set_read": OP_MARK_READ,
        "read": OP_MARK_READ,
        "set_flag": OP_SET_FLAG,
        "flag": OP_SET_FLAG,
        "star": OP_SET_FLAG,
        "flagged": OP_SET_FLAG,
        "move": OP_MOVE,
        "trash": OP_TRASH,
        "delete": OP_TRASH,
        "remove": OP_TRASH,
    }
    return aliases.get(t, t)


def require_remote_id(desired_state: dict[str, Any]) -> str:
    rid = str(desired_state.get("remote_id") or desired_state.get("id") or "")
    if not rid:
        raise ValueError("missing remote_id")
    return rid


def compress_uids(uids: Sequence[int], *, max_chars: int = 1000) -> list[str]:
    """Compress sorted integer UIDs into interval representation, chunked at max_chars."""
    return [chunk_str for chunk_str, _ in compress_uids_chunked(uids, max_chars=max_chars)]


def compress_uids_chunked(uids: Sequence[int], *, max_chars: int = 1000) -> list[tuple[str, list[int]]]:
    """Compress sorted integer UIDs into (spec_string, uids_list) chunks."""
    if not uids:
        return []
    sorted_uids = sorted(set(uids))
    start = sorted_uids[0]
    end = start
    range_uids = [start]

    range_items: list[tuple[str, list[int]]] = []
    for u in sorted_uids[1:]:
        if u == end + 1:
            end = u
            range_uids.append(u)
        else:
            r_str = str(start) if start == end else f"{start}:{end}"
            range_items.append((r_str, list(range_uids)))
            start = end = u
            range_uids = [u]
    r_str = str(start) if start == end else f"{start}:{end}"
    range_items.append((r_str, list(range_uids)))

    chunks: list[tuple[str, list[int]]] = []
    cur_str: list[str] = []
    cur_uids: list[int] = []
    cur_len = 0
    for r_str, u_list in range_items:
        added = len(r_str) if not cur_str else len(r_str) + 1
        if cur_str and cur_len + added > max_chars:
            chunks.append((",".join(cur_str), list(cur_uids)))
            cur_str = [r_str]
            cur_uids = list(u_list)
            cur_len = len(r_str)
        else:
            cur_str.append(r_str)
            cur_uids.extend(u_list)
            cur_len += added
    if cur_str:
        chunks.append((",".join(cur_str), list(cur_uids)))
    return chunks
