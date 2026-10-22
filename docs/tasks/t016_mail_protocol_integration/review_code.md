# t016 代码审查

## 范围与执行方式

审查 t016 真实 IMAP 与协议集成测试的改动：

- `config/test_pg_compose.yaml`: 补充专用测试 `imap` (Dovecot) 服务配置
- `scripts/start-mail-core-imap.sh`: 优先调用专用测试 Compose，免除业务 Compose 环境变量依赖
- `tests/mail_core/test_imap_sync_loop.py`: 修复本地回环 IMAP 测试对 `MAIL_CORE_ALLOW_PRIVATE_HOSTS` 的设置
- `tests/mail_core/test_imap_protocol_suite.py`: 建立真实 IMAP 协议集成测试套件
- `tests/mail_core/test_gmail_graph_contracts.py`: 增加分页终止/重复页、过期 cursor、超时及敏感信息脱敏合约测试

## Finding 处置

- 已修 important: 附件 Blob 模型外键绑定及解密校验。修正 `att.size_bytes` 以及经由 `MessageBlob.content_sha256` 从 BlobStore 解密读取流式字节，断言与原始二进制附件完全一致。
- 已修 important: `push_remote_operations` 参数与返回结构修正。修正传参方式，并断言 `push_res["pushed"] >= 1`。

## 结论

PASS。无未解决 critical 或 important 问题。
