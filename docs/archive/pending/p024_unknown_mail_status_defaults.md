# p024 未知邮件状态仍会被持久化为 false

- 现象：服务商未提供 read/flag/attachment 状态时，新建邮件记录仍将未知状态变成 false；旧库迁移也把无来源状态写成确定 false。
- 影响：初次同步或旧库导入邮件可能显示为未标星、无附件或未读，即使旧数据没有这些字段的可信值。已有记录的 `None` 更新虽会被跳过，新记录仍由数据库默认值变成 false。
- 根因：数据模型把 `is_read`、`is_flagged`、`has_attachments` 设为非空并默认 false（`src/mail_core/mail/storage/models.py:161-163`）；同步新建 `Message` 时未传这些可空 provider 字段，随后 `metadata.py` 跳过 `None`，字段继续留在 false 默认值（`src/mail_core/sync/metadata.py:99-120`）。旧 SQLite 表将 `is_read` 与 `has_attachments` 定义为 `NOT NULL DEFAULT 0`，无法区分默认值和服务商明确 false，也没有 `is_flagged` 列；导入器再对前两者调用 `bool(...)` 并硬编码 `is_flagged=False`（`scripts/migrate_from_legacy_db.py:277-279`）。
- 测试缺口：`tests/mail_core/test_legacy_migration.py` 现已覆盖 importer 对旧列的实际持久化；但旧 SQLite 的 `is_read` / `has_attachments` 为 `NOT NULL DEFAULT 0`，无法区分服务商明确 false 与历史默认值，且没有 `is_flagged` 列，故仍不能证明这些 false 是可信状态。后续需调整状态模型与 API/前端未知值契约，并覆盖首次插入 `RemoteMessageMeta` 状态为 `None`，确认未知状态不呈现为明确 false。
- 线索：`.scratch/repro_unknown_legacy_status.py` 用旧 schema 最小表对比默认 false 与显式 false，二者查询值相同，且表中无 `is_flagged` 列。
- 处理：t041

## 本轮修复（t041）

- `Message.is_read/is_flagged/has_attachments` 改为 nullable，移除 false 默认值；API、查询 DTO、OpenAPI/前端类型保留 null。首次无来源状态保持未知，后续未知 metadata 不覆盖已有确定值。
- 新增 `20261023_0019`：仅放宽状态与 `FolderStats.unread_count` 约束，不重写历史邮件。降级发现 null 时拒绝，不回填 false/0。
- 文件夹含未知读状态时未读数为 null；账号、分组、全局聚合传播未知，可知总数保留。前端仅以 `is_read === false` 呈现未读、筛选未读或自动标已读；操作失败恢复真实原值，包括 null。
- 旧库无 flag 列，导入 null；旧 read/attachment 列原值保留。历史默认 false 与明确 false 无来源标记，不能凭推测区分或批量改写。
- 新增 `tests/mail_core/test_unknown_mail_status.py` 覆盖首次插入、更新与统计；API/codegen、迁移和旧库导入由相关契约及集成测试验证；前端补未知状态交互与乐观回滚回归。修复已提交 `300d394`；代码与测试 review PASS。前端 260 passed，类型/构建/lint/OpenAPI/CSS 通过；PG 定向验证通过，最终串行全量 477 passed / 0 skipped。

## IMAP 同类位点补齐

- `f5ef673`：FETCH 缺少 FLAGS 时 metadata 保留未知、delta 不生成 false patch；明确 FLAGS () 为 false。系统旗标按完整 token 忽略大小写匹配，扩展旗标不冒充 Seen/Flagged。
- 新增 `test_imap_unknown_flags.py` 覆盖两入口的缺失、空值、扩展旗标与大小写。实现与测试已独立复核；真实协议最终结果见 t041 总账。

## 最终闭环验证

- 主分支最终后端全量 477 passed / 0 skipped；前端 260 passed，类型、构建、lint、OpenAPI/CSS 均通过；真实全栈 E2E 8 passed，stub E2E 13 passed。
- 代码/测试审查及逐 AC 证据见对应 t041/t042/t043 总账。未部署生产，未改写运行邮件数据。
