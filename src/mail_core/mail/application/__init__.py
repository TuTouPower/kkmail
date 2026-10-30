"""Application layer: the only entry point HTTP routes use for mail reads and mutations.

Exports are resolved lazily (PEP 562) so importing a submodule does not pull in the
whole sync/provider graph.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, str] = {
    # queries
    "InvalidCursor": "queries",
    "MessageDetail": "queries",
    "MessageListItem": "queries",
    "MessagePage": "queries",
    "account_emails_by_id": "queries",
    "decode_cursor": "queries",
    "encode_cursor": "queries",
    "get_folder_stats": "queries",
    "get_message_detail": "queries",
    "list_folder_stats_for_account": "queries",
    "list_messages_keyset": "queries",
    "messages_by_ids": "queries",
    "query_global_inbox_stats": "queries",
    "query_group_inbox_stats": "queries",
    "select_display_body": "queries",
    "unified_inbox": "queries",
    # search
    "SearchPage": "search",
    "search_message_ids": "search",
    "search_messages_page": "search",
    # mutations
    "MutationResult": "mutations",
    "mark_all_messages_read": "mutations",
    "set_message_flagged": "mutations",
    "set_message_read": "mutations",
    "trash_message": "mutations",
    # remote operations
    "enqueue_remote_operation": "remote_ops",
    "mark_remote_operation": "remote_ops",
    "reclaim_stale_in_progress": "remote_ops",
    # attachments
    "AttachmentAccessError": "attachments",
    "PathTraversalRejected": "attachments",
    "load_attachment": "attachments",
    # message details
    "get_message_detail_with_archive_status": "message_details",
    "sync_message_body": "message_details",
    # remote images allowlists (t066)
    "InvalidSenderEmailError": "remote_images",
    "normalize_sender_email": "remote_images",
    "is_remote_images_allowed": "remote_images",
    "allow_message_remote_images": "remote_images",
    "allow_sender_remote_images": "remote_images",
    "list_allowed_senders": "remote_images",
    "remove_allowed_sender": "remote_images",
    # accounts
    "AccountDTO": "accounts",
    "AccountPageDTO": "accounts",
    "GroupDTO": "accounts",
    "SyncJobDTO": "accounts",
    "SyncAllDTO": "accounts",
    "SettingsDTO": "accounts",
    "list_accounts_app": "accounts",
    "create_account_app": "accounts",
    "update_account_app": "accounts",
    "delete_account_app": "accounts",
    "sync_account_app": "accounts",
    "sync_all_accounts_app": "accounts",
    "list_groups_app": "accounts",
    "create_group_app": "accounts",
    "delete_group_app": "accounts",
    "rename_group_app": "accounts",
    "save_sidebar_layout_app": "accounts",
    "get_sidebar_layout_app": "accounts",
    "reset_sidebar_account_order_app": "accounts",
    "get_settings_app": "accounts",
    "update_settings_app": "accounts",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    mod = _EXPORTS.get(name)
    if mod is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{mod}"), name)
    globals()[name] = value
    return value
