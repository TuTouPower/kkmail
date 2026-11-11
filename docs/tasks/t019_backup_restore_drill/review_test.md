# t019 测试审查

## 范围与执行方式

核查真实加密备份与跨库恢复演练自动化测试套件：

- `tests/mail_core/test_backup_restore_drill_live.py` (真实恢复与异常边界防护测试)
- `tests/mail_core/test_backup_verify_drill.py` (离线与 stub 校验测试)
- `scripts/mail-core-backup-restore-drill.sh` (演练执行脚本)

## 门禁验证结果

1. **真实跨库恢复演练**: `scripts/run-mail-core-tests.sh run -k test_backup_restore_drill_live` 2 项全通 (5.73s)。
2. **离线包校验演练**: `scripts/mail-core-backup-restore-drill.sh` 顺利完成 (DRILL_OK)。
3. **单元与快速门禁**: `test_encrypted_backup_verify_drill` 1 项全通。

## 结论

PASS。测试不再仅止于校验 checksum，而是完成了全新测试数据库与 Blob 存储的真实还原和业务数据解密核验。
