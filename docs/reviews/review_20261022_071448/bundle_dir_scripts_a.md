# Bundle Review — dir:scripts_a

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 8 allowlisted tracked files

## Findings

- [High][99] scripts/migrate_from_legacy_db.py:50-L57 — 旧密文解密失败被静默转换为空凭据并继续迁移 — 证据：enc: 字段解密任意异常后返回空字符串；调用方仍保存 credentials 并提交迁移，错误旧密钥或损坏密文会造成静默凭据丢失。 — 依据：scripts/migrate_from_legacy_db.py:158-178；src/mail_core/accounts/credentials.py:249-259 未拒绝空值。 — 修复：迁移对密文解密 fail closed；提交前验证所有加密字段成功解密并报告行号/字段名。
- [High][99] scripts/run-mail-core-tests.sh:13-L17 — 测试数据库安全门禁只检查 test 子串，attest 等生产库名也会通过 — 证据：shell 只判 DB_NAME 是否包含 test；attest 符合子串条件，后续脚本会对该数据库执行 Alembic upgrade 和 pytest。 — 依据：升级命令见同脚本第 30 行。 — 修复：要求严格数据库名模式或显式 disposable 标志，并校验数据库连接目标。
- [High][96] scripts/mail-core-backup-restore-drill.sh:32-L42 — 备份演练输出目录的逻辑路径校验可被父目录软链绕过 — 证据：pwd 保留逻辑 symlink 路径并通过仓内或 /tmp 字符串检查，随后 rm -rf OUT；父目录链接到仓外时可删除仓外同名目录。 — 依据：脚本第 21-42 行按字符串界定删除边界。 — 修复：用物理 realpath 校验；拒绝路径祖先软链，删除前再次确认目标 containment。
- [Low][88] scripts/fetch-pg-binaries.sh:111-L159 — PostgreSQL 二进制下载没有连接或总时限，网络停滞可让脚本无限等待 — 证据：下载命令配置 retry 但未配置 connect-timeout/max-time；连接保持挂起时重试策略不会及时推进或失败。 — 依据：外部下载需有明确超时以保证脚本可恢复。 — 修复：设置连接与总时限，并让有限重试后明确失败。

## Files examined

- scripts/build-sidecar.sh
- scripts/export_openapi.py
- scripts/fetch-pg-binaries.sh
- scripts/gen-openapi.sh
- scripts/mail-core-backup-restore-drill.sh
- scripts/mail-core-chaos-lease.sh
- scripts/migrate_from_legacy_db.py
- scripts/run-mail-core-tests.sh
