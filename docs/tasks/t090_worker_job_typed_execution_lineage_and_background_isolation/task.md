# Task spec

## 背景

2026-11-25 生产诊断与 `.scratch/repro_gmail_retry_cascade.py` 复现发现：虽然 `conventions.md` 约定「后台静默同步故障不外溢到账号连接健康态」，但 `WorkerJob` 表缺乏表达执行来源/后台属性的一等公民字段，全链路依赖自由 JSON `payload` 与 `resolve_sync_context` 猜谜（缺省判为前台），且 `sync_context_payload(request_id, ...)` 在 `request_id=None` 时直接丢弃 `background` 标记。导致 `patrol.py`、`idle_watcher.py` 以及 `worker/main.py` 周期同步触发的重入队/续跑全部在失败时被误判为前台同步，集体触发 `record_connectivity_failure` 把所有 Gmail 账号染为 `degraded` / `unreachable`。

按开发铁律，放弃在零散调用点手工补写 `"background": True` 的脆弱补丁，直接将任务执行血缘提升为 `WorkerJob` Schema 一等公民，强制所有入队调用显式声明执行域，并在重排、续批与后继任务派生中原生自动继承。

## 契约区

### 范围

- 数据库模型与迁移：`WorkerJob` 新增非空执行域/后台标记一等公民列（如 `is_background: bool NOT NULL` 或强类型 `execution_origin`），新增 Alembic 迁移（衔接 `20261124_0005`）并更新 `db/baseline.py` 的 `CURRENT_HEAD_REVISION` 与校验基线。
- 强类型入队契约：`enqueue_job` 强制要求显式传入执行上下文/后台标记（消除无参默认悄悄变成前台的陷阱）；清理 `sync_context_payload` 仅靠 `request_id` 猜测的旧 shim，并同步更新或退役固化该缺陷的旧测试（如 `test_sync_context_payload_never_emits_background_marker`，按 TDD 原则写明理由，不就地改期待值）。
- 全链路原位覆盖与自动继承：
    - 显式前台入口：`sync_requests.py`（非 `background` 请求）、`accounts/service.py`（用户显式新增账号首扫，或按设计明确归属）、`message_details.py`（按需正文同步）等显式传入对应来源；
    - 显式后台入口：`worker/main.py` 周期收件箱轮询、`patrol.py` 全夹巡检入队 delta、`idle_watcher.py` 建连补偿与 IDLE 唤醒入队 delta、`blobs/archive.py` 后台批量归档、`sync_requests.py` `background=True` 后台子请求、`remote_push.py` 后台目录发现兜底（统一显式声明）；
    - 自动继承：`complete_job` 派生 successor、`reschedule_job` 重排、`delta.py`（`LeaseBusy` / `RateLimitedError` / `CAPACITY_ERRORS` / `FencingMismatch` / `!exhausted`）、`engine.py`（`sync_account_folders` 与 `sync_folder_metadata` 及其全部子任务与重建分支）与 `reconcile.py` 自动从当前任务继承执行血缘，不再丢失 `background` 身份。
- `handlers.py` 与 `resolve_sync_context` 直接基于 `WorkerJob` 一等公民列（结合 `SyncRequest.scope` 一致性约束）裁决健康状态隔离。
- 更新相关 blueprint 与 spec `mail_sync_and_storage.md`。

### 非范围

- 不修改出站代理、双栈建连与 `ConnectionPermit` 连接槽策略（`t089` 范围）。
- 不重构 `StructuredFailure` 与 `redact()` 文本脱敏边界（`t091` 范围）。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [x] AC-001：`WorkerJob` 具有持久化的非空执行血缘字段；新增 Alembic 迁移在真实 PostgreSQL 上通过 `upgrade head` → `downgrade` → `upgrade head` 双向循环与 ORM schema 0 drift 校验。
- [x] AC-002：所有任务入队入口均显式指定前台或后台执行血缘（省略则立即在入队接口被显式拒绝），不存在「缺省静默变前台」的路径。
- [x] AC-003：`worker/main.py` 周期轮询、`patrol.py` 巡检、`idle_watcher.py` 建连补偿/IDLE 唤醒入队的同步任务及其任意重排/续跑/后继任务（含 `LeaseBusy`、`RateLimitedError`、`CAPACITY_ERRORS`、`FencingMismatch`、多页未穷尽与 `complete_job` 后继）全部保留后台血缘，在发生传输失败时绝不把账号 `connectivity_state` 置为 `degraded` 或 `unreachable`。
- [x] AC-004：用户显式触发的前台同步任务（及由其派生的同请求子任务与重试）发生传输失败仍按既有连续窗口熔断规则更新 `connectivity_state`，但认证错误（`AUTH`）无论前台后台均按契约使 `credential_state` 失效。
- [x] AC-005：全量真实 PostgreSQL 测试套件（`scripts/run-mail-core-tests.sh run`，含 `test_migration_validation` 与 `test_migrate_to_unified_baseline`）及 `test_cmd` 全部通过。
- [x] AC-006：同步更新 `docs/specs/mail_sync_and_storage.md`（登记 `t090`）及对应 blueprint 文档。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试：AC-001 由真实 PG 迁移升降级与 `compare_metadata` 验证；AC-002/003/004 由入队契约单测与真实 PG Worker/巡检/IDLE/续跑集成测试验证；AC-005/006 由门禁命令验证。

## 上下文区

- 关联 spec：docs/specs/mail_sync_and_storage.md
- 来源：p095（2026-11-25 `.scratch/repro_gmail_retry_cascade.py` 复现确认 `patrol` / `idle_watcher` / `sync_context_payload(None, ...)` 均丢失 `background` 标记）

### 有意不测

- 生产环境存量实时队列：通过 Alembic 迁移对存量 `worker_jobs` 行安全填充与独立 PG 迁移往返验证替代。

### 测试策略

- 迁移门禁：`test_migration_validation` 与 `test_migrate_to_unified_baseline` 验证新 revision 可逆循环、存量数据兼容性及 `CURRENT_HEAD_REVISION` 对齐。
- 后台隔离与继承矩阵：真实 PG 分别驱动周期轮询、全夹巡检、IDLE 补偿/唤醒、以及上述任务触发多页续跑/限流重排/`LeaseBusy`/后继派生后遭遇传输错误，断言 `connectivity_state` 保持 `connected`；对照验证显式前台请求传输失败仍正常触发 `degraded`/`unreachable`。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：`enqueue_job` 强制显式执行域后，全仓若存在遗漏调用点或测试夹具未更新会导致运行期/测试期失败；数据库迁移需正确处理生产库已有 `worker_jobs` 行并保持 `downgrade` 可逆。
- 回退：支持通过 Alembic `downgrade` 回到前一版本并按 commit 隔离回退；`task.py` 运行全量 PG 测试可在合入前发现所有未显式声明的调用点与测试夹具。

### 依赖与约束

- 依赖 `t089`（作为重构链第二棒串行集成，保证合并拓扑无冲突）；`review_level: full`。
- 约束：遵守 `docs/blueprint/testing.md` 迁移单一入口与全量 `compare_metadata` 0 drift 契约；旧测试语义失效时新建/退役并写明理由，禁止就地改断言期待。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：更新 `WorkerJob` 一等公民执行血缘与续跑继承架构描述。
- `docs/blueprint/conventions.md`：更新后台静默同步强制显式血缘与防外溢契约。
- `docs/blueprint/testing.md`：更新线性迁移链说明（新增 revision）与后台继承门禁。
