---
tid: "t083"
slug: "test_service_session_lifecycle"
title: "测试服务生命周期改为会话制：按需拉起、会话内常驻、空闲自动回收"
status: "done"
branch: "t083_test_service_session_lifecycle"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "c8b74dd776cda47525e9cc2ef3ef8972c5bb9fd2"
spec_source_sha: "c8b74dd776cda47525e9cc2ef3ef8972c5bb9fd2"
depends_on: ""
conflicts_with: ""
note: "废除 start 后永久保留 + 手动 stop 模型；引入 test session 一等抽象，会话内复用容器、会话结束先清库再销毁；空闲超时自动回收，注册表驱动中断恢复"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 会话状态：`scripts/test_pg_runtime.py` 新增 `.scratch/test_session/session.json` 注册表（容器 ID、端口、cluster identity、全部 run、活跃 run 与最后活动时间），所有状态迁移经文件锁串行化。
- 生命周期：`ensure_session()` 按需拉起并在会话内复用；`register_run` / `unregister_run` 维护活跃 run；`touch_session` 刷新活动；`reaper_loop` 空闲守护在阈值到达后先清库再 `compose down`；`session-end` 显式执行同一回收；旧 `start` / `stop` 入口移除。
- 中断恢复：会话关闭前除注册表 run 外，再扫描带匹配 container_id 的 owned 记录，收敛遗留 run；无需人工指定 UUID。
- 运行期保护：首次完整套件暴露空闲守护在长跑中途误关会话，已改为活跃 run 期间禁止回收（`fresh_active_runs` + 硬上限 `KKMAIL_TEST_SESSION_MAX_RUN_S`），显式结束同样拒绝活跃 run。
- 验证：单元 29 passed（含空闲判定、活跃 run 保护、清理顺序、重建）；真实 harness 验证按需拉起、跨 run 复用同一容器、显式结束清库并销毁容器、低空闲阈值自动回收、长跑不被误关；后端完整 PG 套件 2202 passed / 2 skipped，唯一失败为环境既存 cookie t079 守卫（basetemp 位于 worktree 内，main 同失败）；`test_cmd` 全通过；E2E 23 passed。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-23T01:40:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t083_code_f001|important|已修|spawn_reaper 锁外写回陈旧 state 覆盖并发注册；改为锁内重读仅更新 reaper_pid|scripts/test_pg_runtime.py|
|t083_code_f002|important|已修|中断残留 active_runs 只按时间过滤；改为同时校验进程存活|scripts/test_pg_runtime.py|
|t083_code_f003|important|已修|reaper 单次异常退出且复用路径不重生；改为失败重试并补重生|scripts/test_pg_runtime.py|
|t083_code_f004|minor|已修|移除未用 import 与恒真 changed 标志|scripts/test_pg_runtime.py|

代码轴 FAIL、测试轴 PASS；撤回全部 AC 打勾后修复并重验。

### Round 2 (2026-11-23T02:20:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t083_code_f005|important|已修|ensure_session 在 session_lock 内调用 spawn_reaper 造成 flock 重入死锁；锁内只刷新状态、锁外 spawn|scripts/test_pg_runtime.py:395-438|
|t083_test_f001|minor|已修|死 PID 过滤分支无单测；补 test_dead_pid_does_not_block_idle_reclaim|tests/scripts/test_test_pg_runtime.py|

代码轴 FAIL、测试轴 PASS；撤回全部 AC 打勾后修复并重验。

### Round 3 (2026-11-23T02:50:00+08:00)

Round 3 零 finding。

代码轴 PASS / 测试轴 PASS；`review-status overall=PASS / review_scope=ok / ac_review=ok`；AC 8/8 TICK-VALID。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足（Round 3 双轴 PASS）
- 测试：后端完整 PG 套件 2202 passed / 2 skipped；`test_cmd` 全通过；唯一失败为 main 同现的环境既存用例（cookie t079 out-of-tree symlink 守卫）
- 黑盒：`npm --prefix src/frontend run test:e2e` 23 passed
- review：Round 3 代码轴/测试轴均 PASS，见本报告「Review 处置」
- AC 判定：见 `task.md` 行内打勾

### 结果摘要

- 测试服务生命周期改为会话制：按需拉起、会话内复用、空闲自动回收；移除永久常驻与人工 stop 模型。

### 长期文档闭环

- `docs/specs/testing_quality.md` front matter `tasks` 已登记 t083。
- `docs/blueprint/testing.md` 命令与生命周期说明已改为会话制。
