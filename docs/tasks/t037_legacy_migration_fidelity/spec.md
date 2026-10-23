# Task spec

## 背景

旧库迁移把缺失字段替换为展示占位值、猜测正文类型、生成当前时间，并把本地 SQLite 行号当远端 UID，造成事实字段失真。

## 契约区

### 范围

- 缺失 subject/from/to/date/remote UID 保持缺失语义，不填展示占位、当前时间或 SQLite 行号。
- 按标准地址解析器拆分 From、多个 To/Cc；尊重旧记录显式 body_type。
- 仅从核实后的旧数据时间字段迁移日期；增加可重复的合成 SQLite fixture 测试。
- 更新迁移相关规范文档。

### 非范围

- 不改运行容器或重写已迁移用户数据。
- 不改变实时 provider 同步行为（由 t035/t036 负责）。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：缺失主题/发件人不写“无主题/未知发件人”等占位进邮件事实字段。
- [ ] AC-002：迁移后的 From、To、Cc 是标准解析所得独立地址；显式 text/html 类型不被正文标签覆盖。
- [ ] AC-003：迁移时间仅来自确认的旧时间字段；缺失时保持未知；SQLite 行号不写入远端 UID。
- [ ] AC-004：迁移自动化测试逐字段断言缺失值与合法来源值保真，并验证现有幂等行为。
- [ ] AC-005：缺少 `MessageArchiveState` 的迁移邮件在 API 中以 `is_archived: null` 表示；前端保留未知值，不得默认成已归档。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试；AC-005 覆盖 legacy 空正文且无归档状态的详情与按需同步响应，以及前端转换。

## 上下文区

- 来源：2026-10-23 静态审查 `scripts/migrate_from_legacy_db.py` 邮件字段映射；需求方明确要求不补造数据。
- 同类问题复现：legacy importer 写空 `MessageBody` 但不写 `MessageArchiveState`；`api_get_message` 和前端 mapper 将缺状态改成 `is_archived=true`，导致未知被标成完整。最小复现 `.scratch/repro_missing_archive_state.py` 输出 `empty body + missing MessageArchiveState => is_archived=True`。

### 有意不测

- 真实用户旧库：含业务邮件与凭据，以合成最小 SQLite fixture 代替。

### 测试策略

- 测试映射函数及隔离目标 PostgreSQL migration fixture，覆盖缺失字段、多地址、显式类型、可用/缺失日期、本地行号与缺失归档状态，断言持久化值/API 语义准确。
- 运行脚本迁移目标测试及相关后端门禁。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 旧 SQLite 表的时间及远端 UID 字段来源：`UNVERIFIED-SPIKE`，检查旧 schema、写入路径和仓库 fixture；确认无可靠来源后目标值保持未知，不猜字段。

### 风险与回退

- 风险：脚本可被重复运行，必须保持幂等且不得覆盖既有 mail-core 记录/凭据。
- 回退：不触碰用户运行数据；代码回退不需数据迁移。

### 依赖与约束

- 旧数据字段语义核实后才移除 spike 标记；不得把 SQLite id 当 IMAP UID。

### Finalization 时更新的 blueprint

- 由 t040 集中更新 `docs/blueprint/conventions.md`，本 task 不改共享 blueprint。
