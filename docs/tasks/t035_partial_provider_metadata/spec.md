# Task spec

## 背景

Graph delta 的局部更新把未返回状态解析成 false；IMAP 与 Gmail 元数据把附件状态未知表达成 false。后续同步会清除由真实邮件内容得到的本地状态。

## 契约区

### 范围

- Graph delta 只更新服务商本次明确返回的 read/star 字段。
- IMAP/Gmail 未提供附件标记时保留已有附件状态；能明确提供 true/false 的来源仍按返回值更新。
- 更新 provider 类型、同步应用逻辑、契约与回归测试。

### 非范围

- 不改变用户本地未收敛的 read/star 意图优先级。
- 不推断附件状态，不改附件解析与归档行为。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：Graph delta 仅返回 isRead 时 patch 不含 is_flagged；仅返回 flag 时不含 is_read，未返回字段在数据库保持原值。
- [ ] AC-002：IMAP/Gmail 未提供附件状态的 metadata 重扫不覆盖已知 has_attachments；明确返回 true/false 时仍正确更新。
- [ ] AC-003：Graph 局部状态及附件未知/明确状态均有触达 parser 与生产更新逻辑的自动化测试。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。

## 上下文区

- 来源：2026-10-23 代码审查与 `parse_graph_delta` 直接调用复现；`tests/mail_core/test_gmail_graph_contracts.py` 有仅 isRead 样例但未断言缺失 flag 保持不变。

### 有意不测

- 外部 Gmail/Graph live account：需用户凭据，不用于验证本地更新契约。

### 测试策略

- parser 单测断言 flags 仅含实际出现键；真实 PostgreSQL 更新测试先存已有值，再应用部分/未知字段，验证保留原值与明确返回时更新。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

无。Graph delta 字段存在性与 IMAP/Gmail metadata 能力可由仓库解析器和请求内容核验。

### 风险与回退

- 风险：Optional 状态扩展遗漏 provider 调用点。
- 回退：回退本 task 执行提交；不改数据库结构或历史邮件内容。

### 依赖与约束

- t036 修改相同 provider 时间解析文件，须本 task 合入后再 start，避免冲突。
- 不将未返回字段合成为默认 false，不削弱写回意图保护。

### Finalization 时更新的 blueprint

- 由 t040 集中更新 `docs/blueprint/conventions.md`，本 task 不改共享 blueprint，避免并行 worktree 写冲突。
