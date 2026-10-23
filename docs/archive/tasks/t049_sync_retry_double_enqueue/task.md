---
tid: "t049"
slug: "sync_retry_double_enqueue"
title: "避免同步失败后重复排队重试任务"
status: "done"
branch: "t049_sync_retry_double_enqueue"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "2185a75bbeaa53b10d9c81c3fb4b73ba634ee563"
depends_on: ""
conflicts_with: ""
note: "来源 p036；用户要求直接在 main 修复。同步层已创建后继重试时，Worker 不应再次重试原任务。; 已在 main 完成修复与部署（0ffe35c）；task.py finish 仍要求 active 自有 worktree，状态保留 backlog，未伪造状态或 handoff。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 用户明确要求直接在 `main` 修复。同步入口在已提交后继任务的结果中返回 `followup_scheduled`；Worker 据此完成原任务，并跳过 `_followup_needed` / `_followup_run_after` 的二次入队。`provider_error` 仍更新账号失败状态，普通无后继错误继续走 `fail_job`。实现提交：`0ffe35c`。
- TDD：新增 PostgreSQL 与 Worker 回归，先复现五类内部入队缺标记，再复现 claimed job 带 `_followup_needed` 时出现两条 pending；修复后确认只剩一条。p036 已归档并单独提交。
- 直接 main 实施已在 `0ffe35c` 完成并通过 Round 4 review。用户随后要求归档 task；本 attempt 只收敛已完成实现的 task 状态，代码与测试保持 `2185a75` 基线内容，不新增生产改动。此前保留 `backlog` 是启动归档流程前的状态记录，不代表当前 attempt 状态。
- 当前 attempt：`attempt=1`，`execution_id=235b282b69f742bfa00aaa7e14ebc2a6`；`diff_anchor=2185a75bbeaa53b10d9c81c3fb4b73ba634ee563`。
- 门禁说明：active 初始 `preflight --require-verified` PASS。当前 validator 将只有 `[x]` 的已完成 AC 当成空验收标准；最终 AC 标记后不把该错误报告为 preflight 通过，AC 与行为证据由 Round 5 review 复核。
- final preflight 复验结果：工具报 `spec.md 验收标准为空`，原因是 `validate_task_documents` 仅识别 `- [ ]`，不接受已完成 `- [x]`；review checker 为 PASS，未修改 `.repo_template` 工具链。
- 备份：`[backup.kkbak](../../.scratch/deploy_backups/2026-10-24T03-41-57+08:00/backup.kkbak)`，密封校验 3 members，4,190,955,556 bytes，SHA-256 `4b95152b2911bebfdbd97577bbedeb6d2cdb076725d658169f7b3e92eb4def7c`。
- 部署：Compose distributed profile 重建 API、Worker、migrate；迁移退出码 0，`/health` 与 `/ready` 返回 200，schema `20261023_0019`。SPA、JS、CSS HTTP 200，资源 hash 与本地 dist 一致；部署前镜像保留为 `rollback-0ffe35c`。
- review prompt 渲染要求非空 `diff_anchor`，而直接 main 没有该字段。代码与测试 reviewer 按既有 direct-main 约定独立审查，Round 4 PASS，`reviewed_scope=1eb3b40c21ee29c1`；不声称通过 task-work attempt 门禁。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-24T03:26:52+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t049_code_f001|important|已修|Round 2 加入 guard：同步层已有后继时跳过 Worker 通用 followup 入队；PG 回归覆盖原 job 带 `_followup_needed`。Round 4 复核 PASS。|`src/mail_core/worker/handlers.py:61`|

### Round 2 (2026-10-24T03:28:46+08:00)

Round 2 零新 finding；代码 finding `t049_code_f001` 已按上表处置。

### Round 3 (2026-10-24T03:38:22+08:00)

Round 3 零 finding；复核最终 spec 勾选与测试覆盖。

### Round 4 (2026-10-24T03:47:43+08:00)

Round 4 零 finding；基线改用 `cdfafc7`，排除独立 t050 task 登记。

### Round 5 (2026-10-24T04:15:13+08:00)

Round 5 零 finding；code/test reviewer 均 PASS，`reviewed_scope=8f66d190d7e01e1a`。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：AC-001 至 AC-003 全部满足；p036 已归档；本 task 通过 lifecycle 状态归档。
- 测试：模板契约 149 passed / 1 skipped；t049+t050 合并后 mail-core 500 passed，1 条既有 Starlette deprecation warning；本 worktree 定向 PG 11 passed；前端 274 passed、OpenAPI/CSS、TypeScript、build、oxlint 通过；桌面单测与 packaged smoke 通过。
- 黑盒：stub UI E2E 16 passed；真实全栈 E2E 8 passed；部署后 health/ready/index/JS/CSS smoke 全部 200。
- review：代码与测试 reviewer Round 5 PASS，0 未解决 finding；`reviewed_scope=8f66d190d7e01e1a`。code review 复核 source AC/当前实现；test review 复核 PG 测试、覆盖和既有 500 passed 结果。
- AC 证据：

|AC|实际证据|
|---|---|
|AC-001|`test_delta_and_metadata_lease_busy_results_mark_existing_retries`、delta 与 metadata cursor invalid 用例、provider error Worker 集成用例覆盖五个后继入队路径并验证 `followup_scheduled`。|
|AC-002|`test_delta_provider_error_completes_claim_and_leaves_one_pending_retry` 验证真实 PostgreSQL 下原 job 完成、带 `_followup_needed` 时仍只留一条 pending；Worker 单测验证已排队标记不再调用 `fail_job`。|
|AC-003|同一 provider error 集成用例验证账号仍为 failed、错误摘要已脱敏；`test_evaluate_result_still_fails_without_a_scheduled_followup` 验证普通错误仍调用 `fail_job`。|

### 结果摘要

- 修复提交：`0ffe35c`；pending 登记/归档提交：`9a112d3`、`d3fd350`。
- Worker 与同步入口共享 `followup_scheduled` 队列所有权标记；五种同步内部入队路径不再与 Worker retry 叠加。
- 构建并重新部署 Docker Compose distributed API/Worker；部署前 sealed backup 已校验，健康与静态资源 smoke 通过。
