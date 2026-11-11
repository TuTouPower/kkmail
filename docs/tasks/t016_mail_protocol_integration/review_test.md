# t016 测试审查

## 范围与执行方式

核查 t016 相关自动化测试与协议集成门禁：

- `tests/mail_core/test_imap_protocol_suite.py` (新增 4 个多阶段全真测试)
- `tests/mail_core/test_imap_provider_live.py` (不再跳过，真实通过)
- `tests/mail_core/test_imap_sync_loop.py` (修复 private host 后通过)
- `tests/mail_core/test_gmail_graph_contracts.py` (新增 3 项传输/脱敏测试)

## 门禁验证结果

1. **真实协议套件验证**: `scripts/run-mail-core-tests.sh run -k test_imap_protocol_suite` 4 项全通。
2. **全量后端测试套件**: `scripts/run-mail-core-tests.sh run` 全套 361 passed / 0 skipped / 0 failed。
3. **快速单元套件**: `scripts/run-mail-core-tests.sh unit` 255 passed / 102 skipped / 0 failed。

## 结论

PASS。全量门禁不再产生 IMAP 跳过，覆盖率与协议契约均达到验收要求。
