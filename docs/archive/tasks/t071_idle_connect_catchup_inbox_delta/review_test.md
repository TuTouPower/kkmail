# Task review t071（reviewer_focus: 测试）

- task：`t071_idle_connect_catchup_inbox_delta`
- spec：`docs/tasks/t071_idle_connect_catchup_inbox_delta/spec.md`
- diff_anchor：`e4752c2415d34ac80ebb5ff1e76409a7351fb62d`
- target：`git -C '<repo_root>' diff e4752c2415d34ac80ebb5ff1e76409a7351fb62d`
- round：1
- reviewed_at：2026-10-31T21:36:00+08:00

reviewed_scope: 0313903bebf8ae1a

## Findings

### t071_test_f001 - AC-002 合并测试存在竞态，复跑约 7.5% 失败

- 严重度：important
- 锚点：AC-002（同键 pending 任务合并、不出现并行同键任务）——测试等待条件只覆盖“账号进入 held”，未覆盖“合并已完成”，会读到尚未合并的旧任务并失败，AC-002 的合并证据不可信。
- 位置：`tests/mail_core/test_t061_idle_watcher.py:881`、`tests/mail_core/test_t061_idle_watcher.py:885`（测试 `test_ac002_catchup_merges_with_pending_delta`）
- 问题：生产先 `_set_state(watch, "idling")`（`src/mail_core/sync/idle_watcher.py:496`）再 `_enqueue_catchup`（`src/mail_core/sync/idle_watcher.py:497`）。测试在 `:881` 只等待 `held_account_ids() == {acc_id}`，该状态在合并事务提交前即可为真；随后 `:882-887` 直接读 job 并断言 `priority == 60` / `run_after` 已提前。实测孤立运行 40 次有记录结果中失败 3 次（首轮 10 次中第 3、4 次失败，补充 20 次中第 4 次失败），失败为 `tests/mail_core/test_t061_idle_watcher.py:885: assert 75 == 60`。复现命令：循环执行 `scripts/run-mail-core-tests.sh run -k test_ac002_catchup_merges_with_pending_delta`。
- 建议：等待“合并已完成”的可观察状态后再断言，例如轮询到 `_delta_jobs_snapshot(...)` 唯一 job 的 `priority == 60` 且 `run_after` 已提前，或先等到 `job.payload`/`run_after` 满足再一次性快照；不要用扩大 timeout 或放宽断言掩盖竞态。

### t071_test_f002 - AC-004 未覆盖“永久认证失败”分支

- 严重度：minor
- 锚点：AC-004（服务器不支持 IDLE **或**认证永久失败的账号不产生补偿任务）
- 位置：`tests/mail_core/test_t061_idle_watcher.py:905-906`（仅构造 `IdleNotSupportedError`）；生产分支 `src/mail_core/sync/idle_watcher.py:478-480`
- 问题：AC-004 明确包含两种阻断触发，测试只覆盖无 IDLE 能力。`except PermanentAuthError` 分支若被误改为不再 `_register_blocked` 或开始补偿，当前测试不会失败。
- 建议：新增或参数化一个 `PermanentAuthError` 工厂用例，断言同样“无补偿 job / 账号未 failed / t057 仍轮询”。

### t071_test_f003 - AC-002 只验证 pending 合并，未验证 claimed 合并

- 严重度：minor
- 锚点：AC-002（同去重键任务已 pending/claimed 时合并到既有任务）
- 位置：`tests/mail_core/test_t061_idle_watcher.py:856-889`（`test_ac002_catchup_merges_with_pending_delta`）；claimed 分支在 `src/mail_core/sync/jobs.py:186-192`（`_record_claimed_followup`）
- 问题：测试只预先构造 PENDING 同键任务；补偿入队面对 CLAIMED 同键任务的分支没有任何测试。若该分支抛错（会被 `_enqueue_catchup` 吞掉）或错误地产生第二条可执行任务，现有用例不覆盖。
- 建议：先 claim 同键任务，再触发 catch-up，断言仍只有一条同键记录且 payload 的 `_followup_needed` 被置位（或完成该 job 后得到唯一 successor、无并行同键任务）。

## 结论

- 前轮 finding 复核：Round 1，不适用。
- 改测方向复核：无。diff 未修改任何既有断言或删除测试；仅新增 t071 测试并给 `_FakeDbSession` 补 `scalar` 返回 `None`。既有 `test_ac001_ac002_wake_enqueues_delta` 未改，加入建连补偿后不再能单独区分 changed 分支，但 `test_ac005_catchup_enqueue_failure_does_not_stop_watch` 通过“首次 catch-up 入队失败 + 后续 changed 成功入队”仍覆盖该路径，不构成迁就实现。
- 本轮新发现：3 条（1 important，2 minor）。
- 未进表的提示：
    - 既有红测试（非本 diff 引入）：`test_ac005_quota_limits_sessions`（`_manager` 对 frozen dataclass `IdleWatcherConfig` 执行 `setattr`，`tests/mail_core/test_t061_idle_watcher.py:345`）与 `test_load_candidates_ranks_by_arrival_not_checkpoint`（commit 后访问 detached `Account.id`，`tests/mail_core/test_t061_idle_watcher.py:478`）在当前工作树稳定失败；对应测试/生产代码与 anchor 版本相同。因此 spec 测试策略“既有 t061 配额等回归保持通过”无法在当前工作树验证，建议另立 pending/task。
    - 范围提到“凭据变更或席位重新获取后的重建”也补偿，但 AC-001/002 未要求；`test_ac006_credential_change_rebuilds_session` 只断言会话重建，未断言补偿入队（补断言需先消费首个 delta 才能观察第二次入队）。可选扩展。
    - AC-003 测试直接调用 `sync_folder_delta` 而非经 worker 队列执行已入队 job；这与上下文区测试策略（明确要求执行补偿 `sync_folder_delta`）一致，不作为 finding，但它不验证 job→handler 的派发参数。
- 总体判断：AC-001..005 均有测试且新增 6 条测试主体有效，但 AC-002 合并用例存在可复现竞态、测试门禁不可信，需修复后重审。
- 系统性 follow-up：建议登记 pending 条目 `t061_idle_watcher_preexisting_red_tests`（修复 t061 测试文件两个既有红测试），`task.py list` 未发现等价 tid。

### AC 复验方式

- AC-001：`re_verified` — 独立运行 `test_ac001_first_connect_enqueues_catchup_delta` 通过，断言唯一 PENDING delta（dedupe key、priority 60、payload folder_id）与 state `idling`/held。
- AC-002：`re_verified` — 独立多次运行两条 AC-002 测试；断线重连用例稳定通过，pending 合并行为本身成立，但测试存在竞态（见 f001）。
- AC-003：`re_verified` — 独立运行 `test_ac003_catchup_delta_persists_mail_arrived_without_idle_session` 通过，断言 `Message.remote_id="late-2"` 存在且 `sort_time == arrival`。
- AC-004：`re_verified` — 独立运行 `test_ac004_no_idle_capability_skips_catchup_and_keeps_polling` 通过，断言 `fallback`、无补偿 job、账号非 `failed`、t057 仍入队 1 条 delta；永久认证失败分支未测（见 f002）。
- AC-005：`re_verified` — 独立运行 `test_ac005_catchup_enqueue_failure_does_not_stop_watch` 通过，失败注入后 watch 继续、后续 changed 入队 delta、账号非 `failed`。

coverage = 5/5

verdict: FAIL

## Round 2 (2026-10-31T22:32:00+08:00)

reviewed_scope: 898cb8ed146309d5

### 前轮 finding 复核

- t071_test_f001：已消除。`test_ac002_catchup_merges_with_pending_delta` 现在先等待 `_merged()` 谓词（同时要求唯一 job、`priority == 60`、`run_after` 已提前到当前时刻附近）再读取断言（`tests/mail_core/test_t061_idle_watcher.py:911-923`），不再在 `held_account_ids` 为真后立刻读未合并的旧值。独立复跑 `scripts/run-mail-core-tests.sh run -k test_ac002_catchup_merges_with_pending_delta` 20 次（8 次带 `KKMAIL_TEST_SEED`），20/20 通过，未再出现 `assert 75 == 60`。
- t071_test_f002：已消除。AC-004 用例参数化为 `no_idle` / `permanent_auth`（`tests/mail_core/test_t061_idle_watcher.py:972-1009`），后者由 `PermanentAuthError` 触发生产 `except` 分支；独立运行两个参数均通过（`2 passed`）。断言仍覆盖无补偿 job、state `fallback`、账号非 `failed` 与 t057 仍入队。
- t071_test_f003：已消除。新增 `test_ac002_catchup_merges_with_claimed_delta`（`tests/mail_core/test_t061_idle_watcher.py:928-970`）：先 claim 同键任务，再触发建连补偿，断言唯一同键行仍为 CLAIMED 且 payload 置 `_followup_needed`、`_queue_next.payload.folder_id` 正确；该用例在 8 次全文件运行（其中 7 次 `KKMAIL_TEST_SEED=1..7` 乱序）中均通过。

### 本轮新发现

0 条。危险模式扫描（恒真断言、删/反转 expect、注释断言、skip/only、test 文件 suppress、mock 关键副作用、阈值掩盖、条件断言、存在即通过）未命中；新增 `stop()` 未启动线程防护测试（`tests/mail_core/test_t061_idle_watcher.py:693-721`）直接调用生产 `stop()`，非平行实现。

### 改测方向复核

f001 的改法是把测试同步点改为「合并后的可观察状态」，保留原有 priority/payload 断言并额外等待，不属于迁就实现；f002/f003 均为新增覆盖，无旧断言被改写或删除。无「迁就实现」的改测。

### AC 复验方式（Round 2）

- AC-001：`re_verified` — 8 次全文件运行中 `test_ac001_first_connect_enqueues_catchup_delta` 均通过；断言唯一 PENDING delta（dedupe key、priority 60、payload folder_id）与 `idling`/held。
- AC-002：`re_verified` — `test_ac002_reconnect_enqueues_catchup_delta`、`test_ac002_catchup_merges_with_pending_delta`（独立复跑 20/20）、`test_ac002_catchup_merges_with_claimed_delta` 均通过；pending 合并与 claimed follow-up 均有独立断言。
- AC-003：`re_verified` — `test_ac003_catchup_delta_persists_mail_arrived_without_idle_session` 在全文件运行中通过，断言 `Message.remote_id="late-2"` 存在且 `sort_time == arrival`。
- AC-004：`re_verified` — 独立运行参数化用例，`[no_idle]` 与 `[permanent_auth]` 两参数均通过（2 passed），断言无补偿 job、state `fallback`、账号非 `failed`、t057 仍入队 1 条。
- AC-005：`re_verified` — `test_ac005_catchup_enqueue_failure_does_not_stop_watch` 通过，断言入队异常后 watch 继续、后续 changed 入队 delta、账号非 `failed`。

coverage = 5/5

### 结论

- 前轮 finding 复核：f001 已消除（20/20 复跑通过）；f002 已消除；f003 已消除。无修不彻底或换形式弱化。
- 改测方向复核：无迁就实现。
- 本轮新发现：0 条。
- 未进表的提示：
    - 既有红测试仍存在（非本 diff 引入，anchor 与当前工作树相同）：`test_ac005_quota_limits_sessions`（`_manager` 对 frozen `IdleWatcherConfig` 执行 `setattr`，`tests/mail_core/test_t061_idle_watcher.py:345`）与 `test_load_candidates_ranks_by_arrival_not_checkpoint`（commit 后访问 detached `Account.id`，同文件 `:478`）。因此 spec 测试策略「既有 t061 配额等回归保持通过」在当前工作树仍无法完整验证；建议登记 pending（`t061_idle_watcher_preexisting_red_tests`），`task.py list` 未发现等价 tid。
    - 本轮观察到一个既有测试竞态（该测试在 anchor 与当前一致、非本 diff 引入）：`test_ac006_disabled_account_session_closed` 在 8 次全文件运行中失败 1 次（`tests/mail_core/test_t061_idle_watcher.py:515`，`assert fake.closed is True`）。测试等待 `held_account_ids() == set()`，而 `_close_watch` 先 pop `_watches` 再 join，空集可在旧会话 `close()` 前被观察到；建连补偿的 DB 入队会扩大该窗口。单独运行该测试 6/6 通过，故仅作回归可靠性提示；建议把同步点改为等待 `fake.closed` 或 watch 线程退出。
    - 可选扩展（沿用 Round 1，不阻断）：`test_ac006_credential_change_rebuilds_session` 未断言凭据变更重建后也入队补偿 delta；scope 提到该路径但 AC 未要求。
- 总体判断：三条前轮 finding 均已消除，本轮无新增 critical / important，AC-001..005 全部有测试并通过。
- 系统性 follow-up：建议 pending `t061_idle_watcher_preexisting_red_tests`（覆盖两处既有红测试，并附带 `test_ac006_disabled_account_session_closed` 同步竞态）；`task.py list` 无等价 tid。

verdict: PASS
