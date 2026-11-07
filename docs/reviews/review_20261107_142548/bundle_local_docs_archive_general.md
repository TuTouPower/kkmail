# bundle_local_docs_archive_general

## responsibilities

- 维护全仓通用历史归档资产：历史 CHANGELOG、退役交接日志（archive/handoff.md）、旧版邮件内核重构架构方案（legacy_architecture/）
- 归档已闭环的待办事项（docs/archive/pending/），提供完整的缺陷重现、根因与修复追溯
- 维护历史归档 task 索引（archive/tasks_index.json）及历史串行实施计划（plan.md）

## interfaces

- docs/archive/pending/README.md：已闭环待办的闭环日期与处理指向总对照表
- docs/archive/tasks_index.json：历史归档任务机器索引

## dependencies

- src/ 与各 task 实现历史
- .repo_template/scripts/pending.py 待办归档工具链

## flows

- 缺陷由 bug-to-pending 记录到 docs/pending/todo/，修复并验证闭环后经 pending.py archive 移入 docs/archive/pending/

## constraints

- 历史文档只追加与快照原则
- 公开仓数据脱敏与隐私安全优先原则：当归档只读与敏感信息外泄冲突时，以脱敏优先，留勘误注记

## decisions

- 旧版 mail-core-architecture.md 保留作为设计溯源参考，头部增加清晰的过时/已取代注记
- docs/archive/CHANGELOG.md 封存时点后的变更由 git 提交历史与版本标签承载

## evidence

- docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3
- docs/archive/pending/p027_account_folder_sync_failure_and_unknown_unread_badge.md:11
- docs/archive/pending/README.md:15-75
- docs/archive/legacy_architecture/mail-core-architecture.md:1-5

## uncertainties

- 历史 pending 正文中除已发现项外，是否仍隐性存在未严格符号化的测试别名邮箱

## Findings

- [High][95] docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3 — 已归档 pending 正文泄露真实用户个人 Gmail 邮箱地址

    - ID: f_docs_archive_general_p060_pii_leak; verification: static
    - Evidence: docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md:3 正文写出："用户截图 2026-10-27（账号 xiaoxiaoguang2000@gmail.com）。"; xiaoxiaoguang2000@gmail.com 明显为用户真实个人邮箱，非 example.com / test.com 等脱敏样例，直接导致个人 PII 隐私在公开仓外泄
    - Impact: 公开仓库中直接暴露特定开发者的真实个人邮箱，面临垃圾邮件骚扰与身份关联风险，违反开源安全脱敏铁律
    - Fix: 将 xiaoxiaoguang2000@gmail.com 替换为符合 RFC 2606 的脱敏样例（如 user_gmail@example.com），并在文末注明脱敏修订

- [Medium][90] docs/archive/pending/p027_account_folder_sync_failure_and_unknown_unread_badge.md:11 — 已归档 pending 仍残留真实口令长度特征描述未脱敏

    - ID: f_docs_archive_general_p027_credential_characteristic_leak; verification: static
    - Evidence: docs/archive/pending/p027_account_folder_sync_failure_and_unknown_unread_badge.md:11 描述："（当前保存口令长 13 位，非有效 16 位网易客户端授权码或口令错误）"; 在第四轮 review（review_20261027_021416/review_intensive.md:11）中已作为 Critical 明确指出应"删除账号 UUID 与口令长度描述"，当前仍保留了 13 位口令长度的具体特征
    - Impact: 泄露了特定账号的密码长度与凭据特征，降低了口令字典破解空间
    - Fix: 删除"当前保存口令长 13 位"等精确长度描述，泛化为"因口令配置不匹配导致认证失败"

- [Low][90] docs/archive/pending/README.md:15-75 — docs/archive/pending/README.md 闭环日期对照表漏登 p060 至 p074

    - ID: f_docs_archive_general_pending_readme_index_drift; verification: static
    - Evidence: docs/archive/pending/README.md 的闭环日期对照表只记录到 p059（Line 75），共 59 条; docs/archive/pending/ 目录下实际已存在 p060 至 p074（共计 71 个条目，缺 14 条索引）
    - Impact: 归档待办索引总账与磁盘实际文件不一致，破坏了归档总账的完整性与可检索性
    - Fix: 使用脚本重新抓取 p060 至 p074 的 git 入库日期与处理指向，在 README.md 闭环日期对照表中补全缺失行

## views

```json
{
  "security": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "correctness": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "contracts": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "performance": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "design": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "robustness": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "tests": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "documentation": {
    "status": "completed",
    "reviewer": "subagent_docs"
  }
}
```

## files_reviewed

```json
[
  "docs/archive/CHANGELOG.md",
  "docs/archive/handoff.md",
  "docs/archive/legacy_architecture/mail-core-architecture.md",
  "docs/archive/pending/README.md",
  "docs/archive/pending/p001_trash_action_ux_mismatch.md",
  "docs/archive/pending/p002_empty_body_reader_blank.md",
  "docs/archive/pending/p003_client_filter_pagination_conflict.md",
  "docs/archive/pending/p004_imap_basic_auth_disabled_retry_loop.md",
  "docs/archive/pending/p005_worker_unbound_local_account.md",
  "docs/archive/pending/p006_attachment_size_human_readable.md",
  "docs/archive/pending/p007_settings_general_fields_sync_issue.md",
  "docs/archive/pending/p008_sidebar_accounts_failure_handling.md",
  "docs/archive/pending/p009_refresh_sync_and_imap_id_handshake.md",
  "docs/archive/pending/p010_remote_images_banner_dark_mode.md",
  "docs/archive/pending/p011_imap_raw_gbk_header_mojibake.md",
  "docs/archive/pending/p012_apple_mail_dark_mode_background.md",
  "docs/archive/pending/p013_account_folder_tree_support.md",
  "docs/archive/pending/p014_sidebar_collapse_hide_and_toggle_relocate.md",
  "docs/archive/pending/p015_account_avatar_style_setting.md",
  "docs/archive/pending/p016_mark_all_read_sync_convergence.md",
  "docs/archive/pending/p017_account_order_drag_and_drop.md",
  "docs/archive/pending/p018_account_folder_tree_layout_and_focus_ring.md",
  "docs/archive/pending/p019_clipboard_copy_permission_denied.md",
  "docs/archive/pending/p020_imap_header_mojibake_history_backfill_and_mime_gap.md",
  "docs/archive/pending/p021_on_demand_message_body_sync.md",
  "docs/archive/pending/p022_message_reader_body_preview_leak.md",
  "docs/archive/pending/p023_macos_sidebar_drag_validation.md",
  "docs/archive/pending/p024_unknown_mail_status_defaults.md",
  "docs/archive/pending/p025_partial_provider_delta_fidelity.md",
  "docs/archive/pending/p026_sidebar_tree_alignment.md",
  "docs/archive/pending/p027_account_folder_sync_failure_and_unknown_unread_badge.md",
  "docs/archive/pending/p028_mail_list_cache_prefix_folder_collision.md",
  "docs/archive/pending/p029_dark_mode_background_colors.md",
  "docs/archive/pending/p030_missing_headers_blank_and_body_sync_copy.md",
  "docs/archive/pending/p031_repaired_mime_parse_error_blocks_body_and_fetch_error_conflation.md",
  "docs/archive/pending/p032_settings_account_domain_filter.md",
  "docs/archive/pending/p033_settings_account_edit_action.md",
  "docs/archive/pending/p034_account_sync_failure_self_healing_and_sidebar_status_discrepancy.md",
  "docs/archive/pending/p035_empty_archived_mail_body_placeholder.md",
  "docs/archive/pending/p036_sync_job_error_double_requeue.md",
  "docs/archive/pending/p037_mailbox_folder_role_aliases.md",
  "docs/archive/pending/p038_qq_other_folder_search_failure.md",
  "docs/archive/pending/p039_body_sync_retry_loop.md",
  "docs/archive/pending/p040_fetch_timeout_setting_not_applied.md",
  "docs/archive/pending/p041_unread_badge_stale_on_mark_read.md",
  "docs/archive/pending/p042_copy_account_email_on_click.md",
  "docs/archive/pending/p043_sidebar_account_search_button.md",
  "docs/archive/pending/p044_web_insecure_context_clipboard_copy_failure.md",
  "docs/archive/pending/p045_sidebar_search_click_outside_auto_hide.md",
  "docs/archive/pending/p046_sync_button_spin_and_remove_banner.md",
  "docs/archive/pending/p047_incoming_mail_sync_latency.md",
  "docs/archive/pending/p048_message_reader_already_archived_race.md",
  "docs/archive/pending/p049_settings_header_cleanup_and_sidebar_toggle_relocate.md",
  "docs/archive/pending/p050_sidebar_settings_button_background_style.md",
  "docs/archive/pending/p051_sidebar_account_folder_order_and_indent.md",
  "docs/archive/pending/p052_ui_reference_overlay_prod_and_shortcut_setting.md",
  "docs/archive/pending/p053_message_list_scope_sync_object_error.md",
  "docs/archive/pending/p054_settings_account_management_refactor.md",
  "docs/archive/pending/p055_google_account_onboarding_ux_and_default_provider.md",
  "docs/archive/pending/p056_microsoft_oauth_onboarding_ux_and_credential_guidance.md",
  "docs/archive/pending/p057_imap_custom_username_toggle.md",
  "docs/archive/pending/p058_gmail_folder_tree_flattening.md",
  "docs/archive/pending/p059_search_recipient_and_alias_support.md",
  "docs/archive/pending/p060_gmail_virtual_folder_not_selectable.md",
  "docs/archive/pending/p061_ui_reference_element_coverage_and_overlay_overlap.md",
  "docs/archive/pending/p062_sidebar_toggle_all_account_folder_trees.md",
  "docs/archive/pending/p063_mail_body_sync_queue_hang_and_delay.md",
  "docs/archive/pending/p064_sidebar_scrollbar_gutter_layout_shift.md",
  "docs/archive/pending/p065_message_reader_height_and_dark_scrollbar.md",
  "docs/archive/pending/p066_remote_images_reload_and_source_allow.md",
  "docs/archive/pending/p067_cid_inline_image_mapping.md",
  "docs/archive/pending/p068_reader_view_mode_override_lifecycle.md",
  "docs/archive/pending/p069_remote_image_extract_unquoted_src.md",
  "docs/archive/pending/p070_idle_reconnect_missed_inbox_mail.md",
  "docs/archive/pending/p071_t061_idle_watcher_preexisting_red_tests.md",
  "docs/archive/pending/p072_idle_catchup_enqueue_failure_starvation.md",
  "docs/archive/pending/p074_blob_file_mode_backup_unreadable.md",
  "docs/archive/plan.md",
  "docs/archive/tasks_index.json"
]
```
