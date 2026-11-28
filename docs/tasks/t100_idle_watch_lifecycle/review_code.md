# Task review t100（reviewer_focus: 代码）

- task：`t100_idle_watch_lifecycle`
- spec：`docs/tasks/t100_idle_watch_lifecycle/task.md`
- diff_anchor：`7746212f8d96870d0b7e75fd1868c159993d1a27`
- target：`git diff 7746212f..f5aa5476`
- round：1
- reviewed_at：2026-11-29T00:36:16+08:00

reviewed_scope: 594a478cb0ae23d2

## Findings

### t100_code_f001 - `stop()` 不再 join「执行线程已退出、仅 reader 残留」的关闭中资源

- 严重度：minor
- 锚点：AC-002 / AC-004 关闭路径行为等价性（停止路径的唤醒 / join / abort 顺序与旧实现逐路径对照）
- 位置：`src/mail_core/sync/idle_watcher.py` `IdleWatcherManager.stop()` 的 closing 循环（约 483-491 行）；对照基线 `7746212f` 旧 `stop()` 的 closing 循环。
- 问题：旧实现中关闭中条目以线程为单位登记，执行线程退出而 reader 仍存活时 reader 本人即关闭中条目，`stop()` 会对其 `abort` 并 `join(timeout=remaining)` 等到全局 deadline。新实现 `_ClosingResource` 只以 `watch.thread` 为 join 目标：closing 循环中 `if thread is not None and thread.ident is not None and thread.is_alive()` 不成立（执行线程已退出）时整项被跳过，既不尝试 abort 也不等待 reader 退出，`stop()` 可在 reader 仍存活时返回。影响有限：该资源的席位登记仍保留在 `_closing` 中（不会提前转让席位），且进程级停止后管理器不再 reconcile；漂移仅在于 `stop()` 返回时机的线程退出保证弱于旧实现一档。不构成 AC 违规（AC-002 的席位转让约束、AC-004 的停止后拒接新 watch 均不受影响），故记 minor。
- 建议：closing 循环在执行线程已退出时，改为对 `resource.watch.reader_thread()` 同样执行 join（至同一 deadline），恢复与旧实现等价的停止等待语义；或在 `_ClosingResource` 上提供 `join(deadline)` 统一处理两条线程。

## 逐项核对（无 finding 部分）

- 席位策略无 I/O：`src/mail_core/sync/idle_policy.py` 仅含 `random` / `uuid` / `dataclasses` / `datetime` 与 `mail_core.runtime_budget` 常量引用，无 DB、无线程、无文件 / 网络访问；`select_idle_holders`、`rank_key`、`challenger_advantage_s`、`backoff_delay`、`IdleCandidate`、`IdleWatcherConfig` 与基线旧实现逐行比对为原文迁移（仅去掉下划线前缀），排序（到达时间 → 空收件箱分组 → 稳定次序）与滞回（跨组无限优势、同组缺键优势 0）语义未变。
- 三分所有权：`IdleWatchSession` 单独拥有 provider 连接的建立 / 续订 / 重连（`_run`）、变化通知与有界补偿（`_enqueue_delta` / `_enqueue_catchup`，`_CATCHUP_RETRY_ATTEMPTS=3` 与基线一致）；`IdleWatcherManager` 只拥有席位分配（`_reconcile_once` 经 `select_idle_holders` + `_occupied_seats_locked`）、关闭中资源登记（`_closing: list[_ClosingResource]`）与状态发布（`_publish_state`，payload 结构 `updated_at` / `states` / `held` 与基线逐字一致）。
- 归属约束：`session_state_changed` / `session_blocked` 均以 `self._sessions.get(account_id) is session` 实例同一性校验后才提交状态或注销席位，迟到旧会话的报告被整体忽略；与旧 `_set_state` / `_register_blocked` 的守卫语义一致（旧会话在继任者已被替换且又注销时写 blocked 的边界行为亦与旧实现相同，非本轮引入）。
- 已修竞态复核（实施者自述）：`held_account_ids()` 现为 `{aid for aid in self._sessions if self._states.get(aid) in _SUBSCRIBED_STATES}`，在 `self._lock` 内由管理器已提交状态 `_states` 派生；会话本地 `session.state` 属性只被会话自身写入、不被 `held_account_ids()` 或 `_publish_state()` 读取（全仓 grep 确认无其他读者）。「held 先于状态提交翻转」的根源（会话本地 `subscription_active` 标志派生）已不存在，竞态确已根除。
- 占用与订阅分离：配额占用 = `len(_sessions) + len(_closing)`，`_ClosingResource.is_exited()` 要求执行线程与 reader 线程（`reader_thread()` 优先 provider 当前 reader、回退 `last_reader`）双双退出；轮询跳过集合只认已提交状态 `idling` / `changed`（`_SUBSCRIBED_STATES`），退避 / 关闭中不抑制轮询。与旧 `_closing_threads` 三件套的计数语义等价（旧 prune 后每关闭 watch 至多占一个条目，线程退出后由 reader 顶替计数）。
- 行为等价性逐路径对照（对基线 `git show 7746212f:src/mail_core/sync/idle_watcher.py`）：connect 失败退避（`backoff_delay(attempts)` + `stop_event.wait`）、catch-up 预算与耗尽后置 `backoff` 并靠下一轮重连重试、blocked 登记 / 指纹变化 / `_BLOCKED_RETRY_S=3600` 过期重试、reconcile 先全量 `request_stop` 再逐个 `_close_session` 的 close/open 顺序与开席前配额检查、`_load_candidates` 的收件箱资格 SQL（`sync_enabled` + `provider == "imap"` + `Folder.role == "inbox"` + `syncable_folder_clauses()` + `full_scan_complete`）逐字未变、后台增量去重键 `delta:{account_id}:{folder_id}` 与 `priority=60` / `ExecutionOrigin.BACKGROUND` 未变、`stop()` 先唤醒全部会话再按统一 deadline join/abort 的顺序未变。除 t100_code_f001 外未发现行为漂移。会话 `_run` 不再直接检查管理器 `_stop`，但管理器 `stop()` 对全部登记会话调用 `request_stop()`、reconcile 与 `_open_session` 均有 `_stop` 守卫，等价性成立。
- 被替换实现清除：全仓 grep 确认 `_Watch`、`_closing_threads` / `_closing_readers` / `_closing_watches` 三件套、管理器侧 `_watch_loop` / `_enqueue_delta` / `_set_state` / `_register_blocked` 均已不存在（仅测试文件注释中以历史说明提及 `_Watch` 时代）；`_enqueue_delta` / `_set_state` / `_register_blocked` 仅存于 `IdleWatchSession`（新所有者）；全部 src 与 tests 的 import 点已迁至 `idle_policy` / `IdleWatchSession` 新归属，无 re-export 转发层（`idle_watcher` 对 `idle_policy` 符号的 import 均为其自身内部使用）。

## 结论

- 本轮新发现：1 条（0 critical，0 important，1 minor）。
- 未进表的提示：
    - `IdleWatchSession.provider_session` 由会话线程无锁写入、管理器 `abort_provider()` / `reader_thread()` 无锁读取（旧实现经管理器锁读写 `watch.session`）；CPython 下引用读写原子，实际风险仅为 abort 时机差一拍，不构成功能缺陷，后续如收紧线程模型可一并处理。
    - `idle_watcher.py` 819 行仍偏大，但本 task 已完成契约要求的三分拆分，不以行数立 finding。
- 总体判断：契约四项结构要求（纯策略、会话单独所有权、管理器集中所有权、实例归属约束、占用 / 订阅分离）在实现层真实落地，被替换实现与转发层清除干净；除一条 minor 停止等待语义漂移外与旧实现行为等价。无未解决 critical / important，判定 PASS。
- 系统性 follow-up：无。PG 门禁未跑一项见 review_test 的 TICK 裁量（已登记 p106）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`idle_policy.rank_key` / `seat_group` / `primary_arrival` / `challenger_advantage_s` 与基线逐行一致（滞回只在同组可比较键上生效，跨组分类胜出、缺键优势 0）；reconcile close 循环对指纹不符、候选消失（失去资格）、不在 desired 的会话统一 `request_stop` + `_close_session`（`idle_watcher.py` `_reconcile_once`）；候选资格 SQL 与基线逐字相同。PG 侧候选 SQL 的实跑归 p106（见 review_test 裁量）。
- AC-002：TICK-VALID，re_verified。配额由 `_occupied_seats_locked()`（活动会话 + 关闭中资源）统一约束，开席前与 `_open_session` 内双重检查；`_ClosingResource.is_exited()` 要求执行线程与 reader 双退出才释放；`test_seat_handover_waits_for_thread_and_reader_exit` 以真实线程 + 慢 close + 独立 reader 分阶段验证转让时机；迟到状态防护由 `session_state_changed` / `session_blocked` 实例同一性守卫 + `test_stale_session_late_block_cannot_clobber_successor` 与 t061 `test_register_blocked_stale_thread_cannot_clobber_new_watch` 双重覆盖。
- AC-003：TICK-VALID，re_verified。首连 / 重连 / 订阅变化均经会话 `_enqueue_delta` 以既有后台去重键提交（`test_reconnect_and_change_enqueue_via_background_dedupe_key` 断言三次入队的 job_type / origin / dedupe_key / payload / priority）；补偿预算耗尽置 `backoff` 恢复轮询且会话存续自重试（`test_catchup_budget_exhaustion_drops_subscription_but_keeps_retrying`）；无 IDLE / 永久认证拒绝经 `session_blocked` 注销并置 `fallback`，指纹变化或过期后 reconcile 重试。去重合并的 DB 语义由未改动的 `sync/jobs.py:enqueue_job` 承担，其 PG 回归归 p106。
- AC-004：TICK-VALID，re_verified。`held_account_ids()` 由已提交状态派生，与 `_publish_state` 的 `held` 字段同源，聚合状态与轮询跳过集合不可能不一致；退避占席但恢复轮询由 `test_backoff_session_occupies_seat_but_allows_polling` 验证、关闭中同理由席位交接用例验证；`stop()` 后 `_reconcile_once` 提前返回且 `_open_session` 以 `_stop` 守卫拒接（`test_stopped_manager_accepts_no_new_sessions`）。

coverage = 4 / 4

verdict: PASS
