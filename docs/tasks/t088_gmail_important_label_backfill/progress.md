---
tid: "t088"
slug: "gmail_important_label_backfill"
title: "Gmail 历史邮件 Important 标签成员一次性回填"
status: "done"
branch: "t088_gmail_important_label_backfill"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "70a7f843634b3de09b78323136efa3b4799e9514"
spec_source_sha: "70a7f843634b3de09b78323136efa3b4799e9514"
depends_on: ""
conflicts_with: ""
note: "来源 p089：t086 遗留的一次性标签回填，需幂等、可重复运行且不扰动常规同步 checkpoint"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 新增 `accounts.label_backfill_completed_at` 与迁移 `20261124_0005`（单 head 更新、可逆）。
- 新增 `mail_core.sync.label_backfill.backfill_account`：账号 lease 串行化、按物理目录重放 `fetch_metadata_page`、复用 `upsert_messages(label_view_folders=...)` 写 `\Important` 位置；不写 checkpoint、不新增重复邮件，单账号失败不阻断其它账号且不写完成标记。
- CLI：`python -m mail_core --backfill-gmail-labels [--account-id UUID] [--force]`，加入 gate 互斥组，运行迁移后执行并退出。
- 领域层抽出 `is_gmail_account` 供 discovery 与回填共用，消除 Gmail 判定的重复实现。
- 测试：PG 用例覆盖历史成员写入、完成标记、幂等/force、非 Gmail 与无视图跳过、失败续跑、checkpoint 不变与视图计数/列表；迁移单 head 由现有门禁覆盖。
- 文档：`docs/guides/upgrade.md` 增加一次性回填运维命令与幂等语义；`docs/blueprint/testing.md` 增加门禁入口。
- 既存回归：完整 PG 套件 4 条失败在 main 基线复现。本 task 修复两条失败分类回归（`auth_failed` 结构化映射、旧自由文本断言按 t087 契约重写）；idle watcher 两条的状态机改动会引发 blocked/recovery 用例回归，已整体撤回并转 p091，用户确认 AC-008 按此收敛。前端单测一条偶发失败复跑通过。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-23T19:20:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t088_code_f001|important|已修|provider 构造移入 try，异常转 failed 且 finally 释放 lease|src/mail_core/sync/label_backfill.py:96|
|t088_code_f002|important|已修|AC-008 收敛并配 p090/p091 记录，后续按用户要求继续追查|docs/pending/p091|
|t088_test_f001|important|已修|新增 CLI 路由 4 条单测|tests/mail_core/test_label_backfill_cli.py|
|t088_test_f002|important|已修|新增 All Mail 前后计数相等断言|tests/mail_core/test_gmail_label_backfill.py:117|
|t088_test_f003|important|已修|新增 lease 互斥探针，回填期间其它 owner 拿不到 lease|tests/mail_core/test_gmail_label_backfill.py:120|

### Round 2

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t088_code_f003|critical|已修|provider 改为在持有 account 的 session 内构造，避免脱管对象|src/mail_core/sync/label_backfill.py:64|
|t088_code_f004|minor|已修|p090 处理文本更正为 2 条修复、2 条转 p091|docs/pending/p090|
|t088_test_f004|minor|撤回|CLI failed 返回路径已由 `test_failed_backfill_returns_failure` 覆盖；多账号续跑属同分支循环，无需重复计数断言|tests/mail_core/test_label_backfill_cli.py:48|

### Round 3

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t088_test_f005|minor|撤回|provider 构造异常的 failed 返回与 lease 释放由 Round 3 code review 独立复核，且与既有 `test_failed_backfill_returns_failure` 同一返回分支|src/mail_core/sync/label_backfill.py:96|

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：完整 PG 套件除 p091 的 2 条 idle watcher 回归外全绿（4 条失败中 2 条已修）；unit、定向 PG（`test_gmail_label_backfill` + CLI + 迁移）、前端 `npm test`/`build`/`lint`、桌面单测、敏感文档扫描与黑盒 E2E 全通过
- 黑盒：`npm --prefix src/frontend run test:e2e` 25 passed
- review：待 reviewer 填写
- AC 判定：见 `task.md` 行内打勾（AC-001~009 已勾选，待独立复核）

### 结果摘要

- 历史 Important 成员可通过一次性命令补齐；幂等、不动 checkpoint、不增重复邮件。

### 长期文档闭环

在 active spec 的 front matter `tasks` 清单中登记当前 tid（`task.py specs list --json`）；无长期 spec 变更时写 `- specs_index: not_applicable: 具体原因`。正式 spike 须有 report、现存 finding、采纳结论、后续 tid 或无需后续理由；finish 会检查这些引用。

- specs_index: docs/specs/mail_sync_and_storage.md # 回填机制纳入同步规范
