---
pid: "p102"
slug: "worker_jobs_seq_scan_storm_and_search_index_bloat"
status: "closed"
resolution: "transferred"
reason: "2026-11-28 核实生产索引/水位双源/保留期事实仍成立，按开发铁律以删除反推路径方案转交 t094"
fix_ref: "t094"
---
# p102 worker_jobs 缺索引引发全表扫描风暴、队列长保留膨胀与冗余全文索引

- 现象：
    - 在仅存储 `22,095` 封邮件的单机生产库中，`kkmail-mail-core-pg` 空闲期持续占用 `~3.65%` CPU，累计网络发送量高达 **`10.3 GB`**、磁盘块写入 **`4.55 GB`**，且每 5 分钟不间断触发耗时 `13s–41s` 的定时 WAL Checkpoint。
    - `pg_stat_database` 实测累计顺序扫描返回元组数达 **`tup_returned = 7,664,397,699`（76.6 亿行）**：其中 `worker_jobs` 表（存有 `79,396` 行、占 `96 MB`，含 `79,218` 条 `done` 行）发生了 **`84,199` 次全表顺序扫描（`seq_scan`）**；`outbox` 表囤积 `86,339` 行（占 `72 MB`）。
    - `message_search` 表占 `208 MB`（主表 `34 MB` + 索引 `70 MB` + TOAST `104 MB`），其上同时存在两个定义完全相同的 `from_text` GIN 三元组索引（`ix_message_search_from_trgm` `7,840 kB` 扫描次数 `0`，`ix_message_search_from_text_trgm` `7,840 kB`）；同时 `pg_stat_user_tables` 中 `message_bodies`、`message_search`、`messages` 的统计信息停留在 `n_live_tup = 68`（与真实 `22,095` 行偏差超 320 倍）。
- 影响：
    - 覆盖后台周期收件箱同步调度、已完成任务与已发布 Outbox 周期清理、全文检索索引维护及全库查询计划生成。
    - 每 60 秒调度与回收周期内，40 个账号的非 IDLE 收件箱检查与清理任务反复全表扫描近百 MB 的 `worker_jobs` 堆表，随 7 天窗口内任务累积形成严重的 CPU、Buffer Cache 污染与 I/O 放大。
    - 已确认合并进同一修复范围的同类位点：
        1. 周期收件箱调度无索引回查：`src/mail_core/worker/main.py:253-262`（`schedule_periodic_inbox_sync` 对每个候选收件箱查询 `WHERE dedupe_key = :key AND status IN ('done', 'failed') AND updated_at IS NOT NULL ORDER BY updated_at DESC LIMIT 1`）。
        2. 周期历史任务清理无索引扫描：`src/mail_core/sync/jobs.py:720-743`（`prune_completed_jobs` 每 60s 执行 `WHERE status IN ('done', 'failed') AND updated_at < :cutoff ORDER BY updated_at ASC LIMIT 1000`）。
        3. `worker_jobs` 索引覆盖缺口：`src/mail_core/mail/storage/models.py` 与 Alembic 迁移仅定义了 `ix_worker_jobs_claim (status, run_after, priority)` 与仅限活跃态的部分唯一索引 `ix_worker_jobs_dedupe_active (dedupe_key) WHERE dedupe_key IS NOT NULL AND status IN ('pending', 'claimed')`，终态 `('done', 'failed')` 既无 `(dedupe_key, updated_at)` 索引也无 `(updated_at)` 清理索引。
        4. 瞬态表长保留窗口：`src/mail_core/worker/main.py:137-148` 与 `src/mail_core/realtime/outbox.py:16-17, 90-164` 将已完成 `worker_jobs` 与已发布 `outbox` 统一保留长达 **7 天**，导致瞬态工作队列表常驻近 17 万行 / `168 MB`。
        5. `message_search` 冗余索引与陈旧统计信息：`src/mail_core/mail/storage/models.py` 与历史迁移重复保留了 `ix_message_search_from_trgm` 与 `ix_message_search_from_text_trgm` 两条完全等价的 `gin (from_text gin_trgm_ops)` 索引（白占磁盘并使每次邮件入库承受双倍三元组拆解写放大），且批量导入/迁移后缺乏统计信息收敛导致 `messages` 亦出现 `34,131` 次 `seq_scan`。
- 根因（Schema 索引契约失配 + 用任务历史表充当同步水位元数据）：
    1. **领域职责错位**：「某收件箱上次尝试同步何时结束」本质属于文件夹同步检查点（`SyncCheckpoint`）的持久状态属性，但 `schedule_periodic_inbox_sync` 却通过扫描瞬态队列历史行 `worker_jobs` 来反推上次结束时间，一旦失去终态索引即退化为 `O(账户数 × 7天任务总数)` 全表扫描。
    2. **瞬态队列表被当作 7 天审计归档表**：`worker_jobs`（`done`）与已消费发布的 `outbox` 仅用于短时排障与 SSE 断线重放（SSE 游标落后超窗口本就走快照重同步 `resync`），保留 7 天使高频更新/删除表的活跃页集远超必要规模。
    3. **历史迁移演进遗留重复 GIN 索引**：字段重命名/迁移过程中新增 `ix_message_search_from_text_trgm` 时未删除同列旧索引 `ix_message_search_from_trgm`。
- 铁律重构方向（架构至上、零兼容负担）：
    1. **将同步尝试时间戳收口回检查点权威模型**：在 `SyncCheckpoint`（或文件夹同步状态表）直接记录最近一次 delta 同步完成/失败时间戳，`schedule_periodic_inbox_sync` 直接基于轻量检查点表判定是否到期，彻底移除对 `worker_jobs` 终态行的按 `dedupe_key` 回查。
    2. **补齐终态清理部分索引并大幅缩短瞬态队列保留期**：为 `worker_jobs` 新增面向清理的部分索引 `(updated_at) WHERE status IN ('done', 'failed')`；将已完成 `worker_jobs` 与已发布 `outbox` 的默认保留窗口从 `7d` 收敛至紧凑窗口（如 `6h–24h`，支持环境变量覆盖），使两张高频热表常驻体积从 `168 MB` 压回 MB 级。
    3. **清理冗余全文索引并校准表统计信息**：通过 Alembic 迁移删除冗余的 `ix_message_search_from_trgm`，核查 `message_search` 其余 `pg_trgm` / `tsvector` 索引最小完备集，并在迁移与大批量同步收尾保障统计信息及时更新。
- 测试缺口：
    - `schedule_periodic_inbox_sync` 与 `prune_completed_jobs` 现有单测仅在小样本（数行数据）下验证功能正确性，缺少针对 PostgreSQL `EXPLAIN` 索引命中契约（禁止对 `worker_jobs` 产生 `Seq Scan`）的回归测试。
    - Schema 契约测试未对同表同列同操作符类的重复索引做唯一性断言。
- 线索：
    - 生产 `kkmail-mail-core-pg` 实测查询（2026-11-28）：
        - `pg_stat_database`：`xact_commit=924433, xact_rollback=232762, blks_read=3391027, blks_hit=584219727, tup_returned=7664397699, tup_fetched=210525976`；
        - `pg_stat_user_tables`：`worker_jobs (n_live_tup=79396, n_dead_tup=8664, seq_scan=84199, total_size=96 MB)`，`outbox (n_live_tup=86336, n_dead_tup=16251, total_size=72 MB)`，`message_search (total_size=208 MB, n_live_tup=68, 实际 count(*)=22095)`；
        - `\d+ message_search` 与 `pg_stat_user_indexes` 确认 `ix_message_search_from_trgm` (`idx_scan=0`, `7840 kB`) 与 `ix_message_search_from_text_trgm` (`idx_scan=12`, `7840 kB`) 完全同构。
- 处理：t094；resolution=transferred；reason=2026-11-28 核实生产索引/水位双源/保留期事实仍成立，按开发铁律以删除反推路径方案转交 t094
