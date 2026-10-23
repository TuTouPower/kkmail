# Task spec

## 背景

p036 的 PostgreSQL 复现确认：delta 或 metadata 同步在内部提交后继任务后返回错误状态，Worker 又对原 claimed 任务调用 `fail_job`，造成一次故障生成两条待处理任务。

## 契约区

### 范围

- 同步层已成功创建后继重试任务时，返回明确标记；Worker 据此完成原任务，不再重复创建 Worker 重试。
- 覆盖 delta 的 provider error、lease busy、cursor invalid，以及 metadata 的 lease busy、cursor invalid。
- provider error 仍将账号同步状态标记为 failed，并保留脱敏错误摘要。

### 非范围

- 不改变各同步路径的重试延迟、优先级、后继任务类型和服务商错误脱敏。
- 不调整没有内部重排队结果的 Worker 失败与 backoff 语义。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：五种已核实内部重排队路径均返回重试已排队标记，且保留原有后继任务类型与延迟语义。
- [ ] AC-002：Worker 收到重试已排队标记后完成原 claimed 任务；数据库中只留同步层创建的一条 pending 后继任务，不再通过 `fail_job` 重试原任务。
- [ ] AC-003：provider error 路径仍将账号标记为 failed 并写入脱敏错误摘要；没有内部后继任务的普通错误仍走原 `fail_job` 路径。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。

## 上下文区

- 来源：p036（2026-10-24；隔离 PostgreSQL 复现确认 delta provider error 双排队；核实同类 delta/metadata lease busy 与 cursor invalid 路径）。

### 有意不测

- 真实 OAuth/IMAP 服务商：同步重试由 PostgreSQL 队列状态决定，使用内存 provider 注入确定性错误，不依赖用户账号或外部网络。

### 测试策略

- PostgreSQL 集成测试经真实 `handle_job` 与同步入口验证重试标记和最终队列数量；Worker 结果单元测试验证已排队分支完成原任务、普通错误仍调用 `fail_job`。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无；队列状态和重试语义由本仓 PostgreSQL 实现与集成测试核实。

### 风险与回退

- 风险：漏标内部重排队结果会保留重复重试；误标则会让没有后继任务的失败被吞掉。覆盖每个内部 enqueue 返回点，并验证 Worker 端只对明确标记生效。
- 回退：回滚 Worker 对标记的处理及同步层标记字段，恢复原重试逻辑；无需数据迁移。

### 依赖与约束

- 用户明确要求直接在 main 修复；不创建或伪造 task worktree/attempt 状态。

### Finalization 时更新的 blueprint

- `docs/blueprint/conventions.md`：补充同步层已提交重试任务后由 Worker 完成原任务的队列所有权约定。
