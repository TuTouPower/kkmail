---
tid: "t074"
slug: "inbox_first_account_sync"
title: "账号级同步收件箱优先与同步链重排优先级保持"
status: "done"
branch: "t074_inbox_first_account_sync"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "923bc4b1628e5a528191401d0e903d0935f0d264"
depends_on: ""
conflicts_with: ""
note: "来源 p073；手动刷新收件箱排在全部文件夹 delta 之后串行执行；inbox 优先入队并在 delta 重排时保持优先级; review 修订：metadata 重排路径纳入优先级保持；测试改为断言 priority 数值严格小于同账号其他文件夹；明确不抢占在途任务、无 inbox 时回退、优先级全局副作用"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 实施：`src/mail_core/sync/engine.py` 文件夹发现入队改为收件箱优先（delta 55 / metadata 45，判据 `role == "inbox"`，其余文件夹保持 60 / 50）；`sync_folder_metadata` 新增 `priority` 参数（默认 50），租约冲突、限流、连接预算不足、分页未耗尽四处重排改用该参数，cursor-invalid 重建保持显式 40。`src/mail_core/sync/delta.py` 的 `sync_folder_delta` 与 fencing 重排新增 `priority` 参数（默认 60），租约冲突、限流、容量不足、临时 provider 错误、分页未耗尽五处重排与 fencing 重排改用该参数。`src/mail_core/worker/handlers.py` 的 metadata / delta handler 透传已认领任务的 `job.priority`。
- 非范围项未动：`sync_account_folders` 自身的容量/限流重排（60）、metadata 完成后的新 delta（60）、对账（80）、增量连带归档批次（60）、归档批任务（40）。
- 新增测试 `tests/mail_core/test_sync_inbox_first.py`（22 项，含参数化；与仓库既有集成测试一致地以 `MAIL_CORE_DATABASE_URL` 门控）。本机无 Docker、无测试 PostgreSQL，该文件在本机全数 skip；同一场景另以 `.scratch/` 下的 SQLite harness 驱动真实同步代码取红/绿证据：基线代码 14 项检查失败（发现优先级 60/50、handler 后继 75→60 与 55→50、首认领非收件箱），实现后 50/50 全部通过（harness 为一次性验证脚本，不入库）。PG 环境复跑仍欠。
- 门禁（与干净 base `923bc4b1` 同口径对照）：doctor 契约收集 223 项；contract 全量 222 passed / 1 skipped；`tests/mail_core` unit 模式 1418 passed / 6 failed / 376 skipped，6 条失败与 base 失败集逐行一致（均为无数据库环境失败），零新增失败，skipped 增量 22 即新增测试文件；前端 `npm test`、`tsc -b`、`npm run build` 通过；桌面 `npm test` 在 base 与本分支同为 electron 依赖缺失导致的既存失败（本 task 未触及桌面代码）。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-05T04:35:00+08:00)

review_code：零 finding，PASS，AC 5/5 TICK-VALID。

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t074_test_f001|minor|已修|AC-003 重排后「收件箱先于同账号兄弟同类任务被认领」原无直接组合测试，仅由优先级等值断言与发现用例间接支撑；已补直接组合测试并经 harness 同场景真跑通过|tests/mail_core/test_sync_inbox_first.py（test_requeued_inbox_delta_claimed_before_sibling）|

### Round 2 (2026-11-05T04:40:00+08:00)

review_code：PASS，零 finding，AC 5/5 TICK-VALID；review_test：PASS，零新 finding，确认 t074_test_f001 已消除（新增组合测试经独立复跑 harness 50/50 与代码锚点复核），AC 5/5 TICK-VALID。两路 `reviewed_scope` 一致（c3352168a06b021e）。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：`tests/mail_core` unit 模式 1418 passed / 6 failed / 376 skipped（失败集与 base 逐行一致、零新增）；contract 222 passed / 1 skipped；新增 `tests/mail_core/test_sync_inbox_first.py` 22 项本机 PG 门控 skip，核心场景经 SQLite harness 真跑 50/50 通过（基线同 harness 14 项失败），PG 环境复跑仍欠
- 黑盒：`npm --prefix src/frontend run test:e2e` 21 passed；前端 `npm test`、`tsc -b`、`npm run build` 均通过
- review：full review 两轮——Round 1 code 路 PASS 零 finding、test 路 PASS 1 条 minor（AC-003 认领次序组合测试缺口）；补测修复后 Round 2 双路 PASS、零 finding，AC 5/5 双路 TICK-VALID，reviewed_scope c3352168a06b021e
- AC 证据：见 `handoff.json`

### 结果摘要

- 账号级发现入队收件箱优先（delta 55、metadata 45），delta/metadata 全部重排路径保持原任务 priority，cursor-invalid 重建保持 40，无 inbox 账号回退现有行为，请求终态语义不变；无新增 pending，遗留仅 PG 环境复跑（环境缺口，非缺陷）。
