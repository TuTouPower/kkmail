# Task spec

## 背景

生产单机库仅存 22,095 封邮件，空闲期 PG 持续占 ~3.65% CPU、累计网络发送 10.3 GB、磁盘写 4.55 GB，每 5 分钟触发 13–41s 的 WAL Checkpoint；`pg_stat_database.tup_returned = 7,664,397,699`，`worker_jobs`（79,396 行/96 MB，其中 79,218 行 `done`）发生 84,199 次 `seq_scan`，`outbox` 囤积 86,339 行/72 MB，`message_search` 上并存两个同构 `from_text` GIN 三元组索引（源 p102，2026-11-28 实测）。

核实结论（2026-11-28）：症状是 seq_scan，病根是同一事实存在两个权威源。`SyncCheckpoint` 模型及 `updated_at` 已存在（`models.py:304-320`），`schedule_periodic_inbox_sync` 已读取 checkpoint（`worker/main.py:250-252`），却又叠加扫描 `worker_jobs` 终态行并用 `max()` 取更大值兜底（`worker/main.py:253-264`）——把「上次同步结束时间」这一状态属性寄生在瞬态任务队列里。重复 GIN 索引实际残留在 baseline 迁移（`20261107_0001_unified_baseline.py:469` 创建 `ix_message_search_from_trgm`，471–477 创建 `ix_message_search_from_text_trgm`），ORM 模型（`models.py:504`）仅保留后者。7 天保留仍在（`worker/main.py:139,145`、`realtime/outbox.py:17`）。

按开发铁律（架构至上、拒绝妥协、零兼容性负担）：补终态索引等于固化错误查询，缩短保留期加 env 覆盖属于兼容心理。必须删除反推路径、让 `SyncCheckpoint` 成为唯一水位权威，将队列回归纯瞬态语义，并一次性洗净索引残留。

## 契约区

### 范围

- **同步水位单一权威化**：
    - 删除 `schedule_periodic_inbox_sync`（`src/mail_core/worker/main.py:253-264`）中从 `worker_jobs` 终态行按 `dedupe_key` 反推 `last_synced_at` 的整段查询与 `max()` 兜底；到期判定只读 `SyncCheckpoint`。
    - 在 `SyncCheckpoint` 增加最近一次 delta 同步完成/失败时间戳列，在 delta 同步落库事务内原子更新（成功与失败均写），使检查点自带调度所需的水位事实，不再依赖任务历史。
- **瞬态队列生命周期契约化**：
    - 将已完成 `worker_jobs` 与已发布 `outbox` 的保留从 7 天收敛为消费即删或固定极短 TTL（以代码契约表达，不提供产品级 env 保留开关）；SSE 游标落后超过窗口一律走 `resync` 快照重同步。
    - 移除 `worker/main.py:139,145` 与 `realtime/outbox.py:17` 的 7 天保留常量。
- **索引契约洗净与统计收敛**：
    - 新增面向清理的部分索引 `(updated_at) WHERE status IN ('done','failed')`，仅服务 `prune_completed_jobs`（`src/mail_core/sync/jobs.py:720-743`），禁止用于水位反推。
    - 通过 Alembic 迁移 DROP `ix_message_search_from_trgm`，保证 `message_search.from_text` 在 `gin_trgm_ops` 下仅存唯一 GIN 索引；核查其余 `pg_trgm`/`tsvector` 索引最小完备集。
    - 迁移收尾及批量同步收尾内建 `ANALYZE`，修复 `n_live_tup` 与真实行数偏差（实测 68 对 22,095）。
- **契约测试补齐**：新增 `EXPLAIN` 索引命中回归（禁止对 `worker_jobs` 产生 `Seq Scan`）、水位来源唯一性测试、schema 同列同操作符类重复索引唯一性断言。

### 非范围

- 不新增「反推水位」用的 `(dedupe_key, updated_at)` 终态索引。
- 不改 `outbox` 的 SSE 发布/重放协议与 `resync` 快照机制。
- 不改 `worker_jobs` 的 claim/dedupe 活跃态索引、任务执行血缘与并发执行模型。
- 不执行生产环境部署或线上数据操作。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [ ] AC-001：`schedule_periodic_inbox_sync` 的到期判定仅读取 `SyncCheckpoint`，源码与测试中不存在从 `worker_jobs` 终态行反推同步水位的查询；真实 PostgreSQL 上执行该函数时 `EXPLAIN` 对 `worker_jobs` 零 `Seq Scan`。
- [ ] AC-002：`SyncCheckpoint` 具备最近一次 delta 同步完成/失败时间戳列，且在成功与失败两条路径的落库事务内均被原子更新；到期判定结果与该时间戳严格一致，跨进程重启后保持一致。
- [ ] AC-003：`worker_jobs` 终态行与 `outbox` 已发布行的保留窗口为消费即删或固定极短 TTL，源码中不存在 7 天保留常量；SSE 游标落后超过保留窗口时客户端走 `resync` 快照且不丢邮件。
- [ ] AC-004：Alembic 迁移后 `message_search.from_text` 在 `gin_trgm_ops` 下仅存在一个 GIN 索引；迁移支持 `upgrade head -> downgrade -> upgrade head` 循环且 ORM schema 校验零漂移。
- [ ] AC-005：`prune_completed_jobs` 查询命中新增部分索引（`EXPLAIN` 无 `Seq Scan`），且该索引不被任何水位判定查询引用。
- [ ] AC-006：schema 契约测试对「同表同列同操作符类重复索引」给出唯一性断言并全绿；迁移与批量同步收尾后 `message_search`、`messages`、`message_bodies` 统计信息与真实行数一致；项目全量门禁通过。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试：AC-001/005 通过真实 PostgreSQL `EXPLAIN` 与源码扫描验证；AC-002 通过 delta 同步成功/失败集成测试验证；AC-003 通过保留期单元测试与 SSE 落后游标的 `resync` 集成测试验证；AC-004 通过迁移升降级循环与 schema 漂移校验验证；AC-006 通过契约测试、统计信息查询与全量门禁命令验证。

## 上下文区

- 关联 spec：docs/specs/mail_sync_and_storage.md
- 来源：p102（2026-11-28 核实并转办；生产实测 84,199 次 `worker_jobs` 全表扫描、两个同构 GIN 索引、7 天保留；核实修正：重复索引残留在 baseline 迁移而非 ORM 模型，水位双源在 `worker/main.py:250-264`）

### 有意不测

- 生产 76.6 亿行累计扫描规模：不在 CI 复现绝对数值，改用等价规模种子数据在真实 PostgreSQL 上执行 `EXPLAIN` 验证索引命中契约。

### 测试策略

- 水位唯一性：源码级扫描禁止 `WorkerJob` 出现在调度到期判定查询中；集成测试构造 checkpoint 与终态 job 时间不一致数据，断言调度只服从 checkpoint 时间戳。
- 索引命中：真实 PostgreSQL 构造万行级 `worker_jobs` 终态数据，对调度判定与 `prune_completed_jobs` 执行 `EXPLAIN`，断言无 `Seq Scan`。
- 迁移与统计：验证新增 revision 升降级循环、重复 GIN 索引唯一性断言、批量导入后 `ANALYZE` 使 `n_live_tup` 与 `count(*)` 一致。
- 队列生命周期：验证终态行与已发布行按新窗口回收，SSE 落后游标触发 `resync` 且邮件完整。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无。水位双源、索引残留位置、保留期常量与统计偏差均已在 2026-11-28 生产库与源码核实。

### 风险与回退

- 风险：删除水位反推后若 checkpoint 时间戳更新存在漏写路径，调度会偏保守（重复同步）而非漏同步，须通过成功/失败双路径测试封死；DROP 索引迁移若遇并发入库需评估锁竞争；保留期缩短后 SSE 落后客户端触发 `resync`，须验证不丢邮件。
- 回退：新增 Alembic revision 提供可逆 `downgrade` 重建索引；代码侧通过 revert 实现 commit 回退；生产部署前依赖标准封存备份。

### 依赖与约束

- 依赖：无前置未合并 task，基于当前 `main`（含 t093）立项；`review_level: full`。
- 约束：遵循开发铁律删除水位反推路径与 7 天保留，不补反推索引、不留双源兼容层；迁移走 `.repo_template`/项目单一入口，TDD 先行；不写生产数据。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：更新同步水位权威模型与瞬态队列生命周期边界描述。
- `docs/blueprint/domain.md`：更新 `SyncCheckpoint` 的水位时间戳语义。
- `docs/blueprint/conventions.md`：确立「状态属检查点、过程属队列」的职责边界与索引唯一性契约。
- `docs/blueprint/decisions/20261128_watermark_authority_and_queue_retention.md`：记录删除反推路径与瞬态队列保留契约的架构决策。
- `docs/blueprint/testing.md`：记录新增 `EXPLAIN` 索引命中与重复索引唯一性断言门禁。

______________________________________________________________________

- 关联 spec 登记：实施收尾时在 `docs/specs/mail_sync_and_storage.md` front matter `tasks` 清单追加 `t094`。
