# 需求规格：邮件同步、归档解析与安全存储 (Mail Sync and Storage)

## 背景

支持从标准 IMAP、Gmail REST API 以及 Microsoft Graph API 持续同步邮件元数据，并在本地提供端到端内容寻址分块加密与离线归档能力。

## 契约区

### 范围

- IMAP、Gmail 与 Graph 提供商的元数据分页扫描与增量拉取。
- 邮件原文的后台批次归档下载与 MIME 解析（提取正文和附件）。
- 分块 AES-256-GCM 内容寻址加密存储与延迟引用计数垃圾回收 (GC)。
- 标记状态异步出站写回与 IMAP 安全删除阻断。

### 非范围

- 发送邮件（SMTP 或提供商 send API）。
- 邮件垃圾箱彻底物理清除与邮件在文件夹间跨目录移动。

### 验收标准

- [x] AC-001：IMAP 连接默认强制启用 TLS 证书与主机名验证，mailbox 文件夹名包含空格或特殊字符时自动带双引号转义。
- [x] AC-002：IMAP 执行删除时优先调用 `UID MOVE`；若服务器不支持或移动失败，严禁调用全邮箱 `EXPUNGE`，不打 `\Deleted` 标记并直接向调用方报错。
- [x] AC-003：Graph 提供商在 v1.0 下通过 `/me/mailFolders/inbox` 别名解析真实收件箱 ID，映射为 `role="inbox"`，并递归遍历子文件夹。
- [x] AC-004：Gmail 提供商增量请求发送 repeated `historyTypes` 参数，对 ID stub 邮件调用 `messages.get` 补全元数据，并联动标签与位置增删。
- [x] AC-005：元数据扫描完成后自动调度首个归档批次，归档成功后解析 MIME 生成 `MessageBody` 与 `Attachment`。
- [x] AC-006：垃圾回收 (GC) 必须同时统计 `MessageBlobLink` 与 `Attachment.blob_id` 引用，删除文件前执行数据库二次校验，异常时 Fail-Closed 跳过删除。
- [x] AC-007：IMAP Provider 对名为 `"已发送"`、`"已发送邮件"` 或带有 `\Sent` 标志的目录，解析出 `role="sent"`。
- [x] AC-008：`/api/mail/inbox` 支持 `folder_role` 参数（默认 `inbox`，支持 `sent` 等），支持按角色检索全账号或指定账号邮件。

### 可测试性声明

全部 AC 可自动测试。

## 上下文区

- 来源：`docs/blueprint/decisions.md` (IMAP 安全阻断删除决策)

### 有意不测

- 真实外部三方邮箱的持续长时间在线同步（使用 Stub/Memory Provider 隔离断网与配额风险）。

### 测试策略

- 单元测试：`tests/mail_core/test_gmail_graph_contracts.py`、`test_archive_mime_parser.py`、`test_flag_convergence.py`。
- 契约测试：`test_blob_crypto_gc.py` 验证 GC 与附件引用计数。

### 未知契约清单

无

### 风险与回退

- 风险：临时网络 I/O 错误导致附件写入失败。
- 回退：严格区分 MIME 解析异常与写盘异常，写盘失败时保持 `ARCHIVE_PENDING` 调度退避重试，不标记完成。

### 依赖与约束

- 依赖磁盘存储挂载并配置 `MAIL_CORE_BLOB_ROOT` 与 `MAIL_CORE_BLOB_KEY_V1`。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：同步引擎与存储模块说明。
- `docs/blueprint/decisions.md`：IMAP 删除安全阻断策略。
