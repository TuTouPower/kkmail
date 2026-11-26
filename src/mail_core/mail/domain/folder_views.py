"""Physical mailbox containers vs. Gmail label-derived read-only views."""

from __future__ import annotations

from mail_core.mail.domain.enums import FolderRemoteState, FolderRole

CONTAINER = "container"
VIEW = "view"

VIEW_ROLES = frozenset({FolderRole.ALL.value, FolderRole.IMPORTANT.value})

# Built-in system roles eligible for 1-to-1 identity rebinding when a remote
# server changes display language / localized path for the same logical folder.
REBINDABLE_SYSTEM_ROLES = frozenset(
    {
        FolderRole.SENT.value,
        FolderRole.DRAFTS.value,
        FolderRole.TRASH.value,
        FolderRole.JUNK.value,
        FolderRole.FLAGGED.value,
        FolderRole.ARCHIVE.value,
        FolderRole.ALL.value,
        FolderRole.IMPORTANT.value,
    }
)

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

IMPORTANT_VIEW_REMOTE_IDS = frozenset(
    {"[Gmail]/Important", "[Gmail]/重要", "[Gmail]/&kc2JgQ-"}
)

EXCLUDED_FROM_ALL_VIEW_ROLES = frozenset({FolderRole.TRASH.value, FolderRole.JUNK.value, "spam"})


def is_gmail_account(account: object) -> bool:
    email = str(getattr(account, "email", "")).lower()
    config = getattr(account, "config", None) or {}
    return email.endswith(("@gmail.com", "@googlemail.com")) or "gmail" in str(config.get("imap_host", "")).lower()


def is_gmail_view(role: str, remote_id: str) -> bool:
    return role in VIEW_ROLES or remote_id in GMAIL_VIEW_REMOTE_IDS


def is_view_folder(folder: object) -> bool:
    return getattr(folder, "kind", CONTAINER) == VIEW


def is_important_view(folder: object) -> bool:
    return is_view_folder(folder) and (
        getattr(folder, "role", None) == FolderRole.IMPORTANT.value
        or getattr(folder, "remote_id", None) in IMPORTANT_VIEW_REMOTE_IDS
    )


def is_active_folder(folder: object) -> bool:
    return getattr(folder, "remote_state", FolderRemoteState.ACTIVE.value) == FolderRemoteState.ACTIVE.value


def is_syncable_folder(folder: object) -> bool:
    return (
        not is_view_folder(folder)
        and bool(getattr(folder, "selectable", True))
        and is_active_folder(folder)
    )


def folder_sync_skip_reason(folder: object) -> str | None:
    """Return canonical skip reason when a folder cannot enter sync, else None."""
    if is_view_folder(folder):
        return "derived_view"
    if not getattr(folder, "selectable", True):
        return "folder_not_selectable"
    if not is_active_folder(folder):
        return "folder_deleted"
    return None
