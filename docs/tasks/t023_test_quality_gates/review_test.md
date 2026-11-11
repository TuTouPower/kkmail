# t023 测试审查

## 范围与执行方式

核查全分层测试门禁与本地重放结果：

- 模板契约: `pytest .repo_template/tests -q -m contract`
- 前端门禁: `(cd src/frontend && npm test && npx tsc -b && npm run build && npm run lint)`
- 桌面门禁: `(cd src/desktop && npm test && npm run test:packaged)`
- 后端全量: `scripts/run-mail-core-tests.sh run`
- 全栈 E2E: `python3 scripts/run_full_stack_e2e.py`
- 快速 E2E: `npm --prefix src/frontend run test:e2e`
- 扩展演练: `scripts/run-mail-core-tests.sh run -k "test_backup_restore_drill_live or test_migration_validation or test_worker_process_recovery"`
- 性能基准: `scripts/run-mail-core-tests.sh run -k test_mailbox_performance_baseline`

## 门禁验证结果

1. **本地重放全矩阵**: 全部 8 类分层命令在本地环境 100% 重放通过。
2. **零跳过验证**: 后端数据库及 IMAP 协议测试实现 0 意外跳过。
3. **CI 脚本对齐**: GitHub Actions 步骤严格复用本地脚本入口，无脱节或未定义命令。

## 结论

PASS。全部分层门禁与 CI 流水线形成统一闭环。
