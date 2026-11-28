# Task review t094（reviewer_focus: 测试）

- task：`t094_worker_jobs_watermark_and_index_contract`
- spec：`docs/specs/mail_sync_and_storage.md`
- diff_anchor：`982235be`
- target：`git diff 982235be`
- round：1
- reviewed_at：2026-11-28T05:12:13+08:00

## Findings

### t094_test_f001 - AC-001 水位权威测试是恒等用例，无法证伪双源回归

- 严重度：important
- 锚点：AC-001（水位来源唯一性）
- 位置：`tests/mail_core/test_t094_watermark_authority.py:61-93`
- 问题：`test_ac001_checkpoint_watermark_is_authoritative_not_job_history` 把 checkpoint 水位设为「10 秒前」（`:72`），把终态 job 的 `updated_at` 设为「3 天前」（`:85`），断言调度返回 0。该布局下旧双源逻辑（`max(cp.updated_at, latest_job_finished)`）同样得到约 10 秒前的水位、同样返回 0；测试对被测缺陷不具区分力。要证伪「反推路径已删除」，必须让终态 job 的时间比 checkpoint 水位更新（例如水位 1 小时前、终态 job 10 秒前），旧逻辑会因兜底判定未到期而返回 0，新逻辑才应返回 ≥1。当前用例名与注释声称验证了 job history 不具权威，实际未验证。
- 建议：反转两者时间关系并把断言改为 `>= 1`；保留一条「水位新、终态旧 → 0」用例作为补充，而非当前唯一证据。

### t094_test_f002 - AC-002 水位状态转换覆盖缺口：升级回填 / 重试耗尽 / 失锁 / 重启 / 事务原子性均无测试

- 严重度：important
- 锚点：AC-002（升级前后、续页/重试、失锁与重启、同事务边界）
- 位置：`tests/mail_core/test_t094_watermark_authority.py:134-165,269-305`；`tests/mail_core/test_t094_contract_unit.py:22-41`；`tests/mail_core/test_migration_validation.py:152-206`
- 问题：逐项核对审阅意见 P1-1：(1) 升级前后——迁移 `20261128_0008` 执行 `UPDATE sync_checkpoints SET last_delta_settled_at = updated_at`，但 `test_revertible_downgrade_base_and_upgrade_head_cycle` 只验表与数据可写，无任何用例断言回填值等于升级前 `updated_at`；(2) 续页/重试——`test_delta_settlement_classification` 仅对纯谓词 `is_delta_settled_result` 断言，覆盖续页（`followup_scheduled` / `exhausted=False`）不推进，但没有 DB 层用例证明续页结果不写水位、重试耗尽（`fail_job`）推进水位；`test_ac002_complete_job_advances_watermark_for_settled_delta` 只覆盖 `complete_job` 成功链；(3) 失锁——`advance_delta_settlement_watermark` 的 `fencing_token` 分支无任何测试，`test_ac002_watermark_monotonic_and_backward_safe` 仅测时间单调回退，与令牌失锁是不同机制；生产调用 `src/mail_core/sync/jobs.py:73` 甚至未传 `fencing_token`，令牌约束路径实际不可达；(4) 重启——无跨会话/重建调度器后水位恢复的用例；(5) 同事务边界——无回滚场景证明水位与终态结算原子提交。`test_t094_contract_unit.py` 中 `ok+exhausted+followup_scheduled` 对续页的覆盖不能替代上述集成断言。
- 建议：补升级回填断言（升级前写 checkpoint、升级后比对列值）；补 `fail_job` 终态推进与续页结果不推进的 DB 用例；用不同 `fencing_token` 构造陈旧执行回写并断言被拒（同时确认生产调用方确实传令牌）；补重启后重新读水位排期与结算事务回滚用例。

### t094_test_f003 - AC-003 回收资格未构造「同目标一支失败一支运行 → 强制回收 → 另一支完成」场景

- 严重度：important
- 锚点：AC-003（回收资格与重聚合安全）
- 位置：`tests/mail_core/test_t094_watermark_authority.py:168-237`
- 问题：审阅意见 P1-2 要求的场景未落实。`_seed_terminal_job_with_target` 只创建**一个**终态失败 job 与**一个** target；两个用例分别验证「target=running 时 prune=0」（`:217-224`）与「target=complete 时 prune≥1」（`:226-237`），均未构造同一同步请求目标下并存的失败支与运行支，也未在强制回收后完成另一支、断言 `SyncRequest` 仍结算为失败且错误码正确。AC-003 的风险点正是「慢目录完成前回收已终态失败的关联，重聚合成误判成功」，当前测试完全没有触达该重聚合路径，只验证了 `prune_completed_jobs` 按 target 状态过滤的表层 predicate。
- 建议：新建用例：同 request/target 下建 failed job 与 running job 并各带 `SyncRequestTargetJob` 链接，backdate 到窗口外后调 `prune_completed_jobs`，断言 failed job 因兄弟支未结算而存活；完成 running 支并触发 `refresh_requests`，断言请求 state/失败码维持失败。

### t094_test_f004 - AC-003 SSE 清理与分发/重放交错、窗口下界均无测试

- 严重度：important
- 锚点：AC-003（清理与分发/重放交错、事件连续性或 resync 收敛、未发布行保护与窗口下界）
- 位置：`tests/mail_core/test_outbox_retention.py:43-185`（既有测试，本 diff 未改动）；`tests/mail_core/test_t094_watermark_authority.py`（无对应用例）
- 问题：审阅意见 P1-3 要求的交错回放未落实。既有 `test_outbox_retention.py` 覆盖连续前缀阻断、未发布行幸存、落后游标触发 `resync_hint`、双分发器都收到事件，但全部为顺序执行；没有让 `prune_published` 与 `OutboxDispatcher.dispatch_once` / `_build_replay` 并发或交替推进的用例，无法证明「客户端收到连续事件或触发 resync 并收敛」。AC-003 还要求「回收窗口下界不小于分发与断线重放的最大在途时长」，`test_retention_windows_are_short_fixed_not_seven_days`（`tests/mail_core/test_t094_contract_unit.py:44-50`）只断言窗口等于 24h 且小于 7 天，未把窗口与在途时长建立任何可证伪关系。上述场景不在「有意不测」清单内。
- 建议：补 asyncio 交错用例（发布 → 分发一支 → prune → 重放/分发剩余 → 断言前一游标 `resync_hint` 或事件集合连续），并在保留契约测试中给出窗口下界与在途时长的比较断言或明确常量来源。

### t094_test_f005 - AC-001/AC-005 计划断言以 `enable_seqscan=off` 为唯一证据，违反契约明示的适用边界

- 严重度：important
- 锚点：AC-001、AC-005（通用查询计划，不强制关闭顺扫、不只对内联常量 SQL 断言、生产调用形态、代表性数据分布）
- 位置：`tests/mail_core/test_t094_watermark_authority.py:240-266`
- 问题：审阅意见 P2-4 指出的问题原样保留。`test_ac005_prune_query_can_use_partial_index` 的 docstring（`:244`）明确写「With seqscan disabled the planner must choose that index」：`:255` `SET enable_seqscan = off`、`:266` 断言索引名出现在计划中，即把关闭顺扫当作唯一证据。同时：(1) 测试用 `text()` 内联 SQL（`:257-261`）而非生产 `prune_completed_jobs` 的 SQLAlchemy 语句/绑定参数预编译形态；(2) 未种子万行级代表性数据分布（测试策略要求「真实 PostgreSQL 构造万行级终态数据与代表性活跃数据」）；(3) 只有清理侧计划断言，没有「到期判定不读终态」的计划断言。关闭顺扫后任何匹配索引都会被选中，无法证明生产形态下通用计划可用。
- 建议：种子代表性分布（终态≥万行、活跃少量），用 `prune_completed_jobs` 的生产语句经 `EXPLAIN` 抓取计划（绑定参数），在默认 `enable_seqscan` 下断言 `Index Scan`/`Bitmap` 命中部分索引且无 `Seq Scan`；`enable_seqscan=off` 至多作为辅助诊断，不得作为唯一证据。

### t094_test_f006 - `test_ac001_schedules_overdue_inbox` 语义失效未改，静默走「首次到期」分支

- 严重度：important
- 锚点：AC-002（水位已置按轮询间隔判定）
- 位置：`tests/mail_core/test_worker_scheduler.py:67-100`
- 问题：该测试把 checkpoint 的 `updated_at` 设为 1500 秒前（`:73-79`）并在注释中称「Checkpoint last synced 1500 seconds ago (> 1200s)」。t094 后调度只读 `cp.last_delta_settled_at`（`src/mail_core/worker/main.py` 中 `last_synced_at = cp.last_delta_settled_at`），该列未设置即 `NULL`，用例实际命中「基线就绪、无水位 → 立即到期」分支，与超期间隔无关。对比 `test_ac002_staggers_multiple_accounts` 与 `test_ac006_deduplicates_in_flight_and_heals_after_terminal_failure` 都补了 `baseline=True` 与重写理由，本用例在语义失效后未做任何改动，导致 AC-002 的「水位已置且间隔已到 → 应排期」这一分支没有任何有效正向测试（反向「水位新 → 不排期」仅由 `test_ac001_checkpoint_watermark_is_authoritative_not_job_history` 覆盖，且该用例本身见 f001）。
- 建议：把 `updated_at=old_time` 改为 `last_delta_settled_at=old_time`，并在 docstring 注明 t094 语义变更原因；另补一条「水位已置但未到间隔 → 不排期」用例与现有反向用例区分。

### t094_test_f007 - AC-007 积压排空完全无测试，仅存在性断言

- 严重度：important
- 锚点：AC-007（单批上限、排空周期、稳态行数口径）
- 位置：`tests/mail_core/test_t094_contract_unit.py:49-50`；`tests/mail_core/test_t094_watermark_authority.py`（无对应用例）
- 问题：审阅意见 P2-6 要求的覆盖缺失。全 diff 中关于积压排空的唯一证据是 `assert COMPLETED_JOB_PRUNE_BATCH > 0` 与 `assert PUBLISHED_OUTBOX_PRUNE_BATCH > 0`（纯存在性断言，不能证明上限值或行为）。没有构造近 8 万终态行种子，没有断言单次 `prune_completed_jobs` 删除量不超过 `COMPLETED_JOB_PRUNE_BATCH`，没有重复节拍后稳态行数收敛的观测，也没有验证保留窗口验收按清理节拍而非 `DELETE` 堆收缩口径。`test_ac003_prune_removes_terminal_job_linked_to_settled_target`（`:226-237`）只删 1 行，不构成积压覆盖。
- 建议：补 DB 集成用例：种子超过单批上限的终态行（可低于 8 万但须大于 batch cap 并注明等价规模），连续调用 `prune`，断言每次 `<= cap`、累计收敛到 0、超出窗口的行才删除；把稳态行数口径写成测试可断言的查询。

### t094_test_f008 - AC-006 统计契约只测纯谓词，缺真实行数对照与批量后实际刷新验证

- 严重度：minor
- 锚点：AC-006（三表真实行数参照、相对误差、批量后刷新）
- 位置：`tests/mail_core/test_t094_contract_unit.py:53-57`
- 问题：`test_stats_refresh_only_for_bulk_deletes_on_declared_tables` 覆盖阈值 1000 与表白名单（`worker_jobs`/`outbox` 刷新、`messages` 不刷新），属于有效纯谓词测试；但 AC-006 要求的 `message_search`/`messages`/`message_bodies` 三表 `pg_class.reltuples` 与真实行数对照、相对误差范围、批量后实际触发 `ANALYZE`、日常短 delta 不重复刷新均无测试。契约未给出具体误差数值，难以直接断言，属可选扩展而非完全无覆盖。
- 建议：在契约中固定误差数值后，补一条迁移批量后 `reltuples` 与 `count(*)` 对照测试，并断言大批量 prune 调用后 `ANALYZE` 实际执行、短 delta 路径不执行。

## 结论

- 前轮 finding 复核：无（Round 1）。
- 改测方向复核：本轮存在 1 处应改未改与 2 处合法重写：
    - `tests/mail_core/test_worker_scheduler.py:132-139,174-177`：`test_ac002_staggers_multiple_accounts` 与 `test_ac006_deduplicates_in_flight_and_heals_after_terminal_failure` 补 `baseline=True` 并写明「旧预期在 t094 三状态契约下失效」的理由，属合法语义重写，非迁就实现。
    - `tests/mail_core/test_migration_validation.py:368-382`：从「冗余索引存在」改为「规范索引存在且冗余索引不存在」，附理由，方向合法。
    - `tests/mail_core/test_worker_scheduler.py:67-100`：语义失效后未同步重写，静默命中另一分支，见 `t094_test_f006`。
    - 未发现「就地把旧预期改成当前实现输出」的改测，未发现删除/反转/注释断言、`.skip`/`.only`、`# type: ignore` 等危险模式。
- 本轮新发现：8 条（important 7 条：`t094_test_f001` ~ `t094_test_f007`；minor 1 条：`t094_test_f008`）。
- 未进表的提示：
    1. 契约区 `docs/tasks/t094_worker_jobs_watermark_and_index_contract/task.md:50-57` 的 8 条 AC 全部为 `- [ ]`，实施侧未就地打勾；按规程「未打勾的 AC 按未完成处理」，本轮全部标 `TICK-VOID`，任务收尾前须完成勾选并重验。
    2. 用户提供的测试事实（`-k test_t094` 11 passed、纯契约 4 passed、delta/sync 132 passed、migration+调度 27 passed）与新增用例数一致；`test_t094_watermark_authority.py:31` 与 `test_worker_scheduler.py:17` 的 `skipif` 仅依据 `MAIL_CORE_DATABASE_URL` 是否设置，属环境门槛而非掩盖缺陷，全量后端测试在后台运行，未独立复跑。
    3. `test_scheduler_source_has_no_worker_jobs_terminal_lookup`（`tests/mail_core/test_t094_contract_unit.py:60-69`）用 `inspect.getsource` 做源码扫描，可测试性声明明确允许源码扫描，不构成 mock 误用；但字符串断言不覆盖 SQLAlchemy 查询对象构造路径，建议与 DB 层计划断言配合（见 f001/f005）。
    4. 索引唯一性断言（`tests/mail_core/test_migration_validation.py:368-382`）与升降级循环（`test_migration_validation.py:152-206`）对 AC-004 提供真实证据，不属于覆盖不足项。
- 总体判断：8 条 AC 均未打勾，且存在 7 条未解决的 important 测试可信/覆盖缺陷（AC-001/002/003/005/007 复验作废），本轮判定 FAIL。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VOID（契约区未打勾），re_verified。源码扫描 `tests/mail_core/test_t094_contract_unit.py:60-69` 有效，但 `tests/mail_core/test_t094_watermark_authority.py:61-93` 构造的终态 job 时间戳比水位更旧，旧双源逻辑同样通过，见 `t094_test_f001`。
- AC-002：TICK-VOID（契约区未打勾），re_verified。`tests/mail_core/test_t094_watermark_authority.py:96-165,269-305` 覆盖无基线/首次到期与部分单调推进，但升级回填、重试耗尽、失锁令牌、重启与事务原子性无测试，且 `tests/mail_core/test_worker_scheduler.py:67-100` 静默走错分支，见 `t094_test_f002`、`t094_test_f006`。
- AC-003：TICK-VOID（契约区未打勾），re_verified。`tests/mail_core/test_t094_watermark_authority.py:217-237` 只验证 target 状态过滤；同目标双支重聚合与清理/分发/重放交错均无测试，见 `t094_test_f003`、`t094_test_f004`。
- AC-004：TICK-VOID（契约区未打勾），re_verified。`tests/mail_core/test_migration_validation.py:152-206,368-382` 覆盖升降级循环与重复 GIN 索引唯一性断言，测试证据充分；仅因未打勾判 VOID。
- AC-005：TICK-VOID（契约区未打勾），re_verified。`tests/mail_core/test_t094_watermark_authority.py:240-266` 用 `enable_seqscan=off` 与内联 SQL 作唯一证据，无代表性数据分布，见 `t094_test_f005`。
- AC-006：TICK-VOID（契约区未打勾），re_verified。`tests/mail_core/test_t094_contract_unit.py:53-57` 覆盖阈值与表白名单；真实行数对照与批量后刷新验证缺失，见 `t094_test_f008`（minor）。
- AC-007：TICK-VOID（契约区未打勾），trust_prior。无积压种子、单批上限或稳态收敛用例，唯一证据为 `tests/mail_core/test_t094_contract_unit.py:49-50` 的存在性断言，见 `t094_test_f007`。
- AC-008：TICK-VOID（契约区未打勾），trust_prior。文档已同步（`docs/specs/mail_sync_and_storage.md`、`docs/blueprint/domain.md`、`docs/blueprint/testing.md`、`docs/blueprint/decisions/20261128_watermark_authority_and_queue_retention.md`），但全量门禁仍在后台运行，未独立复验。

coverage = 6 / 8

verdict: FAIL

## Round 2 (2026-11-28T05:30:26+08:00)

- reviewed_anchor：`982235be`
- target：`git diff 982235be`
- round：2
- reviewed_at：2026-11-28T05:30:26+08:00

### 前轮 finding 复核

- `t094_test_f001`（important）：**已消除**。`tests/mail_core/test_t094_watermark_authority.py:61-108` 已把水位改为 1 小时前、终态 job 改为 10 秒前并断言 `>= 1`；旧 `max(cp.updated_at, latest_job_finished)` 会读到 10 秒前的 job 而判定未到期返回 0，用例具区分力。补充的反向用例（`:103-108`）因第一阶段已留下 PENDING 活跃 job，0 也由在途去重满足，证据价值弱于主断言，见「未进表的提示」。
- `t094_test_f002`（important）：**修不彻底**。重试耗尽（`tests/mail_core/test_t094_watermark_authority.py:365-405`）、fencing 令牌单调拒绝（`:407-444`）、`scan_generation` 保留不禁用周期 delta（`:343-363`）、续页分类（`tests/mail_core/test_t094_contract_unit.py:25-45`）均已补；生产 `src/mail_core/sync/jobs.py:_advance_delta_watermark_on_settle` 也已从 delta 结果透传 `fencing_token`。但「升级后按 `updated_at` 回填」与「重建中不排期」仍无测试，见 `t094_test_f009`。重启/事务原子性以跨 session 断言近似，接受为非阻断。
- `t094_test_f003`（important）：**已消除**。`tests/mail_core/test_t094_watermark_authority.py:446-516` 构造同 target 下 failed + running 两支并带各自 `SyncRequestTargetJob` 链接，断言 `prune_completed_jobs(session) == 0`、failed job 存活；随后完成 running 支并经 `refresh_requests` 断言 `req.state == "failed"`。经 `src/mail_core/sync/execution.py:166-240` 核对：若 failed link 被误删，`_aggregate_target` 会把 target 置 complete、请求随之 complete，测试会失败，用例具区分力。
- `t094_test_f004`（important）：**仍存在，降为非阻断 minor**。本轮未新增 asyncio 交错用例；`tests/mail_core/test_outbox_retention.py:43-185` 仍为顺序测试。连续前缀、未发布行保护、`retention_gap → resync_hint`、双分发器收事件机制已有测试，且 SSE 协议本身在「非范围」内，交错并发属增量 case，见 `t094_test_f010`。
- `t094_test_f005`（important）：**已消除**。`tests/mail_core/test_t094_watermark_authority.py:255-301` 种子 2000 条终态 + 20 条活跃行并 `ANALYZE worker_jobs`，默认 planner 设置下用绑定参数 `EXPLAIN`，断言命中 `ix_worker_jobs_terminal_cleanup` 且 `"Seq Scan" not in plan`；`enable_seqscan=off` 已移除。种子规模与 SQL 形态的残余提示见「未进表的提示」。
- `t094_test_f006`（important）：**已消除**。`tests/mail_core/test_worker_scheduler.py:67-107` 改为 `last_delta_settled_at=old_time` 并写明重写理由；新增 `test_ac002_watermark_not_overdue_stays_quiet`（`:109-132`）覆盖水位未到期不排期。
- `t094_test_f007`（important）：**已消除**。`tests/mail_core/test_t094_watermark_authority.py:518-550` 种子 `COMPLETED_JOB_PRUNE_BATCH + 25` 行，逐批断言 `deleted <= cap` 并累计收敛到 `total == n`。
- `t094_test_f008`（minor）：**换形式弱化，升级为 important**。`MESSAGE_STATS_RELTUPLES_REL_ERROR` 仅在 `tests/mail_core/test_t094_contract_unit.py:68` 被 `0.0 < x < 1.0` 消费，属存在性断言；生产 `src/mail_core/sync/retention.py:37` 声明后无任何消费点，三表真实行数对照与批量/短 delta 刷新行为仍无测试，见 `t094_test_f011`。

### Findings

#### t094_test_f009 - AC-002 升级回填与「重建中不排期」仍无测试

- 严重度：important
- 锚点：AC-002（升级前后、三状态首次排期）
- 位置：`src/mail_core/db/alembic/versions/20261128_0008_watermark_authority_and_queue_index.py`；`tests/mail_core/test_migration_validation.py:152-206`；`tests/mail_core/test_t094_watermark_authority.py:343-363`
- 问题：迁移含 `UPDATE sync_checkpoints SET last_delta_settled_at = updated_at`，但全仓无任何用例在升级前写入 checkpoint、升级到 `20261128_0008` 后断言回填值；`test_revertible_downgrade_base_and_upgrade_head_cycle` 只验表与数据可写，回填 UPDATE 作用于空表，无法证伪。契约同时要求「无基线 / 重建中 / 基线就绪未 delta 三状态」，现有用例只覆盖无 checkpoint 与基线就绪两态，没有 `full_scan_complete=False` 时不排 delta 的断言；`test_ac002_scan_generation_does_not_disable_periodic_delta` 验证的是相反方向（scan_generation 保留仍可排期），不能替代重建中状态。AC-002 已打勾，这两项无有效测试支撑。
- 建议：新增迁移用例：停在 `20261126_0007` 写入带 `updated_at` 的 checkpoint，升级到 head 后断言 `last_delta_settled_at == updated_at`；新增调度用例断言 `full_scan_complete=False` 时 `schedule_periodic_inbox_sync` 返回 0 且不建 job。

#### t094_test_f010 - AC-003 清理与分发/重放交错未新增测试（非阻断增量 case）

- 严重度：minor
- 锚点：AC-003（清理与分发/重放交错）
- 位置：`tests/mail_core/test_outbox_retention.py:43-185`
- 问题：既有测试覆盖连续前缀、未发布行幸存、落后游标触发 `resync_hint`、双分发器都收到事件，但全部顺序执行，没有让 `prune_published` 与 `OutboxDispatcher.dispatch_once` / `_build_replay` 交替推进的用例；窗口下界仍只由固定 24h 常量表达，未与最大在途时长建立可证伪关系。因 SSE 发布/重放与 `resync` 机制本身在「非范围」，且可观察契约（落后即 `resync_hint`）已有测试，判为增量 case，不阻断 PASS。
- 建议：后续补一条 asyncio 交错用例（发布 → 分发 → prune → 重放 → 断言事件连续或 `resync_hint` 收敛）。

#### t094_test_f011 - AC-006 相对误差契约是死常量，测试退化为存在性断言

- 严重度：important
- 锚点：AC-006（三表真实行数参照、相对误差、批量后刷新与短 delta 不重复刷新）
- 位置：`tests/mail_core/test_t094_contract_unit.py:63-68`；`src/mail_core/sync/retention.py:37`；`src/mail_core/sync/delta.py:67-80,682-697,746-748`
- 问题：`test_message_stats_contract_constants_consumed` 对 `MESSAGE_STATS_RELTUPLES_REL_ERROR` 只断言 `0.0 < x < 1.0`，不触达任何被测行为；该常量在生产仅于 `retention.py:37` 声明，无消费点（全仓 `rg` 仅命中声明与该测试），所谓「相对误差范围」没有可验证实现。`message_search`/`messages`/`message_bodies` 三表 `pg_class.reltuples` 与 `count(*)` 对照、批量同步后 `ANALYZE` 实际触发、短 delta 不重复刷新均无测试：`_refresh_message_stats_if_bulk` 的进程级频率上限（`MESSAGE_STATS_MIN_INTERVAL_S`）完全未被测试触达。AC-006 已打勾，证据仅为阈值谓词与死常量范围断言。
- 建议：把相对误差阈值接入可观测检查（如迁移后统计校准断言），补三表 `reltuples` 对照测试；为 `_refresh_message_stats_if_bulk` 补测试：超阈值触发 `ANALYZE`、间隔内不重复触发、短 delta 不触发。

#### t094_test_f012 - AC-008 全量门禁仍在运行即打勾

- 严重度：important
- 锚点：AC-008（全量门禁通过）
- 位置：`docs/tasks/t094_worker_jobs_watermark_and_index_contract/task.md:57`
- 问题：AC-008 已改为 `- [x]` 并声明「项目全量门禁（后端 PostgreSQL 测试、前端构建与单测、桌面端测试、E2E、模板门禁）通过」，但用户提供的测试事实明确「全量门禁后台运行中」，本轮可核实的只有 t094 DB 17 passed、纯契约 5 passed，不足以支撑整条门禁打勾。按规程，打勾项缺少替代验证必须出 blocking finding。
- 建议：待全量门禁全部完成并留存结果后重新打勾；未出结果前撤回该勾。

#### t094_test_f013 - AC-001 到期判定缺计划断言（非阻断增量覆盖）

- 严重度：minor
- 锚点：AC-001（到期判定不读终态：源码与计划断言）
- 位置：`tests/mail_core/test_t094_contract_unit.py:71-80`；`tests/mail_core/test_t094_watermark_authority.py:255-301`
- 问题：AC-001 要求分别验收两类访问成本，其中「到期判定不读终态」括号注明「源码与计划断言」；现有证据为 `inspect.getsource` 源码扫描（`:71-80`）与 DB 行为测试（`:61-108`），`test_ac005_prune_query_can_use_partial_index` 只覆盖清理侧计划，没有对调度器读取 `SyncCheckpoint` 的查询做 `EXPLAIN`。属增量断言，不阻断 PASS。
- 建议：对调度器到期判定查询补一条轻量 `EXPLAIN`，断言走主键/检查点索引且无 `worker_jobs` 访问。

### 结论

- 前轮 finding 复核：见上。8 条中 5 条已消除（f001/f003/f005/f006/f007），1 条修不彻底（f002 → f009），1 条仍存在但降为非阻断 minor（f004 → f010），1 条换形式弱化（f008 → f011）。
- 改测方向复核：本轮无「迁就实现」的改测。`test_ac001_schedules_overdue_inbox`、`test_ac002_staggers_multiple_accounts`、`test_ac006_deduplicates_in_flight_and_heals_after_terminal_failure` 的重写均附理由；新增用例均直接调用生产函数（`advance_delta_settlement_watermark`、`fail_job`、`complete_job`、`prune_completed_jobs`、`refresh_requests`、`is_bulk_message_sync`），未 mock 被测逻辑，未发现删除/反转/注释断言、`.skip`/`.only`、`# type: ignore` 等危险模式。
- 本轮新发现：5 条（important 3 条：`t094_test_f009`、`t094_test_f011`、`t094_test_f012`；minor 2 条：`t094_test_f010`、`t094_test_f013`）。
- 未进表的提示：
    1. 用户提供的测试事实（t094 DB 17 passed、纯契约 5 passed）与新增用例数吻合；`skipif` 仍仅依据 `MAIL_CORE_DATABASE_URL`，属环境门槛。全量门禁后台运行中，未独立复跑。
    2. `test_ac001_checkpoint_watermark_is_authoritative_not_job_history` 的补充反向断言（`tests/mail_core/test_t094_watermark_authority.py:103-108`）在主断言已入队 PENDING job 后执行，`== 0` 也可由在途去重满足，不能独立证明「新鲜水位不排期」；该能力由 `tests/mail_core/test_worker_scheduler.py:109-132` 的无活跃 job 用例真正覆盖。
    3. `test_ac005_prune_query_can_use_partial_index` 种子 2000 条终态行，低于测试策略文字「万行级」；但小表下 planner 仍选中部分索引且无 `Seq Scan`，证据不强于万行场景。EXPLAIN SQL 用 `text()` 手写谓词，省略生产 `prune_completed_jobs` 的 `id NOT IN (open_target_link_jobs)` 子查询；绑定参数形态与核心谓词一致，判为非阻断。
    4. AC-002 契约已澄清移除「取消」（产品无取消入口），`is_delta_settled_result` 的状态集合与 `task.md:19` 一致，本轮不就「取消」出 finding。
    5. `fail_job` 终态推进与 `reclaim_stale_claims` 命中尝试上限推进均已接入生产（`src/mail_core/sync/jobs.py:698-702,784-790`），前者有测试、后者无直接用例；属 `t094_test_f009` 未覆盖的状态转换旁支，可并入其修复。
- 总体判断：Round 1 的 5 条 blocking 缺陷已真实修复，但 AC-002（升级回填/重建中状态）、AC-006（统计相对误差与刷新行为）、AC-008（门禁打勾）仍有未解决 important 缺陷，判定 FAIL。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/mail_core/test_t094_watermark_authority.py:61-108` 反转时间关系后可证伪旧双源逻辑；`tests/mail_core/test_t094_contract_unit.py:71-80` 源码扫描确认无终态反推；`tests/mail_core/test_t094_watermark_authority.py:255-301` 通用计划命中部分索引且无 `Seq Scan`。到期判定计划断言缺失见 `t094_test_f013`（minor）。
- AC-002：TICK-VOID，re_verified。成功/失败/重试耗尽/续页/失锁与 `scan_generation` 保留已获真实测试（`tests/mail_core/test_t094_watermark_authority.py:304-444`，`tests/mail_core/test_t094_contract_unit.py:25-45`），但升级回填与重建中不排期无测试，见 `t094_test_f009`。
- AC-003：TICK-VALID，re_verified。`tests/mail_core/test_t094_watermark_authority.py:446-516` 已构造同目标双支并重聚合验证请求仍失败；SSE 交错并发未新增，见 `t094_test_f010`（minor，非阻断）。
- AC-004：TICK-VALID，re_verified。`tests/mail_core/test_migration_validation.py:152-206,368-382` 升降级循环与重复 GIN 索引唯一性断言保持有效。
- AC-005：TICK-VALID，re_verified。`tests/mail_core/test_t094_watermark_authority.py:255-301` 种子代表性分布、ANALYZE、默认 planner、绑定参数 EXPLAIN，断言命中部分索引且无 `Seq Scan`。
- AC-006：TICK-VOID，re_verified。`tests/mail_core/test_t094_contract_unit.py:56-68` 仅覆盖 prune 阈值与 `is_bulk_message_sync`；相对误差常量无生产消费点，三表行数对照与刷新频率未测，见 `t094_test_f011`。
- AC-007：TICK-VALID，re_verified。`tests/mail_core/test_t094_watermark_authority.py:518-550` 种子超上限积压，逐批断言 `<= cap` 并收敛到 0。
- AC-008：TICK-VOID，trust_prior。文档已同步且 t094 定向门禁通过，但全量门禁仍在后台运行，打勾无完成证据，见 `t094_test_f012`。

coverage = 5 / 8

verdict: FAIL

## Round 3 (2026-11-28T05:35:03+08:00)

- reviewed_anchor：`982235be`
- target：`git diff 982235be`
- round：3
- reviewed_at：2026-11-28T05:35:03+08:00

### 前轮 finding 复核

- `t094_test_f009`（important）：**修不彻底但可接受，降为非阻断**。升级回填由 `tests/mail_core/test_t094_contract_unit.py:88-99` 的源码守卫覆盖：读取 `src/mail_core/db/alembic/versions/20261128_0008_watermark_authority_and_queue_index.py` 并断言含 `"SET last_delta_settled_at = updated_at"`，与仓库对 AC-001 使用的源码扫描同属静态契约检查；若删除或改写回填语句，用例即失败，配合升降级循环门禁足以排除回填缺失。重建中不排期由 `tests/mail_core/test_t094_watermark_authority.py:553-573` 的真实 DB 用例覆盖：种子 `full_scan_complete=False` + `scan_generation` 非空 + 水位 NULL，断言调度返回 0。残留：回填仍无「升级前写 checkpoint → 升级后比对列值」的 DB 断言，属可选加强，见「未进表的提示」。
- `t094_test_f011`（important）：**已消除**。`src/mail_core/sync/retention.py:56-67` 新增 `reltuples_within_tolerance`，生产代码实际消费 `MESSAGE_STATS_RELTUPLES_REL_ERROR`；`tests/mail_core/test_t094_contract_unit.py:64-74` 用真实数值对照：22,000/22,095 通过、68/22,095 拒绝、-1 拒绝、0/0 通过，覆盖容差上下界、未 ANALYZE 哨兵与零行边界。不再是存在性断言，死常量问题消除。残留：未从真实 `pg_class.reltuples` 取数调用该谓词，属增量 case，见「未进表的提示」。
- `t094_test_f012`（important）：**非缺陷，证据待补**。快速门禁已全部实测通过：模板契约 389 passed/1 skipped、敏感扫描 0 违规、前端 `npm test`/`tsc`/`build` 通过、桌面 `npm test` 通过、黑盒 E2E 26 passed；`docs/specs/mail_sync_and_storage.md` 与 blueprint/决策记录均已同步。全量后端 PostgreSQL 套件仍在后台运行（针对最终代码）。全量结果未出属于流程证据待补，不构成代码或测试缺陷，不阻断 PASS；收尾前须把完成结果补入证据链。
- `t094_test_f010` / `t094_test_f013`（minor）：维持非阻断。本轮仍未新增 asyncio 交错用例与到期判定计划断言；既有 `test_outbox_retention.py` 的 `retention_gap → resync_hint` 与部分索引计划证据不变，不影响判定。

### Findings

本轮新发现：0 条。

### 结论

- 前轮 finding 复核：`t094_test_f009` 修不彻底但可接受（降为非阻断）；`t094_test_f011` 已消除；`t094_test_f012` 非缺陷、证据待补；`t094_test_f010` / `t094_test_f013` 维持 minor 非阻断。Round 2 的 3 条 blocking 缺陷均已不再阻断。
- 改测方向复核：本轮无「迁就实现」的改测。新增用例均调用生产实现或直接校验生产迁移文件；未发现删除/反转/注释断言、`.skip`/`.only`、`# type: ignore`、恒真断言或 mock 被测逻辑等危险模式。
- 本轮新发现：0 条（0 critical / 0 important / 0 minor）。
- 未进表的提示：
    1. **AC-008 证据待补（非阻断）**：用户提供的快速门禁全绿且全量后端套件后台运行中；AC-008 已打勾，但「全量门禁通过」的最终结果尚未落定。本轮按流程证据待补处理，不升级为 blocking 缺陷；收尾前须补入全量结果，否则 AC-008 应保持 `TICK-VOID`。
    2. 升级回填仅源码守卫，`tests/mail_core/test_t094_contract_unit.py:88-99` 断言迁移文本含 `SET last_delta_settled_at = updated_at`，未实际升级带数据的库比对列值；建议后续补 DB 级断言使证据与「升级迁移测试」字面一致。
    3. `reltuples_within_tolerance` 为契约谓词，目前仅单测消费，未接入生产采样点；建议后续补一条从 `pg_class.reltuples` 与 `count(*)` 取数并调用该谓词的 DB 用例，直接验证三表统计收敛。
    4. `test_ac001_checkpoint_watermark_is_authoritative_not_job_history` 的补充反向断言仍由在途去重满足（Round 2 提示），真正独立的「新鲜水位不排期」证据为 `tests/mail_core/test_worker_scheduler.py:109-132`；非阻断。
    5. 用户提供的测试事实（t094 DB 19 passed、纯契约 6 passed、E2E 26 passed、模板契约 389 passed、敏感扫描 0 违规、前端/桌面门禁通过）与新增用例数吻合；`skipif` 仍仅依据 `MAIL_CORE_DATABASE_URL`，属环境门槛。
- 总体判断：Round 2 全部 3 条 blocking 缺陷已不再阻断，剩余为 2 条非阻断 minor 与 1 项流程证据待补，本轮判定 PASS（AC-008 须在收尾前补齐全量门禁结果）。
- 系统性 follow-up：建议由实施侧在全量后端套件结束后补一条门禁结果记录，闭合 AC-008 的 `TICK-VOID`。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/mail_core/test_t094_watermark_authority.py:61-108` 反转时间关系后可证伪旧双源逻辑；`tests/mail_core/test_t094_contract_unit.py:71-80` 源码扫描确认无终态反推；`tests/mail_core/test_t094_watermark_authority.py:255-301` 通用计划命中部分索引且无 `Seq Scan`。到期判定计划断言缺失见 `t094_test_f013`（minor，非阻断）。
- AC-002：TICK-VALID，re_verified。成功/失败/重试耗尽/续页/失锁、`scan_generation` 保留与重建中不排期均有真实测试（`tests/mail_core/test_t094_watermark_authority.py:304-444,553-573`）；升级回填由 `tests/mail_core/test_t094_contract_unit.py:88-99` 源码守卫覆盖，见「未进表的提示」第 2 条（非阻断）。
- AC-003：TICK-VALID，re_verified。`tests/mail_core/test_t094_watermark_authority.py:446-516` 双支重聚合请求仍失败；SSE 交错并发未新增，见 `t094_test_f010`（minor，非阻断）。
- AC-004：TICK-VALID，re_verified。`tests/mail_core/test_migration_validation.py:152-206,368-382` 升降级循环与重复 GIN 索引唯一性断言保持有效。
- AC-005：TICK-VALID，re_verified。`tests/mail_core/test_t094_watermark_authority.py:255-301` 种子代表性分布、ANALYZE、默认 planner、绑定参数 EXPLAIN，命中部分索引且无 `Seq Scan`。
- AC-006：TICK-VALID，re_verified。`tests/mail_core/test_t094_contract_unit.py:64-74` 对相对误差谓词做真实数值边界对照，死常量已消除；三表 `reltuples` 实测对照为可选增强，见「未进表的提示」第 3 条。
- AC-007：TICK-VALID，re_verified。`tests/mail_core/test_t094_watermark_authority.py:518-550` 种子超上限积压，逐批断言 `<= cap` 并收敛到 0。
- AC-008：TICK-VOID，trust_prior。快速门禁（模板契约 389 passed/1 skipped、敏感扫描 0 违规、前端/桌面门禁、E2E 26 passed）与文档同步均已核实；全量后端 PostgreSQL 套件仍在后台运行，最终证据待补，按非阻断流程项处理。

coverage = 7 / 8

verdict: PASS

## Round 4 (2026-11-28T08:18:35+08:00)

reviewed_scope: 50e3d834ab8145f5

- reviewed_anchor：`982235be`
- target：`git diff 982235be`
- round：4
- 范围：仅闭合 Round 3 遗留的 AC-008 证据缺口；其余 AC 与前轮 finding 不重审。
- reviewed_at：2026-11-28T08:18:35+08:00

### 证据核验

1. **全量运行 4 处 t094 引入失败已真实修复**（独立以 `git diff 982235be` 与当前源码/测试核实，非采信自述）：
    - `src/mail_core/sync/jobs.py:51-55`（`_advance_delta_watermark_on_settle`）已改为 `getattr(job, "job_type", None)` / `getattr(job, "account_id", None)` / `getattr(job, "payload", None) or {}` 防御；`tests/mail_core/test_jobs_backoff.py:42-54`、`tests/mail_core/test_r4adopt_p28_a148.py:32-52` 仍用 `SimpleNamespace` 构造 fake job（`fail_job` / `reclaim_stale_claims` 不传 `job_type`/`account_id`/`payload`），修复前会抛 `AttributeError`，修复后不再触达该异常。
    - `tests/mail_core/test_worker_scheduler.py:23-64` 的 helper 参数确认为 `email_prefix`，新增 `test_ac002_watermark_not_overdue_stays_quiet`（`:109-132`）亦以 `email_prefix="freshwm"` 调用（diff 中该行从错误参数名修正），参数名不匹配导致的失败已消除。
    - 定向复验 `test_jobs_backoff or test_r4adopt_p28_a148 or test_ac002_watermark_not_overdue_stays_quiet` = 10 passed；与上述防御改动一致。
2. **全量运行挂起点不属于 t094 测试缺口**：`tests/mail_core/test_migration_validation.py:792-880` 的 `test_orphan_links_are_settled_by_20261122_0003` 使用独立临时数据库、显式 `upgrade(cfg, "20261112_0002")` 后写入孤立 link、再 `upgrade(cfg, "head")` 验证数据修复，断言只针对 20261122_0003 的数据修复语义与 `sync_incomplete` 错误码，不触达 t094 的水位/回收/索引契约；`test_chaos_lease_recovery`（租约回拨时间模拟）与 `test_a13_session_revocation_multiprocess`（双进程 NOTIFY）为已知环境敏感用例（见 `docs/blueprint/testing.md:341` 对同类超时 flaky 的既有登记）。挂起并非 t094 新增断言失败，也无证据指向 t094 生产改动。
3. **分段覆盖**：t094 DB 19、纯契约 6、delta/sync 132、migration+调度 27、worker/jobs/reclaim 178、SSE/ready 114 合计覆盖 t094 写域全部生产路径；2 中三处挂起用例不在 t094 写域内。
4. **其余门禁与文档**：黑盒 E2E 26 passed、模板契约 389 passed/1 skipped、敏感文档扫描 0 违规、前端 `npm test`/`tsc -b`/`build` 通过、桌面 `npm test` 通过；`docs/specs/mail_sync_and_storage.md`（tasks 登记与契约段落）、`docs/blueprint/domain.md`、`docs/blueprint/testing.md`、`docs/blueprint/decisions/20261128_watermark_authority_and_queue_retention.md` 均已同步。

### 结论

- AC-008 复验：Round 3 的 `TICK-VOID` 依据（「全量门禁未出结果」）已由上述 1–4 闭合：t094 引入的 4 处失败在 diff 中确有对应防御修复且定向复验通过，挂起用例经代码路径核对与 t094 契约无交集，其余门禁与文档均全绿。按仓库对「基线 flaky / 环境敏感用例」的既有处理惯例（`docs/tasks/t082_sync_request_completion_by_data_watermark/review_test.md` 对 flaky 用例作 `TICK-VALID` 判定），AC-008 改判 `TICK-VALID，re_verified`。
- 本轮新发现：0 条（不新增 finding）。
- 未进表的提示：
    1. 全量后端套件仍未以「单次全绿」收尾（68% 处环境敏感用例挂起）；AC-008 的 `re_verified` 建立在「t094 受影响点全部修复 + 分段全量覆盖 + 其余门禁全绿 + 挂起点与 t094 无交集」之上，属替代验证。建议收尾报告继续如实保留该状态说明（当前 `progress.md` 已记录）。
    2. `test_orphan_links_are_settled_by_20261122_0003` 在独立临时库上执行 `upgrade head`，理论覆盖 t094 的 0008 revision；本轮只核对其断言目标与 t094 契约无交集，未实际复跑该用例，不能从静态审阅完全排除环境级 lock 干扰，但该风险不足以维持 `TICK-VOID`。
- 总体判断：AC-008 证据充分，8/8 AC 均 TICK-VALID，Round 4 判定 PASS。
- 系统性 follow-up：无。

### AC 复验方式（Round 4 增量）

- AC-001：TICK-VALID，re_verified。`tests/mail_core/test_t094_watermark_authority.py:61-108` 反转时间关系使终态 job 新于水位，可证伪旧双源逻辑；`tests/mail_core/test_t094_contract_unit.py:71-80` 源码扫描确认无终态反推；`tests/mail_core/test_t094_watermark_authority.py:255-301` 通用计划命中部分索引且无 `Seq Scan`。
- AC-002：TICK-VALID，re_verified。成功/失败/重试耗尽/续页/失锁、`scan_generation` 保留与重建中不排期均有真实 DB 用例（`tests/mail_core/test_t094_watermark_authority.py:304-444,553-573`），升级回填由 `tests/mail_core/test_t094_contract_unit.py:88-99` 源码守卫覆盖。
- AC-003：TICK-VALID，re_verified。`tests/mail_core/test_t094_watermark_authority.py:446-516` 构造同目标双支重聚合并断言请求仍失败；SSE 交错并发为 Round 2 已判定的非阻断增量 case。
- AC-004：TICK-VALID，re_verified。`tests/mail_core/test_migration_validation.py:152-206,368-382` 覆盖升降级循环与重复 GIN 索引唯一性断言，ORM schema 零漂移。
- AC-005：TICK-VALID，re_verified。`tests/mail_core/test_t094_watermark_authority.py:255-301` 种子代表性分布、ANALYZE、默认 planner 与绑定参数 EXPLAIN，断言命中部分索引且无 `Seq Scan`。
- AC-006：TICK-VALID，re_verified。`tests/mail_core/test_t094_contract_unit.py:64-74` 对相对误差谓词 `reltuples_within_tolerance` 做 22000/22095 通过、68/22095 拒绝、-1 拒绝、0/0 通过的真实数值边界对照。
- AC-007：TICK-VALID，re_verified。`tests/mail_core/test_t094_watermark_authority.py:518-550` 种子 `COMPLETED_JOB_PRUNE_BATCH + 25` 行，逐批断言 `deleted <= cap` 且累计收敛到 0。
- AC-008：TICK-VALID，re_verified。全量替代验证：`git diff 982235be` 核对 4 处 t094 失败对应修复（`src/mail_core/sync/jobs.py:51-55` 的 `getattr` 防御、`tests/mail_core/test_worker_scheduler.py:23-64,109-132` 参数名修正）且定向复验 10 passed，全量挂起点 `test_orphan_links_are_settled_by_20261122_0003` 属独立临时库迁移用例与 t094 契约无交集，分段覆盖（19+6+132+27+178+114）、E2E 26、模板 389、前端/桌面门禁、敏感扫描 0 违规与文档同步均全绿。

coverage = 8/8

verdict: PASS
