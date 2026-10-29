# Task spec

## 背景

p063 实测：用户点开新邮件后，正文已由 Worker 归档完成，但阅读器仍停在「正文同步任务已排队」，总耗时近 2 分钟。其中两段延迟与「唤醒」直接相关：

1. Outbox 推送漏唤醒：`src/mail_core/blobs/archive.py` 写入 `archive.progress` / `archive.paused_quota` 等 `OutboxEvent` 后未调用 `try_notify_outbox`，API 进程的 LISTEN 线程收不到 NOTIFY，只能等 `idle_timeout_s=30` 超时兜底派发（实测事件 20:25:01 落库、20:25:25 才推给前端）。同类漏调遍布 `sync/delta.py`、`sync/reconcile.py`、`sync/engine.py`、`mail/application/accounts.py`、`mail/application/remote_ops.py`、`sync/execution.py`；全仓仅 `mutations.py`、`remote_push.py`、`metadata.py` 与 Worker 的 wake handler 显式调用。逐点补调用无法防止新增写入点再次遗漏。
2. 任务入队不唤醒 Worker（2026-10-30 核实新增，p063 未记录）：`enqueue_job` 只写库；Worker 主循环在空闲时把轮询间隔从 `worker_poll_s=2` 指数退避到 `worker_max_idle_s=10`，期间只响应停止信号。用户点击「同步正文」入队的 priority=10 任务在 Worker 空闲时最多要干等约 10 秒才被认领。

参考实现（2026-10-30 源码核查）：Mailspring 用户任务入队后通过 `idleInterrupt` 立即打断前台 worker；Delta Chat 在入队标已读后调用 `interrupt_inbox` 唤醒收件箱循环。两者均为「入队即唤醒执行端」。

## 契约区

### 范围

- 统一 Outbox 唤醒：任何经应用 session 写入 `OutboxEvent` 并提交的事务，在提交时向 `mail_core_outbox` 通道发出一次 NOTIFY；不依赖写入点手工调用。现有分散的 `try_notify_outbox` 显式调用随之移除。
- 统一任务唤醒：任何经应用 session 使某个 `WorkerJob` 立即可执行（新增 `run_after` 不晚于当前时刻的任务，或去重合并把 PENDING 任务的 `run_after` 提前到当前时刻）并提交的事务，在提交时向新的任务通道发出一次 NOTIFY；只产生未来 `run_after` 的写入不唤醒。
- Worker 侧监听任务通道：收到通知后立即结束当前空闲等待并进入下一轮认领；监听连接断开时自动重连，断连期间 Worker 退化为现有轮询行为。
- 同一事务内多次写入只发一次对应通道的 NOTIFY；非 PostgreSQL 方言下唤醒逻辑为空操作，不影响事务提交。
- NOTIFY 失败不得导致业务事务失败，沿用现有 `pg_notify` 失败节流告警口径。

### 非范围

- 不改 API 侧 LISTEN 线程的 30 秒超时兜底与派发逻辑。
- 不改 Worker 的执行模型（串行改并发属 t063）与远程写回批量化（属 t064）。
- 不改前端；不加前端轮询兜底。
- 不处理既有无生产入队方的 `OUTBOX_DISPATCH_WAKE` job type（存量路径，不在本 task 改动）。
- 不调整任何任务优先级数值。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：正文归档完成（目标邮件 `archive.progress` 事件写入并提交）后，订阅该账号 SSE 的客户端在 2 秒内收到该事件，不再依赖 30 秒超时兜底。
- [ ] AC-002：在 `archive.py`、`delta.py`、`reconcile.py`、`engine.py`、`accounts.py`、`remote_ops.py`、`execution.py` 任一路径写入 `OutboxEvent` 并提交后，`mail_core_outbox` 通道收到 NOTIFY；新增的写入点无需额外调用即具备同样行为。
- [ ] AC-003：同一事务写入多条 `OutboxEvent` 时，提交后该通道只收到一次 NOTIFY；事务回滚时不发出 NOTIFY。
- [ ] AC-004：Worker 空闲且轮询间隔已退避到上限时，新任务入队提交后 1 秒内被认领执行。
- [ ] AC-005：去重合并把已存在 PENDING 任务的 `run_after` 提前到当前时刻时，同样触发 Worker 唤醒；只新增或改写未来 `run_after` 任务（如延迟重试、退避重排）的事务不触发任务通道 NOTIFY。
- [ ] AC-006：Worker 的任务通道监听连接断开后自动重连；断连期间新任务仍按现有轮询间隔被认领，Worker 主循环不中断。
- [ ] AC-007：NOTIFY 执行失败时，业务事务照常提交，失败按现有节流口径记录告警，不抛给调用方。
- [ ] AC-008：使用非 PostgreSQL 方言的 session 提交含 `OutboxEvent` / `WorkerJob` 的事务时，不执行 NOTIFY 且提交成功。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试

## 上下文区

- 来源：p063（2026-10-30 核实：根因 1 成立，`archive.py` 7 处 `OutboxEvent` 写入均无 NOTIFY；另核实 Worker 空闲退避最长 10 秒且入队不唤醒，为 p063 未记录的延迟源）

### 有意不测

- 真实网络抖动下 LISTEN 连接的长时间稳定性：以强制断开监听连接的集成测试覆盖重连语义，长期稳定性由上线观测覆盖。

### 测试策略

- PostgreSQL 集成测试：独立 LISTEN 连接订阅两条通道，分别验证各写入路径提交后收到 NOTIFY、同事务单次、回滚不发、失败不阻断提交。
- Worker 测试：将轮询退避推到上限后入队任务，断言认领时延；强制关闭监听连接后验证重连与轮询降级。
- 端到端：沿用 `.scratch/repro_body_sync_queue_delay.py` 场景改造为回归测试，断言归档事件推送时延。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：集中挂载的 session 事件遗漏某种写入方式（如 Core `insert()` 绕过 ORM），导致个别路径仍不唤醒；唤醒过于频繁造成 Worker 空转认领。
- 防御：AC-002 逐路径断言；Worker 唤醒只缩短空闲等待，认领仍走既有 `SKIP LOCKED` 查询，空唤醒成本为一次空查询。
- 回退：git revert 本 task commit；API 30 秒超时兜底与 Worker 轮询仍在，回退后行为与现状一致。

### 依赖与约束

- 应用 session 统一由 `src/mail_core/db/session.py` 的 sessionmaker 创建，唤醒逻辑挂载于此。
- 与 t063 同改 `src/mail_core/worker/main.py`，t063 依赖本 task 先合入。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：Outbox 事件分发章节补记「提交即 NOTIFY 由 session 统一保证」；Worker 章节补记任务通道唤醒与轮询降级关系。
- `docs/specs/mail_sync_and_storage.md`：累积 spec 补记 Outbox 推送与任务认领的唤醒契约。
