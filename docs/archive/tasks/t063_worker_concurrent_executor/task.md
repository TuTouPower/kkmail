---
tid: "t063"
slug: "worker_concurrent_executor"
title: "Worker 按连接预算并发执行任务"
status: "done"
branch: "t063_worker_concurrent_executor"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "6fd78aef33f7b145f9301da4144cd37b73cf71b1"
depends_on: "t062"
conflicts_with: ""
note: "来源 p063 根因 2；串行执行改为 total_slots 大小执行器，按 8/6 流量类别准入与同账号租约任务互斥"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. `claim_jobs` 引入 `LEASE_JOB_TYPES`，通过 `active_lease_accounts` 子查询实现同账号租约类任务的认领期排他，支持 `exclude_background` 流量分类过滤。
2. `handle_job` 将调用租约与归档操作时的 `worker_id` 细化为单次执行唯一的 `execution_owner = f"{worker_id}:{job.id}"`，解决同进程多线程执行时的 fencing token 与归档认领覆盖问题。
3. 重构 `src/mail_core/worker/main.py` 为按 `total_slots` 规模的并发执行池，实现 8/6 流量分类准入与前台容量保留；建立 `UnifiedClaimHeartbeatLoop` 全局统一心跳；周期调度与巡检探测异步化；优雅停机。
4. 修复 `src/mail_core/blobs/quota.py` 中 `_dir_size_cache` 的并发读写竞争（增加 `_dir_size_cache_lock`）。
5. 移除 `worker_claim_batch` 配置项、环境变量与桌面 sidecar 白名单。
6. 编写 8 项集成测试（`tests/mail_core/test_t063_worker_concurrent_executor.py`），覆盖 AC-001 至 AC-012。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-30T06:30:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`scripts/run-mail-core-tests.sh run -k test_t063_worker_concurrent_executor` (8 passed)
- 黑盒：`npm --prefix src/frontend run test:e2e` (18 passed)
- review：code PASS / test PASS (overall PASS)
- AC 证据：见 `handoff.json`

### 结果摘要

- Worker 执行模型改为按 `total_slots` 并发执行池，后台批量归档限制在途数，保障前台即时归档与写回不被压制；同账号租约任务排他认领；停机与心跳逻辑统一。
