# Task review t071（reviewer_focus: 代码）

- task：`t071_idle_connect_catchup_inbox_delta`
- spec：`docs/tasks/t071_idle_connect_catchup_inbox_delta/spec.md`
- diff_anchor：`e4752c2415d34ac80ebb5ff1e76409a7351fb62d`
- target：`git -C '<repo_root>' diff e4752c2415d34ac80ebb5ff1e76409a7351fb62d`
- round：1
- reviewed_at：2026-10-31T21:14:00+08:00

reviewed_scope: 0313903bebf8ae1a

## Findings

### t071_code_f001 - stop() 改为逐条 join watch，串行化停机且无全局超时

- 严重度：minor
- 锚点：非 AC，行为/健壮性缺陷：worker SIGTERM 停机路径被串行化，最坏可超过容器 stop grace 才被 SIGKILL
- 位置：`src/mail_core/sync/idle_watcher.py:253`（`stop()`）、`src/mail_core/sync/idle_watcher.py:459`（`_close_watch`）；关联 `src/mail_core/providers/imap.py:162`、`src/mail_core/providers/imap.py:183`、`src/mail_core/worker/main.py:678`、`src/mail_core/config/models.py:58`
- 问题：新 `stop()` 先快照 `_watches`，再在循环里逐个调用 `_close_watch`；而 `_close_watch` 是「set 本 watch 的 stop_event → join(timeout=5.0)」。真实 `ImapIdleSession.wait_for_change` 每 0.25s 才检查一次 stop_event，退出时还要完成 DONE 往返（服务器无响应时最多再等 10s，见 imap.py:183-189）。因此各 watch 不是并发收到停止信号，而是串行退出：默认配额 32（config/models.py:58）下正常路径约需 8s 量级，叠加半开连接的单席位 5s join 超时后更久；worker `finally` 调用 `stop()` 时没有外层 deadline（worker/main.py:678-682），docker-compose.mail-core.yml 也未声明 `stop_grace_period`（默认 10s），存在 SIGTERM 后超时被 SIGKILL 的风险。其次，注释声称 join 可避免「DB 写在途」，但 join 超时后线程仍可能从卡住的 connect 返回并执行 `_enqueue_catchup`，保证并不完整。该改动也不在 spec 声明的功能范围内（spec 只要求补偿入队失败不终止 watcher）。
- 建议：保持原语义的「锁内快照并清空 `_watches` → 先一次性 set 全部 stop_event → 再按统一 deadline join」，或回退 `stop()` 改动（`_enqueue_catchup` 已自捕获异常，停机期残留写入属既有 `changed` 路径同源风险）；若保留 join，至少先并发唤醒全部 watch，再给总 join 时长设全局上限。

### t071_code_f002 - 模块 docstring 未同步新增的建连补偿语义

- 严重度：minor
- 锚点：文档与实现不一致（非 AC）
- 位置：`src/mail_core/sync/idle_watcher.py:1-22`
- 问题：模块摘要仍只描述「IDLE change notice enqueues the existing SYNC_FOLDER_DELTA」，未提本 task 新增的「每次会话成功建立后先入队一次收件箱补偿 delta」。`docs/blueprint/architecture.md` 与 `docs/specs/mail_sync_and_storage.md` 已补该语义，源码入口摘要却会让人以为 watcher 仅在 change 事件时入队，误导后续维护与排障。
- 建议：在 docstring 第 4-7 行补一句建连/重连补偿 delta（同去重键、失败隔离）的说明。

## 结论

- 前轮 finding 复核：Round 1，不适用。
- 本轮新发现：2 条（均为 minor）。
- 未进表的提示：
    - 文件过大：`src/mail_core/sync/idle_watcher.py` 661 行（实现源码 ≥400 minor 阈值，本 task 净增 33 行）；`tests/mail_core/test_t061_idle_watcher.py` 1195 行（测试源码 ≥600 minor 阈值，本 task 净增 319 行，未到 1200 important 阈值）。按降级规则仅列此处。
    - 圈复杂度（近似 McCabe）：`_watch_loop` ≈16、`_reconcile_once` ≈11，均达 ≥10 提示阈值；本 task 未给 `_watch_loop` 增加分支（只新增一次调用），不构成 finding。
    - 测试复验（供 test reviewer 参考）：独立用 fresh PostgreSQL 跑 `tests/mail_core/test_t061_idle_watcher.py`，结果 29 passed / 2 failed。失败为 `test_ac005_quota_limits_sessions`（`FrozenInstanceError`，helper 对 frozen dataclass `setattr`，test 文件 345/443 行）与 `test_load_candidates_ranks_by_arrival_not_checkpoint`（`DetachedInstanceError`，test 文件 478 行）；两处对应测试/生产代码在 anchor 版本相同、不在本 task diff 内，非本 task 引入，但「既有配额测试保持通过」的回归证据目前为红。本 task 新增 6 条 t071 测试全绿。
    - 残余风险（非 finding，符合 AC-005 字面）：首次建连补偿入队失败时 watch 保持 held/idling，t057 收件箱轮询被跳过；若此后既无新邮件事件也无重连，断线窗口内邮件会持续缺失。AC-005 只要求失败隔离、不要求自愈；如需闭环建议另立 pending。
    - 范围外观察：`stop()` 改动超出 spec 声明的功能范围（已作为 f001 记录）。
- 总体判断：AC-001..005 均有对应用实现，新增 6 条测试在 fresh PostgreSQL 上独立复验通过；仅 2 条 minor，无未解决 critical / important。
- 系统性 follow-up：无等价 tid（`task.py list` 未发现同主题任务）。

### AC 复验方式

- AC-001：`re_verified` — fresh PostgreSQL 跑 `test_ac001_first_connect_enqueues_catchup_delta` 通过，断言唯一 pending delta（dedupe key、priority 60、payload folder_id）与 state `idling`；代码见 `src/mail_core/sync/idle_watcher.py:495-497`。
- AC-002：`re_verified` — `test_ac002_reconnect_enqueues_catchup_delta`、`test_ac002_catchup_merges_with_pending_delta` 通过；另查证 `enqueue_job` 的 pending 合并与 claimed 后继合并，以及 partial unique index（`src/mail_core/sync/jobs.py`、`src/mail_core/mail/storage/models.py:407`）。
- AC-003：`re_verified` — `test_ac003_catchup_delta_persists_mail_arrived_without_idle_session` 通过，断言 `Message.remote_id=late-2` 存在且 `sort_time` 等于服务器到达时间。边界说明：测试直接执行 `sync_folder_delta`，未经过 worker 队列派发；派发链路为既有流水线，本 task 未改。
- AC-004：`re_verified` — `test_ac004_no_idle_capability_skips_catchup_and_keeps_polling` 通过，断言无补偿 job、state `fallback`、账号非 `failed`，且 `schedule_periodic_inbox_sync` 仍为该账号入队 1 条 delta。
- AC-005：`re_verified` — `test_ac005_catchup_enqueue_failure_does_not_stop_watch` 通过；并查证 `_enqueue_catchup` 的 try/except 隔离与日志（`src/mail_core/sync/idle_watcher.py:568-574`）。

coverage = 5/5

verdict: PASS

## Round 2 (2026-10-31T21:56:42+08:00)

reviewed_scope: 223a31dc9654b912

### 前轮 finding 复核

- t071_code_f001：已消除。`stop()` 现在是「锁内快照并清空 `_watches` → 一次性 set 全部 `stop_event` → 共享 deadline（5s）内逐个 `join(remaining)`」（`src/mail_core/sync/idle_watcher.py:258-278`），原先逐 watch 串行 join 与无全局超时两个缺陷均不存在。
- t071_code_f002：已消除。模块 docstring 已补「每次会话成功建立（首连、重连、凭据或席位重建）入队一次同键补偿 delta，入队失败隔离」语义（`src/mail_core/sync/idle_watcher.py:7-12`），与实现及 `docs/blueprint/architecture.md`、`docs/specs/mail_sync_and_storage.md` 的表述一致。

### t071_code_f003 - stop() 对尚未 start 的 watch 线程 join 会抛 RuntimeError

- 严重度：minor
- 锚点：行为缺陷（并发时序，非 AC）：SIGTERM 与 reconcile 的「注册 watch → start 线程」窗口重叠时，`stop()` 抛 `RuntimeError: cannot join thread before it is started`，停止流程在 join reconcile 线程前中断。
- 位置：`src/mail_core/sync/idle_watcher.py:468-471`（锁内注册 watch，出锁后才 `watch.thread.start()`）与 `src/mail_core/sync/idle_watcher.py:269-275`（`stop()` 直接 join）；上游捕获点 `src/mail_core/worker/main.py:678-682`。
- 问题：`_open_watch()` 把 `_Watch` 发布进 `_watches` 后、调用 `watch.thread.start()` 前存在窗口。若另一线程此时执行 `stop()`，快照会包含该 watch 并对未启动的 `Thread` 调 `join()`，Python 抛 `RuntimeError`。已用受控复现（阻塞该 watch 的 `Thread.start()` 直到 `stop()` 执行）稳定得到该异常。实际影响限于停机：worker 主循环捕获并记录 `idle watcher stop failed`，跳过 `self._thread.join(5.0)`，不丢数据、不阻止进程退出，故 minor。`_close_watch()`（`:473-479`）同样直接 join，但它只被 reconcile 线程调用，与 `_open_watch()` 同线程，当前不可达。
- 建议：在锁内发布前先启动线程，或把 `watch.thread.start()` 移入同一 `with self._lock` 块（新线程在 `_set_state` 处等待锁即可），或在 join 前判断 `watch.thread.ident is None` 跳过未启动线程。

### 本轮结论

- 前轮 finding 复核：f001 已消除；f002 已消除；无「修不彻底」项。
- 本轮新发现：1 条（minor）。
- 未进表的提示：
    - 文件过大：`src/mail_core/sync/idle_watcher.py` 675 行（实现源码 ≥400 minor 阈值，本 task 净增 41 行）；`tests/mail_core/test_t061_idle_watcher.py` 1248 行（测试源码 ≥1200 important 阈值，本 task 净增 372 行）。按降级规则仅列此处，不进 finding 表。
    - 圈复杂度（近似 McCabe）：`_watch_loop` ≈16、`_reconcile_once` ≈11，均达 ≥10 提示阈值；本 task 只给 `_watch_loop` 增加一次 `_enqueue_catchup` 调用，未增加分支。
    - 回归复验：fresh PostgreSQL 跑 `scripts/run-mail-core-tests.sh run -k test_t061_idle_watcher --tb=short`，结果 31 passed / 2 failed；失败为既有 `test_ac005_quota_limits_sessions`（`_manager` 对 frozen dataclass `setattr`，`FrozenInstanceError`）与 `test_load_candidates_ranks_by_arrival_not_checkpoint`（`DetachedInstanceError`），两处测试/生产代码在 anchor 与当前 diff 均未改动，非本 task 引入；但 spec 测试策略「既有 t061 配额等回归保持通过」在当前工作树仍不可完全验证（测试 reviewer 已另行记录该既有红测试）。
    - 残余风险（非 finding，AC-005 字面合规，同 Round 1）：补偿入队失败时 watch 仍进入并保持 `idling`/held，t057 收件箱轮询被跳过；若此后无新 IDLE 事件也不重连，断线窗口邮件会持续缺失。本次未引入重试/降级，如需闭环建议另立 pending。
    - 范围外观察：`stop()` 的 join 仍是对 anchor 的额外改动，但已收敛为 5s 共享上限且直接服务于新增的建连副作用，不另出 finding。
- 总体判断：前轮 2 条 minor 已消除；本轮仅新增 1 条停机竞态 minor，无未解决 critical / important。
- 系统性 follow-up：无等价 tid（`task.py list` 未见）；f003 属本 task 修复范围，直接在本轮修。

### AC 复验方式（Round 2）

- AC-001：`re_verified` — 独立运行 `test_ac001_first_connect_enqueues_catchup_delta` 通过，断言唯一 PENDING delta（dedupe key、priority 60、payload folder_id）与 state `idling`/held；并查证 `schedule_periodic_inbox_sync` 对 held 账号直接 `continue`（`src/mail_core/worker/main.py:234-235`）。
- AC-002：`re_verified` — 独立运行 `test_ac002_reconnect_enqueues_catchup_delta`、`test_ac002_catchup_merges_with_pending_delta`、`test_ac002_catchup_merges_with_claimed_delta` 均通过；另查证 `enqueue_job` 的 pending 合并、claimed `_queue_next` 后继记录与 active 去重唯一索引（`src/mail_core/sync/jobs.py:159-187`、`src/mail_core/mail/storage/models.py:407`）。
- AC-003：`re_verified` — 独立运行 `test_ac003_catchup_delta_persists_mail_arrived_without_idle_session` 通过，断言 `Message.remote_id="late-2"` 存在且 `sort_time == arrival`。边界：按已批准测试策略直接执行 `sync_folder_delta`，未验证 worker 队列派发（既有流水线，本 task 未改）。
- AC-004：`re_verified` — 独立运行参数化用例 `test_ac004_no_idle_capability_skips_catchup_and_keeps_polling[no_idle]` 与 `[permanent_auth]` 均通过，断言无补偿 job、state `fallback`、账号非 `failed`，且 `schedule_periodic_inbox_sync` 仍为该账号入队 1 条 delta。
- AC-005：`re_verified` — 独立运行 `test_ac005_catchup_enqueue_failure_does_not_stop_watch` 通过；并查证 `_enqueue_catchup` 的 try/except 隔离与 `log.exception`（`src/mail_core/sync/idle_watcher.py:568-588`）。

coverage = 5/5

verdict: PASS

## Round 3 (2026-10-31T22:03:25+08:00)

reviewed_scope: 898cb8ed146309d5

### 前轮 finding 复核

- t071_code_f001：已消除（自 Round 2 起，本轮未回退）。`stop()` 仍是「锁内快照并清空 `_watches` → 先一次性 set 全部 `stop_event` → 5s 共享 deadline 逐个 join」（`src/mail_core/sync/idle_watcher.py:258-281`）。
- t071_code_f002：已消除（自 Round 2 起）。模块 docstring 已含「建连/重连/凭据或席位重建后入队同键补偿 delta、失败隔离」语义（`src/mail_core/sync/idle_watcher.py:7-12`）。
- t071_code_f003：已消除。`stop()` 在 join 前跳过未启动线程：`if watch.thread is None or watch.thread.ident is None: continue`（`src/mail_core/sync/idle_watcher.py:273-275`）；所有 watch 的 `stop_event` 已在 join 循环前统一 set（`:266-267`），被跳过的线程一启动即因 `_stop`/`stop_event` 为真退出（`_watch_loop` 循环条件 `:488`），不再出现 `RuntimeError: cannot join thread before it is started`。检查与 join 之间也无残余窗口：`Thread.ident` 仅在未 start 时为 None，非 None 即可安全 join（start 内部先置 ident 再置 `_started`）。新增白盒回归 `test_stop_tolerates_registered_but_unstarted_watch`（`tests/mail_core/test_t061_idle_watcher.py:693`）在 fresh PostgreSQL 下通过。
- f003 修复未引入新缺陷：`_close_watch()`（`src/mail_core/sync/idle_watcher.py:476-482`）仍无 ident 守卫，但它只从 reconcile 线程调用，与 `_open_watch()` 同线程，注册的 watch 必然已 start（`:474`），当前不可达。

### 本轮新发现

无。

### 结论

- 前轮 finding 复核：f001 已消除；f002 已消除；f003 已消除；无「修不彻底」项。
- 本轮新发现：0 条。
- 未进表的提示：
    - 文件过大：`src/mail_core/sync/idle_watcher.py` 678 行（实现源码 ≥400 minor 阈值，本 task 净增 44 行）；`tests/mail_core/test_t061_idle_watcher.py` 1278 行（测试源码 ≥1200 important 阈值，本 task 净增 400 行）。按降级规则仅列此处，不进 finding 表。
    - 圈复杂度（近似 McCabe）：`_watch_loop` ≈16、`_reconcile_once` ≈11，均达 ≥10 提示阈值；本轮未增加分支（`stop()` ≈6）。
    - 回归复验：fresh PostgreSQL 跑 `scripts/run-mail-core-tests.sh run -k test_t061_idle_watcher --tb=line`，结果 32 passed / 2 failed；失败仍为既有 `test_ac005_quota_limits_sessions`（`_manager` 对 frozen dataclass `setattr`）与 `test_load_candidates_ranks_by_arrival_not_checkpoint`（`DetachedInstanceError`），两测试在 anchor 版本同样存在且本 task 未改动，非本 task 引入；本 task 新增的 8 个测试函数（9 个用例，含 AC-004 参数化 2 例）全部通过。
    - 残余风险（非 finding，同 Round 1/2）：补偿入队失败后 watch 保持 `idling`/held，t057 收件箱轮询被跳过，若此后既无 IDLE 事件也不重连，断线窗口邮件会持续缺失；AC-005 只要求失败隔离，如需自愈建议另立 pending。
- 总体判断：f003 已按建议修复并附回归测试，本轮未引入新缺陷，无未解决 critical / important。
- 系统性 follow-up：无等价 tid。

### AC 复验方式（Round 3）

- AC-001：`re_verified` — 本次跑 `-k test_t061_idle_watcher`，`test_ac001_first_connect_enqueues_catchup_delta` 通过；代码仍为建连成功后单次 `_enqueue_catchup`（`src/mail_core/sync/idle_watcher.py:514`），测试断言唯一 pending delta、dedupe key 与 state `idling`。
- AC-002：`re_verified` — `test_ac002_reconnect_enqueues_catchup_delta`、`test_ac002_catchup_merges_with_pending_delta`、`test_ac002_catchup_merges_with_claimed_delta` 均通过；去重合并仍由 `enqueue_job` 的 pending 合并/claimed `_queue_next` 承担（`src/mail_core/sync/jobs.py`）。
- AC-003：`re_verified` — `test_ac003_catchup_delta_persists_mail_arrived_without_idle_session` 通过，断言 `Message.remote_id="late-2"` 存在且 `sort_time == arrival`。边界同前：按已批准策略直接执行 `sync_folder_delta`，未验证 worker 队列派发（既有流水线，本 task 未改）。
- AC-004：`re_verified` — 参数化 `test_ac004_no_idle_capability_skips_catchup_and_keeps_polling[no_idle]`/`[permanent_auth]` 通过，断言无补偿 job、state `fallback`、账号非 `failed`，且 t057 调度仍为该账号入队 1 条 delta。
- AC-005：`re_verified` — `test_ac005_catchup_enqueue_failure_does_not_stop_watch` 通过；`_enqueue_catchup` 的 `try/except Exception` + `log.exception` 隔离见 `src/mail_core/sync/idle_watcher.py:585-591`。

coverage = 5/5

verdict: PASS
