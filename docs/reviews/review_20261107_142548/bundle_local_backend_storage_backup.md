# bundle_local_backend_storage_backup

## responsibilities

- 提供基于分块 AES-256-GCM 与明文 SHA-256 内容寻址的加密 Blob 存储与安全流式读写
- 实现数据库转储 (pg_dump) 与加密 Blob 的整包备份构建、AES-GCM 加密密封、清单防篡改签名与跨容器宿主机安全导出
- 提供灾备恢复演练与数据还原流程，强制比对源与目标数据库集群标识、空库空目录门禁、单一事务还原保障
- 实现两阶段提交的 Blob 垃圾回收机制（数据库元数据标记 -> 咨询锁防竞态磁盘安全 unlink）
- 维护基于目录大小缓存与 PostgreSQL 事务咨询锁的硬配额控制与原子预留
- 驱动权威 MIME 归档状态机（MessageArchiveState FSM），实现大附件防 OOM 保护与后台批处理调度
- 提供统一收件箱读取、基于游标的 Keyset 邮件列表高效分页、全文检索投影与本地优先变更（标读/标星/垃圾箱）及远程同步队列

## interfaces

- Python mail_core.backup: create_backup_package, verify_backup_package, run_backup, export_container_package, load_backup_key
- Python mail_core.blobs: BlobStore, run_gc_blobs, check_quota, reserve_quota, release_quota_reservation, rewrap_all_blobs
- Python mail_core.blobs.access: parse_attachment_id, resolve_attachment_bytes, assert_not_path_param
- Python mail_core.mail.application: unified_inbox, get_folder_stats, list_messages_keyset, get_message_detail_with_archive_status, sync_message_body, set_message_read, set_message_flagged, trash_message, mark_all_messages_read, search_messages_page, load_attachment, allow_message_remote_images, allow_sender_remote_images
- Python mail_core.mail.storage.models: Account, Message, MessageBody, MessageBlob, MessageBlobLink, Attachment, Folder, FolderStats, MessageArchiveState, RemoteOperation, OutboxEvent, WorkerJob
- Python mail_core.mail.domain.archive: apply_transition, assert_transition, can_transition

## dependencies

- cryptography
- sqlalchemy
- psycopg
- pydantic
- mail_core.accounts
- mail_core.db.session
- mail_core.security
- mail_core.sync.jobs

## flows

- Blob 加密写入与流式验证流：数据传入 put_streaming -> 增量哈希计算 -> 分块 AES-GCM 封装 (带帧索引与 final 标记) -> 临时文件原子替换并设置 0600 权限 -> 写入 MessageBlob；下载时经 iter_plaintext_verified 先落地匿名临时文件并验证全量 SHA-256，校验通过后才向客户端流式输出
- 备份封装与导出流：create_backup_package -> 通过 PGPASSWORD 执行 pg_dump 生成 custom dump -> 打包 blob 目录 -> 生成并校验 MANIFEST.json 及 sha256 签名 -> 使用独立备份密钥加密为 backup.kkbak -> 宿主机导出时校验 uid/gid 属权并严格禁止软链接
- 灾备还原流：核实备份清单签名与哈希 -> 读取数据库系统标识符确认非原集群 -> 检查目标库无用户对象且目标 blob 目录为空 -> 临时解压并验证 tar 包成员路径合法性 -> 文件落地到目标 blob 目录 -> 执行 pg_restore --single-transaction --exit-on-error 事务性还原 -> 更新恢复操作日志为 complete
- 邮件变更与回写流：用户执行标读/标星/删除 -> 更新本地 Message 记录 -> 构造包含递增 revision 的 desired_state 写入 RemoteOperation -> 投递 OutboxEvent -> 重新计算 FolderStats -> 唤醒 worker 执行推送
- Blob GC 回收流：mark_unreferenced_blobs 批量比对引用计数并打上 gc_eligible_at 时间戳 -> sweep_expired_blobs 筛选超过冷却期的记录在 DB 中执行删除并提交 -> unlink_gc_paths 在持有 digest 咨询锁的事务中二次确认数据库无新引用后，执行磁盘 unlink

## constraints

- 备份密钥必须独立配置，严禁使用 Blob 数据加密密钥作为备份密钥
- 灾难恢复必须在空数据库与空 Blob 目录下进行，禁止在原生产集群上直接就地覆盖恢复
- 附件与 Blob 访问只允许通过 UUID 寻址，拒绝任何路径参数传入，防止路径穿越风险
- Blob 与备份存储的目录权限强制为 0700，文件权限强制为 0600，拒绝处理任何软链接
- 单封邮件 MIME 解析限制最大 50MB，单个附件最大 25MB，防止恶意邮件耗尽内存崩溃

## decisions

- 架构解耦：邮件原始 MIME 数据存储于加密文件系统 Blob，检索与状态元数据保存在 PostgreSQL，职责彻底分离
- 安全还原设计：先完整解密并落地 Blob 存储，最后单一事务提交数据库还原，避免网络或进程中断导致的半落地悬挂
- 两阶段并发 GC：数据库行先提交删除，物理删除前结合咨询锁二次核验数据库引用，从根源规避并发归档竞态误删

## evidence

- src/mail_core/backup/crypto.py:46-88
- src/mail_core/backup/export.py:60-115
- src/mail_core/backup/package.py:256-295
- src/mail_core/backup/package.py:297-332
- src/mail_core/blobs/store.py:98-144
- src/mail_core/blobs/store.py:243-262
- src/mail_core/blobs/access.py:29-45
- src/mail_core/blobs/gc.py:198-338
- src/mail_core/blobs/quota.py:132-180
- src/mail_core/mail/application/mutations.py:106-150
- src/mail_core/mail/application/mutations.py:219-280
- src/mail_core/mail/domain/archive.py:8-59

## uncertainties

## Findings

No findings.

## views

```json
{
  "security": {
    "status": "completed",
    "reviewer": "subagent_backend_1"
  },
  "correctness": {
    "status": "completed",
    "reviewer": "subagent_backend_1"
  },
  "contracts": {
    "status": "completed",
    "reviewer": "subagent_backend_1"
  },
  "performance": {
    "status": "completed",
    "reviewer": "subagent_backend_1"
  },
  "design": {
    "status": "completed",
    "reviewer": "subagent_backend_1"
  },
  "robustness": {
    "status": "completed",
    "reviewer": "subagent_backend_1"
  },
  "tests": {
    "status": "completed",
    "reviewer": "subagent_backend_1"
  },
  "documentation": {
    "status": "completed",
    "reviewer": "subagent_backend_1"
  }
}
```

## files_reviewed

```json
[
  "src/mail_core/backup/__init__.py",
  "src/mail_core/backup/crypto.py",
  "src/mail_core/backup/export.py",
  "src/mail_core/backup/package.py",
  "src/mail_core/blobs/__init__.py",
  "src/mail_core/blobs/access.py",
  "src/mail_core/blobs/archive.py",
  "src/mail_core/blobs/crypto.py",
  "src/mail_core/blobs/gc.py",
  "src/mail_core/blobs/permissions.py",
  "src/mail_core/blobs/private_fs.py",
  "src/mail_core/blobs/quota.py",
  "src/mail_core/blobs/rotate.py",
  "src/mail_core/blobs/store.py",
  "src/mail_core/mail/application/__init__.py",
  "src/mail_core/mail/application/accounts.py",
  "src/mail_core/mail/application/attachments.py",
  "src/mail_core/mail/application/message_details.py",
  "src/mail_core/mail/application/mutations.py",
  "src/mail_core/mail/application/queries.py",
  "src/mail_core/mail/application/remote_images.py",
  "src/mail_core/mail/application/remote_ops.py",
  "src/mail_core/mail/application/search.py",
  "src/mail_core/mail/application/sync_requests.py",
  "src/mail_core/mail/domain/__init__.py",
  "src/mail_core/mail/domain/archive.py",
  "src/mail_core/mail/domain/enums.py",
  "src/mail_core/mail/storage/__init__.py",
  "src/mail_core/mail/storage/folder_stats.py",
  "src/mail_core/mail/storage/health.py",
  "src/mail_core/mail/storage/models.py"
]
```
