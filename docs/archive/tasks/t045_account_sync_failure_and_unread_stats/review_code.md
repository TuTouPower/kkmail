# Task review t045（reviewer_focus: 代码）

- task：`t045_account_sync_failure_and_unread_stats`
- spec：`docs/tasks/t045_account_sync_failure_and_unread_stats/spec.md`
- diff_anchor：`f925d16094950ec856dc837319e40c15b91dbfe8`
- target：`git -C '/Users/karson/kar/code/kkmail_t045' diff f925d16094950ec856dc837319e40c15b91dbfe8`
- round：1
- reviewed_at：2026-10-23T22:20:00+08:00
reviewed_scope: 3a36868d176bf82c

## Findings

无。

## 结论

- 前轮 finding 复核：首轮，无前轮 finding。
- 本轮新发现：0 条。
- 未进表的提示：规格合规、实现正确性、安全、契约·类型、性能·资源、架构·可维护性、健壮性·可观测、测试与文档均已全面核验；无范围外修改。

### AC 复验方式

- AC-001：`re_verified`。核验 `Sidebar.tsx` 中 `AccountFolders`：当 `folders.length === 0` 时，若 `syncStatus` 为 `auth_failed` / `failed` 渲染“同步失败，请检查账户设置”，否则渲染“暂无文件夹”，不再单独裸露虚拟“未读邮件”按钮。
- AC-002：`re_verified`。核验 `queries.py` 中 `query_global_inbox_stats` 与 `query_group_inbox_stats`：排除 `folder_count == 0` 且 `sync_enabled=False` 或 `sync_status in ('failed', 'auth_failed')` 的故障账号后计算 `total_unread`；核验 `MessageList.tsx` 与 `Sidebar.tsx`：统一单账号与多账号在 0 目录或故障状态下的未知与聚合排除语义。
- AC-003：`re_verified`。核验 `imap.py:328`：`_connect` 捕获 `imaplib.IMAP4.error` 时匹配 `login error or password error` 抛出 `PermanentAuthError`，阻断 8 次重试并使账号置为 `auth_failed` 及 `sync_enabled=False`。
- AC-004：`re_verified`。核验 `metadata.py:193`：`apply_metadata_page` 检查若 `FolderStats` 尚不存在即触发 `recompute_folder_stats`，空目录立即初始化 `total_count=0, unread_count=0`。
- AC-005：`re_verified`。核验 `worker/handlers.py:34-42`：跟进任务重新入队时过滤内部 `_followup_*` 键，完整保留原业务 `payload`（如 `folder_id`）。

- coverage = 5 / 5

- 总体判断：全部 5 条 AC 实现均精准满足契约区要求，0 finding，判定 PASS。

- 系统性 follow-up：无。

verdict: PASS
