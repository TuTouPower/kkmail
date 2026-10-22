# t018 代码审查

## 范围与执行方式

审查 t018 数据库迁移与结构一致性验证模块：

- `tests/mail_core/test_migration_validation.py`: 建立 Alembic 线性单 head 校验、三版本历史窗口数据升级保留、真实 PostgreSQL 关系约束/外键级联/FTS 查询、ORM catalog drift 检查与最近迁移可逆循环。

## Finding 处置

- 已修 important: Alembic ConfigParser URL 特殊字符转义。针对含 `%` 的密码安全转义为 `%%`，防止 BasicInterpolation 抛出语法异常。
- 已修 important: 历史版本测试数据 SQL 对齐。`message_locations.id` 补齐 UUID 主键；`remote_operations` 列名对齐 `entity_key`；`auth_credentials` 列名对齐 `login_password_hash`。
- 已修 important: ORM drift 校验显式 catalog 绑定。对 tsvector 计算列 `document` 及 GIN 索引进行显式 catalog 校验，未做全量 blanket ignore。

## 结论

PASS。无未解决 critical 或 important 问题。
