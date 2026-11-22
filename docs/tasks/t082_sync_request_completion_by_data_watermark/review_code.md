# Task review t082（reviewer_focus: 代码）

- task：`t082_sync_request_completion_by_data_watermark`
- spec：`docs/tasks/t082_sync_request_completion_by_data_watermark/task.md`
- diff_anchor：`1998e95ff67999ac896b9e118b47902ebfefdfc8`
- target：`git diff 1998e95ff67999ac896b9e118b47902ebfefdfc8`
- round：1
- reviewed_at：2026-11-22T15:46:46+08:00
    reviewed_scope: d56bcbb2bb33b2a1

## Findings

### t082_code_f001 - 停滞巡检按创建时间误杀仍在推进的请求

- 严重度：important
- 锚点：AC-004（"仅当数据确实无法推进才判 failed"）；AC-005 的收敛条件被实现为纯墙钟年龄
- 位置：`src/mail_core/sync/execution.py:471-480`、`:499-514`；调用点 `src/mail_core/worker/main.py:150-153`
- 问题：`converge_stalled_targets` 仅以 `SyncRequestTarget.created_at < now - 30min` 且 state 为 open 选取目标，随后无条件把其 open links 与目标置为 `failed` / `sync_incomplete` / "同步未能完成，请重试"，**不检查 link 指向的 WorkerJob 是否 PENDING/CLAIMED 且仍有心跳在推进**。对照被替换的旧 `converge_orphaned_bindings`：它逐个查 job 状态并在决策时重检 live generation，专门避免误杀健康请求。可复现场景：2403 封账号发起同步，job 已被认领并持续写库，单次遍历耗时 >30 分钟；worker 每轮 reclaim（默认 300s 间隔）把该 target 判 failed，界面出现失败横条，而数据仍在入库——正是本 task 要根除的 p083 假失败类别。
- 建议：判失败前对 stale target 的 open link 复核其 `job_id` 对应 job 的 `status` / `locked_at`（心跳）；仅当无任何可推进 job 时收敛为可操作文案，把"无任务推进"作为判据而非 `created_at` 阈值。

## 结论

- 本轮新发现：1 条
- 未进表的提示：
    - 文件过大：`src/mail_core/sync/execution.py` 518 行（anchor 725 行）、`src/mail_core/sync/jobs.py` 616 行（anchor 659 行），本 task 均净减，不命中净增条件。
    - 圈复杂度：`settle_job_links`（`execution.py:272-342`）约 9，`converge_stalled_targets` 约 6，未达 15，不进表。
    - 范围外观察：`blackbox_verify` 首轮 1 例 t032 侧栏 toggle E2E（与本 task 无关）出现 flake，隔离重跑该 spec 11/11 通过；前端/桌面源码本 task 未改动。
    - `docs/specs/inbox_ui_and_search.md` 未随范围项更新：其现有契约无同步错误文案条目，且前端无内部术语硬编码、后端已不再产出该字符串，暂不构成可观测不一致。
    - 新增交付 `20261122_0003_real_job_links.py` 与 `test_sync_request_completion_by_data.py` 为未跟踪文件（未 `git add -N`），已通过 `git status` 可见并直接读取审查；指纹覆盖其变更。
- 总体判断：1 条 important 未解决（AC-004 已打勾但实现存在可观测假失败），阻断 PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`execution.py` 运行期已无 `execution_lost` 产生点；`tests/mail_core/test_sync_request_completion_by_data.py:116-133` 断言 CLAIMED 到达请求在两次 pass 后 complete 且无 `execution_lost`；前端无相关硬编码文案（真实 Gmail 大账号点击在「有意不测」内，按本地替代验证复验）。
- AC-002：TICK-VALID，re_verified。retry/reclaim/coalesce/cleanup 分别由 `settle_job_links(outcome=retriable)`、`reset_links_for_job`（`execution.py:379-409`）、`migrate_waiting_links + has_waiting_links`（`:104-133`，`jobs.py:316-379`）覆盖；`prune_completed_jobs`（`jobs.py:593-616`）仅删 DONE/FAILED 且 link 已终态；全仓 grep 无运行期 `execution_lost` 写出。
- AC-003：TICK-VALID，re_verified。`bind_target` 以 `(target_id, job_id)` 为键（`execution.py:70-100`），配合迁移后的唯一约束；重复触发时终态 link 被重置为 open（`:95-99`）；引擎幂等使入库数据不重复（非本 task 范围）。
- AC-004：TICK-VOID，re_verified。`converge_stalled_targets` 仅按 30 分钟年龄失败请求，未验证"数据确实无法推进"；正在推进的大账号同步会被误杀，见 f001（`execution.py:471-480,499-514`）。
- AC-005：TICK-VALID，re_verified。有界收敛与可操作文案落地（`execution.py:41` 的 `SYNC_INCOMPLETE_MESSAGE`、`:460-518` 的巡检）；不再留永久 queued/running。收敛条件过宽的缺陷归入 AC-004 / f001。
- AC-006：TICK-VALID，re_verified。后台请求独立创建与汇报（`sync_requests.py:475-490`、`_build_report:545-553` 的 `bg_state`/`bg_errors`），主报告 inbox_ready 仅取主请求的 inbox target（`:536-540`）；`refresh_requests` 按 request 隔离聚合。
- AC-007：TICK-VALID，re_verified。运行期无 `execution_lost` error_code；失败分支强制非空 safe_error（`execution.py:319-323`、`jobs.py:513-519`）；迁移升级清理 `job_id IS NULL` 关联并把目标置 failed + 中文文案（`20261122_0003_real_job_links.py:25-80`）；报告 errors 取自 target 的 code/safe_error（`sync_requests.py:529-533`）。
- AC-008：TICK-VALID，re_verified。重跑 `test_cmd`：模板契约 388 passed / 1 skipped、敏感扫描 0 违规、前端 593 单测 + tsc + build 通过、桌面单测通过；`blackbox_verify` 首轮 22 passed / 1 flaky（t032 侧栏用例），隔离重跑该 spec 11/11 通过，非本 task 回归。

coverage = 8/8

verdict: FAIL

## Round 2 (2026-11-22T16:05:00+08:00)

reviewed_scope: 01e4e79bfeee0c35

### 前轮 finding 复核

- t082_code_f001（important，停顿巡检误杀仍在推进的长账号同步）：**已消除**。以当前 diff 为准，`src/mail_core/sync/execution.py:492-513` 在收敛前先取全库 PENDING/CLAIMED 的 `WorkerJob.id` 集合（`:496-500`），再按候选 target 的 open link 的 `job_id` 过滤出 live target（`:501-510`），仅对 `stalled`（无任何 live job）执行失败收敛（`:511-541`）。f001 的可复现场景（2403 封账号、job 仍 CLAIMED 并持续写库、target 超过 30min）中该 target 的 link 指向 CLAIMED job，落入 live_target_ids 后被排除，不再判 failed。新增测试 `tests/mail_core/test_sync_execution_tracking.py:513-531`（`test_stalled_reaper_keeps_target_with_live_job`）以 31min 陈旧 target + live job 断言 `changed == 0` 且 report 非 failed，直接覆盖该分支；对侧阳性用例 `test_stalled_target_converges_with_readable_message`（`:483-509`）把 job 置 DONE 后仍收敛为 `sync_incomplete`，证明有界终止未被破坏。结论：finding 真修，非撤回。

### Findings

Round 2 零 finding。

### 结论

- 前轮 finding 复核：t082_code_f001 已消除（以 diff 与新增测试为证）。
- 本轮新发现：0 条。
- 未进表的提示：
    - 性能/规模：`converge_stalled_targets:496-500` 每轮把全库 PENDING/CLAIMED job 的 id 全量读入内存 set，未按候选 target 的 link job_id 收窄；active job 受并发上限约束，当前规模无可观测缺陷，按规模/性能提示不进表，建议后续按候选 link job_id 过滤查询。
    - 新增交付 `src/mail_core/db/alembic/versions/20261122_0003_real_job_links.py` 与 `tests/mail_core/test_sync_request_completion_by_data.py` 仍为未跟踪文件（未 `git add -N`），经 `git status` 可见并已直接读取审查（迁移清理与 AC-007 一致）；指纹覆盖其变更，非不可见交付。
    - E2E `blackbox_verify` 本轮 23 passed，Round 1 出现 flake 的 t032 侧栏用例本轮通过，无回归；cookie t079 环境既有失败不记为本 task finding。
    - 有意不测的真实 Gmail 2403 封人工点击不评；前端/桌面源码本 task 未改。
- 总体判断：f001 真修、无新增 blocking 问题，8 条 AC 打勾均成立。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。运行期 `execution_lost` 产生点已移除，修复后 live-job 的陈旧 target 不再被误判 failed；测试断言 report 终态 complete 且无内部术语，前端无相关硬编码文案（真实 Gmail 大账号点击属有意不测，以本地断言替代）。
- AC-002：TICK-VALID，re_verified。retry 经 `fail_job` PENDING+backoff、reclaim 经 `reclaim_stale_claims` 复用同 job 行、coalesce 经 `complete_job` 建后继并迁移 link、cleanup 仅删终态 job（`jobs.py`）；全仓 grep 无运行期 execution_lost 写出，修复未改变该解耦。
- AC-003：TICK-VALID，re_verified。`bind_target` 以 `(target_id, job_id)` 为键（`execution.py:70-100`），迁移加唯一约束 `uq_sync_target_jobs_target_job`（`20261122_0003:59-61`）；重复触发复用/重置 link，请求间无共享执行观察。
- AC-004：TICK-VALID，re_verified。修复使 `converge_stalled_targets` 仅失败无任何 live job 的 target（`execution.py:492-541`），f001 假失败消除；瞬时错误经 `fail_job` retriable 保持 open 并由同 job 重试推进至 complete（`jobs.py:478-502`、`test_sync_execution_tracking.py:248-295`），Round 1 的 TICK-VOID 已翻正。
- AC-005：TICK-VALID，re_verified。有界终止仍成立：`test_stalled_target_converges_with_readable_message`（`:483-509`）证明死 job 的陈旧 target 收敛为 `sync_incomplete` 与可操作文案 `SYNC_INCOMPLETE_MESSAGE`（`execution.py:41`）；live job 由 reclaim/fail_job cap 各自收敛，不留永久 queued/running。
- AC-006：TICK-VALID，re_verified。主/后台为独立 `SyncRequest`（`sync_requests.py:509-574` 的 `bg_state`/`bg_errors`），`refresh_requests`（`execution.py:196-240`）按 request 独立聚合，后台 target 失败不污染主请求终态；修复未触及该路径。
- AC-007：TICK-VALID，re_verified。运行期无 `execution_lost` 码，失败分支强制非空 safe_error；迁移 `20261122_0003:25-80` 清理 `job_id IS NULL` 关联并把目标置 failed + 中文文案、删 generation 列；报告 errors 取自 target code/safe_error。
- AC-008：TICK-VALID，re_verified。本 reviewer 独立重跑：模板契约 388 passed/1 skipped、敏感扫描 34 文件 0 违规、前端 npm test + tsc -b + build 通过、桌面 npm test 通过、`blackbox_verify` E2E 23 passed；无弱化断言或临时补丁残留（DB 集成套件受 `KKMAIL_TEST_MODE`/`MAIL_CORE_DATABASE_URL` 守卫未独立重跑，属 test_cmd/blackbox 之外套件）。

coverage = 8/8

verdict: PASS

## Round 3 (2026-11-22T16:10:00+08:00)

reviewed_scope: dad3685032ec1332

### 前轮 finding 复核

- t082_code_f001（important，停顿巡检误杀仍在推进的长账号同步）：维持已消除。格式化后以当前 worktree 为准，`src/mail_core/sync/execution.py:496-513` 的 live-job 过滤仍在，`tests/mail_core/test_sync_execution_tracking.py:513-531` 的 `test_stalled_reaper_keeps_target_with_live_job` 仍在；本轮未发现实现层改动，结论沿用 Round 2。

### Findings

Round 3 零新增 finding。

### 结论

- 格式复验范围：Markdown 格式化仅调整排版（docs/blueprint、docs/specs、task.md 等文档），未改动 `src/` 与 `tests/`；相对 `1998e95ff67999ac896b9e118b47902ebfefdfc8` 的完整交付内容指纹由 Round 2 的 `01e4e79bfeee0c35` 变为 `dad3685032ec1332`，系排版变化所致，非实现变更。已按新指纹重新核对 f001 修复与 8 条 AC。
- 前轮 finding 复核：f001 维持已消除；无撤回、无新增 blocker。
- 本轮新发现：0 条。
- 未进表的提示：无（沿用 Round 2 结论段所列规模/范围外提示，格式化未引入新项）。
- 总体判断：格式化后复审范围与结论不变，仍为 PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。运行期无 execution_lost 产生点；live-job 陈旧 target 不再误判 failed，测试断言 report 终态 complete，前端无内部术语硬编码（真实大账号点击属有意不测，以本地断言替代）。
- AC-002：TICK-VALID，re_verified。retry/reclaim/coalesce/cleanup 均走 `jobs.py` 与 `execution.py` 解耦路径，全仓 grep 运行期无 execution_lost 写出；格式化未触及实现。
- AC-003：TICK-VALID，re_verified。`bind_target` 以 `(target_id, job_id)` 为键（`execution.py:70-100`），迁移唯一约束 `uq_sync_target_jobs_target_job`；重复触发复用/重置 link。
- AC-004：TICK-VALID，re_verified。`converge_stalled_targets`（`execution.py:496-513`）仅失败无 live job 的 target，f001 假失败维持消除；瞬时错误经 fail_job 推进至 complete。
- AC-005：TICK-VALID，re_verified。`test_stalled_target_converges_with_readable_message`（`test_sync_execution_tracking.py:483-509`）证明有界收敛为 `sync_incomplete` 与可操作文案，不留永久 queued/running。
- AC-006：TICK-VALID，re_verified。主/后台独立请求，`bg_state`/`bg_errors` 隔离聚合，后台失败不污染主请求终态；格式化未触及该路径。
- AC-007：TICK-VALID，re_verified。运行期无 execution_lost 码；迁移 `20261122_0003:25-80` 清理旧关联并置 failed + 中文文案；报告 errors 取自 target code/safe_error。
- AC-008：TICK-VALID，re_verified。本 reviewer Round 2 已独立重跑 `test_cmd` 与 `blackbox_verify` 全绿（388 passed/1 skipped、E2E 23 passed）；本轮格式化未改测试、门禁配置或断言，代码/测试实现层证据不变，维持 re_verified。

coverage = 8/8

verdict: PASS
