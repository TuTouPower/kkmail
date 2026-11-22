# Task review t082（reviewer_focus: 测试）

- task：`t082_sync_request_completion_by_data_watermark`
- spec：`docs/tasks/t082_sync_request_completion_by_data_watermark/task.md`
- diff_anchor：`1998e95ff67999ac896b9e118b47902ebfefdfc8`
- target：`git diff 1998e95ff67999ac896b9e118b47902ebfefdfc8`
- round：1
- reviewed_at：2026-11-22T15:44:10+08:00

reviewed_scope: d56bcbb2bb33b2a1

## Findings

### t082_test_f001 - AC-007 承诺的“迁移后数据断言”缺失

- 严重度：minor
- 锚点：AC-007（数据库迁移执行后旧观察关系被清理、报告与列表一致）
- 位置：`tests/mail_core/test_sync_execution_unit.py:34`（`test_target_link_always_points_at_a_real_job`）；迁移 `src/mail_core/db/alembic/versions/20261122_0003_real_job_links.py:29-44`
- 问题：可测试性声明明确写“AC-007 另由迁移后 schema 与数据断言验证”。现有测试只有 schema shape 断言（`job_id` NOT NULL、`execution_generation` 不存在、`needs_successor` 存在）与 alembic head 链断言；没有任何测试构造 `job_id IS NULL` 的旧 link + queued/running target 并执行 `20261122_0003` 迁移，验证旧观察关系被删除、target 转 failed/safe_message 可读、报告与列表一致。迁移清理 SQL 的正确性无可执行的测试证据。
- 建议：新增迁移专项测试，在旧 schema 插入 `job_id IS NULL` 的 link，upgrade 到 head 后断言 link 被删除、对应 target 为 failed 且 safe_message 可读、报告无 `execution_lost`。

### t082_test_f002 - AC-004“瞬时错误经重试后最终 complete”缺直接断言

- 严重度：minor
- 锚点：AC-004（瞬时网络错误经重试后数据推进的，请求最终 complete）
- 位置：`tests/mail_core/test_sync_execution_tracking.py:248`（`test_retriable_failure_keeps_target_open_terminal_failure_fails_request`）
- 问题：该测试覆盖“瞬时失败后请求保持 open”与“终态失败 fail + code=job_failed”，但未覆盖 AC-004 明确的另一半因果链——瞬时错误后重试成功、请求最终 complete。正常路径 complete 由同文件 `:137` 测试覆盖，但“重试推进后 complete”这一链本身无断言。
- 建议：把第二次 attempt 改为成功执行 `handle_job`（而非再次 `fail_job`），断言 `_report(request_id).state == "complete"` 且 `failed_count == 0`，形成“瞬时失败→重试推进→complete”闭环。

### t082_test_f003 - known_revisions 断言由 `==` 放宽为 `<=`

- 严重度：minor
- 锚点：AC-008（无弱化断言、无临时补丁残留）
- 位置：`tests/mail_core/test_baseline_unit.py:147`
- 问题：`assert ctx.known_revisions == frozenset({UNIFIED_BASELINE_REVISION, CURRENT_HEAD_REVISION})` 改为 `{...} <= ctx.known_revisions`。因新增 `20261122_0003` 迁移且 `known_revisions` 动态取自 alembic 树（`src/mail_core/db/baseline.py:988`），放宽有正当理由，非迁就缺陷；但 `<=` 允许任意额外 revision 混入而不失败。`ctx.heads == (CURRENT_HEAD_REVISION,)` 与线性链断言仍在，实际风险低。
- 建议：保留 `<=` 同时补一条对完整 revision 集合（含 `20261112_0002`）的精确断言，或在断言旁注明放宽理由，防止历史迁移被误删而无人察觉。

## 结论

- 前轮 finding 复核：无（Round 1 首轮）
- 改测方向复核：无“迁就实现”的改测。删除的 3 个文件（`test_a322_live_generations_payload.py`、`test_sync_orphan_patrol_live_generations.py`、`test_sync_orphan_patrol_stale_snapshot.py`）被测机制（预分配后继代际、孤儿巡检 live-generation 快照）已由本 task 整体移除，属规格要求的合法删除；其终态失败语义由 `test_sync_request_completion_by_data.py` 与 `converge_stalled_targets` 测试在更高层补回。其余改写均为“代际→真实 job link”的规格迁移（API 更名 `settle_job_bindings`→`settle_job_links`、`converge_orphaned_bindings`→`converge_stalled_targets`、schema 字段移除）。唯一弱化断言见 f003，有正当理由。
- 本轮新发现：3 条（均 minor）
- 未进表提示：
    - 用户提供的门禁结果：后端完整 PostgreSQL 套件 2202 passed / 2 skipped；`test_cmd` 全通过；`blackbox_verify` 23 passed。`test_cookie_secure_guard_ignores_out_of_tree_symlink` 为 pre-existing 环境失败（harness 默认 basetemp 在 worktree 内导致，main 分支同失败），不计入本 task。
    - 本 reviewer 环境未设 `MAIL_CORE_DATABASE_URL` 且受 `KKMAIL_TEST_MODE` 守卫，无法独立重跑 DB 集成与前端 npm 门禁；已用 `KKMAIL_TEST_MODE=unit ... --collect-only` 独立确认 19 个相关测试全部可收集、无 import/collection error（被测 API 均存在）。AC-008 因此标 `trust_prior`。
    - 新增测试用 `pytest.mark.skipif(not MAIL_CORE_DATABASE_URL)` 为环境守卫，非危险模式 `.skip`。
    - 危险模式全项扫描（恒真断言、删/反转 expect、注释断言、弱化断言、删测试、skip/only、静默错误、mock 误用、阈值掩盖、条件跳过、程序赋值替代交互、存在即通过）未命中伪造绿；删除的 expect（`test_sync_execution_lock_order.py` 的 event state 断言、`test_sync_execution_tracking.py` 中间态 `completed_count == 0`）在其它测试有等价或更强断言，非掩盖失败。
- 总体判断：测试直接触达生产函数（`create_sync_request` / `get_sync_request_report` / `claim_jobs` / `complete_job` / `fail_job` / `converge_stalled_targets` / `settle_job_links`），断言 `report.state` / `errors[].code` / `safe_message` 等用户可观察效果，无恒真断言、无 mock 被测逻辑、无假绿；3 条 minor 不阻断。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。新增 `test_sync_request_completion_by_data.py` 与 `test_sync_execution_tracking.py:137,201` 断言 report 终态 complete 且无 `execution_lost`；前端无内部术语硬编码，既有 `src/frontend/src/api/sync.test.ts:167` 证实 UI 仅透传 safe_message。
- AC-002：TICK-VALID，re_verified。`test_sync_request_completion_by_data.py:116-133`、`test_sync_execution_tracking.py:201-245` 覆盖 CLAIMED job 经 successor pass 收敛 complete、无 execution_lost。
- AC-003：TICK-VALID，re_verified。`test_sync_execution_tracking.py:169-198` 两请求共享同一真实 job 且均 complete；`test_sync_request_completion_by_data.py:101-113` 断言无 link 指向幻影 successor。
- AC-004：TICK-VALID，re_verified。`test_sync_execution_tracking.py:248-295` 与 `test_sync_request_completion_by_data.py:136-152` 断言明确原因 failed + 可读文案、瞬时失败保留 open；“重试后 complete”链缺直接断言（f002）。
- AC-005：TICK-VALID，re_verified。`test_sync_execution_tracking.py:483-504` 超时 target 经 `converge_stalled_targets` 转 failed / `sync_incomplete`，文案无 “no longer exists”。
- AC-006：TICK-VALID，re_verified。既有 `src/frontend/src/api/sync.test.ts:177-342` A21 describe 断言后台失败隔离、主请求终态不被污染、safe_message 可读；前端本轮行为未变。
- AC-007：TICK-VALID，re_verified。`test_sync_request_completion_by_data.py:149-152` 与 `test_sync_execution_tracking.py:503-504` 断言 errors code 无 `execution_lost` 且 safe_message 非空可读；`test_sync_execution_unit.py:34-43` 断言迁移后 schema shape；迁移数据清理缺直接断言（f001）。
- AC-008：TICK-VALID，trust_prior。依赖实施侧提供的 `test_cmd` / `blackbox_verify` / 后端套件结果；reviewer 独立 `--collect-only` 确认 19 个相关测试可收集；弱化断言见 f003（有正当理由）。

coverage = 7/8

verdict: PASS

## Round 2 (2026-11-22T16:15:00+08:00)

- task：t082_sync_request_completion_by_data_watermark
- spec：docs/tasks/t082_sync_request_completion_by_data_watermark/task.md
- diff_anchor：1998e95ff67999ac896b9e118b47902ebfefdfc8
- target：git diff 1998e95ff67999ac896b9e118b47902ebfefdfc8
- round：2
- reviewed_at：2026-11-22T16:15:00+08:00

reviewed_scope: 01e4e79bfeee0c35

## Findings

Round 2 零 finding：本轮无新 finding。

## 结论

- 前轮 finding 复核：
    - `t082_test_f001`（minor，AC-007 迁移后数据断言缺失）：遗留 p084，接受。已核实 `docs/pending/p084_sync_migration_orphan_link_assertion.md` 为 `status: todo` 的已登记跟进项，`线索` 明确引用本 finding，缺口定性为测试基础设施（缺中间版本临时库夹具）而非产品缺陷；相对 Round 1 交付无新变化，不阻断。AC-007 其余证据仍成立，维持 TICK-VALID。
    - `t082_test_f002`（minor，AC-004「瞬时错误重试后 complete」缺断言）：已消除。新增 `test_sync_request_completion_by_data.py:156-185`（`test_transient_failure_then_retry_completes_request`）先 `fail_job(..., max_attempts=5)` 断言 state 仍 queued/running 且 `failed_count == 0`，再用 `claim_jobs(now=due)` 越过 backoff 重认领同一 job 并 `complete_job`，最终断言 `state == "complete"`——形成「瞬时失败→重试推进→complete」闭环，非迁就实现的恒真断言。
    - `t082_test_f003`（minor，known_revisions `==`→`<=`）：同意维持，理由成立。diff 中 `tests/mail_core/test_baseline_unit.py:37` 仍为 `<=`；因新增迁移 `20261122_0003` 且 known_revisions 动态取自 alembic 树，放宽有正当理由，且 `ctx.heads == (CURRENT_HEAD_REVISION,)` 与线性链断言仍在，不构成无理由弱化；处置理由记于 `progress.md:40`。
    - 代码轴 `t082_code_f001` 修复的覆盖：新增 `test_sync_execution_tracking.py:507-528`（`test_stalled_reaper_keeps_target_with_live_job`）独立复验——将 target.created_at 设为 31 分钟前但保留其 link 指向 PENDING 真实 job，`converge_stalled_targets(stale_after=30min)` 应返回 0 且请求不被 failed。该用例与 `:483-504`（job 已 DONE 时收敛为 `sync_incomplete`）构成正反对照。已核实 `create_sync_request` 经 `enqueue_job` + `bind_target`（`sync_requests.py:370-398`）为 target 绑定真实存活 job，故该用例非假绿，真实覆盖「长账号活 job 不被误杀」修复。
- 改测方向复核：无「迁就实现」的改测。相对 Round 1 的测试侧交付新增两个用例（f002 修复、reaper 修复覆盖），均为新增覆盖而非改写既有断言预期；既有改写延续「代际→真实 job link」的规格迁移（API 更名、schema 字段移除），Round 1 已逐项核对合法。
- 本轮新发现：0 条（Round 2 零 finding）。
- 未进表的提示：
    - `test_sync_request_completion_by_data.py` 为未跟踪文件且未经 `git add -N`，不出现在 `git diff` 中；本 reviewer 已直接读取全文复核，且本轮指纹与当前重算一致，无 reviewer 不可见的交付文件。建议派审前对新增交付文件执行 `git add -N`（流程提示，非本 task finding）。
    - reviewer 环境未设 `MAIL_CORE_DATABASE_URL`，未独立重跑 PostgreSQL 集成套件与前端 npm 门禁；AC-008 标 `trust_prior`，依赖实施侧门禁记录。范围外环境既存失败 `test_cookie_secure_guard_ignores_out_of_tree_symlink`（t079，basetemp 落在 worktree 内）不计入本 task。
    - AC-003「入库数据不重复」无独立的入库消息计数断言，仅由「同键合并到同一真实 job」间接支撑；去重键语义属非范围且未改，可选覆盖扩展，非阻断。
- 总体判断：前轮三条 finding 均核实闭环——f002 由真实重试闭环测试消除、f003 理由成立维持、f001 以已登记 p084 遗留；新增 reaper 正反对照用例真实覆盖代码轴修复。全量测试改动直接触达生产函数，断言 `report.state` / `errors[].code` / `safe_message` 等用户可观察效果，无恒真断言、无 mock 被测逻辑、无假绿、无新 blocker；8 条 AC 打勾持续获测试侧支撑，PASS。
- 系统性 follow-up：p084（`docs/pending/p084_sync_migration_orphan_link_assertion.md`，AC-007 迁移数据清理断言，minor/非阻断）。

### 危险模式扫描（Round 2）

- 恒真 / 存在即通过 / 弱化断言 / 删反转或注释断言 / `.skip` / `.only` / `ts-ignore` / `eslint-disable` / mock 被测逻辑 / 阈值掩盖 / 条件跳过 / 程序赋值替代交互：相对 Round 1 的新增测试（`test_transient_failure_then_retry_completes_request`、`test_stalled_reaper_keeps_target_with_live_job`）逐条核对均为真实状态断言（`state == "complete"`、`changed == 0`、`failed_count == 0`）；`assert len(links) >= 2` 仅为 setup 前置，真实证据在其后 `job_id is not None` 与 `s.get(...) is not None` 循环断言；`pytest.mark.skipif(not MAIL_CORE_DATABASE_URL)` 为环境守卫非 `.skip`。未命中伪造绿。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_sync_request_completion_by_data.py:117-134` 与 `test_sync_execution_tracking.py:137-166` 断言 report.state=complete 且 errors 无 execution_lost；`src/frontend/src/api/sync.test.ts:162-174` 断言无失败时 `syncFailureDetail` 返回 null、失败仅透传 safe_message，UI 不出现内部术语。
- AC-002：TICK-VALID，re_verified。`test_sync_request_completion_by_data.py:117-134` 与 `test_sync_execution_tracking.py:201-245` 覆盖 CLAIMED 期间到达请求经后继 pass 收敛 complete；`converge_stalled_targets`（`execution.py:460-541`）不再产生 execution_lost，正向失败码为 sync_incomplete。
- AC-003：TICK-VALID，re_verified。`test_sync_execution_tracking.py:169-199` 两请求共享同一真实 job（job_id 相等且非空）并均 complete；`test_sync_request_completion_by_data.py:102-114` 断言所有 link 指向真实存在的 job，无幻影后继。
- AC-004：TICK-VALID，re_verified。`test_sync_request_completion_by_data.py:137-153` 终态失败带可读 safe_message 且无内部术语；`:156-185` 证明瞬时失败 `failed_count == 0`、重试推进后 complete；`test_sync_execution_tracking.py:201-245` 覆盖后继迁移链路。
- AC-005：TICK-VALID，re_verified。`test_sync_execution_tracking.py:483-504` 停滞目标经 `converge_stalled_targets` 转 failed / `sync_incomplete` 且文案不含 "no longer exists"；`:507-528` 活 job 目标不被误杀（`changed == 0`），无悬挂。
- AC-006：TICK-VALID，re_verified。`src/frontend/src/api/sync.test.ts:177-195` A21 describe 断言后台失败隔离、仅取 background safe_message，主请求终态不被污染；`:197+` 轮询至后台 complete；前端本轮无改动。
- AC-007：TICK-VALID，re_verified。`test_sync_request_completion_by_data.py:149-153` 与 `test_sync_execution_tracking.py:503-504` 断言 errors.code 无 execution_lost 且 safe_message 非空可读；`test_sync_execution_unit.py:30-56` 断言迁移后 schema shape（job_id NOT NULL、generation 列移除、needs_successor、CASCADE FK、head=20261122_0003）；迁移数据清理的直接断言遗留 p084（f001，minor，已登记）。
- AC-008：TICK-VALID，trust_prior。依赖实施侧 `test_cmd` / `blackbox_verify` / 后端 2202 passed 的门禁记录；本测试轴独立扫描完整 diff 未发现弱化断言、恒真断言、mock 被测逻辑、`.skip` 或临时补丁；f003 的 `<=` 放宽有新增迁移正当理由且强断言仍在。

coverage = 7 / 8

verdict: PASS

## Round 3 (2026-11-22T16:04:53+08:00)

- task：t082_sync_request_completion_by_data_watermark
- spec：docs/tasks/t082_sync_request_completion_by_data_watermark/task.md
- diff_anchor：1998e95ff67999ac896b9e118b47902ebfefdfc8
- target：git diff 1998e95ff67999ac896b9e118b47902ebfefdfc8
- round：3
- reviewed_at：2026-11-22T16:04:53+08:00
- 复验触发：Markdown 格式化后 review scope 指纹由 `01e4e79bfeee0c35` 漂移至 `dad3685032ec1332`；本轮确认格式化仅改排版，交付语义与测试证据未变，并重算范围指纹。

reviewed_scope: dad3685032ec1332

## Findings

Round 3 零 finding：本轮无新增 finding，finding 编号不续编。

## 结论

- 前轮 finding 复核：Round 2 零 finding；Round 1 三条 minor 的处置（`t082_test_f001` 遗留 p084、`t082_test_f002` 由真实重试闭环测试消除、`t082_test_f003` 放宽理由成立）已在 Round 2 逐条核实。本轮交付相对 Round 2 仅 Markdown 排版变化，无回归，处置结论不变。
- 改测方向复核：无。格式化未触及测试断言或生产代码；`tests/mail_core/test_sync_request_completion_by_data.py:156-185`（`test_transient_failure_then_retry_completes_request`）仍为「瞬时失败→重试推进→complete」真实状态断言，非迁就实现。
- 本轮新发现：0 条。
- 未进表的提示：
    - 格式化触碰的非排除文件为 `docs/blueprint/conventions.md`（另有 task 目录内的进度/过程文件，均在指纹排除列表内）；逐项核对排版变化未改变任何 AC 语义、测试断言或生产行为，`git status --short` 中测试与源码文件相对 Round 2 无新增改动。
    - reviewer 环境未设 `MAIL_CORE_DATABASE_URL`，AC-008 维持 `trust_prior`，依赖实施侧 `test_cmd` / `blackbox_verify` 门禁记录；code 轴已独立重跑其门禁项，本测试轴不重复。
    - `tests/mail_core/test_sync_request_completion_by_data.py` 仍为未跟踪新增文件（未 `git add -N`），已直接读取全文复核，非 reviewer 不可见交付（流程提示，非本 task finding）。
- 总体判断：格式化后复审范围指纹更新为 `dad3685032ec1332`，结论仍为 PASS；8 条 AC 打勾持续获测试侧支撑，8/8 AC 均 `TICK-VALID`（7 条 re_verified + AC-008 trust_prior，coverage=7/8），零新增 finding、无 blocker。
- 系统性 follow-up：p084（`docs/pending/p084_sync_migration_orphan_link_assertion.md`，AC-007 迁移数据清理断言，minor/非阻断，沿用 Round 2）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/mail_core/test_sync_request_completion_by_data.py:117-134` 与 `tests/mail_core/test_sync_execution_tracking.py:137-166` 断言 report.state=complete 且 errors 无 execution_lost；`src/frontend/src/api/sync.test.ts:162-174` 断言无失败时 `syncFailureDetail` 返回 null、失败仅透传 safe_message，UI 不出现内部术语。
- AC-002：TICK-VALID，re_verified。`tests/mail_core/test_sync_request_completion_by_data.py:117-134` 与 `tests/mail_core/test_sync_execution_tracking.py:201-245` 覆盖 CLAIMED 期间到达请求经后继 pass 收敛 complete；`converge_stalled_targets` 不再产生 execution_lost，正向失败码为 sync_incomplete。
- AC-003：TICK-VALID，re_verified。`tests/mail_core/test_sync_execution_tracking.py:169-199` 两请求共享同一真实 job（job_id 相等且非空）并均 complete；`tests/mail_core/test_sync_request_completion_by_data.py:102-114` 断言所有 link 指向真实存在的 job，无幻影后继。
- AC-004：TICK-VALID，re_verified。`tests/mail_core/test_sync_request_completion_by_data.py:137-153` 终态失败带可读 safe_message 且无内部术语；`:156-185` 证明瞬时失败 `failed_count == 0`、重试推进后 complete；`tests/mail_core/test_sync_execution_tracking.py:201-245` 覆盖后继迁移链路。
- AC-005：TICK-VALID，re_verified。`tests/mail_core/test_sync_execution_tracking.py:483-504` 停滞目标经 `converge_stalled_targets` 转 failed / `sync_incomplete` 且文案不含 "no longer exists"；`:513-528` 活 job 目标不被误杀（`changed == 0`），无悬挂。
- AC-006：TICK-VALID，re_verified。`src/frontend/src/api/sync.test.ts:177-195` A21 describe 断言后台失败隔离、仅取 background safe_message，主请求终态不被污染；`:197+` 轮询至后台 complete；前端本轮无改动。
- AC-007：TICK-VALID，re_verified。`tests/mail_core/test_sync_request_completion_by_data.py:149-153` 与 `tests/mail_core/test_sync_execution_tracking.py:503-504` 断言 errors.code 无 execution_lost 且 safe_message 非空可读；`tests/mail_core/test_sync_execution_unit.py:30-56` 断言迁移后 schema shape；迁移数据清理的直接断言遗留 p084（f001，minor，已登记）。
- AC-008：TICK-VALID，trust_prior。依赖实施侧 `test_cmd` / `blackbox_verify` / 后端 2202 passed 的门禁记录；本测试轴独立扫描完整 diff 未发现弱化断言、恒真断言、mock 被测逻辑、`.skip` 或临时补丁；f003 的 `<=` 放宽有新增迁移正当理由且强断言仍在。

coverage = 7 / 8

verdict: PASS
