---
pid: "p083"
slug: "manual_sync_execution_lost_false_failure"
status: "closed"
resolution: "transferred"
reason: "已核实根因与范围并转交该 task"
fix_ref: "t082"
---
# p083 手动立即同步预分配后继执行丢失误报 The bound sync execution no longer exists

- 现象：
    1. 用户账号 `fengandelliot@gmail.com` 在 Gmail 有 2,403 封邮件；2026-11-22 12:36/12:37 CST 在收件箱点「立即同步」，UI 同时出现红字「立即同步失败：The bound sync execution no longer exists」与灰字「收件箱已同步，后台正在同步其余文件夹...」。用户据此判断邮件没同步到。
    2. 实际是**假失败**：该账号本地库 `messages` 有 11,182 条，最新 3 封（12:37 CST，如「Use 821729 to set up recovery email」）已入库，与 Gmail 截图时间吻合；账号 `credential_state=valid`、`connectivity_state=connected`、`sync_enabled=t`。邮件已同步，仅请求被判失败并暴露内部实现文案。
    3. 生产库证据（2026-11-22 04:36–04:39Z）：主请求 `2b406d64-54d3-4040-b76d-8ea8956762e4` state=`failed`，其 inbox target `1778b3bc-...` `error_code=execution_lost`、`safe_error=The bound sync execution no longer exists`、`requested_generation=ac891d78-...`；绑定 `f0a2fa8c-...` `job_id=NULL`、generation=`ac891d78-...`、`phase=delta`，创建于 04:37:14Z。父 job `438c32b9-...`（dedupe `delta:...:c198d81a`，自身 gen `baee90a4-...`）当时处于 CLAIMED，其 `_queue_next.execution_generation` 预分配了 `ac891d78-...`，但**从未 materialize 出对应 job**。04:37:39Z worker 日志 `converged 1 orphaned sync-request binding(s)`，reaper 判 `execution_lost`；父 job 04:38:52Z 终态 `done`（`failure_attempts=1`，`last_error=OSError code=[REDACTED]`）。同次后台请求 `a5c1ee6d-...` 仍 `running`，与主失败提示并存。
- 影响：
    1. 手动「立即同步」在邮件实际已入库时向用户报假失败；内部英文实现文案经 `MessageList.tsx:584` 进入「立即同步失败：」横条，误导用户认为邮件/账号异常。
    2. 同族位点（均经 `binding_generation_for` 产生 `job_id=NULL` 的后继绑定，同一失效机制）：`sync_requests.py:391`（delta 目标，本次命中）、`:421`（full 目标）、`:486`（A21 后台文件夹发现）、`execution.py:329`（`_bind_initialization`）、`engine.py:163`（`_bind_phase_jobs`）。五处确认成立。
    3. 未 materialize 的候选路径（生产只确认结果，未逐一确认命中哪条）：`fail_job` 达重试上限终态、`reclaim_stale_claims` 终态、`complete_job` 因 `followup_was_scheduled=True` 不建 successor、`_queue_next` 在 wakeup/merge（`jobs.py:57-96`，仅在快照含该键时保留 generation）中被重建而丢失。生产父 job 最终 `done` 而非 `failed`，最似 generation 在 payload 中丢失或 `complete_job` 走了不建后继分支。
- 根因：
    1. 产品缺陷（执行跟踪设计，非环境/配置）：`converge_orphaned_bindings`（`execution.py:624-725`）把「绑定 `job_id=NULL` 且 generation 不在 live 集合」一律等同于「执行丢失」，写 `error_code=execution_lost` + `EXECUTION_LOST_MESSAGE`（`execution.py:60`、`:711-714`）；`refresh_requests` 聚合为 request `failed`，报告端点原样透出 `safe_message`，前端 `MessageList.tsx:583-584` 直接拼接成用户可见错误。
    2. 设计根因：预分配后继 generation 的绑定生命周期绑在父 job 的 `_queue_next` payload 上，任何使该 generation 不再 live 的路径（父 job 终态、payload 重建丢失、`complete_job` 不建后继）都会让健康请求被判死。reaper 的 decision-time recheck（`execution.py:700-710`）仅防「快照竞态」（见 `test_sync_orphan_patrol_stale_snapshot.py`），不防「generation 真的被丢」；`test_sync_orphan_patrol_live_generations.py:10-24` 甚至把 execution_lost 定义为合法终态。
    3. 测试假绿：`test_sync_execution_tracking.py:201-255` 只覆盖「CLAIMED → successor 正常 materialize → 绑定满足」的 happy path；`test_sync_execution_tracking.py:493-517` 覆盖「job 被删 → execution_lost 是期望结果」，均不覆盖「后继从未 materialize 时健康请求应如何收敛」。
- 测试缺口：
    1. 后端 PG 集成测试：补「CLAIMED job 的后继绑定 → 父 job 终态失败 / payload 丢失后继 generation / `complete_job` 走 `followup_scheduled` 不建 successor → reaper 后请求不得报 `execution_lost`」用例，应重新绑定到在途 job 或收敛为可重试的明确失败；覆盖上列 5 个 `binding_generation_for` 位点中 delta / full / A21 后台 / `_bind_initialization` 至少四条。保留现有以 `execution_lost` 为合法终态的用例，新增反例语义。
    2. 前端组件测试：`MessageList.test.tsx` 补断言——内部实现文案（如 `The bound sync execution no longer exists`）不得原样出现在「立即同步失败：」之后，应映射为用户可理解文案或静默重试；并覆盖主失败与「收件箱已同步，后台正在同步其余文件夹...」并存的矛盾状态。
    3. `.scratch/repro_execution_lost.py` 可直接作为后端集成用例骨架（真实 `create_sync_request`/`claim_jobs`/`fail_job`/`converge_orphaned_bindings`，已复现精确文案）。
- 线索：
    - `.scratch/repro_execution_lost.py`（隔离库已迁移，复现输出：`request#2 state=failed errors=[('execution_lost', 'The bound sync execution no longer exists')]`）
    - 生产 DB：请求 `2b406d64-54d3-4040-b76d-8ea8956762e4`（failed）/ `a5c1ee6d-0f33-4e55-9072-b582cfec5de8`（running）；binding `f0a2fa8c-...`；父 job `438c32b9-...`；后继 gen `ac891d78-7fa7-41d9-bcbb-44d946adbb4d`
    - 关键代码：`src/mail_core/sync/execution.py:60,624-725`、`src/mail_core/sync/jobs.py:57-96,316-327,394-404`、`src/mail_core/mail/application/sync_requests.py:391-400,433-500`、`src/frontend/src/components/MessageList.tsx:583-584,594-612`
- 处理：t082；resolution=transferred；reason=已核实根因与范围并转交该 task
