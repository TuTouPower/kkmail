# p024 未知邮件状态仍会被持久化为 false

- 现象：服务商未提供 read/flag/attachment 状态时，新建邮件记录仍将未知状态变成 false；旧库迁移也把无来源状态写成确定 false。
- 影响：初次同步或旧库导入邮件可能显示为未标星、无附件或未读，即使旧数据没有这些字段的可信值。已有记录的 `None` 更新虽会被跳过，新记录仍由数据库默认值变成 false。
- 根因：数据模型把 `is_read`、`is_flagged`、`has_attachments` 设为非空并默认 false（`src/mail_core/mail/storage/models.py:161-163`）；同步新建 `Message` 时未传这些可空 provider 字段，随后 `metadata.py` 跳过 `None`，字段继续留在 false 默认值（`src/mail_core/sync/metadata.py:99-120`）。旧 SQLite 表将 `is_read` 与 `has_attachments` 定义为 `NOT NULL DEFAULT 0`，无法区分默认值和服务商明确 false，也没有 `is_flagged` 列；导入器再对前两者调用 `bool(...)` 并硬编码 `is_flagged=False`（`scripts/migrate_from_legacy_db.py:277-279`）。
- 测试缺口：`tests/mail_core/test_legacy_migration.py` 现已覆盖 importer 对旧列的实际持久化；但旧 SQLite 的 `is_read` / `has_attachments` 为 `NOT NULL DEFAULT 0`，无法区分服务商明确 false 与历史默认值，且没有 `is_flagged` 列，故仍不能证明这些 false 是可信状态。后续需调整状态模型与 API/前端未知值契约，并覆盖首次插入 `RemoteMessageMeta` 状态为 `None`，确认未知状态不呈现为明确 false。
- 线索：`.scratch/repro_unknown_legacy_status.py` 用旧 schema 最小表对比默认 false 与显式 false，二者查询值相同，且表中无 `is_flagged` 列。
- 处理：未开
