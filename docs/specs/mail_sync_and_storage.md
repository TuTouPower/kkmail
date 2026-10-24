# 需求规格：邮件同步、归档解析与安全存储 (Mail Sync and Storage)

## 背景

支持从标准 IMAP、Gmail REST API 以及 Microsoft Graph API 持续同步邮件元数据，并在本地提供端到端内容寻址分块加密与离线归档能力。

## 契约区

### 范围

- IMAP、Gmail 与 Graph 提供商的元数据分页扫描与增量拉取。
- 邮件原文的后台批次归档下载与 MIME 解析（提取正文和附件）。
- 分块 AES-256-GCM 内容寻址加密存储与延迟引用计数垃圾回收 (GC)。
- 标记状态异步出站写回与 IMAP 安全删除阻断。
- 旧 SQLite 邮件迁移：字段保真、canonical provider identity 映射，以及不可寻址邮件的本地行为。

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
- [x] AC-009：归档 MIME 正文、报头或附件文件名解析失败时持久化 `MessageBody.parse_error` 并跳过损坏派生物，保留原始 MIME，不阻塞同批合法邮件。
- [x] AC-010：阅读器在检测到 `parse_error` 时明确展示“邮件解析失败”及脱敏原因，即使存在摘要或部分内容亦不被空占位掩盖，切换邮件即时隔离。
- [x] AC-011：Graph Delta 只更新本次明确返回的 `isRead` 与 `flag.flagStatus`；字段缺失时，数据库保留已有 read/star 状态。
- [x] AC-012：IMAP 与 Gmail 元数据未提供附件状态时，不覆盖本地 MIME 解析得到的 `has_attachments`；元数据明确提供 `true` 或 `false` 时按返回值更新。
- [x] AC-013：IMAP、Gmail、Graph 缺少或非法 provider received time 时保持 null，不用当前时间或 Graph last-modified 代替；Graph `receivedDateTime` 需带时区。MIME Date 不覆盖已有 provider 收件时间。
- [x] AC-014：缺失收件时间在 API 中为 null，不显示成当前日期；升序与降序列表都把 null 稳定排在末尾，keyset cursor 能跨页遍历已知与未知时间而不漏项、不重复。
- [x] AC-015：旧库邮件缺少或为空的 subject/sender 按空事实值迁移；非空原值（包括旧占位词）原样保留，不按字符串推断并清理。
- [x] AC-016：旧库 From、To、Cc 按标准地址解析器拆分；已存 body_type 为 text/html 时按存储值写入对应正文列，缺失或不支持时只写纯文本列，不 sniff HTML。
- [x] AC-017：旧库日期仅在 `id_mode=graph` 且 received_at 是有效、带时区的 Graph `receivedDateTime` 时迁入 sort_time；日期缺失、非法、无时区及来源不明的 IMAP、sequence、空白或未知模式保持 null。UID 仅从 `id_mode=uid` 且 provider_message_id 可解析为 PostgreSQL signed BIGINT 范围内正整数（1 至 9223372036854775807）时迁入，SQLite 本地行号不作为日期或 UID。
- [x] AC-018：旧库 importer 通过只读 SQLite 源和隔离 PostgreSQL 写入；合成 fixture 逐字段验证缺失值与有效来源值、重复运行幂等，并确认源文件未变。
- [x] AC-019：没有 `MessageArchiveState` 的迁移邮件在详情与 sync-body API 中返回 `is_archived: null`；sync-body 调用真实归档 runner 后仍无 archive state、claim/job 或 provider 调用。前端保留 null/缺失语义，不默认成已归档。
- [x] AC-020：只有 Graph 模式的原始非空白 provider_message_id 作为 `Message.remote_id`；其他旧模式或缺失/空白 ID 的邮件保留内容并使用 null remote_id。null remote_id 不传入 provider fetch、reconcile 或 remote push。
- [x] AC-021：Message.remote_id 可为空，迁移不改写已有远端 ID；存在 null 值时数据库降级明确失败，不合成远端 ID。
- [x] AC-022：null remote_id 邮件的 read/flag 可本地更新且不创建 remote operation；trash 与 sync-body 返回 409，不调用 provider。
- [x] AC-023：服务商未提供 read/flag/attachment 时，新邮件状态持久化为 null，API/前端保留未知；未知更新不覆盖已知状态，用户显式操作仍可设置布尔值。
- [x] AC-024：未知读状态不渲染未读标记，也不因打开邮件自动标已读；乐观更新失败恢复原状态，包括 null。
- [x] AC-025：文件夹包含未知读状态时未读数为 null；账号、分组与全局聚合传播未知，不展示部分和；可知总数仍准确。
- [x] AC-026：状态迁移不改写已有 true/false；旧 SQLite 无 flag 列时导入 null，已有 read/attachment 原值保留。降级遇到状态或未读统计 null 时拒绝，不补 false/0。
- [x] AC-027：Graph 部分内容 delta 仅应用实际返回字段；明确空主题、空摘要、空收件人数组可清空旧值，缺省字段保留原值。
- [x] AC-028：同页同封邮件的 partial upsert 与 flag patch 按响应顺序合并，后续提供字段覆盖先前同字段；delete 丢弃此前 patch，不破坏本地未收敛状态意图保护。
- [x] AC-029：Gmail metadata hydrate 必须返回请求 ID、列表 labelIds 与列表 payload.headers；无 id、id 不匹配、id-only 或 GET 异常均不得返回成功 metadata/delta 页，不用 History stub 回退。
- [x] AC-030：Gmail metadata projection 未返回 snippet 时保留已有服务商摘要；新邮件保持空，列表展示 fallback 不写回源字段。
- [x] AC-031：带 HTML body_preview 的邮件详情 body 为空时不将摘要渲染成正文；加载、详情错误、解析失败和空正文互斥渲染，已有正文按 html/text 分流。
- [x] AC-032：Graph 收件箱 ID 可用时只凭 canonical ID 或 well-known 标记赋予 inbox 角色；仅在无法取得 ID 时才回退英文名称，避免同名自定义目录成为第二个收件箱。
- [x] AC-033：IMAP `Deleted Messages` 名称映射为 `trash` 角色。
- [x] AC-034：IMAP LIST 的 `\NoSelect` 目录保留为 `paused` 结构节点，不创建元数据任务；已有任务以 skipped 完成，`MessageLocation`、邮件及子目录关系保留。

### 可测试性声明

全部 AC 可自动测试。

## 上下文区

- 来源：`docs/blueprint/decisions.md` (IMAP 安全阻断删除决策)；task t037 对旧 SQLite 数据迁移来源、身份与未知归档状态的核实见 [`docs/archive/tasks/t037_legacy_migration_fidelity/spec.md`](../archive/tasks/t037_legacy_migration_fidelity/spec.md)。

- 本轮来源：t041/p024（未知状态）、t042/p025（部分字段）、t043/p022（正文摘要隔离闭环）、t051/p037（文件夹角色与显示）、t052/p038（QQ 不可选择父目录）；最终验证由各 task 总账补入。

### 有意不测

- 真实外部三方邮箱的持续长时间在线同步（使用 Stub/Memory Provider 隔离断网与配额风险）。

### 测试策略

- 未知状态与部分更新：`tests/mail_core/test_unknown_mail_status.py`、`test_partial_metadata_fidelity.py`；前端 `MessageList.test.tsx`、`MessageReader.test.tsx` 与查询缓存回归。

- 单元测试：`tests/mail_core/test_gmail_graph_contracts.py`、`test_delta_flag_patch.py`、`test_metadata_apply.py`、`test_archive_mime_parser.py`、`test_flag_convergence.py`。

- 契约测试：`test_blob_crypto_gc.py` 验证 GC 与附件引用计数。

- 旧库迁移：`tests/mail_core/test_legacy_migration.py`、`test_migration_validation.py`、Message detail/mutation/provider-boundary tests。

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
