"""Physical mailbox containers vs. Gmail label-derived read-only views."""

from __future__ import annotations

import uuid

CONTAINER = "container"
VIEW = "view"

VIEW_ROLES = frozenset({"all", "important"})

GMAIL_VIEW_REMOTE_IDS = frozenset(
    {
        "[Gmail]/&YkBnCZCuTvY-",
        "[Gmail]/&kc2JgQ-",
        "[Gmail]/All Mail",
        "[Gmail]/Important",
        "[Gmail]/所有邮件",
        "[Gmail]/重要",
    }
)

EXCLUDED_FROM_ALL_VIEW_ROLES = frozenset({"trash", "junk", "spam"})


def is_gmail_view(role: str, remote_id: str) -> bool:
    return role in VIEW_ROLES or remote_id in GMAIL_VIEW_REMOTE_IDS


def is_view_folder(folder: object) -> bool:
    return getattr(folder, "kind", CONTAINER) == VIEW


def is_syncable_folder(folder: object) -> bool:
    return not is_view_folder(folder) and getattr(folder, "sync_status", "") != "paused"
