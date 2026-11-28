# Task review t100（reviewer_focus: 测试）

- task：`t100_idle_watch_lifecycle`
- spec：`docs/tasks/t100_idle_watch_lifecycle/task.md`
- diff_anchor：`7746212f8d96870d0b7e75fd1868c159993d1a27`
- target：`git diff 7746212f..f5aa5476`
- round：1
- reviewed_at：2026-11-29T00:36:16+08:00

reviewed_scope: 594a478cb0ae23d2

## Findings

无（已逐文件对照 `git diff` 审查新增用例与全部既有测试改写，未发现断言语义被改弱、恒真断言、跳过掩盖或未触达生产逻辑的用例）。

## 逐项核对

- 新增 `tests/mail_core/test_t100_idle_watch_lifecycle.py`（6 用例）真触达生产逻辑：全部经 `IdleWatcherManager._reconcile_once` / `_open_session` / `_close_session` / `stop()` 与真实 `IdleWatchSession` 线程驱动，仅在 DB 会话工厂（`_FakeDbSession`）与 provider 会话两处用替身，属契约声明的「真实线程 + fake 会话」层级，与既有 t061 unit 用例同一手法。
    - `test_seat_handover_waits_for_thread_and_reader_exit`：慢 `close()` + 独立存活 reader 的 provider，分三阶段断言席位不转让（关闭中）→ 执行线程退出仍不转让（reader 存活）→ reader 退出后转让，且关闭中 `held_account_ids() == set()`（订阅失效、轮询恢复）。直接覆盖 AC-002 的双线程退出条件与 AC-004 的占用 / 订阅分离。
    - `test_stale_session_late_block_cannot_clobber_successor`：卡在 connect 的旧会话迟到抛 `IdleNotSupportedError`，断言继任者的 `_sessions` 登记、`idling` 状态、`_blocked` 缺席与 held 集合均不被覆盖。经真实线程走完会话 `_run` → `session_blocked` 生产路径，非直接调守卫函数造假。
    - `test_backoff_session_occupies_seat_but_allows_polling`：connect 持续失败时断言状态 `backoff`、held 为空（轮询恢复）、席位仍被该会话占用（另一候选不开席）、且会话自重试（factory 调用 ≥2 次）。
    - `test_reconnect_and_change_enqueue_via_background_dedupe_key`：以 monkeypatch 记录 `idle_watcher.enqueue_job`，断言首连补偿 + 断线重连补偿 + changed 通知三次入队的 `job_type` / `execution_origin is BACKGROUND` / `dedupe_key` / `payload` / `priority=60` 全等。替身只替换最末端 DB 入队函数，去重键的构造仍走生产 `_enqueue_delta`。
    - `test_catchup_budget_exhaustion_drops_subscription_but_keeps_retrying`：入队恒失败时断言预算耗尽后置 `backoff`、held 为空、会话未被注销且下一轮重连继续重试（provider 构造 ≥2 次）。
    - `test_stopped_manager_accepts_no_new_sessions`：`stop()` 后分别直调 `_reconcile_once` 与 `_open_session`，断言均不建会话、factory 不再被调用。
- `test_t061_idle_watcher.py` 改写（对照 diff 逐处核）：均为所有权迁移的接缝替换，断言语义不变——`_Watch` 构造改为等价 `IdleWatchSession` 构造；`manager._register_blocked` / `manager._set_state` 改为公开 host 回调 `session_blocked` / `session_state_changed`（断言对象 `_watches` → `_sessions`，其余断言逐字保留）；`_closing_threads` 系列断言在 t095 改写中改为 `manager._closing` 长度与 `r.watch.has_live_threads()`，与新登记结构一一对应。t073 / AC-005 的 catch-up 用例将实例级 `manager._enqueue_delta = flaky` 改为 `monkeypatch.setattr(IdleWatchSession, "_enqueue_delta", flaky)` 类级接缝：作用域实际更宽（覆盖全部会话），其中多账号用例（ac003）在替身内按 `session.account_id` 过滤、单账号用例不受影响，调用计数与重试断言逐字保留，未改弱。文件头注释已按仓库规矩写明 t100 接缝迁移及理由。
- `test_t090_execution_origin.py` 改写：原 `manager._enqueue_delta(watch)` 改为构造真实 `IdleWatchSession` 后调 `watch._enqueue_delta()`，对 DB 中 `dedupe_key == delta:{aid3}:{inbox3}` 的 job 及其 execution_origin 的断言不变（该文件为 db_only，云端未跑，归 p106）。
- 其余改写（t090_coalescing、t095_combined、t095_contract、t096_fixes_unit）仅 import 归属迁移（`IdleWatcherConfig` / `IdleCandidate` / `select_idle_holders` 改从 `idle_policy` 导入），断言零改动。
- 独立复跑（reviewer 本轮，`KKMAIL_TEST_MODE=unit`，worktree `.venv` Python 3.14）：`test_t100_idle_watch_lifecycle.py` 6 passed；三文件合跑 `test_t100_idle_watch_lifecycle.py + test_t061_idle_watcher.py + test_t095_patrol_and_idle_fixes.py` 28 passed / 30 skipped（跳过均为 db_only 的 PG 门控用例），与实施者报告的口径一致（t061 unit 部分 15、t095 idle 部分 6 含在内）。

## PG 未验证对 TICK 判定的影响（reviewer 独立裁量）

- 事实：t061 全部 db_only 用例（候选加载 SQL、补偿与 pending/claimed 去重合并、凭据轮换关闭等）与全量 PG 门禁未在云端执行，已登记 `docs/pending/p106_t100_pg_gate_rerun.md` 待本地复跑。
- 裁量：四条 AC 全部维持 TICK-VALID，不因 PG 未跑而判 VOID。理由：（1）本 task 改动的生产代码（策略纯函数、会话循环、管理器席位 / 状态逻辑）在 unit 模式下已被真实线程与 stub 协议用例完整触达，AC 的可观察行为在这一层均有直接断言；（2）PG 用例所验证的生产代码——`_load_candidates` 的 SQL 文本、`sync/jobs.py` 的 `enqueue_job` 去重合并语义——经逐字对照未被本 task 修改，PG 层回归风险来自「未改动代码与新调用方的集成」，属门禁完整性缺口而非打勾虚假；（3）缺口已按仓库规矩登记 p106 且实施者在 progress.md 如实披露，未以 unit 结果冒充 PG 结果。若 p106 复跑出现失败，应按 review FAIL 流程撤回打勾重验。
- 保留意见（不立 finding）：task.md 测试策略写有「复用真实 PG 的断线补偿、后台去重、入队重试及轮询兜底用例」，该部分在本轮交付中实为「用例已按新接缝改写、待 p106 复跑」，而非已执行；AC 打勾依据应以 progress.md 实施笔记的披露口径为准。

## 结论

- 本轮新发现：0 条
- 未进表的提示：t100 新用例的 `_FakeDbSession.get()` 仅支持 Account / Folder，`_publish_state` 在这些用例中走异常吞掉路径（`log.debug`），故「发布到 AppSetting 的内容与 held 一致」未在新用例中直接断言；该行为由代码对照确认（payload 与基线逐字一致、held 与 states 同源派生），且 t061 既有发布相关断言未被改动，不另立 finding。
- 总体判断：新增用例真触达生产逻辑，既有改写无一改弱断言语义，独立复跑结果与实施者报告一致；PG 缺口已登记 p106 并如实披露，按上节裁量不影响 TICK 判定。无 critical / important / minor finding，判定 PASS。
- 系统性 follow-up：p106（已登记，本地 PG 复跑）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。t061 既有席位选择 / 滞回纯单测（用例本体未改、仅 import 迁移）与 t095 contract 的配额选择断言在合跑中通过；策略函数与基线逐行一致（unit 层）。候选 SQL 的 PG 实跑归 p106。
- AC-002：TICK-VALID，re_verified。t100 席位交接用例与迟到 block 用例、t061 `test_register_blocked_stale_thread_cannot_clobber_new_watch`、t095 慢关闭 / 挂起 reader 真实线程用例（断言已等价迁移至 `_closing`）在 unit 合跑中通过。
- AC-003：TICK-VALID，re_verified。t100 去重键入队用例与预算耗尽用例通过（unit 层）；t061 的 catch-up 重试类用例为 db_only，云端跳过，其接缝改写经 diff 核对未改弱，实跑归 p106。
- AC-004：TICK-VALID，re_verified。t100 退避占席恢复轮询用例、停止后拒接用例通过；`held_account_ids()` 由已提交状态派生的代码事实经 review_code 复核，与聚合状态同源。

coverage = 4 / 4

verdict: PASS
