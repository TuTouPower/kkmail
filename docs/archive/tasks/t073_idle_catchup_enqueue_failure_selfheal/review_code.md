# Task review t073（reviewer_focus: 代码）

- task：`t073_idle_catchup_enqueue_failure_selfheal`
- spec：`docs/tasks/t073_idle_catchup_enqueue_failure_selfheal/spec.md`
- diff_anchor：`c7ce5875956c622498af62bd7397b3bc86b726a6`
- target：`git -C '<repo_root>' diff c7ce5875956c622498af62bd7397b3bc86b726a6`
- round：1
- reviewed_at：2026-10-31T23:16:08+08:00

reviewed_scope: bf8af71b696b979a

## Findings

本轮零 finding。

## 结论

- 前轮 finding 复核：首轮，无前轮 finding。
- 本轮新发现：0 条。
- 7 视角（安全 / 正确性 / 契约·Breaking / 性能·资源 / 架构·可维护性 / 健壮性·可观测 / 细节·文档·规格）均已逐项扫过，无进表项。交付面核对：`git status --short` 仅 5 个修改文件（2 文档、1 实现、1 测试、task.md），无 reviewer 不可见的未跟踪交付物。
- 未进表的提示：
    - 文件过大：`src/mail_core/sync/idle_watcher.py` 718 行（实现源码阈值 ≥400，本 task 净增 40 行）；`tests/mail_core/test_t061_idle_watcher.py` 1278 行（测试源码阈值 ≥600/≥1200，本 task 净增 120 行）。按规则不进 finding 表；后续可考虑拆分（watcher 选座/会话/入队分层，测试按 t061/t071/t073 语义分文件）。
    - 复杂度：`_watch_loop`（`src/mail_core/sync/idle_watcher.py:491`）手算近似 McCabe CC≈19（本 task 前 16，新增「补偿失败 → 置 backoff、关会话、退避」分支 +3），≥15。建议把该失败释放分支抽成独立 helper 以降嵌套；非阻塞。
    - 健壮性观察：持续补偿入队失败期间，`attempts` 在每次成功建连后被重置（`src/mail_core/sync/idle_watcher.py:519`），catch-up 失败后的重连退避固定为 attempt=1（默认 10–20s + 抖动），不会随连续失败增长到 `backoff_max_s`；即跨重连频率不升级。`_enqueue_catchup` 内部确为指数退避（0.2s→0.4s），spec 风险区已接受该连接 churn，故仅提示而非 finding。
    - 范围外观察：`scripts/run-mail-core-tests.sh run tests/mail_core/test_t061_idle_watcher.py` 实际先跑全量 `tests`；全量运行在无关的 `tests/mail_core/test_a104_pool_kwargs.py` 夹具 setup 触发 `TRUNCATE ... statement timeout`（非本 diff 触及）。改用 owned test DB 直接执行目标文件：37 passed。该超时未复现验证，不建议据单次运行立项。
    - 注释提示：模块 docstring（`src/mail_core/sync/idle_watcher.py:11-12`）仍写 “enqueue failures are isolated from the watch loop”，未提及预算耗尽后关闭会话让位；语义不算错误（watch 线程仍存活），可在 finalization 更新 blueprint 时顺手补一句。
- 总体判断：实现完整覆盖 AC-001..AC-004，未发现 critical / important 缺陷，仅有上述非阻塞提示。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：re_verified — 核对 `_enqueue_catchup` 重试与成功返回路径、`_watch_loop` 仅在预算耗尽时才关会话；fresh owned PostgreSQL 上运行 `test_t073_ac001_catchup_retries_transient_enqueue_failure` 通过（同文件 37 passed）。
- AC-002：re_verified — 核对预算耗尽分支置 `backoff`、`session.close()`、`held_account_ids` 只统计 `_LIVE_STATES`；运行 `test_t073_ac002_persistent_catchup_failure_releases_seat_for_polling` 通过，断言包含 `schedule_periodic_inbox_sync` 可入队与 `sync_status != failed`。
- AC-003：re_verified — 核对 `watch.stop_event.wait(delay)` 可中断并返回 False、调用方随即退出；运行 `test_t073_ac003_stop_during_catchup_retry_returns_promptly` 通过（`< 2.0s`）。
- AC-004：re_verified — 去重键 `delta:{account_id}:{folder_id}` 与 `enqueue_job` 调用未变；同次运行 t071 回归 `test_ac001_catchup_merges_with_pending_delta`、`test_ac002_catchup_merges_with_claimed_delta` 通过。

coverage = 4/4

verdict: PASS

## Round 2 (2026-10-31T23:37:07+08:00)

reviewed_scope: eb456e938615009f

### Findings

本轮零 finding。

### 结论

- 前轮 finding 复核：Round 1 代码 review 为零 finding，无修复项可复核。相对 Round 1（指纹 `bf8af71b696b979a`），本轮审查范围变化如下，均已核对未引入新问题：
    - `src/mail_core/sync/idle_watcher.py` 仅模块 docstring 更新：Round 1 结论指出旧句 “enqueue failures are isolated from the watch loop”，当前 `:11-13` 已改为「有界重试 + 预算耗尽释放席位让 t057 兜底」描述。行为代码与 Round 1 所见一致（相关行号整体 +1，与 docstring 增行相符）；`_watch_loop` 的失败释放分支、`_enqueue_catchup` 的 `stop_event` 检查均未变。
    - `tests/mail_core/test_t061_idle_watcher.py` 仅 AC-003 用例加强（先等 `len(calls) >= 2` 再置 stop、增加健康账号隔离断言、`time.sleep(0.8)` 后断言不再重试），属测试层改动，未触及生产逻辑；`manager._enqueue_delta` 注入点是 spec 上下文明确允许的测试缝，非 mock 掉被测逻辑。
    - 两个文档与 `task.md` 相对 Round 1 未变。逐项重扫当前完整 diff（安全 / 正确性 / 契约·Breaking / 性能·资源 / 架构·可维护性 / 健壮性·可观测 / 细节·文档·规格），无新增进表项。
- 本轮新发现：0 条。
- 未进表的提示：
    - 文件过大（按降级规则仅列结论）：`src/mail_core/sync/idle_watcher.py` 719 行（阈值 ≥400，本 task 净增 41 行）；`tests/mail_core/test_t061_idle_watcher.py` 1426 行（测试阈值 ≥600/≥1200，本 task 净增 146 行）。后者已越过 important 阈值线，但按规则不进 finding 表；后续建议按 t061/t071/t073 语义拆测试文件。
    - 复杂度：`_watch_loop`（`src/mail_core/sync/idle_watcher.py:492`）手算近似 McCabe CC≈19（task 前约 16，本 task +3），≥15 但属 Round 1 已披露的同一函数，本轮未再增加分支；维持非阻塞提示。
    - `_CATCHUP_RETRY_MAX_S = 2.0`（`:63`）在当前 3 次预算下实际只用到 0.2s/0.4s，上限分支不可达；作为未来扩预算的防御性上限可接受，不构成缺陷。
- 总体判断：当前实现覆盖 AC-001..AC-004，无未解决 critical / important；Round 1 后新增的 docstring 与测试加强未引入新问题。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：`re_verified` — 重读 `_enqueue_catchup` 的 retry 成功路径与 `_watch_loop` 的 state 保持（成功不置 backoff、不关会话）；fresh owned PostgreSQL 上 `-k "t073 or ac001_first_connect or ac002_reconnect or ac002_catchup_merges or ac005_catchup_enqueue"` 选中 8 条，全部通过（含 `test_t073_ac001_catchup_retries_transient_enqueue_failure` 对 delta 任务、held/idling、`sync_status != failed` 的断言）。
- AC-002：`re_verified` — 代码核对预算耗尽分支置 `backoff`、`session.close()`、`held_account_ids()` 排除非 live 状态；同一次 fresh DB 运行中 `test_t073_ac002_persistent_catchup_failure_releases_seat_for_polling` 通过，断言 `schedule_periodic_inbox_sync` 入队 1 个 delta 且账号未 failed。
- AC-003：`re_verified` — 核对 `watch.stop_event.wait(delay) or self._stop.is_set()` 短路返回 False、调用方随即在已置位的 stop_event 上退出；同一次运行 `test_t073_ac003_stop_during_catchup_retry_returns_promptly` 通过（加强后以 `calls >= 2` 前置门槛和 `len(calls) == 2` 区分旧实现）。
- AC-004：`re_verified` — `_enqueue_delta` 去重键 `delta:{account_id}:{folder_id}` 与 `enqueue_job` 调用未改，重试为串行同键；同一次运行 t071 回归 `test_ac001_first_connect_enqueues_catchup_delta`、`test_ac002_reconnect_enqueues_catchup_delta`、`test_ac002_catchup_merges_with_pending_delta`、`test_ac002_catchup_merges_with_claimed_delta` 全部通过。
- coverage = 4/4

verdict: PASS
