# Task review t083（reviewer_focus: 代码）

- task：`t083_test_service_session_lifecycle`
- spec：`docs/tasks/t083_test_service_session_lifecycle/task.md`
- diff_anchor：`c8b74dd776cda47525e9cc2ef3ef8972c5bb9fd2`
- target：`git diff c8b74dd776cda47525e9cc2ef3ef8972c5bb9fd2`
- round：1
- reviewed_at：2026-11-23T02:27:10+08:00

reviewed_scope: 5e86adb6bdbb9d9a

## Findings

### t083_code_f001 - spawn_reaper 在会话锁外写回陈旧 state，覆盖并发 run 的注册表更新

- 严重度：important
- 锚点：AC-004（会话关闭无遗留 owned 数据库）、AC-006（中断恢复）
- 位置：`scripts/test_pg_runtime.py:353-364`（`save_session` 于 :364），调用点 `scripts/test_pg_runtime.py:409`
- 问题：`ensure_session` 在 `scripts/test_pg_runtime.py:408` 释放 `session_lock` 后才于 `:409` 调用 `spawn_reaper`；后者用进入 `ensure_session` 时的旧 `state` 快照追加 `reaper_pid` 后整表写 `session.json`，临时文件 `session.tmp` 为全局共享。可复现交错：P1 新建会话释放锁 → P2 复用会话并 `register_run` 写入 run2（`scripts/test_pg_runtime.py:422-434`）→ P1 的 `spawn_reaper` 用不含 run2 的旧快照 `replace` 掉 `session.json`，run2 的 `runs` 与 `active_runs` 条目丢失。该 run 若随后被强杀，其 owned DB 不再进入 `_clean_registered_runs` 的注册表分支（`scripts/test_pg_runtime.py:304-327`），会话关闭时残留，活跃 run 保护同时失效。
- 建议：将 `spawn_reaper` 移入 `ensure_session` 的 `session_lock` 内，或在锁内重新 `load_session()` 后只写 `reaper_pid` 字段，禁止用陈旧快照整表覆盖。

### t083_code_f002 - 中断残留的 active_runs 无存活校验，长期阻塞空闲回收与显式结束

- 严重度：important
- 锚点：AC-004（超阈值自动回收）、AC-005（session-end 立即清理）、AC-006（中断恢复）
- 位置：`scripts/test_pg_runtime.py:258-266`（`fresh_active_runs`）、`scripts/test_pg_runtime.py:338-339`、`scripts/test_pg_runtime.py:422-443`、`scripts/test_pg_runtime.py:635-636`
- 问题：`active_runs` 仅在 `run()` 的 finally（`:636`）由 `unregister_run` 移除，`fresh_active_runs`（`:258-266`）只按时间过滤、从不清条目。run 进程被 SIGKILL/OOM 后其 `active_runs` 条目残留：`reaper_should_close`（`:269-275`）因 `fresh_active_runs` 非空，在 `KKMAIL_TEST_SESSION_MAX_RUN_S`（默认 7200s）内恒返回 False，空闲阈值（默认 900s）到达也不回收；`close_session` 的 `fresh_active_runs` 守卫（`:338-339`）使 `session-end` 抛 `SafetyError`，不清理数据库也不销毁容器。结果是「已死但仍标记活跃」的 run 被注册表识别为活跃，中断后既不清 owned DB 也不重建会话，与 AC-004/005/006 语义不符。
- 建议：`register_run` 记录 run 进程 PID 或 ownership，让 `fresh_active_runs` 只保留确实存活的 run；reaper 与 `close_session` 对确认结束的 run 主动剔除 `active_runs`，而非只靠 2 小时硬上限自然过期。

### t083_code_f003 - 空闲守护无异常兜底且复用路径不重生，单次 docker 故障即永久失去回收

- 严重度：important
- 锚点：AC-004（空闲自动回收）、AC-001（无测试活动时容器不存在）
- 位置：`scripts/test_pg_runtime.py:367-376`（`reaper_loop`）、`scripts/test_pg_runtime.py:384-387`（复用早退）、`scripts/test_pg_runtime.py:409`
- 问题：`reaper_loop` 对 `close_session` 无 `try/except`；`close_session` 中 `docker(*COMPOSE, "down", "--remove-orphans")`（`:341`）抛出 `SafetyError`（docker 守护进程抖动、非零退出）即让 reaper 进程退出，此时 `SESSION_FILE` 尚未删除、容器仍在。之后 `ensure_session` 命中存活会话在 `:387` 提前返回，跳过 `:409` 的 `spawn_reaper`，后续所有 `run` 都复用而不再生成守护。净结果：会话无活动也永不回收，容器长期残留，AC-004 与 AC-001 的可观测行为失效。
- 建议：`reaper_loop` 捕获异常并继续轮询（带错误计数/退避）；`ensure_session` 命中会话时检查 `reaper_pid` 是否存活，失效则在锁内补 `spawn_reaper`。

### t083_code_f004 - 死代码：未使用 import 与恒真分支

- 严重度：minor
- 锚点：代码质量（死代码，不改变行为）
- 位置：`scripts/test_pg_runtime.py:9`、`scripts/test_pg_runtime.py:427-433`
- 问题：`:9` 引入的 `timedelta` 在文件内零引用（测试文件各自局部导入）；`register_run` 中 `changed` 在 `:432` 被无条件置 `True`，`:433` 的 `if changed` 恒真，前面的 `changed = False`（`:427`）与条件赋值（`:430-431`）为无效逻辑。
- 建议：删除未使用的 `timedelta` import；去掉 `changed` 标志，直接 `save_session(state)`。

## 结论

- 前轮 finding 复核：首轮（round=1），无前轮。
- 本轮新发现：4 条（important 3 / minor 1）。
- 未进表的提示：
    - 文件过大：`scripts/test_pg_runtime.py` 714 行（手写脚本，阈值 400/800），本任务净增 310 行。按降级规则只在结论段提示，不进 finding 表；未观察到因过大直接导致的行为不一致。
    - 圈复杂度：`close_session` / `ensure_session` 分支较密（手算 McCabe 约 10-12），未达 15 的 minor 门槛，仅提示拆分可能，不进 finding 表。
    - 范围外观察：跨 worktree 共用固定 Compose project `kkmail_test`（`COMPOSE` 常量与 `config/test_pg_compose.yaml` 本任务未改），spec 风险区已承认，不计本 task finding。
    - 环境既存失败（cookie t079 守卫，harness basetemp 位于 worktree 内，main 同失败）按用户指示排除，未记为本 task finding。
- 总体判断：会话状态机主体已落地，但并发写回、残留活跃 run 与守护自愈三处缺陷使空闲回收、显式结束与中断恢复不可靠；存在未解决 important，FAIL。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`close_session` 在 `scripts/test_pg_runtime.py:341` 对 postgres/imap 执行 `compose down --remove-orphans`，空闲回收路径 `reaper_loop → close_session` 在阈值到达后销毁容器；f003 属异常加固项，不改变常态实现判定。
- AC-002：TICK-VALID，re_verified。`ensure_session` 命中存活会话只刷新 `last_activity`（`scripts/test_pg_runtime.py:384-387`）并原样复用 `container_id`/`port`，不调用 `start` 或容器重启；`create_run` 仅轮换一次性库。
- AC-003：TICK-VALID，re_verified。`run` 每轮 `create_run`（`scripts/test_pg_runtime.py:473-497`）生成独立 owned 库，finally `cleanup`（`:626-634`）删本轮库，会话容器不动。
- AC-004：TICK-VOID，re_verified。f002 残留 `active_runs` 使 `reaper_should_close` 在 2 小时硬上限内恒假，超过空闲阈值不回收；f001 并发写回丢注册导致 owned DB 残留。
- AC-005：TICK-VOID，re_verified。f002 残留 `active_runs` 触发 `close_session` 的 `fresh_active_runs` 守卫（`scripts/test_pg_runtime.py:338-339`）抛 `SafetyError`，`session-end` 无法「立即完成」清理与销毁。
- AC-006：TICK-VOID，re_verified。f001/f002：强杀后残留 `active_runs` 使下次调用走复用分支，既不清理残留 run 也不重建会话，注册表清理与重建语义未满足。
- AC-007：TICK-VALID，re_verified。`instance()`（`scripts/test_pg_runtime.py:97-107`）与 `guard_database()`（`:170-187`）的 label、loopback、comment、owner、密码守卫未削弱；`save_session` 与日志不写密码。
- AC-008：TICK-VALID，trust_prior。`docs/blueprint/testing.md` 命令与生命周期、`test_test_pg_runtime.py` 会话生命周期用例已在 diff 核对；`test_cmd`/`blackbox_verify` 与 PG 全量套件结果依赖实施侧报告，环境既存 cookie t079 失败按指示排除。

coverage = 5 / 8

verdict: FAIL

## Round 2 (2026-11-23T03:02:59+08:00)

reviewed_scope: 548c9fe45095d2a1

### t083_code_f005 - ensure_session 在会话锁内调用 spawn_reaper 自死锁，reaper 失效后的恢复路径永久挂起

- 严重度：important
- 锚点：AC-006（异常中断恢复）、AC-004（空闲自动回收）、AC-002（会话复用）
- 位置：`scripts/test_pg_runtime.py:407`（复用分支在 `session_lock()` 临界区内调用 `spawn_reaper(state)`）、`scripts/test_pg_runtime.py:367`（`spawn_reaper` 再次 `with session_lock()`）、`scripts/test_pg_runtime.py:205-213`（`session_lock` 每次 `SESSION_LOCK.open("a+")` 新建 fd 并 `flock LOCK_EX`）
- 问题：`ensure_session` 的复用分支在持有 `session_lock()` 的临界区（`:399-408`）内调用 `spawn_reaper(state)`（`:407`），而 `spawn_reaper` 在 `:367` 再次获取同一把锁。`session_lock`（`:208-209`）每次调用都新建文件描述符，`flock` 锁绑定 open file description，同一进程用新 fd 重入会阻塞等待自己尚未释放的锁，形成自死锁。可复现场景：`session.json` 与容器均存活、但 `reaper_pid` 指向已死进程（reaper 被 OOM/SIGKILL 或任何使 pid 失效的中断）时调用 `run` → `ensure_session` 命中复用分支（`:401`）→ `:403-405` 将 `reaper_pid` 置 `None` 并落盘 → `:406-407` 触发 `spawn_reaper` → 在 `:367` 永久阻塞；此后任何 `run` 都卡死，且状态文件已被写成 `reaper_pid=None`，形成粘挂。该路径正是 f003「复用会话时 reaper 已死则重生」的修复点，修复本身引入挂起。实测：以真实 `session_lock` 复现重入阻塞（持锁时内层获取超时 2s 仍未拿到）；用替身隔离外部 I/O 后跑真实 `ensure_session`，3s 超时内不返回、线程持续阻塞。`tests/scripts/test_test_pg_runtime.py` 中所有 `ensure_session` 用例均把 `spawn_reaper` 替换为 no-op（`test_ensure_session_reuses_active_session_and_refreshes_activity` / `test_ensure_session_rebuilds_after_stale_state`），未覆盖该分支。
- 建议：把复用分支的 `spawn_reaper(state)` 移出 `session_lock()` 临界区（与新建路径 `:430` 一致，在 `with` 块返回后调用），或让 `spawn_reaper` 接受「已持锁」参数跳过内层加锁；补一条 reaper_pid 已死时复用会话的测试，断言 `ensure_session` 能返回且重新拉起 reaper。

## 结论

- 前轮 finding 复核（以 diff 为准）：
    - t083_code_f001 已消除：`spawn_reaper`（`:357-377`）Popen 后在 `session_lock()` 内 `load_session()` 重读，仅写 `reaper_pid`，会话变更则 kill 新进程；`test_spawn_reaper_preserves_concurrent_registry_updates` 断言并发注册的 `runs` 未被旧快照覆盖。
    - t083_code_f002 已消除：`register_run`（`:443-454`）把 `active_runs` 值改为 `{started_at, pid}`，`fresh_active_runs`（`:258-270`）同时校验时间与 `_pid_alive(pid)`；`test_reaper_keeps_session_while_a_test_run_is_active` 与 `test_explicit_close_refuses_while_a_run_is_active` 覆盖。
    - t083_code_f003 部分修复：`reaper_loop`（`:380-393`）每轮 `try/except` 失败重试已消除单次故障永久退出，`test_reaper_loop_retries_after_a_failed_cycle` 覆盖；但「复用会话 reaper 已死则重生」的修复引入 f005 死锁，未真正修好。
    - t083_code_f004 已消除：未使用的 `timedelta` import 与恒真 `changed` 标志已移除，`:9` 仅 `datetime, timezone`，`register_run` 直接 `save_session(state)`。
- 本轮新发现：1 条（important 1 / critical 0 / minor 0）。
- 未进表的提示：
    - 文件过大：`scripts/test_pg_runtime.py` 734 行（手写脚本，阈值 400/800），本任务净增约 330 行；按降级规则仅在结论段提示，未观察到因过大直接导致的行为不一致。
    - 圈复杂度：`ensure_session` 约 9 分支、`close_session` 约 7 分支，均低于 15 的 minor 门槛，仅提示拆分可能。
    - 范围外观察：跨 worktree 共用固定 Compose project `kkmail_test`（`COMPOSE` 与 `config/test_pg_compose.yaml` 本任务未改），spec 风险区已承认，不计本 task finding。
    - 环境既存失败（cookie t079 守卫，harness basetemp 位于 worktree 内，main 同失败）按用户指示排除，未记为本 task finding。
- 总体判断：f001/f002/f004 已真正修复，f003 的守护自愈部分修复但重生分支引入自死锁（f005），在 reaper 失效场景下 `run` 永久挂起，属未解决 important，FAIL。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`reaper_loop` 空闲到期调 `close_session(only_if_idle=True)`，后者在 `scripts/test_pg_runtime.py:345-346` 执行 `docker down --remove-orphans` 并删除会话文件；真实 harness 已验证空闲后容器回收。
- AC-002：TICK-VALID，re_verified。`ensure_session` 复用分支（`:401-408`）只刷新 `last_activity`，不调 `start()`、不重启容器；live 用例 `test_session_registry_tracks_and_reuses_active_service` 断言 container_id/session_id 与 `pg_postmaster_start_time()` 不变，harness 验证跨 run 同容器复用。f005 仅影响 reaper 已死的恢复变体，常态复用路径成立。
- AC-003：TICK-VALID，re_verified。`run` 每轮 `create_run`（`:614`）生成独立 owned 库，finally `cleanup(directory)`（`:646-649`）删本轮库且不动会话容器。
- AC-004：TICK-VALID，re_verified。f002 修复后 `fresh_active_runs`（`:258-270`）剔除死 pid 的 run，`reaper_should_close`（`:273-279`）可在阈值到达时判真；`close_session` 先 `_clean_registered_runs`（`:344`）再 `docker down`（`:345`），`test_close_session_cleans_runs_before_removing_containers` 断言顺序为 `["clean","down"]`，harness 验证空闲自动回收且无遗留 owned DB。
- AC-005：TICK-VALID，re_verified。`main` 的 `choices`（`:668`）已移除 `start`/`stop`，`session-end` 直接 `close_session("explicit")`（`:678-679`），`docs/blueprint/testing.md` 同步移除永久常驻说明。
- AC-006：TICK-VALID，re_verified。`ensure_session` 残留态分支（`:409-429`）先 `_clean_registered_runs` 再 down 并重建会话；f002 修复剔除死 pid 的 active_runs，harness 验证中断恢复无需指定 run UUID。f005 影响 reaper 自身被杀的变体，已单独出 finding。
- AC-007：TICK-VALID，re_verified。`instance()` / `guard_database()` / `start()` 的身份、loopback、comment、owner、密码守卫未改动；`save_session`（`:228-237`）以 0600 写会话文件且不含密码，日志不打印密码；业务 Compose 与卷未触及。
- AC-008：TICK-VALID，trust_prior。`docs/blueprint/testing.md` 的命令与生命周期及 `test_test_pg_runtime.py` 会话用例已在 diff 内核对；`test_cmd`/E2E（23 passed）与后端完整套件（2202 passed / 2 skipped）执行结果依赖实施侧与 harness 报告，code 侧无法独立重跑全套。

coverage = 7 / 8

verdict: FAIL

## Round 3 (2026-11-23T03:37:36+08:00)

reviewed_scope: 354f01d3bd98f0c6

### 本轮新发现

Round 3 零 finding。

## 结论

- 前轮 finding 复核（以 diff 为准）：
    - t083_code_f005 已消除：`ensure_session`（`scripts/test_pg_runtime.py:399-413`）复用分支在 `session_lock` 内只刷新 `last_activity`、计算 `reaper_alive`，并把死 reaper 的 `reaper_pid` 置 `None` 后落盘；`spawn_reaper(state)` 移至锁外（`:411-412`）由 `if not reaper_alive` 驱动，不再与 `spawn_reaper` 内部 `:367` 的 `session_lock()` 形成同 fd 重入。`test_ensure_session_respawns_dead_reaper_without_reentrant_lock` 用重入检测锁断言 `session_lock` 不嵌套，并验证死 pid 被清除后重生为 5252。原挂起场景（会话与容器存活、`reaper_pid` 指向死进程）不再复现。
    - t083_code_f001 / f002 / f003 / f004：Round 2 已确认消除，本轮 diff 未回退。f001 见 `spawn_reaper` 锁内重读仅写 `reaper_pid`（`:367-377`）；f002 见 `fresh_active_runs` 的 `_pid_alive` 校验（`:267-268`）；f003 见 `reaper_loop` 的 `try/except`（`:385-393`）与复用分支重生；f004 见 `:9` 仅 `datetime, timezone`、`register_run` 直接 `save_session`（`:461`）。
- 本轮新发现：0 条。
- 未进表的提示：
    - 文件过大：`scripts/test_pg_runtime.py` 741 行（手写脚本，阈值 400/800），本任务净增约 330 行；按降级规则仅在结论段提示，未观察到因过大直接导致的行为不一致。
    - 圈复杂度：`ensure_session` 约 9 分支、`close_session` 约 7 分支，均低于 15 的 minor 门槛，仅提示拆分可能。
    - 并发观察：复用分支重生死 reaper 时，两个并发 `ensure_session` 观察同一死 pid 可能各起一个 reaper；后者以自身 pid 覆盖 `reaper_pid`，前者在首个轮询周期自检退出，无功能影响，未达 finding 阈值。
    - 范围外观察：跨 worktree 共用固定 Compose project `kkmail_test`（`COMPOSE` 与 `config/test_pg_compose.yaml` 本任务未改），spec 风险区已承认，不计本 task finding。
    - 环境既存失败（cookie t079 守卫，harness basetemp 位于 worktree 内，main 同失败）按用户指示排除，未记为本 task finding。
- 总体判断：f005 自死锁已真正修复，f001–f004 保持消除；8 条 AC 打勾均成立，无未解决 critical / important，PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`close_session` 执行 `docker down --remove-orphans`（`scripts/test_pg_runtime.py:345`）同时移除 postgres 与 imap；`reaper_loop` 空闲到期走同一路径，已无永久常驻入口，harness 验证空闲后容器回收。
- AC-002：TICK-VALID，re_verified。`ensure_session` 复用分支（`:401-406`）只刷新 `last_activity`，不改 `container_id`/`session_id`、不调 `start()`；live 用例 `test_session_registry_tracks_and_reuses_active_service` 断言容器/session 不变且 `pg_postmaster_start_time()` 不变，harness 验证跨 run 同容器复用。
- AC-003：TICK-VALID，re_verified。`run`（`:620-622`）每轮 `create_run()` 生成独立 owned 库，`finally` 的 `cleanup(directory)`（`:656`）删本轮库；`unregister_run`/`touch_session`（`:662-665`）不动容器。
- AC-004：TICK-VALID，re_verified。`reaper_loop`（`:385-393`）→ `close_session("idle", only_if_idle=True)` 先 `_clean_registered_runs`（`:344`）再 `docker down`（`:345`）；死 pid 过滤由 `test_dead_pid_does_not_block_idle_reclaim` 覆盖，清理顺序由 `test_close_session_cleans_runs_before_removing_containers` 断言 `["clean","down"]`，harness 验证空闲回收且无遗留 owned DB；f005 修复保证守护不再挂起。
- AC-005：TICK-VALID，re_verified。`session-end` → `close_session("explicit")`（`:691-692`）执行相同清库+销毁；`main` 的 `choices`（`:675`）已移除 `start`/`stop`，`docs/blueprint/testing.md` 同步；`test_explicit_close_refuses_while_a_run_is_active` 覆盖活跃 run 守卫。
- AC-006：TICK-VALID，re_verified。`ensure_session` 残留态分支（`:414-436`）先 `_clean_registered_runs` 再 down、丢弃旧注册表并 `start()` 重建，无需指定 run UUID；reaper 自身被杀的变体由 f005 修复消除挂起，harness 验证中断恢复。
- AC-007：TICK-VALID，re_verified。`instance()`（`:97-107`）的 label/loopback 校验与 `guard_database()`（`:170-187`）的 comment/owner/密码守卫未改；`save_session`（`:228-236`）以 0600 写且不含密码，`close_session` 日志只含 session 前缀（`:347`），未打印密码；业务 Compose 与卷未触及。
- AC-008：TICK-VALID，trust_prior。`docs/blueprint/testing.md` 命令与生命周期、`test_test_pg_runtime.py` 会话用例已在 diff 内核对；`test_cmd`/E2E（23 passed）、单元（33 passed）、后端完整 PG 套件（2202 passed / 2 skipped）执行结果依赖实施侧与 harness 报告，code 轴无法独立重跑全套。

coverage = 7 / 8

verdict: PASS
