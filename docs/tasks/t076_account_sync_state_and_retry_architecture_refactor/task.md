# Task spec

## 背景

当前系统将凭据认证态、网络连接态与调度执行态三维正交状态强行坍缩在单一枚举 `Account.sync_status`（`idle` / `running` / `paused` / `failed` / `auth_failed`）中。当遇到本地代理瞬断、网络不可达（`OSError code=101`）或网络超时等传输层异常时，系统粗粒度将账号全局状态提升为 `failed`，并在前端展示误导性的硬编码文案「同步失败，请检查账户设置」。此外，`delta.py` 等同步模块私自通过重新创建新任务并谎报原任务 `done` 的方式来实现重试，绕过了 Worker 框架的重试代数、失败计数与指数退避契约，且依赖脆弱的扫表自愈逻辑（`_recover_account_sync_status`）掩盖缺陷。

依据开发铁律（架构至上、拒绝妥协、零兼容负担），彻底废除单值 `sync_status`，正交解耦凭据态、网络态与活动态，将任务重试统一交由 Worker 调度器管理，并彻底重构前端状态感知契约。

## 契约区

### 范围

- **模型与数据表物理解耦**：
    - 彻底移除 `Account.sync_status` 字段。
    - 新增 `credential_state`（VARCHAR(32)，值域：`valid` / `invalid`，默认 `valid`）。
    - 新增 `connectivity_state`（VARCHAR(32)，值域：`connected` / `degraded` / `unreachable`，默认 `connected`）。
    - 新增 `sync_activity`（VARCHAR(32)，值域：`idle` / `syncing`，默认 `idle`）。
    - 新增 Alembic 迁移脚本，安全完成历史数据迁移与字段替换。
- **任务队列重试回归 Worker 框架**：
    - 移除 `delta.py`、`engine.py` 内部手动 `enqueue_job(run_after=now+15s)` 并把原任务谎报为 `done` 的私有重试逻辑。
    - 异常统一交由 Worker 调度器通过 `reschedule_job` 维护重试代数 `attempts`、失败计数 `failure_attempts` 与指数退避调度（Exponential Backoff with Jitter）。
- **调度上下文与故障域隔离**：
    - `src/mail_core/worker/main.py` 中 `schedule_periodic_inbox_sync` 入队任务显式注入 `{"background": True}` 上下文。
    - `resolve_sync_context` 识别该上下文，确保后台周期性轮询与静默同步的偶发异常不外溢污染账号状态。
- **确定性连接健康度状态机与熔断机制**：
    - 单次网络异常将 `connectivity_state` 标记为 `degraded`（退避重试中）。
    - 引入熔断规则：连续失败达 5 次且时间跨度超过 5 分钟窗口时，升级为 `unreachable`。
    - 远端邮件服务商任意一次网络握手/请求成功，由事件确定性重置计数器并将 `connectivity_state` 恢复为 `connected`；彻底删除 `_recover_account_sync_status` 扫表补丁。
- **认证失效精准判定**：
    - 仅在远端服务商确凿返回 401、`AUTHENTICATIONFAILED` 或 OAuth `invalid_grant` 且不可刷新时，将 `credential_state` 置为 `invalid` 并置 `sync_enabled=False`。
    - 任何非认证类的传输层错误严禁篡改 `credential_state`。
- **API 契约升级与前端呈现重构**：
    - `AccountOut` 移除旧 `sync_status`，结构化输出 `credential_state`、`connectivity_state`、`sync_activity` 及链路诊断信息。
    - 同步更新 OpenAPI 规范（`schemas/openapi.json`）与前端生成类型（`src/frontend/src/api/schema.ts`）。
    - 前端 `Sidebar.tsx` 与 `SettingsModal.tsx` 移除硬编码文案「同步失败，请检查账户设置」，根据结构化状态分别展示凭据失效、网络重试与正常同步态。

### 非范围

- 不改动邮件正文解析与分块加密存储算法。
- 不引入外部第三方分布式消息队列（如 Redis/RabbitMQ），保持以 PostgreSQL SKIP LOCKED 与 Notify/Listen 为底座的高性能纯净架构。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [ ] AC-001：`Account` 模型与 PostgreSQL `accounts` 表结构移除 `sync_status`，新增 `credential_state`（`valid` / `invalid`，默认 `valid`）、`connectivity_state`（`connected` / `degraded` / `unreachable`，默认 `connected`）和 `sync_activity`（`idle` / `syncing`，默认 `idle`）字段，并提供完整的 Alembic 迁移脚本。
- [ ] AC-002：移除 `delta.py` 中捕获 provider 异常后自行入队新任务并返回伪 `done` 的私有重试逻辑；单次网络异常（如 `OSError`、超时）直接交由 Worker 调度器调用带退避参数的 `reschedule_job`，保留原始任务 ID 并递增 `attempts` 与 `failure_attempts`。
- [ ] AC-003：`worker/main.py` 的 `schedule_periodic_inbox_sync` 为所有周期性增量任务显式注入 `{"background": True}` 上下文；`resolve_sync_context` 识别该标记并返回 `is_background=True`，使周期同步的偶发网络抖动不外溢污染账号状态。
- [ ] AC-004：实现确定性连接健康度状态机，单次网络异常使 `connectivity_state` 转为 `degraded`，只有在连续失败达 5 次阈值且超过 5 分钟窗口时才转为 `unreachable`；任一任务建连成功即由成功事件将 `connectivity_state` 立即恢复为 `connected`，彻底废除 `_recover_account_sync_status` 扫表擦除逻辑。
- [ ] AC-005：当邮件服务商返回 401、`AUTHENTICATIONFAILED` 或 OAuth `invalid_grant` 且不可刷新时，准确将 `credential_state` 标记为 `invalid` 并置 `sync_enabled=False`；非认证异常（网络中断、超时、限流）严禁将 `credential_state` 修改为 `invalid`。
- [ ] AC-006：`GET /api/accounts` 返回包含 `credential_state`、`connectivity_state`、`sync_activity` 和 `last_connectivity_error` 的 `AccountOut` 结构，移除旧 `sync_status`，OpenAPI 契约及前端类型同步对齐。
- [ ] AC-007：前端 `Sidebar.tsx` 与 `SettingsModal.tsx` 移除静态硬编码文案「同步失败，请检查账户设置」；仅在 `credential_state === 'invalid'` 时渲染红标与凭据失效指引，在 `connectivity_state === 'degraded' | 'unreachable'` 时渲染网络重试或不可达状态，后台静默同步网络异常不触发侧栏全局报警。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。

## 上下文区

- 关联 spec：docs/specs/account_connection.md
- 来源：p075（2026-11-12 核实根因：`sync_status` 概念混淆、自造重试绕过 Worker 调度、周期同步缺少 background 标记致瞬时网络抖动被粗粒度提升为全局失败）

### 有意不测

- 无：所有模型字段迁移、Worker 调度重试、状态流转与前端界面分支均在自动化测试中覆盖

### 测试策略

- 后端模型与迁移测试：验证 Alembic 迁移脚本正向应用与回滚，确保现有数据安全映射到新字段。
- Worker 重试与调度集成测试：模拟 provider 抛出 `OSError code=101`、连接超时与 401 认证异常，断言 `WorkerJob` 的重试退避行为与 `Account` 状态字段的确定性转换。
- API 契约与序列化测试：断言 `GET /api/accounts` 响应体结构与 OpenAPI 模式定义一致。
- 前端组件测试（React Testing Library）：覆盖 `Sidebar.tsx` 与 `SettingsModal.tsx` 在三维状态各组合（正常、网络重试中、网络不可达、凭据失效）下的视觉组件渲染与文案准确性。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

无

### 风险与回退

- 风险：数据库字段破坏性变更需同步更新全部引用点（后端查询、API、前端组件）。
- 回退：通过 Alembic 降级迁移脚本回退数据库表结构，恢复旧有字段。

### 依赖与约束

- 严格遵循开发铁律，零兼容性负担，直接执行破坏性重构，完全不保留单值 `sync_status` 兼容层。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：更新账号状态模型、连接熔断器与 Worker 重试调度架构。
- `docs/blueprint/conventions.md`：废除单一 `sync_status` 约定，增加三维正交状态与错误分级隔离规范。
