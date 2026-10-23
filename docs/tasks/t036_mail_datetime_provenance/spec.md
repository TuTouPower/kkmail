# Task spec

## 背景

IMAP/Gmail/Graph 缺失或非法时间可能被当前时刻替代，重扫会让旧邮件移到列表顶部；Graph 最后修改时间冒充收件时间，归档解析还会用 MIME Date 覆盖已有 received time。

## 契约区

### 范围

- IMAP、Gmail、Graph 缺失或非法时间不生成当前时刻，也不把 lastModifiedDateTime 冒充 received time。
- MIME Date 归档解析不得覆盖已有 provider 收件时间。
- API 对未知时间保持明确语义，列表排序与 keyset 分页对未知值确定、稳定。
- 更新数据库迁移、查询、契约、测试和必要 blueprint。

### 非范围

- 不更改已经有效保存的邮件时间。
- 不使用 MIME Date 冒充 provider received time，也不重新下载邮件。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：适配器缺少/无法解析 provider 时间时不生成当前时刻；Graph 缺 receivedDateTime 时不使用 lastModifiedDateTime 作为 received time。
- [ ] AC-002：归档解析不得用 MIME Date 覆盖现存 received time；空主题只触发其本身缺失字段的回填。
- [ ] AC-003：缺失 received time 可在存储/API 中辨识；列表排序、游标和 API 输出不显示成当前日期且重复查询稳定。
- [ ] AC-004：自动测试覆盖 IMAP/Gmail/Graph 有效/缺失/非法时间、归档相异 MIME Date、空主题和未知时间跨页。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试，使用 parser、真实 PostgreSQL migration/query 测试验证。

## 上下文区

- 来源：2026-10-23 静态代码链审查 IMAP/Gmail/Graph 时间解析与 `archive.py` header backfill。

### 有意不测

- Provider live account：无用户凭据，不作为重复验证依赖。

### 测试策略

- Parser 单测覆盖时间来源；真实 PostgreSQL 测试覆盖时间迁移无损、未知值排序/分页/API；归档测试确认 MIME Date 不覆盖已有 received time。
- 运行后端相关测试、migration 门禁和后端完整门禁。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 未知时间在现有 keyset sort 中的顺序：`UNVERIFIED-SPIKE`，先核对 PostgreSQL NULL 排序、组合 cursor 与 API 合约，验证方案后移除此标记；不得保存当前时间规避。

### 风险与回退

- 风险：sort_time nullable 涉及 schema、OpenAPI、排序游标和历史值迁移。
- 回退：迁移保留现有非空时间并可回退；禁止回退时删除已有时间数据。

### 依赖与约束

- 与 t035 修改相同 provider parser，须 t035 合入后再 start。
- 收件时间、MIME Date 与未知时间不能混用。

### Finalization 时更新的 blueprint

- 由 t040 集中更新 `docs/blueprint/conventions.md` 与 `docs/blueprint/architecture.md`，本 task 不改共享 blueprint。
- 若新增独立门禁命令，由 t040 一并更新 `docs/blueprint/testing.md`。
