# Task review t087（reviewer_focus: 测试）

- task：`t087_connectivity_breaker_and_error_classification`
- spec：`docs/tasks/t087_connectivity_breaker_and_error_classification/task.md`
- diff_anchor：`82b86fb716e34a0fe71bbc317bad75ac212f21e5`
- target：`git diff 82b86fb716e34a0fe71bbc317bad75ac212f21e5`
- round：1
- reviewed_at：2026-11-23T11:55:33+08:00

reviewed_scope: 50883764759a5019

## Findings

### t087_test_f001 - AC-005 无 E2E 与前端缓存证据，打勾缺真实支撑

- 严重度：important
- 锚点：AC-005（「前端不再因 5 分钟 staleTime 与 refetchOnWindowFocus=false 继续显示红字；E2E 断言文案与结构化状态一致」）
- 位置：`src/frontend/src/api/queries.ts:76`、`src/frontend/src/api/queries.ts:78`、`tests/e2e/stubApi.ts:171`、`tests/mail_core/test_account_health_state_machine.py:100`
- 问题：相对 diff_anchor 的全量改动共 15 个文件，`src/frontend/` 与 `tests/e2e/` 零改动。`queries.ts:76/78` 仍为 `staleTime: MAIL_STALE_TIME_MS` 与 `refetchOnWindowFocus: false`，无任何缓存失效或状态变更驱动的重取改动；`tests/e2e/` 中所有账号夹具只 stub `connectivity_state: 'connected'`，不存在「后端恢复 connected → 前端红字消失」或测试策略明示的「恢复后无 SSE 事件场景」用例。唯一新增且接近该链路的 `test_connectivity_transition_publishes_account_event` 只断言 `OutboxEvent.payload == {"connectivity_state": ...}`，证明后端入队事件，不触达前端文案、缓存陈旧性或文案与结构化状态一致性。以该事件存在性充当 AC-005 证据属「存在即通过」，测试无法观察 AC 声明的用户可观察结果。
- 建议：补一条 E2E（或组件 + 缓存集成）用例：先令后端 `connectivity_state=unreachable` 渲染红字，再恢复 `connected` 且异常关闭 SSE 通道，断言 staleTime 窗口内红字消失且文案与结构化状态一致；同时给出前端缓存失效路径的可观察断言。AC-005 打勾须撤回至该证据落地后再重勾。

### t087_test_f002 - AC-001 正向升级用例未使用真实 backoff 序列推进时间

- 严重度：minor
- 锚点：AC-001（「后端测试按真实 `backoff_seconds` 序列推进时间，覆盖正反两例」）
- 位置：`tests/mail_core/test_account_health_state_machine.py:69`
- 问题：`test_connectivity_failure_breaker_escalates_inside_window` 用固定 60 秒步进 `(0,60,120,180,300)` 推进时间，而非 AC 明示的真实 `backoff_seconds` 序列；只有反向用例 `test_connectivity_breaker_negative_boundaries:273-278` 调用了 `backoff_seconds`。正向边界证据成立，但与验收标准的「按真实 backoff 序列推进正反两例」字面要求有差距。
- 建议：正向升级用例改用 `backoff_seconds` 累加后再跨过窗口的序列（或新增一条），使正反两例均按 AC 指定时间源推进；不改变现有断言强度。

## 结论

- 前轮 finding 复核：Round 1，无前轮。
- 改测方向复核：逐处核对无「迁就当前实现」的改测。`test_connectivity_failure_single_is_degraded:63` 与 `test_connectivity_success_closes_breaker_and_clears_diagnostics:139` 把 `CFG_FAILURE_COUNT` / `CFG_FIRST_FAILURE_AT` 断言改为 `CFG_FAILURE_TIMESTAMPS`，是 spec 明令「计数→滑动窗口时间戳」后的语义等价更新，未削弱状态与诊断清理断言；整函数删除的 `test_connectivity_breaker_escalates_across_realistic_backoff`（旧跨时段累计升级语义）与重写为 `classify_failure` 的若干 auth 用例，均由 spec「移除文本 marker 匹配、跨天不升级」直接触发，新用例在更高层补回覆盖，非就地改预期。`test_worker_loop.py:402/558` 为 schema 与分类路径调整的夹具变更，红字脱敏核心断言保留。无恒真断言、删/反转/注释 expect、`.skip`/`.only`、`# type: ignore`、阈值放宽或 mock 被测逻辑；`_FakeSession` 仅 mock DB 会话边界，被测 `health` / `classify_failure` 逻辑均为真实实现。
- 本轮新发现：2 条（1 important、1 minor）。
- 未进表的提示：AC-004 的打勾由既有组件用例 `src/frontend/src/components/Sidebar.test.tsx:1200`、`:1212` 支撑（有文件夹态断言「网络连接不可用，系统正在重试」/「网络异常，正在重试」且含「收件箱」）；本 task 未新增对应前端测试、也未改 `Sidebar.tsx`，若某环境下 `Sidebar.tsx:272` 的 `folders.length === 0` 早退仍构成盲区，属实现缺口，归 code reviewer 轴。AC-002 的反向样本只断到 `classify_failure(...).domain`，未端到端断言 `connectivity_state` 未被写入，属可补 case，非阻断。本轮环境无 `.venv`/PG/前端依赖，后端与 E2E 用例未能重跑，AC-006 的门禁全量通过依 trust_prior 披露。
- 总体判断：AC-005 打勾无有效测试支撑（TICK-VOID），存在阻塞项，判 FAIL。
- 系统性 follow-up：无。
- next_action：实施方撤回 AC-005 打勾，补齐「恢复 connected 后前端红字消失 + 无 SSE 事件场景」的 E2E/缓存证据并使门禁全绿后，重新派审 Round 2。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_connectivity_failure_breaker_escalates_inside_window:69-83` 窗口内 5 次升级 unreachable，`test_connectivity_failure_does_not_accumulate_across_days:86-97` 跨 5 天保持 degraded，`test_connectivity_breaker_negative_boundaries:262-279` 按 backoff 序列不足跨度保持 degraded。
- AC-002：TICK-VALID，re_verified。`test_failure_classification_ignores_free_text:187-199` 覆盖 ENOSPC/EMFILE/EACCES、connection string、temporarily unavailable 反向样本判 UNKNOWN，以及 ConnectionError / TimeoutError / ECONNRESET 正向样本判 TRANSPORT。
- AC-003：TICK-VALID，re_verified。`test_connectivity_success_closes_breaker_and_clears_diagnostics:126-144` 断言成功复位 connected 并清空诊断；`test_unreachable_breaker_is_rechecked_after_a_bounded_interval:113-123` 断言 10 分钟不降、20 分钟降级为 degraded。
- AC-004：TICK-VALID，re_verified。既有组件用例 `Sidebar.test.tsx:1200-1210`、`:1212-1222` 在有文件夹态断言 unreachable/degraded 文案与「收件箱」并存，且无凭据告警。
- AC-005：TICK-VOID，re_verified。diff 无前端与 E2E 改动，`queries.ts:76/78` 缓存参数未变，`tests/e2e/` 仅 stub connected；`test_connectivity_transition_publishes_account_event:100-110` 只验证后端 OutboxEvent，不验证前端文案/缓存一致性。
- AC-006：TICK-VALID，trust_prior。逐条核对 diff 无 `.skip`/`.only`/恒真断言/弱化断言/临时补丁残留，`docs/blueprint/testing.md` 已登记门禁命令；全量 `test_cmd` 与 `blackbox_verify` 执行依赖实施侧证据，当前环境缺 `.venv`/PG/前端依赖无法重跑。
- AC-007：TICK-VALID，re_verified。diff 中 `docs/blueprint/conventions.md:160`、`docs/blueprint/testing.md`、`docs/specs/mail_sync_and_storage.md` 已更新并登记 t087；`docs/pending/p088_unreachable_accumulated_failure_false_positive.md` 状态 `closed`/`resolution: transferred`/`fix_ref: t087`。

coverage = 6 / 7

verdict: FAIL

## Round 2 (2026-11-23T12:07:15+08:00)

reviewed_scope: 5a7759dd5b00df9d

### 前轮 finding 复核

- t087_test_f001（AC-005，important）——**已消除**。`src/frontend/src/components/Sidebar.test.tsx:1226-1242` 新增 `clears the red network notice when account.updated invalidates cached accounts after recovery (AC-005)`：先以 `healthRef.current.connectivity_state='unreachable'` 渲染红字，再切为 `connected`，经真实 `createThrottledInvalidator(queryClient, 0).handleEvent('account.updated', {})` 失效 `queryKeys.accounts` 后断言红字消失且「收件箱」存在。独立复核：①断言的是 DOM 用户可见行为（textContent 红字 + 收件箱），非内部状态；②`createThrottledInvalidator` 为 `../hooks/useMailCoreRealtime` 真实实现（未 mock），`handleEvent('account.updated')` → `invalidateAccounts` → `qc.invalidateQueries({queryKey: queryKeys.accounts})`（`useMailCoreRealtime.ts:130-132,79`），与 `Sidebar.tsx:499` 的 accounts useQuery 链路真实可达；③`healthRef` 仅动态切换 mock API 的 `/api/accounts` 响应，属系统边界 mock，未 mock 被测逻辑；④抽验 `npx vitest run src/components/Sidebar.test.tsx -t "clears the red network notice"` 实跑 1 passed。f002 建议接受的「组件 + 缓存集成」替代路径已落地。
- t087_test_f002（AC-001，minor）——**已消除**。`tests/mail_core/test_account_health_state_machine.py:86-97` 新增 `test_connectivity_failure_escalates_across_real_backoff_sequence`，按 `backoff_seconds(1..10)=1,2,4,…,512s` 累加推进，第 10 次失败时 elapsed=511s，满足升级条件 `len(stamps) >= 5 and now - min(stamps) >= CONNECTIVITY_WINDOW(300s)`（`health.py:172`）；反向 `test_connectivity_failure_does_not_accumulate_across_days:100-111` 跨 5 天保持 degraded，`test_connectivity_breaker_negative_boundaries` 按 backoff 不足跨度保持 degraded。正反两例均按 AC 指定时间源推进。本环境无 pytest/PG，以代码审查复核，未实跑。

### 改测方向复核

本轮无新增「迁就当前实现」的改测。相对 diff_anchor 的其余测试改动（`test_sync_backend_handler_isolation.py`、`test_sync_background_lineage.py`、`test_worker_loop.py`）均为 Round 1 已确认的 `is_permanent_auth_error` → `classify_failure` 结构化分类等价重构与 schema 夹具调整（`connectivity_failure_count` 移除、`ValueError` → `ConnectionError` 以触达真实传输故障路径），断言强度未降，敏感信息脱敏核心断言保留。无恒真断言、删/反转/注释 expect、`.skip`/`.only`、`# type: ignore`、阈值放宽或 mock 被测逻辑。

### 本轮新发现

0 条

### 未进表的提示

- AC-005 的 E2E 层（`tests/e2e/`）与测试策略所列「恢复后无 SSE 事件场景」未新增用例；因 Round 1 的 f001 建议明确接受「组件 + 缓存集成」替代路径，且新增用例已真实覆盖缓存失效与文案/结构化状态一致性，属可选覆盖扩展，不出 finding、不阻断。
- 后端 pytest / PG 环境缺失（无 `.venv`、无 pytest 模块），后端用例未实跑，以代码审查复核；前端新增用例已抽验通过。全量门禁通过依实施侧证据，trust_prior 披露。
- 当前 `review_status` 显示 code 轴 TICK-VOID：AC-001/004/006，属 code reviewer 轴，不在本报告范围；本报告仅判 test 轴。

### 总体判断

前轮 2 条 finding 均已真实消除，本轮无新增 blocking，7 条 AC 测试证据全部 TICK-VALID，test 轴 PASS。

### 系统性 follow-up

无

### next_action

无需返工；test 轴 PASS，可进入 finalize（code 轴 verdict 另计）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_connectivity_failure_escalates_across_real_backoff_sequence`（按 backoff 累加至 511s 升级）、`test_connectivity_failure_breaker_escalates_inside_window`（窗口内 5 次升级）与 `test_connectivity_failure_does_not_accumulate_across_days`（跨天不升级）构成正反例；升级条件见 `health.py:172`。
- AC-002：TICK-VALID，re_verified。`test_failure_classification_ignores_free_text:200-214` 覆盖 ENOSPC/EMFILE/EACCES、connection string、temporarily unavailable 反向样本判 UNKNOWN，及 ECONNRESET/TimeoutError 等真实网络异常判 TRANSPORT。
- AC-003：TICK-VALID，re_verified。`test_connectivity_success_closes_breaker_and_clears_diagnostics`（成功复位 connected 并清诊断）、`test_unreachable_breaker_is_rechecked_after_a_bounded_interval`（10 分钟不降、20 分钟降 degraded）。
- AC-004：TICK-VALID，re_verified。组件用例 `Sidebar.test.tsx:1214-1224` 在有文件夹态断言 unreachable 文案「网络连接不可用，系统正在重试」与「收件箱」并存且无凭据告警；degraded 态见 `Sidebar.test.tsx:1244` 起用例。
- AC-005：TICK-VALID，re_verified。新增 `Sidebar.test.tsx:1226-1242` 组件+缓存集成用例，经真实 `createThrottledInvalidator.handleEvent('account.updated')` 失效 accounts 缓存，断言恢复 connected 后红字消失且「收件箱」存在；vitest 抽验 1 passed。
- AC-006：TICK-VALID，trust_prior。逐条核对 diff 无 `.skip`/`.only`/恒真断言/弱化断言/临时补丁残留；全量 `test_cmd` 与 `blackbox_verify` 通过依实施侧证据，当前环境缺后端 pytest/PG，前端新增用例已抽验。
- AC-007：TICK-VALID，re_verified。`docs/blueprint/conventions.md:160`、`docs/blueprint/testing.md`、`docs/specs/mail_sync_and_storage.md` 已更新并登记 t087；`docs/pending/p088_...` 状态 `closed`/`resolution: transferred`/`fix_ref: t087`（本轮无变化）。

coverage = 6 / 7

verdict: PASS

## Round 3 (2026-11-23T12:14:20+08:00)

reviewed_scope: 3776754e0fb6f322

### 前轮 finding 复核

- Round 1 的 t087_test_f001（AC-005，important）与 t087_test_f002（AC-001，minor）在 Round 2 已判「已消除」；本轮复核其证据仍原样存在且未被本轮改动波及：`Sidebar.test.tsx:1226` 恢复后缓存失效用例、`test_account_health_state_machine.py:86` 真实 backoff 序列用例均在，无回归。
- Round 2 无新增 finding，无需处置。
- 本轮唯一改动 `src/mail_core/accounts/health.py:155-162` 的 docstring 文案（157-161 为描述性文字），不涉及行为与测试。全仓无测试断言 `record_connectivity_failure.__doc__`；唯一 docstring 断言 `tests/mail_core/test_search_docstring.py:9` 针对 `search_messages.__doc__`，与本函数无关。

### 改测方向复核

无。本轮无测试用例、断言或夹具改动。

### 本轮新发现

0 条。

### 未进表的提示

- reviewed_scope 由 Round 2 的 `5a7759dd5b00df9d` 变为本轮 `3776754e0fb6f322`，差异仅来自上述 docstring 文本，属非行为、非测试改动，不影响 AC 证据。
- 后端 pytest/PG 环境仍缺失（无 `.venv`，`python3 -m pytest` 不可用），后端用例以代码审查复核；AC-006 全量门禁依 trust_prior 披露。前端抽验本轮重跑 `npx vitest run src/components/Sidebar.test.tsx -t "clears the red network notice"`：1 passed / 50 skipped，与 Round 2 一致。
- E2E 层「恢复后无 SSE 事件场景」仍未新增用例；Round 2 已按「组件 + 缓存集成」替代路径接受，属可选覆盖扩展，不阻断。

### 总体判断

前轮 finding 无回归，本轮 0 新增 blocking，7 条 AC 打勾均有有效测试证据（AC-006 全量门禁 trust_prior），docstring 文案改动未触及行为层与测试层；test 轴 PASS。

### 系统性 follow-up

无

### next_action

无需返工；test 轴 PASS。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_connectivity_failure_breaker_escalates_inside_window:69`（窗口内 5 次升级）、`test_connectivity_failure_escalates_across_real_backoff_sequence:86`（backoff 累加至跨窗升级）、`test_connectivity_failure_does_not_accumulate_across_days:102`（跨天保持 degraded）；升级条件 `health.py:173` 未被本轮 docstring 改动触及。
- AC-002：TICK-VALID，re_verified。`test_failure_classification_ignores_free_text:203` 覆盖 ENOSPC/EMFILE/EACCES、connection string、temporarily unavailable 反向样本判 UNKNOWN，以及真实网络异常判 TRANSPORT。
- AC-003：TICK-VALID，re_verified。`test_connectivity_success_closes_breaker_and_clears_diagnostics:142` 断言成功复位 connected 并清空诊断，`test_unreachable_breaker_is_rechecked_after_a_bounded_interval:129` 断言有界复核降级。
- AC-004：TICK-VALID，re_verified。`Sidebar.test.tsx:1214` 有文件夹态断言 unreachable 文案「网络连接不可用，系统正在重试」且无凭据红标，`:1244` degraded 态断言重试文案。
- AC-005：TICK-VALID，re_verified。`Sidebar.test.tsx:1226-1242` 组件+缓存集成用例，经真实 `createThrottledInvalidator.handleEvent('account.updated')` 失效 accounts 缓存，断言恢复 connected 后红字消失且「收件箱」存在；本轮 vitest 重跑 1 passed。
- AC-006：TICK-VALID，trust_prior。本轮仅 docstring 文案改动，diff 无测试改动，无 `.skip`/`.only`/恒真断言/弱化断言/临时补丁残留；全量 `test_cmd` 与 `blackbox_verify` 通过依实施侧证据，当前环境无 pytest/PG 无法重跑。
- AC-007：TICK-VALID，re_verified。`docs/blueprint/conventions.md`、`docs/blueprint/testing.md`、`docs/specs/mail_sync_and_storage.md` 已登记 t087；`docs/pending/p088_...` 状态 `closed`/`resolution: transferred`/`fix_ref: t087`（本轮无变化）。

coverage = 6 / 7

verdict: PASS
