# Task review t074（reviewer_focus: 测试）

- task：`t074_inbox_first_account_sync`
- spec：`docs/tasks/t074_inbox_first_account_sync/task.md`
- diff_anchor：`923bc4b1628e5a528191401d0e903d0935f0d264`
- target：`git diff 923bc4b1628e5a528191401d0e903d0935f0d264`（worktree 根为仓库根）
- round：1
- reviewed_at：2026-11-05T04:34:36+08:00

reviewed_scope: d1b1fe5741d51526

## Findings

### t074_test_f001 - AC-003 重排后「收件箱先于同账号兄弟任务被认领」无直接组合测试

- 严重度：minor
- 锚点：AC-003 尾句「重新进入 pending 且同账号无在途任务时，收件箱任务先于同账号其他文件夹同类任务被认领」
- 位置：`tests/mail_core/test_sync_inbox_first.py:274`（`test_delta_lease_busy_requeue_keeps_priority` 起的全部重排用例，至 `:461`；handler 后继用例 `:473`、`:488` 同）
- 问题：全部重排用例只断言后继 pending 任务的 priority 数值等于原任务（如 `:281`、`:304`、`:319`、`:334`、`:359`、`:376`、`:391`、`:414`、`:429` 的 `_pending_job(...).priority == <原值>`），没有任何用例在重排后同时构造同账号兄弟文件夹的同类 pending 任务并断言 `_claim_one` 先取收件箱。该认领次序由 priority 数值经 `claim_jobs` 排序决定，已由发现用例的先认领断言（`:169`、`:214`）与既有优先级认领测试间接支撑，属组合覆盖可更广，非假绿、非 AC 无测试，故 minor 不阻断。
- 建议：后续在 PG 环境补一条组合用例：收件箱 delta 以 55 重排、同账号兄弟 delta（60）同为 pending 且 `run_after` 均已到期时，首次认领取收件箱。

## 结论

- 改测方向复核：无。diff 未修改、删除或反转任何既有测试，仅新增 `tests/mail_core/test_sync_inbox_first.py` 一个文件（19 个测试函数、参数化后 21 项，reviewer 以 `KKMAIL_TEST_MODE=unit` 独立收集核对：21 tests collected）。
- 危险模式扫描：逐条扫过，无命中。无恒真断言（全部断言为 priority 精确等值、状态等值、消息 `remote_id` 落库集合等可观察结果）、无弱化断言（唯一的 `<` 断言在 `:187`，是精确等值断言之外的附加严格小于断言）、无删/注释断言、无 `.only`、无静默错误标记、无阈值掩盖、无条件跳过断言。文件级 `pytestmark = pytest.mark.skipif(not MAIL_CORE_DATABASE_URL)`（`:46`）是仓库既有 PG 集成测试门控模式（同型见 `tests/mail_core/test_auth_epoch_concurrency.py`、`tests/mail_core/test_backend_isolation.py` 等），非规避真实交互；本机无 PG 时 21 项全 skip（reviewer 独立复现：21 skipped），与环境事实一致。mock 边界合规：只 mock 系统边界 `build_provider`（provider 构造）与 handler 的 `get_credential_store`，租约、认领、入队、同步函数与请求聚合均为真实生产代码；注入错误的 stub provider 只实现 provider 接口方法，未 mock 被测逻辑本身。
- 本轮新发现：1 条（minor 1；critical 0、important 0）
- 未进表的提示：AC-004 的测试只走 `complete` 终态路径，未构造 `failed` 终态；测试策略只要求「全部结算前非终态、全部结算后终态」，且请求结算逻辑不在本 task 改动面内，作可选扩展。handler priority 透传的端到端用例只经 lease_busy 出口、delta fencing 只经一条入口，其余出口/入口共用同一 `priority` 形参与同一重排 helper，函数级用例已逐出口覆盖、diff 可核全部调用点均传该形参，作可选扩展。committed 测试套件在真实 PG 环境的复跑仍欠（本机环境缺口，实施侧已在 `progress.md` 声明）；reviewer 的动态复验以本机重跑 `.scratch` 下 SQLite harness 代替——该 harness 驱动真实 `sync_account_folders`/`sync_folder_metadata`/`sync_folder_delta`/`handle_job` 生产代码而非平行实现，重跑结果 48/48 PASS，覆盖场景与 committed 测试一一对应。
- 总体判断：新增测试真实、可信地覆盖全部 5 条 AC 的核心行为（priority 严格数值、先后认领与完成、落库、逐出口重排保持、cursor-invalid 保持 40、请求聚合终态、无 inbox 回退），无 blocking 问题。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_discovery_delta_inbox_priority_strictly_smaller_and_claimed_first`（`tests/mail_core/test_sync_inbox_first.py:169`）断言 inbox delta ==55、兄弟 ==[60, 60] 且严格小于、先认领先 DONE、兄弟仍 PENDING、新邮件 `new-1` 已落 Message 表；reviewer 重跑 SQLite harness 对应检查 S1 全部 PASS。
- AC-002：TICK-VALID，re_verified。`test_discovery_metadata_inbox_priority_strictly_smaller_and_claimed_first`（`:214`）断言 inbox metadata ==45、兄弟 ==[50, 50] 并先认领先完成；`test_metadata_pagination_continuation_keeps_inbox_priority`（`:242`）断言多页续页后继仍 ==45（默认对照 ==50）；harness S2、S3 对应检查 PASS。
- AC-003：TICK-VALID，re_verified。delta 六类重排（租约冲突参数化 55/75/20 及默认 60、限流、容量、provider 错误、fencing、未耗尽分页，`:274`–`:381`）与 metadata 四类重排及 cursor-invalid 保持 40（`:384`–`:449`）逐条断言后继 priority 精确等于原值，handler 透传由 claimed-job 用例（`:473`、`:488`）端到端证明；harness S4–S8 对应检查 PASS。尾句的认领次序无直接组合测试，见 finding t074_test_f001（minor）。
- AC-004：TICK-VALID，re_verified。`test_request_settles_only_after_all_folder_deltas`（`:508`）断言收件箱先结算后请求 `state != "complete"` 且 `finished_at is None`，全部兄弟 delta 结算后才 `state == "complete"` 且 `finished_at` 非空；harness S9 对应检查（中间态 `running`、终态 `complete`）PASS。
- AC-005：TICK-VALID，re_verified。`test_no_inbox_account_keeps_existing_priorities`（`:563`）断言无 inbox 账号 delta 任务 priority 集合 =={60}、metadata =={50}、发现与单文件夹 delta 同步均返回 ok；harness S10 对应检查 PASS。

coverage = 5 / 5

verdict: PASS

## Round 2 (2026-11-05T04:40:11+08:00)

- task：`t074_inbox_first_account_sync`
- diff_anchor：`923bc4b1628e5a528191401d0e903d0935f0d264`
- round：2

reviewed_scope: c3352168a06b021e

## Findings

本轮无新 finding。

## 结论

- 前轮 finding 复核：t074_test_f001 已消除（以 diff 与代码为准，非采信处置表）。新增 `test_requeued_inbox_delta_claimed_before_sibling`（`tests/mail_core/test_sync_inbox_first.py:588`）正是 f001 建议的组合用例：外部持有账号租约后以 priority=55 直调真实 `sync_folder_delta`，断言返回 `lease_busy`（`:596`，后继由生产重排路径 `src/mail_core/sync/delta.py:379` 以原 priority 入队、`run_after` +5s）；同 session 内以真实 `enqueue_job` 入队同账号 Archive 文件夹 pending delta（priority=60、`run_after` 默认为当前时刻、即刻可认领，`src/mail_core/sync/jobs.py:153`）；以真实 `release_lease` 释放租约，并把后继 `run_after` 改到过去模拟 5 秒重试延迟已过（`:625`，是对测试数据时间的模拟，非阈值掩盖）；随后经真实 `claim_jobs` 的 `_claim_one`（limit=1，按 `priority asc, created_at asc` 排序，`src/mail_core/sync/jobs.py:272`）断言被认领的是收件箱任务且 `priority == 55` 精确等值（`:631`–`:633`）。断言为文件夹身份 + priority 精确值的双重可观察断言：即便后继 created_at 较早，priority 若被错误重排为 60 也会被 `:633` 抓出，非假绿。无 mock（该用例零 mock，租约/入队/释放/认领全走生产代码），无恒真/弱化/条件跳过断言，未以「修」之名换形式弱化。
- 改测方向复核：无。本轮测试改动仅新增上述一个测试函数；Round 1 既有测试的锚点行号全部未动（`:169`、`:214`、`:242`、`:274`、`:508`、`:563` 与 Round 1 报告引用一致），未修改、删除或反转任何既有断言。实现代码本轮未再改动。
- 本轮新发现：0 条
- 未进表的提示：committed 测试在本机仍全数 PG 门控 skip（reviewer 独立复现：`KKMAIL_TEST_MODE=unit` 收集 22 tests collected、运行 22 skipped，与新增 1 项后的计数一致）；动态复验沿用 `.scratch` SQLite harness——本轮 reviewer 独立重跑 50/50 PASS，其中新增 S11 两项检查（`S11 inbox requeued`、`S11 requeued inbox claimed before sibling`，`.scratch/t074_harness.py:446`、`:477`）与 committed 新用例场景一一对应且真跑通过。真实 PG 环境复跑仍欠（环境缺口，同 Round 1）。
- 总体判断：f001 已真修，AC-003 尾句现由直接组合测试 + harness S11 双路支撑；其余 AC 的测试证据与 Round 1 一致且未受本轮改动影响；无未解决 critical / important。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。证据同 Round 1（`tests/mail_core/test_sync_inbox_first.py:169` 断言 inbox delta ==55 严格小于兄弟 60、先认领先完成、新邮件落库）；本轮 reviewer 重跑 harness S1 对应检查 PASS，且该测试未被本轮改动触及。
- AC-002：TICK-VALID，re_verified。证据同 Round 1（`:214` metadata ==45 先认领、`:242` 分页续页仍 ==45）；harness S2、S3 本轮重跑 PASS。
- AC-003：TICK-VALID，re_verified。逐出口重排保持原 priority 的断言同 Round 1（`:274`–`:449`、handler 透传 `:473`、`:488`）；尾句新增直接组合测试 `test_requeued_inbox_delta_claimed_before_sibling`（`:588`）断言重排后收件箱（55）先于同账号兄弟 delta（60）被认领且 priority 精确 ==55；harness S4–S8 与新增 S11 本轮重跑全部 PASS，f001 缺口已闭合。
- AC-004：TICK-VALID，re_verified。`test_request_settles_only_after_all_folder_deltas`（`:508`）断言收件箱先结算后请求非终态、全部结算后才 `complete`；harness S9 本轮重跑 PASS。
- AC-005：TICK-VALID，re_verified。`test_no_inbox_account_keeps_existing_priorities`（`:563`）断言无 inbox 账号 delta =={60}、metadata =={50} 且同步正常完成；harness S10 本轮重跑 PASS。

coverage = 5 / 5

verdict: PASS
