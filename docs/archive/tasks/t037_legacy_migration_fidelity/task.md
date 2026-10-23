---
tid: "t037"
slug: "legacy_migration_fidelity"
title: "保真迁移旧邮件字段与远端身份"
status: "done"
branch: "t037_legacy_migration_fidelity"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "22a3f23c48fa7e66daff400ca6f2db3c7cfd0c19"
depends_on: "t036"
conflicts_with: ""
note: "来源：审查确认旧库迁移补造主题发件人和时间、误判正文类型并伪造 UID。; 依赖 t036 的 sort_time nullable/API 语义后确定旧库时间映射，避免两个迁移语义并行变化。; 已扩展 AC-005：缺少 MessageArchiveState 时 is_archived 必须保持未知。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 历史 SQLite 核实：SQLite `id` 是本地自增行号；Graph 原始 `provider_message_id` 可作为唯一 canonical 远端 ID；IMAP UID 缺少 UIDVALIDITY，sequence/未知模式不可寻址。IMAP 日期缺少行级来源，Graph 日期仅保留有效带时区值。
- TDD：首轮回归测试先复现 importer helper 缺失与缺归档状态被 API 改成 `true`；review 新增 signed BIGINT 上界后，fixture 先复现 `9223372036854775808` 写入溢出和 5000 位十进制触发 Python `ValueError`，生产转换增加长度/字典序边界；边界值、超界值、空 subject/sender 都有真实 importer 持久化断言。
- Round 1 finding 已修，等待 Round 2 复核：`t037_code_f001`、`t037_test_f001`、`t037_test_f002`；具体处置见下表和对应 fix_ref。
- AC-005 回归测试保留真实 `run_archive_batch`，只 spy provider builder；确认 sync-body 返回 null、归档状态与 worker job 均未创建。
- 实现：迁移器只读 SQLite，UUID5 仅作本地 `Message.id`，仅 Graph 原始 ID 作为 `remote_id`，其他 legacy 行保留内容且 `remote_id=null`；缺失来源不填展示文本或时间。加入 nullable `Message.remote_id` migration；local-only read/flag 本地生效，trash/sync-body 返回不可寻址结果。
- 相关审计：远端 ID 消费点覆盖 archive fetch、reconcile、remote push、API sync-body、trash 与 ORM/唯一约束；无 null 值传给 provider。新邮件未知状态默认 false 是另一个已复现问题，登记 [`p024_unknown_mail_status_defaults.md`](../../pending/todo/p024_unknown_mail_status_defaults.md)，不扩入当前实现。
- 门禁观察：strict preflight PASS；唯一警告为工具把 24 个与本 task 相关的 API/schema/generated/frontend/migration/shared-spec 路径分类为 unrelated，逐项核实均属于当前 AC 或收尾规范文档。
- 测试环境：主仓 `.venv` 与 `src/frontend/node_modules` 依赖快照 15,264 项均未变化；t037 隔离 frontend copy 仅本轮 Vitest `.vite` 结果缓存改变。已移除 worktree `.venv` symlink、isolated `node_modules` copy 与依赖快照。测试 run ownership 均已清理；full-stack E2E 的 UUID 专属日志/blob/artifact 保留供核验。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-23T17:32:12+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t037_code_f001|important|已修|先按 signed BIGINT 最大位数与词典序拒绝超界，再转 int；5000 位输入保留邮件并令 uid=null。|scripts/migrate_from_legacy_db.py:104|
|t037_test_f001|minor|已修|fixture 覆盖 5000 位 UID；导入汇总与持久化断言确认整批继续，uid/remote_id 为 null。|tests/mail_core/test_legacy_migration.py:336|
|t037_test_f002|minor|已修|fixture 增加空字符串 subject/sender 并断言数据库保留空事实值。|tests/mail_core/test_legacy_migration.py:322|

### Round 2 (2026-10-23T17:38:11+08:00)

Round 2 零 finding；code/test 均 PASS，reviewed_scope=`e7d935c32ba1685d`。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足。
- 测试：后端完整套件 453 passed、0 failed/errors/skips、1 warning（run `3a7f83f770694c10b04ea71e7cee134e` 与首轮复核后 `48304c9a11154c86ac1f8044d87fd2ae`）；Round 1 修复后 importer/detail 定向 2 passed（`69bca3dfd794415ab01a5e7aa0d296ab`），最终 importer 边界定向 1 passed（`44e3a0f8c0244072b2bbaac44631a30d`），各含同一 Starlette deprecation warning；前端完整 256 tests / 39 files passed，`tsc -b`、build、lint、OpenAPI/schema/CSS 检查通过，收尾 API/Reader 定向 31 passed / 2 files；模板契约 149 passed / 367 deselected。
- 黑盒：stub browser E2E 13 passed；full-stack E2E 8 passed（run `f3290360ba79`），数据库与 API/Worker 进程由 runner 清理。
- review：Round 2 code/test PASS，reviewed_scope=`e7d935c32ba1685d`；Round 1 的 1 条 important 与 2 条 minor 全部修复，零遗留。
- AC 证据：见 `handoff.json`

### 结果摘要

- 旧邮件字段、时间与远端身份按可证来源迁移；不可寻址邮件保留本地内容和行为边界。AC-001..AC-008 全部通过。唯一范围外遗留状态问题登记为 p024。
