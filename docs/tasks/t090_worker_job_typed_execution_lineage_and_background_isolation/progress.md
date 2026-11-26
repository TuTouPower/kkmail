---
tid: "t090"
slug: "worker_job_typed_execution_lineage_and_background_isolation"
title: "WorkerJob强类型执行血缘一等公民化与后台隔离"
status: "done"
branch: "t090_worker_job_typed_execution_lineage_and_background_isolation"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "452dc8f3d7308f2651a05aa16b2132508f6927dd"
spec_source_sha: "88d0e377f0abf0b063bd05424904cc83748b1fd0"
depends_on: "t089"
conflicts_with: ""
note: "来源 p095；WorkerJob 一等公民列与 Alembic 迁移、强制显式血缘与续跑继承"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 引入 `ExecutionOrigin`（`foreground` / `background`）与 `WorkerJob.execution_origin`（`String(32) NOT NULL`、`ck_worker_jobs_execution_origin` 与 `@validates`），彻底移除 `WorkerJob` 默认前台回落及历史 `sync_context_payload` shim；新增线性迁移 `20261125_0006`（基于 `20261124_0005`）并对齐 `CURRENT_HEAD_REVISION`。
- 为 `enqueue_job`、`enqueue_account_sync`、`sync_folder_delta`、`sync_account_folders`、`sync_folder_metadata`、`push_remote_operations` 全量启用必填 keyword-only `execution_origin` 契约；补齐轮询/巡检/IDLE 建连补偿与唤醒/常规归档等后台入口与全链路继承，并在合并/后继派生中实行前台优先合并与跨来源失效 lineage 剥离。
- 实施与 Review 前全量门禁验证通过后，按 Round 1 `review_test.md` 两条非阻断 `minor` 建议在主仓登记 `p097` 统一收口。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-25T19:58:50+08:00)

`review_code.md` Round 1 零 finding；`review_test.md` 2 条 non-blocking `minor` 转入 `p097`：

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t090_test_f001|minor|遗留|engine/remote_push 部分重试与重建分支的 background 覆盖扩展建议已转入待办|p097|
|t090_test_f002|minor|遗留|公开 push_remote_operations 替代私有 helper 及部分入口显式值断言已转入待办|p097|

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：`./scripts/run-mail-core-tests.sh run` 全量 PostgreSQL 门禁通过（`2263 passed, 2 skipped`，分支覆盖率 `86%`，含 `test_t090_migration_0006`、`test_t090_execution_origin`、`test_t090_coalescing_and_fencing` 及全量迁移升降级与 ORM 0 drift 校验）；`.venv/bin/pytest .repo_template/tests -q -m contract` 通过（`389 passed, 1 skipped`）；`npm --prefix src/frontend test`（56 文件 597 tests + `openapi:check` + `css:check`）、`tsc -b` + `vite build`、`npm --prefix src/desktop test`（12 套件）及 `scripts/check_doc_sensitive.py docs --check` 全部通过
- 黑盒：`npm --prefix src/frontend run test:e2e` 通过（`25 passed`）；`git diff --check` 与 `.repo_template/scripts/md_format.py --changed --check` 通过
- review：`review_level=full`；Round 1 `review_code.md` PASS（0 finding，`reviewed_scope: 97b54d5e4f037fb6`）、`review_test.md` PASS（2 条 non-blocking `minor` 遗留转 `p097`，`reviewed_scope: 97b54d5e4f037fb6`）
- AC 判定：见 `task.md` 行内打勾

### 结果摘要

- 将任务执行来源提升为 `WorkerJob.execution_origin` 一等公民列并完成全链路显式入队、继承与健康隔离；Round 1 两项非阻断测试扩展建议记录于 `p097`。

### 长期文档闭环

- [`docs/specs/mail_sync_and_storage.md`](../../specs/mail_sync_and_storage.md)：已于 front matter `tasks` 登记 `t090` 并补充一等公民执行血缘规范。
- `docs/blueprint/architecture.md`、`docs/blueprint/conventions.md`、`docs/blueprint/testing.md`：已同步一等公民模型、后台不污染连接态契约与 `20261125_0006` 迁移门禁。
