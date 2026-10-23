# Task review t045（reviewer_focus: 测试用例）

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
- 未进表的提示：测试充分覆盖 AC-001 ~ AC-005 的正向行为、异常场景及边界隔离，无弱化断言或假绿。

### AC 复验方式

- AC-001：`re_verified`。`src/frontend/src/components/Sidebar.test.tsx` 新增空文件夹下 `auth_failed` 展示错误提示及 `idle` 展示暂无文件夹两项用例，断言不渲染“未读邮件”；Vitest 实测通过。
- AC-002：`re_verified`。`tests/mail_core/test_global_stats.py` 新增用例断言排除故障 0 文件夹账号后汇总正常账号真实未读数、正常账号缺统计仍传播 null，以及分组统计的排除逻辑；单元套件与真实全栈 E2E 实测通过。
- AC-003：`re_verified`。`tests/mail_core/test_imap_id_handshake.py` 新增用例断言网易 `LOGIN Login error or password error` 严格抛出 `PermanentAuthError`；实测通过。
- AC-004：`re_verified`。`tests/mail_core/test_metadata_apply.py` 新增用例断言空文件夹执行 `apply_metadata_page` 后立即生成 `FolderStats(0, 0)`；实测通过。
- AC-005：`re_verified`。`tests/mail_core/test_worker_loop.py` 新增用例断言 `_evaluate_result` 重入队跟进任务保留 `folder_id` 等业务载荷并剥离 `_followup_*` 内部字段；实测通过。

- coverage = 5 / 5

- 总体判断：测试覆盖全面，断言直接锚定真实行为与数据结构，0 finding，判定 PASS。

- 系统性 follow-up：无。

verdict: PASS
