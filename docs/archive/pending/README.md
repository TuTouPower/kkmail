# 已闭环 pending 索引

本目录为已闭环待办的归档（`docs/archive/pending/`）。各条目正文为历史记录，普遍未统一记录提出日期与闭环日期；本索引在索引层补齐闭环日期对照，不逐个改写历史正文。

## 后续归档条目模板要求

后续归档条目正文必须包含提出日期与闭环日期两项元数据（建议置于文件首部，格式 `YYYY-MM-DD`），缺失任一项不得归档入库。

## 闭环日期对照表

- 「闭环日期」为该条目在当前 git 历史中首次入库 `docs/archive/pending/` 的日期（`git log --diff-filter=A` 核得）。
- 「提出日期」各条目正文未统一记录，统一标「未记录」；正文个别含日期者不视为提出日期，不在此推定。
- 「处理指向」摘自各条目正文的「处理：」行原文。

|条目|文件|闭环日期|提出日期|处理指向|
|:---|:---|:---|:---|:---|
|p001|[p001_trash_action_ux_mismatch.md](p001_trash_action_ux_mismatch.md)|2026-10-22|未记录|fix/p001-p004|
|p002|[p002_empty_body_reader_blank.md](p002_empty_body_reader_blank.md)|2026-10-22|未记录|fix/p001-p004|
|p003|[p003_client_filter_pagination_conflict.md](p003_client_filter_pagination_conflict.md)|2026-10-22|未记录|fix/p001-p004|
|p004|[p004_imap_basic_auth_disabled_retry_loop.md](p004_imap_basic_auth_disabled_retry_loop.md)|2026-10-22|未记录|fix/p001-p004|
|p005|[p005_worker_unbound_local_account.md](p005_worker_unbound_local_account.md)|2026-10-22|未记录|fix/p005|
|p006|[p006_attachment_size_human_readable.md](p006_attachment_size_human_readable.md)|2026-10-22|未记录|main|
|p007|[p007_settings_general_fields_sync_issue.md](p007_settings_general_fields_sync_issue.md)|2026-10-22|未记录|main|
|p008|[p008_sidebar_accounts_failure_handling.md](p008_sidebar_accounts_failure_handling.md)|2026-10-22|未记录|t004|
|p009|[p009_refresh_sync_and_imap_id_handshake.md](p009_refresh_sync_and_imap_id_handshake.md)|2026-10-22|未记录|t005|
|p010|[p010_remote_images_banner_dark_mode.md](p010_remote_images_banner_dark_mode.md)|2026-10-22|未记录|t006|
|p011|[p011_imap_raw_gbk_header_mojibake.md](p011_imap_raw_gbk_header_mojibake.md)|2026-10-22|未记录|t007|
|p012|[p012_apple_mail_dark_mode_background.md](p012_apple_mail_dark_mode_background.md)|2026-10-22|未记录|t006|
|p013|[p013_account_folder_tree_support.md](p013_account_folder_tree_support.md)|2026-10-22|未记录|t008|
|p014|[p014_sidebar_collapse_hide_and_toggle_relocate.md](p014_sidebar_collapse_hide_and_toggle_relocate.md)|2026-10-22|未记录|t009|
|p015|[p015_account_avatar_style_setting.md](p015_account_avatar_style_setting.md)|2026-10-22|未记录|t010|
|p016|[p016_mark_all_read_sync_convergence.md](p016_mark_all_read_sync_convergence.md)|2026-10-22|未记录|t012|
|p017|[p017_account_order_drag_and_drop.md](p017_account_order_drag_and_drop.md)|2026-10-23|未记录|t027|
|p018|[p018_account_folder_tree_layout_and_focus_ring.md](p018_account_folder_tree_layout_and_focus_ring.md)|2026-10-23|未记录|t024|
|p019|[p019_clipboard_copy_permission_denied.md](p019_clipboard_copy_permission_denied.md)|2026-10-23|未记录|t025|
|p020|[p020_imap_header_mojibake_history_backfill_and_mime_gap.md](p020_imap_header_mojibake_history_backfill_and_mime_gap.md)|2026-10-23|未记录|t026|
|p021|[p021_on_demand_message_body_sync.md](p021_on_demand_message_body_sync.md)|2026-10-23|未记录|t034|
|p022|[p022_message_reader_body_preview_leak.md](p022_message_reader_body_preview_leak.md)|2026-10-23|未记录|t043|
|p023|[p023_macos_sidebar_drag_validation.md](p023_macos_sidebar_drag_validation.md)|2026-10-23|未记录|t032|
|p024|[p024_unknown_mail_status_defaults.md](p024_unknown_mail_status_defaults.md)|2026-10-23|未记录|t041|
|p025|[p025_partial_provider_delta_fidelity.md](p025_partial_provider_delta_fidelity.md)|2026-10-23|未记录|t042|
|p026|[p026_sidebar_tree_alignment.md](p026_sidebar_tree_alignment.md)|2026-10-23|未记录|t044|
|p027|[p027_account_folder_sync_failure_and_unknown_unread_badge.md](p027_account_folder_sync_failure_and_unknown_unread_badge.md)|2026-10-23|未记录|t045|
|p028|[p028_mail_list_cache_prefix_folder_collision.md](p028_mail_list_cache_prefix_folder_collision.md)|2026-10-23|未记录|t046|
|p029|[p029_dark_mode_background_colors.md](p029_dark_mode_background_colors.md)|2026-10-23|未记录|t047|
|p030|[p030_missing_headers_blank_and_body_sync_copy.md](p030_missing_headers_blank_and_body_sync_copy.md)|2026-10-23|未记录|t047|
|p031|[p031_repaired_mime_parse_error_blocks_body_and_fetch_error_conflation.md](p031_repaired_mime_parse_error_blocks_body_and_fetch_error_conflation.md)|2026-10-23|未记录|t048|
|p032|[p032_settings_account_domain_filter.md](p032_settings_account_domain_filter.md)|2026-10-24|未记录|main|
|p033|[p033_settings_account_edit_action.md](p033_settings_account_edit_action.md)|2026-10-24|未记录|main|
|p034|[p034_account_sync_failure_self_healing_and_sidebar_status_discrepancy.md](p034_account_sync_failure_self_healing_and_sidebar_status_discrepancy.md)|2026-10-24|未记录|main|
|p035|[p035_empty_archived_mail_body_placeholder.md](p035_empty_archived_mail_body_placeholder.md)|2026-10-24|未记录|main|
|p036|[p036_sync_job_error_double_requeue.md](p036_sync_job_error_double_requeue.md)|2026-10-24|未记录|t049|
|p037|[p037_mailbox_folder_role_aliases.md](p037_mailbox_folder_role_aliases.md)|2026-10-24|未记录|t051|
|p038|[p038_qq_other_folder_search_failure.md](p038_qq_other_folder_search_failure.md)|2026-10-24|未记录|t052|
|p039|[p039_body_sync_retry_loop.md](p039_body_sync_retry_loop.md)|2026-10-24|未记录|fix-p039-p040|
|p040|[p040_fetch_timeout_setting_not_applied.md](p040_fetch_timeout_setting_not_applied.md)|2026-10-24|未记录|fix-p039-p040|
|p041|[p041_unread_badge_stale_on_mark_read.md](p041_unread_badge_stale_on_mark_read.md)|2026-10-25|未记录|8a80186|
|p042|[p042_copy_account_email_on_click.md](p042_copy_account_email_on_click.md)|2026-10-25|未记录|8a80186|
|p043|[p043_sidebar_account_search_button.md](p043_sidebar_account_search_button.md)|2026-10-25|未记录|8a80186|
|p044|[p044_web_insecure_context_clipboard_copy_failure.md](p044_web_insecure_context_clipboard_copy_failure.md)|2026-10-26|未记录|fix-p044|
|p045|[p045_sidebar_search_click_outside_auto_hide.md](p045_sidebar_search_click_outside_auto_hide.md)|2026-10-26|未记录|review_20261026_005019|
|p046|[p046_sync_button_spin_and_remove_banner.md](p046_sync_button_spin_and_remove_banner.md)|2026-10-26|未记录|review_20261026_005019|
|p047|[p047_incoming_mail_sync_latency.md](p047_incoming_mail_sync_latency.md)|2026-10-26|未记录|review_20261026_005019|
|p048|[p048_message_reader_already_archived_race.md](p048_message_reader_already_archived_race.md)|2026-10-26|未记录|review_20261026_005019|
|p049|[p049_settings_header_cleanup_and_sidebar_toggle_relocate.md](p049_settings_header_cleanup_and_sidebar_toggle_relocate.md)|2026-10-26|未记录|review_20261026_005019|
|p050|[p050_sidebar_settings_button_background_style.md](p050_sidebar_settings_button_background_style.md)|2026-10-26|未记录|review_20261026_005019|
|p051|[p051_sidebar_account_folder_order_and_indent.md](p051_sidebar_account_folder_order_and_indent.md)|2026-10-26|未记录|review_20261026_005019|
|p052|[p052_ui_reference_overlay_prod_and_shortcut_setting.md](p052_ui_reference_overlay_prod_and_shortcut_setting.md)|2026-10-26|未记录|review_20261026_005019|
|p053|[p053_message_list_scope_sync_object_error.md](p053_message_list_scope_sync_object_error.md)|2026-10-25|未记录|fix/review-20261026-commits|
|p054|[p054_settings_account_management_refactor.md](p054_settings_account_management_refactor.md)|2026-10-25|未记录|fix/review-20261026-commits|
|p055|[p055_google_account_onboarding_ux_and_default_provider.md](p055_google_account_onboarding_ux_and_default_provider.md)|2026-10-25|未记录|fix/review-20261026-commits|
|p056|[p056_microsoft_oauth_onboarding_ux_and_credential_guidance.md](p056_microsoft_oauth_onboarding_ux_and_credential_guidance.md)|2026-10-25|未记录|fix/review-20261026-commits|
|p057|[p057_imap_custom_username_toggle.md](p057_imap_custom_username_toggle.md)|2026-10-25|未记录|fix/review-20261026-commits|
|p058|[p058_gmail_folder_tree_flattening.md](p058_gmail_folder_tree_flattening.md)|2026-10-27|未记录|main|
|p059|[p059_search_recipient_and_alias_support.md](p059_search_recipient_and_alias_support.md)|2026-10-27|未记录|main|
