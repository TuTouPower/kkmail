# Task spec

## 背景

p025 复现 Graph partial delta 把缺省字段覆盖为空，Gmail metadata projection 缺 snippet 也清空既有摘要；不完整 hydration 被误当完整记录。

## 契约区

### 范围

- 区分 provider 未返回字段与显式空值；修复 Graph partial content 与 Gmail metadata/history hydration，经真实 upsert 保留原字段。

### 非范围

- 不批量重写历史邮件，不删除运行容器数据，不改服务商原始摘要，不执行生产部署。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [x] AC-001：Graph 部分更新只改变响应明确包含字段，subject/from/snippet/地址组等未返回字段保持原值。
- [x] AC-002：Graph 明确返回空 subject、空 snippet 或空收件人数组时，能够清除对应旧值，不因真假判断丢掉清空操作。
- [x] AC-003：Gmail metadata projection 未返回 snippet 时保留已存服务商摘要；初次无摘要保持空，不生成摘要写回。
- [x] AC-004：Gmail history upsert 必须成功 hydrate；缺 id、ID 不匹配、只有 id、GET 失败均不得作为完整邮件成功应用或推进游标。
- [x] AC-005：常规完整邮件仍正确同步，状态未知与本地未收敛写回意图保护不回退。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。

## 上下文区

- 来源：p025（2026-10-23；根因与官方文档链接见原 pending）；p024 仅共享未知值原则，状态持久化独立由 t041 交付。

### 有意不测

- 真实 OAuth 邮箱：不依赖用户凭据；通过服务商响应契约 fixture 与真实 PostgreSQL 验证落库行为。

### 测试策略

- Graph 只含 id+subject/from 的变更与显式空值经真实 PG upsert；Gmail metadata projection 缺省 snippet；缺 id/id-only/mismatch 与 GET 异常不推进成功页。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- Graph updated resource 只保证 id 与更新字段；Gmail metadata 为 ID、labels、headers，History 常只有 id/threadId；来源见 p025 官方 API 文档与本仓契约 fixture。

### 风险与回退

- 风险：调用方将 null 误当 false 或把部分响应当完整快照；测试覆盖首次插入、已有数据与显示分支。
- 回退：保留历史事实值；迁移降级遇未知值拒绝造假，可回滚应用并从部署前备份恢复数据库。

### 依赖与约束

- 用户明确要求直接在 main 修复；登记引用不冒充工具链 worktree 执行状态。

### Finalization 时更新的 blueprint

- `docs/blueprint/conventions.md`：未知邮件状态与服务商字段缺省语义。
