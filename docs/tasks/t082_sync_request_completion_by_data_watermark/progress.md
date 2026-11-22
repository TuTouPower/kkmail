---
tid: "t082"
slug: "sync_request_completion_by_data_watermark"
title: "从根因重构同步请求完成判定：数据水位驱动替代执行代际观察"
status: "done"
branch: "t082_sync_request_completion_by_data_watermark"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "1998e95ff67999ac896b9e118b47902ebfefdfc8"
spec_source_sha: "1998e95ff67999ac896b9e118b47902ebfefdfc8"
depends_on: ""
conflicts_with: ""
note: "p083：手动同步误报 execution_lost，预分配后继代际绑定机制抽象错位，需彻底解耦请求完成与任务调度状态"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 根因处理：删除 `WorkerJob.execution_generation` 与 `_queue_next.execution_generation` 的预分配语义。同步请求目标与任务的关联改为只指向真实 `WorkerJob` 行：重试/回收共享同一 job 行；任务处于 CLAIMED 期间到达的请求关联该真实任务并标记 `needs_successor`，`complete_job` 先创建后继、再在同事务把等待关联迁移到后继。不存在指向尚未创建执行的关联，`execution_lost` 状态类无法再产生。
- 失败语义：终态失败写稳定 `error_code` 与用户可读 `safe_error`（`sync_incomplete` / `baseline_required` / `account_deleted` / `folder_deleted`）；新增 `converge_stalled_targets` 替换孤儿巡检，对停滞目标给出可操作重试提示，不留悬挂请求。
- 迁移：`20261122_0003_real_job_links` 清理 `job_id IS NULL` 的历史关联并把其目标收敛为可读失败，修改外键为级联，移除两个 generation 列；`baseline.py` head 同步更新。
- 测试：新增 `test_sync_request_completion_by_data.py` 覆盖 CLAIMED 到达、后继迁移、终态失败文案与链接真实性；重写 `test_sync_execution_tracking.py`、`test_sync_execution_lock_order.py`、`test_sync_lock_order_unified.py`、`test_sync_settlement_target_prelock.py`、`test_sync_successor_binding_backfill.py`、`test_sync_execution_unit.py` 等为真实 job 关联语义。
- 删除三个纯代际巡检测试（`test_a322_live_generations_payload.py`、`test_sync_orphan_patrol_live_generations.py`、`test_sync_orphan_patrol_stale_snapshot.py`）：其被测机制（预分配后继 + 孤儿巡检 live-generation 快照）已整体移除，保留将断言已不存在的 API；新等价能力由 `test_sync_request_completion_by_data.py` 与 `converge_stalled_targets` 覆盖。
- 门禁结果：`test_cmd` 全通过（模板契约 388 passed、前端单测/tsc/build、桌面单测、敏感扫描 0 违规）；`blackbox_verify` 23 passed；后端完整 PostgreSQL 套件 2202 passed / 2 skipped。唯一失败 `test_cookie_secure_guard_ignores_out_of_tree_symlink` 为环境既存：harness 默认 basetemp 位于 worktree 内，使该测试构造的「外部」软链实际在树内；main 分支同命令同失败，且与本 task 无关，以外部 basetemp 重跑该用例通过。

## Review 处置

### Round 1 (2026-11-22T15:40:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t082_code_f001|important|已修|停顿巡检原按 created_at 误杀仍在推进的长账号同步；改为跳过关联 PENDING/CLAIMED 真实 job 的目标|src/mail_core/sync/execution.py:471-520|
|t082_test_f001|minor|遗留|迁移数据修复路径缺可执行断言，需先建中间版本临时库夹具|p084|
|t082_test_f002|minor|已修|补瞬时失败后重试完成请求的直接断言|tests/mail_core/test_sync_request_completion_by_data.py|
|t082_test_f003|minor|已修|known_revisions 由 == 改为 \<= 以容纳新增中间迁移，理由已写明|tests/mail_core/test_baseline_unit.py|

Round 1 代码轴 FAIL、测试轴 PASS；按门禁撤回全部 AC 打勾后修复 f001，重跑测试与黑盒，Round 2 重新打勾并复审。

### Round 2 (2026-11-22T16:20:00+08:00)

Round 2 零 finding。

代码轴 PASS / 测试轴 PASS，`review_status overall=PASS / review_scope=ok / ac_review=ok`；AC 8/8 TICK-VALID。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足（Round 2 复审通过后）
- 测试：后端完整 PostgreSQL 套件 2202 passed / 2 skipped；`test_cmd` 全通过；唯一失败为 main 同现的环境既存用例（cookie t079 out-of-tree symlink 守卫，basetemp 在 worktree 内所致），外部 basetemp 重跑通过
- 黑盒：`npm --prefix src/frontend run test:e2e` 23 passed
- review：Round 2 见本报告「Review 处置」；代码轴与测试轴均 PASS
- AC 判定：见 `task.md` 行内打勾

### 结果摘要

- 根因重构完成：同步请求完成不再依赖预分配执行代际，execution_lost 状态类与内部文案移除；待 Round 2 复审确认。

### 长期文档闭环

- `docs/specs/mail_sync_and_storage.md` front matter `tasks` 已登记 t082，并新增「同步请求完成判定由真实工作驱动」契约。
- `docs/blueprint/architecture.md` 新增「同步请求完成判定：真实工作驱动 (t082)」。
- `docs/blueprint/conventions.md` 新增同步请求完成与失败文案约定。
