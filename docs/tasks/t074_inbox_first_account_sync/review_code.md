# Task review t074（reviewer_focus: 代码）

- task：`t074_inbox_first_account_sync`
- spec：`docs/tasks/t074_inbox_first_account_sync/task.md`
- diff_anchor：`923bc4b1628e5a528191401d0e903d0935f0d264`
- target：`git diff 923bc4b1628e5a528191401d0e903d0935f0d264`（worktree 根为落点仓库，已校验）
- round：1
- reviewed_at：2026-11-04T20:35:09+08:00

reviewed_scope: d1b1fe5741d51526

## Findings

本轮无 finding（0 条；critical 0 / important 0 / minor 0）。

逐项核查记录（均未命中缺陷，供复核）：

- 发现入队优先级：`src/mail_core/sync/engine.py:398` delta 收件箱 55 / 其余 60；`src/mail_core/sync/engine.py:428` metadata 收件箱 45 / 其余 50；判据 `existing.role == "inbox"` 与仓库既有 role 约定一致（如 `src/mail_core/sync/idle_watcher.py:387`、`src/mail_core/worker/main.py:225` 均以 `Folder.role == "inbox"` 判收件箱）。认领排序 `src/mail_core/sync/jobs.py:271` 为 `priority asc, created_at asc`，同事务 `created_at` 并列时严格靠数值更小保证次序，符合 spec 判据说明。
- delta 重排全覆盖：`src/mail_core/sync/delta.py:384`（租约冲突）、`:501`（限流）、`:518`（连接预算）、`:546`（临时 provider 错误）、`:662`（分页未耗尽）均改用 `priority` 参数；fencing 重排统一经 `src/mail_core/sync/delta.py:302` 的 `_reschedule_delta_after_fencing_mismatch(..., priority=priority)`，其全部 4 个调用点（`:466`、`:573`、`:613`、`:638`）均已透传。`build_provider` 阶段的容量错误不入队新任务、由 `src/mail_core/worker/handlers.py:171` 的 `_evaluate_result` 对同一 job 行 `reschedule_job`，priority 随行保留，不构成缺口。
- metadata 重排全覆盖：`src/mail_core/sync/engine.py:523`（租约冲突）、`:669`（连接预算）、`:693`（限流）、`:776`（分页未耗尽续页）均改用 `priority` 参数；cursor-invalid 重建在 `src/mail_core/sync/engine.py:645` 与 `src/mail_core/sync/delta.py:458` 保持显式 40，未随透传降低。metadata 的 fencing_mismatch 路径原本即不重排（直接返回），不在 spec 的 metadata 重排清单内，未动属正确。
- handler 透传：`src/mail_core/worker/handlers.py:308`（metadata）与 `:373`（delta）均传 `priority=job.priority`；生产代码中 `sync_folder_delta` / `sync_folder_metadata` 的唯一调用方即这两处 handler（已 grep 全仓核实），周期轮询 75、文件夹级手动 20、IDLE 入队 60、发现根任务等其他入队点均未被改动，其重排自本 task 起随 handler 透传保持原值。
- 非重排的新任务未误改：metadata 完成后的新 delta（`src/mail_core/sync/engine.py:752`，60）、对账（`:726`/`:744`，80）、归档批（`:760`，40）、delta 完成连带的归档批（`src/mail_core/sync/delta.py:653`，60）、`sync_account_folders` 自身容量/限流重排（`src/mail_core/sync/engine.py:229`/`:264`，60）均保持原值，与 spec 非范围及风险说明一致；`enqueue_job` 的 dedupe 合并取 `min` 语义（`src/mail_core/sync/jobs.py:129`）为既有行为，本 diff 未触及。
- 契约/安全/性能面：新增参数均为内部函数末尾带默认值的 `priority: int`（delta 默认 60、metadata 默认 50、fencing helper 默认 60），向后兼容，无公开 API / schema / 配置键变更；无新增查询、无循环内 IO、无新依赖、无敏感数据处理，安全与性能视角无命中。
- 文档一致性：`docs/blueprint/architecture.md` 新增条目、`docs/specs/mail_sync_and_storage.md` 第十三节与 `docs/specs_index.md` 的 t074 登记，与实现数值（55/45、保持原 priority、cursor-invalid 40、无 inbox 回退、跨账号副作用）逐项一致。

## 结论

- 本轮新发现：0 条。
- 未进表的提示：文件过大——`src/mail_core/sync/engine.py` 814 行（实现源码 ≥800 档；基线已 801 行，本 task 净增 13 行）、`src/mail_core/sync/delta.py` 667 行、`src/mail_core/worker/handlers.py` 447 行（均达 ≥400 档）；按降级规则只在此列出，未见由此产生的可观测缺陷。复杂度——`sync_account_folders`（手算近似 CC 55）、`sync_folder_delta`（43）、`sync_folder_metadata`（32）、`_handle_job_impl`（42）均为存量高复杂度函数，本 task 仅在 `sync_account_folders` 增加两个三元分支、其余为参数透传，未见分支漏处理。范围外观察——发现入队的 metadata 分支同时覆盖 `full=True` 全量扫描与新发现的收件箱文件夹，其收件箱 metadata 同样为 45（方向与 AC-002 一致、无任何 AC 与之矛盾；同账号其他文件夹的 A320 metadata 仍为 50，与 spec 非范围注记一致）。环境说明——新增测试在本机因无 PostgreSQL 而 skip（与仓库既有集成测试同门控）；reviewer 已在本机用主仓 venv 独立复跑 `.scratch` 的 SQLite harness（驱动真实同步代码、与新增测试同场景），48/48 全部通过，PG 环境复跑仍欠（环境缺口，实施侧已在 progress.md 注明，非实现缺陷）。
- 总体判断：实现完整覆盖 AC-001～AC-005，全部重排路径保持原 priority 且无范围外行为变更，无未解决 critical / important，PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`src/mail_core/sync/engine.py:398` 收件箱 delta 55 严格小于同账号其余 60，认领序由 `src/mail_core/sync/jobs.py:271` 的 priority 升序保证；新增测试 `test_discovery_delta_inbox_priority_strictly_smaller_and_claimed_first` 断言 55/60、先认领先完成且完成时新邮件已落库，reviewer 复跑 SQLite harness 48/48 通过（含「first delta claim is inbox」检查）。
- AC-002：TICK-VALID，re_verified。`src/mail_core/sync/engine.py:428` 收件箱 metadata 45 严格小于其余 50；分页续页 `src/mail_core/sync/engine.py:776` 使用透传的 `priority` 参数保持 45，测试 `test_metadata_pagination_continuation_keeps_inbox_priority` 与 harness 对应场景均通过。
- AC-003：TICK-VALID，re_verified。delta 六类重排（`src/mail_core/sync/delta.py:384`/`:501`/`:518`/`:546`/`:662` 及 fencing helper `:323`）与 metadata 四类重排（`src/mail_core/sync/engine.py:523`/`:669`/`:693`/`:776`）全部改用原任务 priority，handler 在 `src/mail_core/worker/handlers.py:308`/`:373` 透传 `job.priority`，cursor-invalid 重建保持 40（`src/mail_core/sync/engine.py:645`）；harness 复跑验证 55/75/20 delta 与 45 metadata 后继 priority 等于原值、后继先于同类同账号任务被认领。
- AC-004：TICK-VALID，re_verified。本 diff 未触及同步请求结算逻辑，测试 `test_request_settles_only_after_all_folder_deltas` 断言收件箱先完成时请求保持非终态、全部文件夹结算后才 `complete`；harness S9 同场景复跑通过（state 先 running 后 complete）。
- AC-005：TICK-VALID，re_verified。`src/mail_core/sync/engine.py:398`/`:428` 的三元回退使无 `role="inbox"` 账号全部文件夹保持 delta 60 / metadata 50、不产生额外任务；测试 `test_no_inbox_account_keeps_existing_priorities` 与 harness S10（all 60 / all 50 且同步正常完成）复跑通过。

coverage = 5 / 5

verdict: PASS

## Round 2 (2026-11-05T04:39:59+08:00)

- task：`t074_inbox_first_account_sync`
- diff_anchor：`923bc4b1628e5a528191401d0e903d0935f0d264`
- round：2

reviewed_scope: c3352168a06b021e

## Findings

本轮无 finding（0 条；critical 0 / important 0 / minor 0）。

前轮 finding 复核：

- 本路（review_code）Round 1 零 finding，无待复核项。
- test 路 Round 1 的 t074_test_f001（minor：AC-003 重排后认领次序缺直接组合测试）处置为「已修」，以 diff 核实属实：新增 `tests/mail_core/test_sync_inbox_first.py:588` 的 `test_requeued_inbox_delta_claimed_before_sibling`——外部持有账号租约时以 priority=55 调用 `sync_folder_delta` 得 `lease_busy`（走 `src/mail_core/sync/delta.py:384` 租约冲突重排），再入队同账号 Archive 兄弟 delta（60），以真实 `fencing_token` 释放租约并把后继 `run_after` 置为已到期，经真实 `claim_jobs`（`src/mail_core/sync/jobs.py:271`，`priority asc, created_at asc`）以 `_claim_one` 认领，断言认领到的是 INBOX 且 `priority == 55`。该用例未 mock 被测逻辑（租约、重排、入队、认领均为真实生产代码），无恒真/弱化断言。从代码角度确认：此修复不需要也不应改动实现——`src/` 三文件行数与 Round 1 完全一致（`src/mail_core/sync/engine.py` 814 行、`src/mail_core/sync/delta.py` 667 行、`src/mail_core/worker/handlers.py` 447 行），Round 1 已核实的全部锚点（发现入队 55/45、delta 六类重排与 fencing 透传、metadata 四类重排、cursor-invalid 40、handler 透传 `job.priority`）在本轮最终 diff 中逐项未变。
- 修复引入新问题扫描：本轮相对 Round 1 的交付变化仅为上述新增测试与 `progress.md` 处置记录；新增测试不触及生产代码路径，无新缺陷命中。安全/契约/性能视角复扫最终 diff：结论与 Round 1 相同，无公开 API / schema / 配置键变更、无新增查询、无敏感数据处理。

## 结论

- 前轮 finding 复核：见上；test 路 minor 已真修（diff 核实），本路无前轮 finding。
- 本轮新发现：0 条。
- 未进表的提示：文件过大——`tests/mail_core/test_sync_inbox_first.py` 现 633 行，跨测试源码 ≥600 档（minor 建议拆分档）；按降级规则只在此列出，本 task 新建该文件且本轮净增，未见由此产生的可观测缺陷。实现文件沿用 Round 1 提示：`src/mail_core/sync/engine.py` 814 行（≥800 档）、`src/mail_core/sync/delta.py` 667 行、`src/mail_core/worker/handlers.py` 447 行（均 ≥400 档），行数与 Round 1 一致、本轮未再增长。复杂度沿用 Round 1 结论（存量高复杂度函数，本轮零改动）。环境说明——新增测试在本机仍因无 PostgreSQL 而 skip（仓库既有门控）；reviewer 本轮独立复跑 `.scratch` SQLite harness（驱动真实同步代码），50/50 全部通过，含新增 S11「requeued inbox claimed before sibling」（folder match=True、prio=55）；后端全量 unit 与 base 失败集一致为实施侧与派审侧共同环境事实，PG 环境复跑仍欠（环境缺口，非实现缺陷）。
- 总体判断：最终态实现与 Round 1 已 PASS 的实现完全一致，AC-003 的测试侧 minor 已以直接组合测试补齐且未引入新问题，无未解决 critical / important，PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。实现未变：`src/mail_core/sync/engine.py:398` 收件箱 delta 55 严格小于其余 60，认领序由 `src/mail_core/sync/jobs.py:271` 保证；reviewer 本轮复跑 harness 50/50 通过（含发现优先级与「first delta claim is inbox」、完成时新邮件落库场景）。
- AC-002：TICK-VALID，re_verified。实现未变：`src/mail_core/sync/engine.py:428` 收件箱 metadata 45 严格小于其余 50，分页续页 `src/mail_core/sync/engine.py:776` 透传 `priority` 保持 45；harness 对应场景本轮复跑通过。
- AC-003：TICK-VALID，re_verified。实现未变：delta 六类重排（`src/mail_core/sync/delta.py:384`/`:501`/`:518`/`:546`/`:662` 及 fencing helper）与 metadata 四类重排（`src/mail_core/sync/engine.py:523`/`:669`/`:693`/`:776`）均保持原 priority，handler 在 `src/mail_core/worker/handlers.py:308`/`:373` 透传 `job.priority`，cursor-invalid 保持 40；尾句认领次序本轮新增直接组合测试 `test_requeued_inbox_delta_claimed_before_sibling`（`tests/mail_core/test_sync_inbox_first.py:588`），harness 新增 S11 同场景本轮复跑通过（重排后继 55 先于兄弟 60 被认领）。
- AC-004：TICK-VALID，re_verified。实现未触及请求结算逻辑（本轮零改动）；测试 `test_request_settles_only_after_all_folder_deltas` 与 harness S9（先 running 后 complete）本轮复跑通过。
- AC-005：TICK-VALID，re_verified。实现未变：无 `role="inbox"` 时三元回退保持 delta 60 / metadata 50、不产生额外任务；harness S10（all 60 / all 50 且同步正常完成）本轮复跑通过。

coverage = 5 / 5

verdict: PASS
