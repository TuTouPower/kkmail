# t018 测试审查

## 范围与执行方式

核查 t018 相关数据库迁移与完整性测试套件：

- `tests/mail_core/test_migration_validation.py` (5 项全真测试)
- `tests/mail_core/test_schema_pg.py`

## 门禁验证结果

1. **迁移与完整性套件**: `scripts/run-mail-core-tests.sh run -k test_migration_validation` 5 项全通 (6.24s)。
2. **全量数据库测试套件**: `scripts/run-mail-core-tests.sh run -k test_schema_pg` 2 项全通。
3. **快速单元模式**: `scripts/run-mail-core-tests.sh unit` 256 passed / 105 skipped。

## 结论

PASS。测试对空库迁移、历史数据升级保留、真实数据库完整性约束和可逆降级形成了完整闭环。
