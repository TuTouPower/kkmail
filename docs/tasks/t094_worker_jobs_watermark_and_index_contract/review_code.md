# Task review t094（reviewer_focus: 代码）

- task：`t094_worker_jobs_watermark_and_index_contract`
- spec：`docs/specs/mail_sync_and_storage.md`
- diff_anchor：`982235be`
- target：`git diff 982235be`
- round：1
- reviewed_at：2026-11-28T05:15:15+08:00

reviewed_scope: 19e005ad3dc9ecdb

## Findings

### t094_code_f001 - 把 scan_generation 当作重建中，周期 delta 排期被永久关闭

- 严重度：critical
- 锚点：AC-002（无基线/重建中不排期、基线就绪首次排期、水位已置按间隔排期三状态契约）
- 位置：`src/mail_core/worker/main.py:259`
- 问题：`begin_scan_generation` 在受跟踪全量扫描入口给 `SyncCheckpoint.scan_generation` 写入代际 UUID（`src/mail_core/sync/checkpoints.py:191-199`），`commit_checkpoint` 只校验、不清空（`:143-146`）；唯一清空点是 `invalidate_checkpoint_for_rebuild`（`:227`），且该处同时置 `full_scan_complete=False`。因此「重建中」已由 `not cp.full_scan_complete` 表达，`scan_generation is not None` 实际表示「做过受跟踪全量扫描」。调度器把后者也 `continue`，导致所有经全量扫描建立基线的文件夹（含 inbox）不再进入 `overdue`；首次 delta 仍由元数据链显式入队（`src/mail_core/sync/engine.py:738-745`），但此后的周期增量同步永久停摆。新增用例均以 `scan_generation=None` 建基线（`tests/mail_core/test_t094_watermark_authority.py:122-127`、`tests/mail_core/test_worker_scheduler.py:52-60`），无法暴露该路径。
- 建议：删除 `cp.scan_generation is not None` 条件，仅以 `not cp.full_scan_complete`（必要时叠加活跃 metadata/reconcile 任务）判定重建中；补一条 `full_scan_complete=True, scan_generation=<uuid>, last_delta_settled_at` 已过期时 `schedule_periodic_inbox_sync >= 1` 的复验用例。

### t094_code_f002 - 生产调用未传 fencing_token，且现有令牌校验在结算时不可用

- 严重度：important
- 锚点：AC-002（旧执行令牌落后不得覆盖新执行写入的水位；验收覆盖失锁）
- 位置：`src/mail_core/sync/jobs.py:73-78`；`src/mail_core/sync/checkpoints.py:260-288`
- 问题：`advance_delta_settlement_watermark` 声明 `fencing_token` 并在 `:287-288` 调 `assert_fencing`，但唯一生产调用方 `_advance_delta_watermark_on_settle` 没有传该参数（`:73-78`），`complete_job`/`fail_job` 也未把执行令牌带到结算处。单调比较只拒绝时间更旧的 `settled_at`（`:292-293`）；陈旧执行失锁后晚提交，`settled_at=now` 反而更大，会通过单调检查并把水位推到新执行之后，抑制本应到期的重拉。即便补传令牌也不可直接修复：`release_lease` 已递增租约令牌（`src/mail_core/sync/leases.py:173-175`），`assert_fencing` 会把正常结算误判为失锁。审阅意见要求的令牌约束路径实际不可达。
- 建议：在 handler 最终结算事务（`src/mail_core/sync/delta.py:667-707`、`release_lease` 之前）取令牌并写水位，或让结算携带捕获的令牌，与 `SyncCheckpoint.fencing_token`（`src/mail_core/sync/checkpoints.py:158`，记录最后写入游标的执行代次）比较并拒绝更小者；不要直接用已释放租约的当前令牌调 `assert_fencing`。单调时间比较保留为第二道防护。

### t094_code_f003 - 终态 reclaim 遗漏水位推进，崩溃循环task无法按契约结算

- 严重度：important
- 锚点：AC-002（重试耗尽推进水位）
- 位置：`src/mail_core/sync/jobs.py:757-777`
- 问题：`reclaim_stale_claims` 在 `failure_attempts >= cap` 时把 job 置 `FAILED` 并调 `settle_job_links(outcome="failed")`（`:768-776`），这是与 `fail_job` 终态并列的另一条重试耗尽路径，但未调用 `_advance_delta_watermark_on_settle`。delta 任务属于 `LEASE_JOB_TYPES`（`:83-89`），worker 崩溃循环触发该路径后 checkpoint 水位保持旧值：调度器会把该文件夹持续判为到期并反复入队（与「重试耗尽应结算」不符），在 f001 同时存在时则表现为既不结算也不周期同步。
- 建议：在 `reclaim_stale_claims` 的 `terminal` 分支按 `fail_job` 终态相同方式调用 `_advance_delta_watermark_on_settle(session, job, settled=True, result=None, now=now)`，与链接结算同事务提交。

### t094_code_f004 - 批量同步后三张消息表统计刷新与误差/频率契约未落地

- 严重度：important
- 锚点：AC-006（三表统计以真实行数为参照、明确大批量阈值/目标表/ANALYZE 频率上限与相对误差、批量后刷新而短 delta 不重复刷新）
- 位置：`src/mail_core/sync/retention.py:32-37`；`src/mail_core/db/alembic/versions/20261128_0008_watermark_authority_and_queue_index.py:18,41-43`
- 问题：`refresh_table_stats_if_bulk` 的表白名单只有 `("worker_jobs", "outbox")`（`:32`），全仓 `ANALYZE` 调用点仅 `src/mail_core/sync/jobs.py:816-817`、`src/mail_core/realtime/outbox.py:169-170` 两处 prune 路径；`message_search`、`messages`、`message_bodies` 只在迁移 `20261128_0008` 升级时刷新一次（`:41-43`），批量同步后无任何刷新触发点。代码与文档中也没有给出三表 `reltuples` 相对真实行数的误差范围，或 `ANALYZE` 频率上限；「大批量」仅由删除行数阈值 `STATS_REFRESH_MIN_DELETED=1000` 表达，不覆盖批量导入/同步写入。
- 建议：把三张消息表纳入统计刷新契约（显式阈值、目标表、频率上限与误差范围），在批量同步/大批量写入路径调用同一刷新判定；日常短 delta 仍不触发。

## 结论

- 前轮 finding 复核：无（Round 1）。
- 本轮新发现：4 条（critical 1 条：f001；important 3 条：f002/f003/f004）。
- 未进表的提示：
    1. 文件过大：`src/mail_core/sync/jobs.py` 818 行（实现源码，达到 important 阈值 ≥800，本 task 净增 80 行，diff 未给出不可拆硬约束）；`src/mail_core/worker/main.py` 714 行（≥400 minor 阈值，本 task 净减，不单独提示）。按规程仅在此列出，不进 finding 表。
    2. 圈复杂度：`schedule_periodic_inbox_sync`（`src/mail_core/worker/main.py:194-282`）、`_advance_delta_watermark_on_settle`（`src/mail_core/sync/jobs.py:34-78`）均低于 minor 阈值 15，未达提示线。
    3. 范围外观察：`docs/specs/mail_sync_and_storage.md:56` 新增 t095 章节，与 spec 中「t094/t095 共同更新该文档」的写域协调一致，未判偏航；`docs/tasks/t094_worker_jobs_watermark_and_index_contract/task.md:50-57` 的 8 条 AC 全部未打勾，按规程逐条记 TICK-VOID。
    4. 已扫过但未命中：迁移升降级（`20261128_0008` 的 down_revision、列回填、重复 GIN 索引 DROP/重建、baseline 常量同步）无可逆性缺陷；`prune_completed_jobs` 的 `NOT IN` 子查询以 `SyncRequestTarget.state IN ('queued','running')` 排除未结算目标，与 `settle_job_links` 把失败码/文本持久化到 link 行、`_aggregate_target` 只读 link 行的事实一致，无重聚合误判；到期判定已无 `worker_jobs` 终态查询；新增部分索引未被任何水位判定引用；未发现 SQL 注入、敏感信息落日志、未用 import/死代码；`src/mail_core/sync/jobs.py:818` 行与 `src/mail_core/realtime/outbox.py:171` 行的 `ANALYZE` 使用固定表名常量拼接，无注入面。测试文件本身的测试质量不在本轴评审范围。
- 总体判断：f001 直接关闭周期增量同步，f002/f003 使结算令牌与重试耗尽语义失守，f004 使统计契约半落地；均为未解决 blocking finding，判定 FAIL。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VOID，re_verified。契约区 `task.md:50` 未打勾；源码确认 `src/mail_core/worker/main.py:249-261` 只读 checkpoint 水位，终态反推查询已删除。
- AC-002：TICK-VOID，re_verified。契约区 `task.md:51` 未打勾；`worker/main.py:259` 误判重建中（f001）、`jobs.py:73-78` 未传令牌（f002）、`jobs.py:757-777` 漏终态 reclaim（f003），打勾不成立。
- AC-003：TICK-VOID，re_verified。契约区 `task.md:52` 未打勾；`retention.py:12-18` 移除 7 天常量并固定 24h 窗口，`jobs.py:798-807` 排除未结算目标的关联，实现层未发现阻断缺陷。
- AC-004：TICK-VOID，re_verified。契约区 `task.md:53` 未打勾；迁移 `20261128_0008` 的 `DROP INDEX IF EXISTS ix_message_search_from_trgm` 与 downgrade 重建对称，ORM 仅保留 `ix_message_search_from_text_trgm`，baseline 常量已同步。
- AC-005：TICK-VOID，re_verified。契约区 `task.md:54` 未打勾；`models.py:471-476` 与迁移新增同名部分索引一致，调度与水位判定无该索引引用。
- AC-006：TICK-VOID，re_verified。契约区 `task.md:55` 未打勾；三张消息表批量后刷新与误差/频率契约缺失，见 f004。
- AC-007：TICK-VOID，re_verified。契约区 `task.md:56` 未打勾；`COMPLETED_JOB_PRUNE_BATCH=5000` 单批上限与 `retention.py:21-27` 稳态口径在代码层存在，未独立复跑积压种子。
- AC-008：TICK-VOID，trust_prior。契约区 `task.md:57` 未打勾；文档已同步（spec/domain/testing/decision），但全量门禁仍在后台运行，依赖用户提供的事实的通过数，未独立复验。

coverage = 7 / 8

verdict: FAIL

## Round 2 (2026-11-28T05:23:26+08:00)

reviewed_scope: f1e849aab29de12d

- 前轮 finding 复核（以 diff 为准，不采信自述）：
    - `t094_code_f001`（critical）— 已消除。`src/mail_core/worker/main.py:259-260` 现仅 `if cp is None or not cp.full_scan_complete: continue`，`scan_generation` 已不在调度判定中。重建中由 `full_scan_complete=False`（`src/mail_core/sync/checkpoints.py:197,226`）表达，元数据末页提交置 True（`:156-157`），三状态契约成立。
    - `t094_code_f002`（important）— 已消除。`src/mail_core/sync/checkpoints.py:287-288` 改为 `fencing_token < int(row.fencing_token or 0)` 拒绝；`src/mail_core/sync/delta.py:740` 成功结果携带 `fencing`，`src/mail_core/sync/jobs.py:71-80` 提取并传入。方向核对：合法结算时执行 token 等于 `checkpoint.fencing_token`（`commit_checkpoint` 每页写 `:158`），`release_lease` 递增的是租约 token（`src/mail_core/sync/leases.py:173-175`），改用令牌比较后不再误拒合法结算；迟到的旧执行 token 更小则被拒。新增结果键经 `_result_log_summary` 白名单（`src/mail_core/worker/handlers.py:65-78`）过滤，未污染结算与日志。
    - `t094_code_f003`（important）— 已消除。`src/mail_core/sync/jobs.py:784-789` 在 terminal reclaim 分支调用 `_advance_delta_watermark_on_settle(..., now=now)`，与链接结算同事务提交。
    - `t094_code_f004`（important）— 修不彻底。阈值、目标表、频率上限与成功终态 ANALYZE 已落地（`src/mail_core/sync/retention.py:35-38`、`src/mail_core/sync/delta.py:56-80,729-731`），但只在成功路径触发，分页中断路径仍漏刷新，见 f005；上限与误差常量另有缺口，见 f006/f007。
- 本轮新发现：4 条（important 2 条：f005/f008；minor 2 条：f006/f007）。

### t094_code_f005 - 大批量统计刷新只在 delta 成功终态触发，分页中断丢失刷新

- 严重度：important
- 锚点：AC-006（批量后刷新而日常短 delta 不重复刷新）
- 位置：`src/mail_core/sync/delta.py:729-731`；对照早退路径 `:446-584,704-709`
- 问题：`totals` 是单次执行内的局部累加，而所有早退分支都在 `_refresh_message_stats_if_bulk` 之前 `return`。若第 1 页已提交 ≥1000 行变更、第 2 页遇 `rate_limited`/`capacity_unavailable`/`provider_error`/`fencing_mismatch`/`cursor_invalid`，本次不会 ANALYZE；followup delta 的 `totals` 从 0 重算，若后续页变更不足阈值，三张消息表长期保留批量变更后的陈旧 `reltuples`。AC-006 的「批量后刷新」在这些路径没有实现。
- 建议：在会提交数据页的早退路径统一调用刷新判定，或把跨续页的累计变更数持久化到 checkpoint/payload，让任意终态都能判断本执行链是否大批量。

### t094_code_f006 - 统计刷新频率上限初值错误且非线程安全

- 严重度：minor
- 锚点：AC-006（ANALYZE 频率上限明确）
- 位置：`src/mail_core/sync/delta.py:56,68-80`
- 问题：`_last_message_stats_refresh = 0.0` 与 `time.monotonic()` 比较，在 monotonic 纪元小于 300s 时首次大批量同步被误跳过；该进程级全局无锁，worker 多 slot 并发（`src/mail_core/worker/main.py` 的 `_tick`）下两个 bulk delta 可同时通过检查并各自执行 3 次 ANALYZE；全局值在 `session.commit()` 之前写入，事务回滚后仍会抑制后续 300s 刷新。
- 建议：初值改为负无穷；用 `threading.Lock` 保护检查与更新，并在提交成功后更新上限时间；或把上限落到 DB 单例状态。

### t094_code_f007 - MESSAGE_STATS_RELTUPLES_REL_ERROR 定义后全仓零引用

- 严重度：minor
- 锚点：AC-006（三表以自身真实行数为参照、落在约定相对误差范围内）
- 位置：`src/mail_core/sync/retention.py:37`
- 问题：该常量全仓仅定义处一处，没有任何以 `pg_class.reltuples` 对照三表真实行数并判定 25% 误差的实现；AC-006 的相对误差要求只落到常量声明，属死代码。
- 建议：在实现或门禁中实际消费该常量做 reltuples 对照；否则删除该常量，避免宣称落地实际未消费的契约。

### t094_code_f008 - AC-002 的「取消推进水位」无实现，打勾不成立

- 严重度：important

- 锚点：AC-002（成功、失败、跳过、重试耗尽、取消均推进水位）

- 位置：`src/mail_core/sync/checkpoints.py:241`；`src/mail_core/sync/jobs.py:698-701,784-789`

- 问题：`_DELTA_SETTLED_STATUSES` 仅含 `ok/skipped/sync_disabled`；`fail_job` 与 `reclaim_stale_claims` 的终态只写 `JobStatus.FAILED`；全仓无设置 `JobStatus.CANCELLED` 或返回 `status="cancelled"` 的 delta 路径（`JobStatus.CANCELLED` 仅存在于枚举定义 `src/mail_core/mail/domain/enums.py:105`）。AC-002 已打勾，但其中「取消」分类没有结算分支，取消不会发生水位推进。

- 建议：补取消终态结算（纳入 settled 分类并在终态路径统一调用 `_advance_delta_watermark_on_settle`）；若产品范围确无取消入口，则撤回 AC-002 打勾并先补齐契约要求的结算语义。

- 未进表的提示：

    1. 文件过大：`src/mail_core/sync/jobs.py` 833 行（实现源码，≥800 important 阈值，本 task 净增约 90 行）、`src/mail_core/sync/delta.py` 742 行（≥400 minor 阈值，本 task +36 行）；按规程仅在此列出，不进 finding 表。
    2. 圈复杂度未达提示线。`ANALYZE` 在 PostgreSQL 允许置于事务块内，Round 1 对事务安全的疑虑已解除；`fencing_token` 作为 result 新增键只被白名单日志消费，未发现下游副作用。
    3. 测试文件本轮新增用例的覆盖质量由 test reviewer 负责，本轴未评审；全量门禁仍在后台运行，未独立复跑。

- 总体判断：f001~f003 已真修，f004 修不彻底并引出 f005；f008 使已打勾的 AC-002 不成立。存在未解决 important（f005/f008），判定 FAIL。

- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`src/mail_core/worker/main.py:249-261` 只读 checkpoint 水位，无 `worker_jobs` 终态反推查询。
- AC-002：TICK-VOID，re_verified。`worker/main.py:259` 三状态修复、`checkpoints.py:287-288` 令牌比较方向正确、`jobs.py:784-789` reclaim 已补；但「取消」分类无结算分支，见 f008。
- AC-003：TICK-VALID，re_verified。`src/mail_core/sync/retention.py:12-18` 固定 24h 且无 7 天常量；`jobs.py:798-817` 对未结算目标关联的排除与 link 行持久化一致。
- AC-004：TICK-VALID，re_verified。迁移 `20261128_0008` 升降级对称、baseline 常量同步、ORM 仅保留规范 GIN 索引。
- AC-005：TICK-VALID，re_verified。`src/mail_core/mail/storage/models.py:471-476` 与迁移部分索引一致，水位判定未引用该索引。
- AC-006：TICK-VOID，re_verified。阈值/目标表/频率上限已落地，但分页早退漏刷新（f005）、上限初值与并发缺陷（f006）、误差常量零引用（f007）。
- AC-007：TICK-VALID，re_verified。`src/mail_core/sync/retention.py:19-27` 单批上限 5000 与稳态口径明确，`prune_completed_jobs` 按上限删除。
- AC-008：TICK-VALID，trust_prior。文档已同步（spec/domain/testing/decision），依赖实施侧全量门禁结果，未独立复跑全部门禁。

coverage = 6 / 8

verdict: FAIL

## Round 3 (2026-11-28T05:27:06+08:00)

reviewed_scope: 50e3d834ab8145f5

- 前轮 finding 复核（以 diff 为准，不采信自述）：
    - `t094_code_f005`（important）— 已消除。`src/mail_core/sync/delta.py:682-694` 在 `apply_delta_page` 成功、数据页写入本事务后、`session.commit()` 之前调用 `_refresh_message_stats_if_bulk`，入参为 `totals`（前序页已提交变更）+ 当前页 `result.upserted/result.deleted`。已发布数据页所在 session 与 ANALYZE 同一事务；此前只覆盖成功终态的调用（现 `:743-745`）保留，作为无数据页执行链的兜底。rate limit / capacity / fencing / cursor_invalid 早退前若已提交数据页，刷新已经发生，不会再因 `totals` 重置而丢失。
    - `t094_code_f006`（minor）— 已消除。`src/mail_core/sync/delta.py:59-60` 改为 `float("-inf")` 初值与模块级 `threading.Lock`；`:68-80` 把「检查上限 → issuing ANALYZE → 更新时间戳」整体置于锁内，进程级并发槽不会重复刷新，启动初期也不会误跳过首次刷新。
    - `t094_code_f007`（minor）— 形式上已消除。`src/mail_core/sync/retention.py:37` 的 `MESSAGE_STATS_RELTUPLES_REL_ERROR` 现被 `tests/mail_core/test_t094_contract_unit.py:63-68` 引用。代码轴不再判零引用死代码；该测试仅做范围断言，是否满足 AC-006「相对误差」的验证强度属 test reviewer 职责，见下方未进表提示。
    - `t094_code_f008`（important）— 已消除，且澄清合理。`docs/tasks/t094_worker_jobs_watermark_and_index_contract/task.md:19,51,81` 三处一致移除「取消」：范围区注明「产品无 delta 取消入口，不存在取消结算路径（Round 2 契约澄清）」，AC-002 改为「成功、失败、跳过、重试耗尽推进水位（产品无取消入口）」，测试策略删除取消场景。代码侧确认全仓无设置 `JobStatus.CANCELLED` 或返回 `status="cancelled"` 的 delta 路径（`JobStatus.CANCELLED` 仅存在于 `src/mail_core/mail/domain/enums.py:105`），移除的是不存在的路径而非合法需求。
- 本轮新发现：0 条。
- 未进表的提示：
    1. f007 的测试仅断言 `0.0 < MESSAGE_STATS_RELTUPLES_REL_ERROR < 1.0`，没有用 `pg_class.reltuples` 对照三表真实行数判定 25% 误差；AC-006 相对误差的验证强度由 test reviewer 判定，代码轴不重复出 finding。
    2. Round 2 f006 建议中「时间戳在 commit 成功后更新」未被采纳：`src/mail_core/sync/delta.py:76-78` 在 ANALYZE 语句下发后即更新 `_last_message_stats_refresh`，若随后 `session.commit()` 回滚，统计更新可能被回滚但上限仍生效 300s。该场景影响有限，未达 blocking 阈值，仅作提示。
    3. 文件过大：`src/mail_core/sync/delta.py` 759 行（≥400 minor 阈值，本 task 净增约 51 行）、`src/mail_core/sync/jobs.py` 833 行（≥800 important 阈值）；按规程仅在此列出，不进 finding 表。
    4. `ANALYZE` 置于 PostgreSQL 事务块内合法（迁移本身同样使用），不构成缺陷；`threading.Lock` 只包围 ANALYZE 下发，不涉及跨进程锁或与 DML 的锁序冲突。
- 总体判断：Round 2 的 4 条 finding 全部消除（f007 为形式修复，残留测试验证强度问题归 test reviewer），未发现修复引入的新问题；8 条 AC 打勾均有实现层支撑，无未解决 critical/important，判定 PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`src/mail_core/worker/main.py:249-261` 到期判定只读 checkpoint 水位，无 `worker_jobs` 终态反推查询。
- AC-002：TICK-VALID，re_verified。三状态排期已按 `full_scan_complete` 判定；成功/失败/跳过/重试耗尽均有结算分支，令牌比较方向正确；「取消」已按 Round 2 契约澄清从范围、AC 与测试策略一致移除。
- AC-003：TICK-VALID，re_verified。`src/mail_core/sync/retention.py:12-18` 固定 24h 且无 7 天常量；`jobs.py:798-817` 对未结算目标关联的排除与 link 行持久化一致。
- AC-004：TICK-VALID，re_verified。迁移 `20261128_0008` 升降级对称、baseline 常量同步、ORM 仅保留规范 GIN 索引。
- AC-005：TICK-VALID，re_verified。`src/mail_core/mail/storage/models.py:471-476` 与迁移部分索引一致，水位判定未引用该索引。
- AC-006：TICK-VALID，re_verified。阈值 1000、三张目标表、300s 频率上限与线程锁明确；数据页提交前与执行链终态均按累计变更触发 ANALYZE，短 delta 不触发。
- AC-007：TICK-VALID，re_verified。`src/mail_core/sync/retention.py:19-27` 单批上限 5000 与稳态口径明确，`prune_completed_jobs` 按上限删除。
- AC-008：TICK-VALID，trust_prior。文档已同步（spec/domain/testing/decision），全量门禁仍在后台运行，依赖实施侧门禁结果，未独立复跑。

coverage = 8 / 8

verdict: PASS
