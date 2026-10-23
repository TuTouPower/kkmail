# Task spec

## 背景

旧库迁移把缺失字段替换为展示占位值、猜测正文类型、生成当前时间，并把本地 SQLite 行号当远端 UID，造成事实字段失真。

## 契约区

### 范围

- 缺失 subject/from/to/date/remote UID 保持缺失语义，不填展示占位、当前时间或 SQLite 行号。
- 按标准地址解析器拆分 From、多个 To/Cc；尊重旧记录显式 body_type。
- 仅从核实后的旧数据时间来源迁移日期；增加可重复的合成 SQLite fixture 测试。
- 更新迁移相关规范文档。
- 缺失或不可安全映射为 canonical remote ID 的旧邮件保留内容，remote_id 写 null 并报告数量。

### 非范围

- 不改运行容器或重写已迁移用户数据。
- 不改变实时 provider 同步行为（由 t035/t036 负责）。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：缺失或空 subject/sender 写为空事实值，不生成展示占位文本；源中已有非空字面值（包括旧占位词）原样保留，不按字符串猜测并清洗。
- [ ] AC-002：迁移后的 From、To、Cc 是标准邮件地址解析所得独立地址；旧记录 body_type 为 text 或 html 时按该值选择正文列；body_type 缺失或不支持时不 sniff HTML，正文只保存到纯文本列。
- [ ] AC-003：仅当 `id_mode=graph` 且旧 received_at 是有效、带时区的 Graph `receivedDateTime` 时迁入 sort_time；日期缺失、非法、无时区，以及显式 `imap`、sequence、空白或未知 id_mode 的时间保持 null。UID 仅从 `id_mode=uid` 且 provider_message_id 可解析为 PostgreSQL signed BIGINT 范围内正整数（1 至 9223372036854775807）时写入；SQLite 行号永不作为时间或 UID。
- [ ] AC-004：合成 SQLite 源经生产 importer 写入隔离 PostgreSQL 后，测试逐字段断言缺失值与有效来源值保真、重跑幂等且源文件未改动。
- [ ] AC-005：缺少 `MessageArchiveState` 的迁移邮件在详情与 sync-body API 中以 `is_archived: null` 表示；sync-body 调用真实归档 runner 后仍无 archive state、claim/job 或 provider 调用；前端保留未知值，不得默认成已归档。
- [ ] AC-006：只有 `id_mode=graph` 且 provider_message_id 非空白时，Message.remote_id 保存原始 Graph ID；其余模式或缺失/空白 ID 的旧行保留邮件内容但 remote_id 为 null。SQLite id 仅用于稳定生成本地 Message.id，不生成 remote_id 或 UID；null remote_id 不传入 provider fetch、reconcile 或 remote push。
- [ ] AC-007：数据库允许 Message.remote_id 为 null 且不改写已有 remote_id；存在 null remote_id 时 downgrade 明确拒绝，不伪造远端 ID。
- [ ] AC-008：remote_id 为 null 的本地邮件仍可更新本地 read/flag 状态且不创建 remote operation；trash 与 sync-body 请求明确返回 409 不可寻址，不调用 provider。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试；AC-005 覆盖有可寻址 provider ID、空正文且无归档状态的详情与按需同步响应，以及前端转换；AC-008 单独覆盖 local-only 邮件的 409 不可寻址结果。

## 上下文区

- 来源：2026-10-23 静态审查 `scripts/migrate_from_legacy_db.py` 邮件字段映射；需求方明确要求不补造数据。
- 同类问题复现：legacy importer 写空 `MessageBody` 但不写 `MessageArchiveState`；`api_get_message` 和前端 mapper 将缺状态改成 `is_archived=true`，导致未知被标成完整。最小复现 `.scratch/repro_missing_archive_state.py` 输出 `empty body + missing MessageArchiveState => is_archived=True`。
- 历史 SQLite 来源核实：`id` 是本地 `INTEGER PRIMARY KEY AUTOINCREMENT`；`provider_message_id` 与 `id_mode` 独立。旧 Graph formatter 仅将服务商 `receivedDateTime` 写入 date 并设 `id_mode='graph'`，因此 Graph ID 原样进入 remote_id。旧 IMAP UID 缺少 UIDVALIDITY，无法构成当前 mail-core canonical remote_id；sequence/未知模式也不可寻址，迁移后 remote_id 保持 null。旧 IMAP 列表及详情可能将 MIME `Date` 回退写入 received_at，且没有行级来源列；因此 IMAP/sequence 日期不可证明是 provider received time，迁移后保持 null。旧 schema 的 body_type 有 `DEFAULT 'text'`；无法从存储值判别该值是显式还是 DB 默认，迁移以已存 text/html 为唯一可用来源并按其保存；缺失/不支持时正文只进 text_plain，不推断 HTML。
- 历史 sentinel 无可靠 provenance：旧代码在写入时可将缺失 subject/from 改成“无主题/未知”等文本，但同字面值也可能是真实邮件内容；迁移只将现有 null/空值写为空串，不按文字值清洗。

### 有意不测

- 真实用户旧库：含业务邮件与凭据，以合成最小 SQLite fixture 代替。

### 测试策略

- 通过真实 importer、临时 SQLite 源和隔离目标 PostgreSQL fixture，覆盖空值/字面 sentinel、多地址、text/html/未知正文类型、Graph/IMAP/sequence/未知日期来源、UID/缺失 provider ID、缺失 archive state、null remote_id 的 provider 边界、local-only read/flag 与 409 trash/sync-body 以及迁移降级保护，断言持久化值/API 语义准确并校验 SQLite 源未变。
- 运行脚本迁移目标测试及相关后端门禁。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

无。已核实旧 SQLite 的 id、id_mode、received_at 和 body_type 写入来源；结论与验证方式见上方上下文与 AC。

### 风险与回退

- 风险：脚本可被重复运行，必须保持幂等且不得覆盖既有 mail-core 记录/凭据。
- 回退：不触碰用户运行数据；代码回退不需数据迁移。

### 依赖与约束

- 旧数据字段语义核实后才移除 spike 标记；不得把 SQLite id 当 IMAP UID。

### Finalization 时更新的 blueprint

- 由 t040 集中更新 `docs/blueprint/conventions.md`，本 task 不改共享 blueprint。
