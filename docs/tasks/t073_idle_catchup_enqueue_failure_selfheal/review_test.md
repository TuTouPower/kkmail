# Task review t073（reviewer_focus: 测试）

- task：`t073_idle_catchup_enqueue_failure_selfheal`
- spec：`docs/tasks/t073_idle_catchup_enqueue_failure_selfheal/spec.md`
- diff_anchor：`c7ce5875956c622498af62bd7397b3bc86b726a6`
- target：`git -C '<repo_root>' diff c7ce5875956c622498af62bd7397b3bc86b726a6`
- round：1
- reviewed_at：2026-10-31T23:28:31+08:00

reviewed_scope: bf8af71b696b979a

## Findings

### t073_test_f001 - AC-003 的停机测试在旧实现上同样通过，未验证「不再继续重试」与「不影响其他 watch」

- 严重度：important
- 锚点：AC-003（「重试退避期间收到停止信号时，watch 线程在 2 秒内退出，不再继续重试，也不影响其他 watch」）
- 位置：`tests/mail_core/test_t061_idle_watcher.py:1103`（`test_t073_ac003_stop_during_catchup_retry_returns_promptly`），断言在 `:1112-1116`
- 问题：
    - 测试只断言 `elapsed < 2.0` 与 `held_account_ids() == set()`，两项都无法区分「退避期间响应 stop」和「无视 stop 继续重试」。重试预算本身是 3 次、退避 0.2s + 0.4s（`src/mail_core/sync/idle_watcher.py:617-629`），合计约 0.6s，天然小于 2s；即使 `_enqueue_catchup` 完全不看 `stop_event`，`watch` 也会在 ~0.6s 后返回 False 并退出，断言照样通过。
    - `manager.stop()` 会清空 `_watches` 并 join 线程（`src/mail_core/sync/idle_watcher.py:265-288`），因此 stop 之后 `held_account_ids() == set()` 与实现是否响应重试期间的 stop 无关，是恒成立项。
    - 反向验证：diff 之前的 `_enqueue_catchup` 只调用一次 `_enqueue_delta` 并吞掉异常，随后进入内层循环；`manager.stop()` 后假会话返回 `stopped`，watch 立即退出，`calls == 1`、`elapsed < 2s`、held 为空。即该测试在 t073 之前的实现上也是 PASS，不能作为 AC-003 新行为的红灯证据。
    - AC-003 的两个关键条款完全无断言：stop 之后 `calls` 不再增长（「不再继续重试」）；其他 watch 不受影响（测试只有单个账号，也没有第二个 watch 的存活断言）。
    - 次要：`elapsed` 从 `manager.start()` 之前开始计时（`:1109`），包含启动与等待首次调用时间，测的不是 stop 延迟；在慢机上可能假失败，同时也没让「停机响应」更可区分。
- 建议：`manager.stop()` 后等待超过剩余重试预算（例如 `time.sleep(1.0)` 或轮询确认）再断言 `len(calls) == 1`，证明没有继续重试；把计时起点移到 `manager.stop()` 调用前；再加一个健康账号的 watch（`_FakeSession` 正常），断言失败账号退避/退出期间该账号仍 held 且其会话未被关闭，覆盖「不影响其他 watch」。

## 结论

- 前轮 finding 复核：本轮为 Round 1，无前轮。
- 改测方向复核：无。diff 未修改任何既有测试断言，只在 `test_t061_idle_watcher.py` 末尾新增 3 个测试；t071 的首连/重连/去重测试原样保留且通过。
- 本轮新发现：1 条（important）。
- 未进表的提示：
    - `test_t073_ac001_catchup_retries_transient_enqueue_failure` 只验证重试成功后的 held/idling 状态，未验证重试期间会话未被重建或关闭（scope 的「保持当前 IDLE 会话」）；可在 factory 中记录构建次数并断言只有一次、`closed is False`。属可选补强。
    - 两个新测试直接 import 私有常量 `_CATCHUP_RETRY_ATTEMPTS` 作为注入次数；若预算改为 1，`flaky_enqueue` 不再注入失败，`test_t073_ac001` 会退化为无失败场景的恒真测试。当前可接受，建议测试内显式断言预算大于 1 或固定注入次数。
    - AC-002 的「下一次重连继续尝试补偿」属于范围描述而非 AC，未测；本 task 不据此出 finding。
- AC 复验方式：
    - AC-001：`re_verified`。重跑 `scripts/run-mail-core-tests.sh run tests/mail_core/test_t061_idle_watcher.py -k "t073 or ac001_first_connect or ac002_reconnect or ac002_catchup_merges or ac005_catchup_enqueue"`，8 passed；`test_t073_ac001` 断言 delta 任务存在、`calls == _CATCHUP_RETRY_ATTEMPTS`、held/idling、`sync_status != failed`。
    - AC-002：`re_verified`。同一命令通过；`test_t073_ac002` 断言 snapshot 为 `backoff`、首个会话 `closed`、held 为空、`schedule_periodic_inbox_sync` 入队 1 个且 delta 任务存在、`sync_status != failed`。
    - AC-003：`re_verified`（实现层）。同一命令通过；代码 `src/mail_core/sync/idle_watcher.py:629` 确实在重试退避中检查 `watch.stop_event` / `_stop`。但测试本身的判别力不足，见 f001。
    - AC-004：`re_verified`。同一命令包含 t071 首连/重连/pending 与 claimed 合并测试，全部通过；`test_t073_ac001` 断言重试成功后同去重键任务只有 1 行。
    - coverage = 4/4
- 总体判断：AC-001/AC-002/AC-004 有可判别的新测试；AC-003 的测试在 t073 之前的实现上同样通过，核心条款无证据，未解决 important 阻断。
- 系统性 follow-up：无。

verdict: FAIL

## Round 2 (2026-10-31T23:53:43+08:00)

reviewed_scope: eb456e938615009f

### 前轮 finding 复核

- `t073_test_f001`：**已消除**（以 diff 与实测为准，不采信 `task.md` 处置表）。
    - 位置：`tests/mail_core/test_t061_idle_watcher.py:1104`（`test_t073_ac003_stop_during_catchup_retry_returns_promptly`）。
    - 修复点：先 `_wait_until(lambda: len(calls) >= 2)` 证明至少发生一次重试；把计时起点移到 `stop_event.set()` 之后（`:1140-1141`）；停止后等待线程退出并断言 `elapsed < 2.0`；随后 `time.sleep(0.8)`（大于第二次失败后剩余的 0.4s 退避），再断言 `len(calls) == 2` 证明没有第三次尝试（`:1146-1150`）；新增健康账号的 held / 线程存活 / 会话未关闭断言（`:1151-1153`）。
    - 判别力实测：把当前测试文件放入 anchor `c7ce5875` 的 pre-fix 实现（临时目录，不改 worktree）单独运行 `test_t073_ac003_stop_during_catchup_retry_returns_promptly`，得到 `1 failed`，失败点为 `AssertionError: catch-up retry never ran`（`_wait_until(len(calls) >= 2)` 超时）；当前实现下同一测试通过。该测试已能区分 pre-fix，Round 1 指出的「旧实现同样 PASS」不再成立。
    - 不再依赖 `elapsed < 2` 或 `held == set()` 单独作证：「不再继续重试」由线程已退出 + 停止后不再出现第三次调用共同证明；「不影响其他 watch」有独立断言。
    - 弱化风险复核：修复方向是加强断言，不是把断言改成迁就实现的弱形式；无删断言、反转、注释、`.skip` / `.only`。

### 本轮新发现

无（0 条）。

### AC 复验方式

- AC-001：`re_verified`。`scripts/run-mail-core-tests.sh run tests/mail_core/test_t061_idle_watcher.py -k "t073 or ac001_first_connect or ac002_reconnect or ac002_catchup_merges or ac005_catchup_enqueue" -q` → 8 passed；`test_t073_ac001_catchup_retries_transient_enqueue_failure` 断言 delta 任务存在、`calls == _CATCHUP_RETRY_ATTEMPTS`、held/idling、`sync_status != failed`。
- AC-002：`re_verified`。同一命令通过；`test_t073_ac002_persistent_catchup_failure_releases_seat_for_polling` 断言 snapshot 为 `backoff`、首个会话 `closed`、held 为空、`schedule_periodic_inbox_sync` 入队 1 且 delta 任务存在、`sync_status != failed`。
- AC-003：`re_verified`。同一命令通过；断言链见上，且已在 anchor pre-fix 实现上复跑确认红灯。
- AC-004：`re_verified`。同一命令包含 t071 首连/重连/pending/claimed 回归测试并全部通过；`test_t073_ac001` 对重试成功后同去重键任务行数断言为 1。
- coverage = 4/4

### 结论

- 前轮 finding 复核：`t073_test_f001` 已消除（证据与 pre-fix 红灯实测见上）。
- 改测方向复核：无。Round 1→2 的测试改动只有强化 AC-003 测试；未把既有断言改成迁就实现，未删除/反转/注释断言，无 `skip` / `only` / `type: ignore` 等静默模式；`# noqa: SLF001` 仅用于测试内访问私有 seam，不是掩盖失败。
- 本轮新发现：0 条。
- 未进表的提示：
    - AC-003 测试的 0.8s 负向窗口与当前 `_CATCHUP_RETRY_BASE_S=0.2`、`_CATCHUP_RETRY_ATTEMPTS=3` 绑定（`src/mail_core/sync/idle_watcher.py:61-62`）；若退避参数调整，需同步复核该测试，建议导入常量并断言预算至少 3 或改用事件同步，避免时序退化。
    - AC-001 仍未直接断言「当前 IDLE 会话未被关闭/重建」（scope 的「保持当前 IDLE 会话」）；可在 factory 记录实例并断言 `closed is False` 且只构建一次。属可选补强，不阻断。
    - `test_ac005_catchup_enqueue_failure_does_not_stop_watch`（`:1160`）的「later IDLE change enqueues」现在被 t073 重试成功后已存在的同去重键任务掩盖，`changed` 分支是否再次入队无法从 job 行数区分；该测试仍验证失败隔离，且 changed 路径另有 t071 测试覆盖，故未出 finding，建议后续清理其 docstring/场景描述。
    - Round 1 提示的 AC-002「下一次重连继续尝试补偿」属于范围描述而非 AC，仍未直接覆盖；本 task 不据此出 finding。
- 总体判断：前轮唯一 important 已消除，未发现新的 AC 覆盖缺口或危险测试模式；本轮 PASS。
- 系统性 follow-up：无。

verdict: PASS
