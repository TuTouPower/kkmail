# Task review t083（reviewer_focus: 测试）

- task：`t083_test_service_session_lifecycle`
- spec：`docs/tasks/t083_test_service_session_lifecycle/task.md`
- diff_anchor：`c8b74dd776cda47525e9cc2ef3ef8972c5bb9fd2`
- target：`git diff c8b74dd776cda47525e9cc2ef3ef8972c5bb9fd2`
- round：1
- reviewed_at：2026-11-23T02:26:19+08:00

## Findings

本轮无 finding（0 条）。已逐条扫描危险模式：无恒真断言、无删/反转/注释断言、无弱化断言、无 `.skip` / `.only`、无静默错误指令、无阈值放宽、无「程序赋值替代真实交互」、无「存在即通过」、无 mock 掉被测逻辑本身；无删除测试文件/it/test 块；未知契约清单为「无」。

## 结论

- 前轮 finding 复核：无（Round 1）。
- 改测方向复核：`tests/scripts/test_test_pg_runtime.py:112` 的 `_stub_run_pipeline` 把 stub 的 `instance` 换成 `ensure_session` / `register_run` / `touch_session` 并补 `run_id`，是适配 `run()` 新编排（allocate 阶段调用 ensure_session/register_run）的必要维护；三处既有断言（cleanup 抛错不掩盖测试失败码、tests 通过时抛 cleanup 错、全阶段通过返回 0）原样保留，未迁就实现。无其他改测。
- 本轮新发现：0 条。
- 未进表的提示：AC-001/004/005 中「容器销毁 + 无遗留 owned 数据库」的可观察结果依赖 harness 验证，未固化为提交进仓库的真实 Docker 集成测试；当前仅 `tests/scripts/test_test_pg_runtime_live.py:125` 一条 live 测试覆盖会话复用，建议后续补「run → 空闲/显式结束 → 断言容器消失且无 owned 库残留」的 live 测试以抗回归（可选覆盖扩展，非阻断）。cookie t079 属环境既存失败，按指示不计入本 task finding。
- 总体判断：测试改动未命中危险模式，单元复跑 29 passed，8 条 AC 均有可信测试或已验证 harness 支撑，无未解决 critical/important → PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，trust_prior。无提交进仓库的测试直接断言容器缺席；依据用户已验证的 harness「按需拉起」（无活动时容器不存在）事实，并核对代码：`ensure_session()` 仅在 `run` 时惰性拉起，模块导入与 `session-status` 不启动容器。
- AC-002：TICK-VALID，re_verified。已复跑单元 29 passed；`tests/scripts/test_test_pg_runtime_live.py:125` 真实断言复用同一 container_id/session_id 且 `pg_postmaster_start_time()` 不变，`test_ensure_session_reuses_active_session_and_refreshes_activity` 断言 `start` 不被调用。
- AC-003：TICK-VALID，re_verified。`tests/scripts/test_test_pg_runtime_live.py:22` 断言并发 run 建不同 owned 库、精确 cleanup 后 postmaster 时间不变；`test_run_registers_and_touches_session` 断言 run 注册 run 并 refresh 会话；本轮复跑单元全绿。
- AC-004：TICK-VALID，trust_prior。单元复跑已覆盖阈值判定（`test_reaper_should_close_uses_idle_threshold`）、长跑保护（`test_reaper_keeps_session_while_a_test_run_is_active`）与「先 clean 后 down」顺序（`test_close_session_cleans_runs_before_removing_containers`）；容器销毁与无遗留 owned 库的可观察结果依赖用户已验证的低阈值 harness 回收事实。
- AC-005：TICK-VALID，trust_prior。`test_close_session_cleans_runs_before_removing_containers` 以 `reason="explicit"` 复跑验证先清库再销毁并删除 session 文件，`main()` argparse 已移除 start/stop 入口经代码核对；显式结束的真实销毁依赖用户已验证的 harness 事实。
- AC-006：TICK-VALID，re_verified。`test_ensure_session_rebuilds_after_stale_state` 复跑验证残留状态下 `clean → down → up` 顺序、新 container_id、runs 清空、last_activity 刷新，全程无需 run UUID；`_clean_registered_runs` 的真实扫描清理由 `test_close_session_cleans_runs_before_removing_containers` 覆盖。
- AC-007：TICK-VALID，re_verified。guard 相关既有测试（`test_reject_unsafe_url_before_connecting`、`test_docker_failure_surfaces_redacted_stderr`、`tests/scripts/test_test_pg_runtime_live.py:50`）未被删除或弱化；对照生产 diff，`checked_url` / `instance` / `guard_database` / `cleanup` / 密码脱敏逻辑未变，Compose 未指向业务项目。
- AC-008：TICK-VALID，re_verified。已核对 `docs/blueprint/testing.md` 命令与生命周期说明改为会话制、两组测试同步改写；本轮复跑单元 29 passed；`test_cmd` / `blackbox_verify`（E2E 23 passed）/ 后端完整 PG 套件（2202 passed / 2 skipped）结果采纳用户已验证事实。

coverage = 5 / 8

建议合并前人工抽查 trust_prior 项。

reviewed_scope: 5e86adb6bdbb9d9a

verdict: PASS

## Round 2 (2026-11-23T03:02:34+08:00)

- round：2
- reviewed_at：2026-11-23T03:02:34+08:00

reviewed_scope: 548c9fe45095d2a1

## Findings

### t083_test_f001 - f002 修复的死 PID 过滤分支无测试锁定

- 严重度：minor
- 锚点：行为覆盖缺口（AC-004/005/006 的中断残留 run 场景）；非「AC 完全无测试」，属可补 case，不阻断
- 位置：`scripts/test_pg_runtime.py:258-266`（`fresh_active_runs` 的 `_pid_alive(info.get("pid"))` 分支）；`tests/scripts/test_test_pg_runtime.py:359-381`
- 问题：code f002 修复的核心是 `fresh_active_runs` 用 PID 存活校验过滤「已死但仍标记活跃」的 run，但新增/更新的 `test_reaper_keeps_session_while_a_test_run_is_active` 与 `test_explicit_close_refuses_while_a_run_is_active` 全部使用 `pid=os.getpid()`（活进程），只覆盖「时间上限 120s 到期」分支，未覆盖「started_at 仍新鲜但 PID 已死」分支。若移除 `fresh_active_runs` 中的 `_pid_alive` 条件，这两条测试仍全绿；本轮用户提供的 harness 事实仅含「活跃 run 保护 / 空闲回收」，未含 SIGKILL 残留 run 后再回收。该关键分支无单测锁定，可静默回归到 f002 原状。
- 建议：补一条单测：`active_runs` 的 `started_at` 新鲜但 `pid` 指向已退出进程（或 monkeypatch `runtime._pid_alive` 返回 False），断言 `reaper_should_close(state, now=now) is True`，并断言 `close_session("explicit")` 不再抛 `SafetyError`。

## 结论

- 前轮 finding 复核：Round 1 测试轴零 finding，无前轮项可复核。
- 改测方向复核：`active_runs` 形状由 list 改为 `dict[run_id] = {started_at, pid}` 是 code f002 修复（记录 run PID 供存活校验）驱动的设计变更。`test_reaper_keeps_session_while_a_test_run_is_active` / `test_explicit_close_refuses_while_a_run_is_active` 改数据结构后仍断言「活跃 run 保护会话」「显式结束拒绝活跃 run」的应有预期，非迁就实现输出；`_stub_run_pipeline` 继续 stub `ensure_session`/`register_run`/`touch_session` 适配 `run()` 新编排，原三条编排断言原样保留。无「迁就实现」的改测。
- 本轮新发现：1 条（minor）。
- 未进表的提示：cookie t079 环境既存失败按指示排除，不计本 task finding。
- 总体判断：两条真正新增测试均触达生产逻辑、无假绿——`test_spawn_reaper_preserves_concurrent_registry_updates` 用真实 `save_session`/`load_session` 断言并发 run 注册不被陈旧快照覆盖（直接锁定 f001），`test_reaper_loop_retries_after_a_failed_cycle` 断言 `close_session` 首轮抛错后 `reaper_loop` 仍二次调用（直接锁定 f003）；两条均非恒真、未 mock 掉被测逻辑本身，无 `.skip` / 弱化断言等危险模式。单元独立复跑 31 passed，8 条 AC 均有真实测试或 harness 事实支撑，仅 1 条 minor 覆盖扩展，无未解决 critical/important → PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，trust_prior。`test_session_status_reports_no_session_without_touching_service` 断言无会话时 `session_status()` 返回 None 且不调用 docker；无活动时容器缺席的可观察事实依赖用户已验证的 harness「按需拉起」。
- AC-002：TICK-VALID，re_verified。独立复跑单元 31 passed；`test_ensure_session_reuses_active_session_and_refreshes_activity` 断言复用存活会话时 `start` 不被调用且 `last_activity` 刷新，复用原 `container_id`/`port`，无重建重启。
- AC-003：TICK-VALID，re_verified。`test_run_registers_and_touches_session` 断言 run 注册 run 并 touch 会话；guard 组与 `test_close_session_cleans_runs_before_removing_containers` 复跑全绿，每轮 owned 库精确清理、容器持续运行。
- AC-004：TICK-VALID，trust_prior。`test_reaper_should_close_uses_idle_threshold`、`test_reaper_keeps_session_while_a_test_run_is_active`、`test_reaper_loop_retries_after_a_failed_cycle` 复跑验证阈值判定、活跃 run 保护与失败重试；容器销毁且无遗留 owned 库的可观察结果依赖用户已验证的低阈值 harness 回收。
- AC-005：TICK-VALID，trust_prior。`test_close_session_cleans_runs_before_removing_containers`（`reason="explicit"`）复跑验证先清库再 `down` 并删除 session 文件，`test_explicit_close_refuses_while_a_run_is_active` 验证活跃 run 拒绝；argparse 已移除 start/stop 入口经代码核对，真实销毁依赖用户已验证的 harness 事实。
- AC-006：TICK-VALID，re_verified。`test_ensure_session_rebuilds_after_stale_state` 复跑验证 `clean → down → up` 顺序、新 `container_id`、`runs` 清空；新增 `test_spawn_reaper_preserves_concurrent_registry_updates` 用真实注册表读写断言并发更新不被陈旧快照覆盖，全程无需 run UUID。
- AC-007：TICK-VALID，re_verified。guard 既有测试复跑全绿（`test_reject_unsafe_url_before_connecting`、`test_docker_failure_surfaces_redacted_stderr`、`test_direct_pytest_and_cleanup_reject_unowned_sentinel`）；生产 diff 中 `instance`/`guard_database`/`cleanup`/密码脱敏逻辑未削弱，Compose 未指向业务项目。
- AC-008：TICK-VALID，re_verified。已核对 `docs/blueprint/testing.md` 命令与生命周期、`test_pg_runtime.py` 单测同步反映会话生命周期；单元复跑 31 passed；`test_cmd` / E2E 23 passed / 后端完整 PG 套件 2202 passed / 2 skipped 采纳用户已验证事实（cookie t079 环境既存失败按要求排除）。

coverage = 5 / 8

建议合并前人工抽查 trust_prior 项。

verdict: PASS

## Round 3 (2026-11-23T03:37:39+08:00)

- round：3
- reviewed_at：2026-11-23T03:37:39+08:00

reviewed_scope: 354f01d3bd98f0c6

## Findings

Round 3 零 finding（0 条）。已逐条复查本轮新增的两条断言：无恒真断言、无删/反转/注释断言、无弱化断言、无 `.skip` / `.only`、无静默错误指令、无阈值放宽、无「程序赋值替代真实交互」、无「存在即通过」、无 mock 掉被测逻辑本身；未知契约清单仍为「无」。

## 结论

- 前轮 finding 复核：t083_test_f001（Round 2 minor，`fresh_active_runs` 死 PID 分支无单测锁定）——**已消除**。`tests/scripts/test_test_pg_runtime.py:453` 新增 `test_dead_pid_does_not_block_idle_reclaim`：`active_runs` 的 `started_at` 新鲜（now）、`pid=999999`，`_pid_alive` 被 stub 为 False，断言真实 `reaper_should_close(state, now=now) is True`。该断言直接触达生产 `reaper_should_close` → `fresh_active_runs`（`scripts/test_pg_runtime.py:258`）的 `_pid_alive` 分支；若移除该条件，`fresh_active_runs` 会把该 run 判为 fresh 并令 `reaper_should_close` 返回 False，测试转红。仅 mock 系统边界（OS PID 存活探测），属真锁定、无假绿。
- 代码轴 f005 修复的测试锁定复核：`tests/scripts/test_test_pg_runtime.py:426` 新增 `test_ensure_session_respawns_dead_reaper_without_reentrant_lock`。测试用 `detecting_lock` 替换 `session_lock`，进入时断言 `not held["value"]`；真实 `ensure_session`（`scripts/test_pg_runtime.py:396`）在锁内检测到死 reaper 后清 `reaper_pid`、出锁再调 `spawn_reaper`，后者自行取锁。若把 `spawn_reaper` 放回锁内，第二次取锁触发 `assert not held["value"]` → AssertionError，测试转红；`result["reaper_pid"] is None` 与 `load_session()["reaper_pid"] == 5252` 同时锁定「 stale PID 清除 + 重存活成功」。真触达 `ensure_session` / `spawn_reaper`，仅 mock 同步原语与 `Popen` 系统边界，无假绿。
- 改测方向复核：无。本轮仅新增测试，未修改既有测试的预期；`_stub_run_pipeline` 适配 `run()` 新编排属 Round 1 已审内容。
- 本轮新发现：0 条。
- 未进表的提示：cookie t079 环境既存失败按指示排除，不计本 task finding。「容器销毁 + 无遗留 owned 库」的可观察结果仍依赖 harness 验证，未固化为提交进仓库的真实 Docker 集成测试（可选覆盖扩展，非阻断）。
- 总体判断：两条新增断言均真实触达生产逻辑、可经变异反证转红、无假绿与危险模式；前轮唯一 minor finding 已消除，8 条 AC 打勾均有可信测试或 harness 事实支撑，无未解决 critical/important → PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，trust_prior。`test_session_status_reports_no_session_without_touching_service` 断言无会话时 `session_status()` 返回 None 且不调用 docker；无活动时容器缺席的可观察事实依赖用户已验证的 harness「按需拉起」，并经代码核对 `ensure_session` 仅在 `run` 时惰性拉起。
- AC-002：TICK-VALID，re_verified。独立复跑单元 33 passed；live 测试 `test_session_registry_tracks_and_reuses_active_service` 断言 `again["container_id"] == state["container_id"]`、`again["session_id"] == state["session_id"]` 且 `_postmaster_start()` 不变（无重启）；`test_ensure_session_reuses_active_session_and_refreshes_activity` 断言复用时 `start` 不被调用。
- AC-003：TICK-VALID，re_verified。`test_run_registers_and_touches_session` 断言 run 注册 run 并 touch 会话；guard 组与 `test_close_session_cleans_runs_before_removing_containers` 复跑全绿；live 测试 postmaster 时间跨 run 不变佐证容器持续运行、owned 库按轮清理。
- AC-004：TICK-VALID，trust_prior。`test_reaper_should_close_uses_idle_threshold`、`test_reaper_keeps_session_while_a_test_run_is_active`、`test_reaper_loop_retries_after_a_failed_cycle`、新增 `test_dead_pid_does_not_block_idle_reclaim` 复跑验证阈值判定、活跃 run 保护、失败重试与死 PID 不阻塞；`test_close_session_cleans_runs_before_removing_containers` 断言 `events == ["clean", "down"]`；容器销毁且无遗留 owned 库的可观察结果依赖用户已验证的低阈值 harness 回收。
- AC-005：TICK-VALID，trust_prior。`test_close_session_cleans_runs_before_removing_containers`（`reason="explicit"`）断言先清库再 `down` 并删除 session 文件，`test_explicit_close_refuses_while_a_run_is_active` 验证活跃 run 拒绝；argparse 已移除 start/stop 入口经代码核对，真实销毁依赖用户已验证的 harness 事实。
- AC-006：TICK-VALID，re_verified。`test_ensure_session_rebuilds_after_stale_state` 断言 `clean → down → up` 顺序、新 `container_id`、`runs` 清空；`test_spawn_reaper_preserves_concurrent_registry_updates` 用真实注册表读写断言并发更新不被陈旧快照覆盖；新增 `test_ensure_session_respawns_dead_reaper_without_reentrant_lock` 断言重入检测锁不被二次进入且死 reaper 重存活，全程无需 run UUID。
- AC-007：TICK-VALID，re_verified。guard 既有测试复跑全绿（`test_reject_unsafe_url_before_connecting`、`test_docker_failure_surfaces_redacted_stderr`、`test_direct_pytest_and_cleanup_reject_unowned_sentinel`）；生产 diff 中 `instance` / `guard_database` / `cleanup` / 密码脱敏逻辑未削弱，Compose 未指向业务项目。
- AC-008：TICK-VALID，re_verified。已核对 `docs/blueprint/testing.md` 命令与生命周期、`test_pg_runtime.py` 单测同步反映会话生命周期；独立复跑单元 33 passed；`test_cmd` / E2E 23 passed / 后端完整 PG 套件 2202 passed / 2 skipped 采纳用户已验证事实（cookie t079 环境既存失败按要求排除）。

coverage = 5 / 8

建议合并前人工抽查 trust_prior 项。

verdict: PASS
