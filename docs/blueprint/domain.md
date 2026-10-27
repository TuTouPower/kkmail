# 领域模型 (Domain Model)

kkmail 的核心领域概念与数据实体术语表。各层代码、数据迁移与文档命名统一以此为准。

## 实体与概念术语表

|概念 (English)|对应模型 / 数据库表|业务定义与生命周期说明|
|:---|:---|:---|
|**Account**|`accounts`|邮件账户实体。包含邮箱、提供商 (`imap`/`graph`/`memory`/`stub`，与后端 `AllowedProvider` 对齐)、关联凭据引用 (`credential_ref`)、配置项与同步状态。|
|**AccountGroup**|`account_groups`|账户分组。允许用户将多个邮箱归类整理，支持颜色与聚合展示。|
|**Folder**|`folders`|邮件文件夹/标签。映射远端 mailbox 或 label，维护 `role`（如 `inbox`, `trash`, `other`）。|
|**FolderStats**|`folder_stats`|文件夹聚合统计。维护总邮件数 (`total_count`) 与未读邮件数 (`unread_count`)，由数据库事务/对账即时维护。|
|**Message**|`messages`|逻辑邮件主体元数据。包含账户、远端 ID、主题、发件人、收发时间、`is_read`、`is_flagged`、附件标识等。|
|**MessageLocation**|`message_locations`|邮件与文件夹的关联位置。一封邮件可存在于多个文件夹（如 Gmail 多标签），维护对应文件夹下的 UID。|
|**MessageBody**|`message_bodies`|邮件正文解析产物。独立存储从 raw MIME 中提取出的 `text_plain` 与 `text_html`。|
|**Attachment**|`attachments`|邮件附件实体。提取自 MIME multipart，独立关联 `blob_id`，记录文件名、MIME 类型与字节大小。|
|**MessageBlob**|`message_blobs`|加密内容寻址二进制块。存储 raw MIME 邮件原文或独立附件 payload，通过 SHA-256 哈希去重。|
|**MessageBlobLink**|`message_blob_links`|邮件与存储 blob 的强引用关系，用于支持内容去重与引用计数垃圾回收 (GC)。|
|**RemoteOperation**|`remote_operations`|出站异步写回操作。记录读状态、星标、移入废纸篓等本地期望，支持幂等合并与指数退避重试。|
|**AccountSyncLease**|`account_sync_leases`|账户级排他执行租约。防止多个 Worker 抢占同一账户引发并发踩踏，维护递增 `fencing_token`。|
|**OutboxEvent**|`outbox`|事务性本地事件出箱。由写事务原子产生，经由 PostgreSQL `LISTEN/NOTIFY` 驱动 SSE 实时推送到前端。|
|**AuthCredential**|`auth_credentials`|登录密码与会话状态持久化存储。权威记录登录 bcrypt hash 与全局 `session_epoch` 版本号。|
|**Thread**|`threads`|邮件会话线程。按账户与提供商线程键 (`provider_thread_key`) 聚合多封邮件。|
|**ThreadMessage**|`thread_messages`|线程与邮件的关联位置。记录邮件在线程中的顺序 (`position`)，线程与邮件组合唯一。|
|**SyncCheckpoint**|`sync_checkpoints`|同步检查点。按账户与文件夹保存增量同步游标 (`cursor`、`uidvalidity`、`modseq`、`history_id` 等) 与全量扫描完成状态。|
|**SyncRun**|`sync_runs`|同步运行记录。记录一次同步运行的阶段、状态、统计与错误。|
|**WorkerJob**|`worker_jobs`|后台任务队列。基于 PostgreSQL 的任务表，以 `FOR UPDATE SKIP LOCKED` 领取，支持去重、优先级与 `run_after` 调度。|
|**MessageArchiveState**|`message_archive_state`|邮件归档状态。逐封邮件的 MIME 归档状态机，记录状态、优先级、认领与重试信息。|
|**CredentialSecret**|`credential_secrets`|提供商凭据密文。以 `ref` 为主键，AES-GCM 加密保存 OAuth token 与 IMAP 口令；`Account.credential_ref` 指向本表。|
|**AppSetting**|`app_settings`|应用设置。非密键值设置，不得存放口令或 token。|
|**OutboxPublicationState**|`outbox_publication_state`|Outbox 发布状态。单例行，跟踪 outbox 流的 epoch 与单调递增的发布序号。|

> 本表列核心实体；完整数据库表清单以 `src/mail_core/mail/storage/models.py` 为准（含 `message_search` 全文检索投影、`blob_quota_reservations` 配额预留、`sync_requests` / `sync_request_targets` / `sync_request_target_jobs` 同步请求跟踪、`account_sync_activity` 同步活跃度等投影与调度辅助表）。
