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
