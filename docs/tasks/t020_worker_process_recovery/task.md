---
tid: "t020"
slug: "worker_process_recovery"
title: "验证多进程 Worker 竞争与故障后恢复"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: "t016"
conflicts_with: "t012,t013,t014,t015,t016,t017,t018,t019,t021,t022,t023"
note: "本会话批准测试增强；本地复用专用 PG 容器、每轮独立测试库；仅创建 backlog"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

2026-10-22 核实 test_sync_leases_jobs.py 为真实双事务，test_chaos_lease_recovery.py 为回写时间模拟死亡；本 task 增加进程层验证，不否定现有测试价值。

### 2026-10-22 主分支执行

- 用户明确要求直接在 main 分支按顺序执行 t013–t023，每完成一个 task 独立 commit。
- 生产优化：在 `src/mail_core/worker/main.py` 支持 `MAIL_CORE_RECLAIM_STALE_SECONDS` 配置回收陈旧任务的超时阈值，默认保持 300 秒（5分钟），使测试能够以自然时间（如 2 秒）演进真实过期，无需在数据库修改时间字段。
- 新增 `tests/mail_core/test_worker_process_recovery.py`：
    - AC-001：启动两个独立真实 Worker 进程，并发竞争一批跨账号任务，验证 SKIP LOCKED 独占认领、活动 claim 不重叠、租约互斥，全部 6 个任务顺利完成，无重复执行；
    - AC-002：对正在处理任务的 Worker 1 真实发送 `SIGKILL` 强制终止，等待自然超时（2.2s）后由存活的 Worker 2 自动 reclaim 并在独立 session 中接管执行完成，任务标记 `reclaimed_stale_claim`；
    - AC-003：模拟旧持有者携陈旧 token 恢复提交，调用 `assert_fencing` 触发 `FencingMismatch` 异常，阻止覆盖新数据；
    - AC-004：API 与 Worker 分离进程模式下，Worker 提交事务后真实 LISTEN/NOTIFY 触发事件派发，显式 rollback 事务严格不广播；
    - AC-006：`managed_subprocesses` fixture 使用独立 process group，测试收尾时以 `os.killpg(..., signal.SIGKILL)` 严格清理全部子进程，无僵尸进程。
- 门禁通过：3 项测试全通过 (8.25s)。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

- 已修：子进程环境变量显式补充 `PYTHONPATH`、`MAIL_CORE_BLOB_KEY_V1`、`MAIL_CORE_SECRET_KEY`；
- 已修：更新已废弃的枚举 `JobStatus.DONE`；
- 双人审查（code + test）结论均 PASS。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：多进程 Worker 并发竞争与故障后恢复验证完成，全行为 AC 均满足。
- 测试：`scripts/run-mail-core-tests.sh run -k test_worker_process_recovery` 3 passed。
- 黑盒：两个真实操作系统 Worker 进程并发争夺同一批任务、SIGKILL 强制终止后由存活进程自动 reclaim 继续执行、跨进程事务性 NOTIFY 广播与回滚隔离。
- review：`review_code.md` PASS，`review_test.md` PASS。
- AC 证据：`test_worker_process_recovery.py` 终端实测输出。

### 结果摘要

建立了基于真实操作系统多进程的 Worker 并发与故障恢复测试体系，验证了基于 SKIP LOCKED 的非重叠任务争夺、真实 SIGKILL 杀进程后存活 Worker 的自然超时回收与幂等完成、基于 fencing token 的陈旧提交防护，以及跨进程 PostgreSQL NOTIFY 事件广播与事务回滚隔离。
