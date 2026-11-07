# bundle_local_backend_sync_providers

## responsibilities

- 统一定义并实现邮件提供商协议适配器（IMAP, Microsoft Graph, MemoryStub），隔离协议细节与业务逻辑
- 管理全局出站连接槽位预算（connection_slots），对前台与后台归档流量执行分级配额控制与预留
- 实现单账号互斥的分布式租约（AccountSyncLease）与 Fencing Token 校验，杜绝并发脑裂与乱序写入
- 驱动文件夹发现、元数据分页抓取、增量变更合并与删除对账（reconcile）全流程
- 管理 IMAP IDLE 收件箱长连接监听与基于邮件到达时间的动态配额席位调度
- 执行非收件箱文件夹状态巡检（STATUS patrol），以极低开销检测远程信箱变化并触发同步
- 承载本地操作（标读、标星、移动、删除）向远端服务的批量安全回写（remote_push）

## interfaces

- MailProvider Protocol (list_folders, full_scan, fetch_metadata_page, fetch_mime, delta_changes, apply_remote_operations, reconcile, probe_folder_status, open_idle_session, rate_limit_hint)
- build_provider(account, store, ...) -> MailProvider
- acquire_lease, heartbeat_lease, assert_fencing, release_lease
- enqueue_job, claim_jobs, complete_job, fail_job, reschedule_job
- sync_account_folders, sync_folder_metadata, sync_folder_delta, reconcile_folder, push_remote_operations

## dependencies

- mail_core.mail.storage.models (Account, Folder, Message, MessageLocation, SyncCheckpoint, WorkerJob, AccountSyncLease, OutboxEvent)
- mail_core.accounts.credentials (CredentialStore, load_json_secret)
- mail_core.config (get_config)
- psycopg / sqlalchemy (PostgreSQL 锁机制与连接池)
- Python 标准库 imaplib, urllib.request, ssl, socket, email

## flows

- 定期轮询/手动请求 -> sync_account_folders -> provider.list_folders() -> 更新本地 Folder 记录 -> 排队对应 metadata 或 delta 任务
- sync_folder_metadata -> 验证租约及 generation -> provider.fetch_metadata_page() (短事务外网络I/O) -> 事务内 apply_metadata_page (upsert消息及Checkpoint) -> 翻页完毕排队 reconcile 与 delta
- sync_folder_delta -> 验证租约 -> provider.delta_changes() -> 事务内 apply_delta_page 合并增量变更 -> 提交 Checkpoint
- reconcile_folder -> 验证 baseline 完整性 -> provider.reconcile() -> 批量安全删除已在远端移除的本地消息 (\_apply_delete_batch)
- push_remote_operations -> 锁定待推送操作为 in_progress -> provider.apply_remote_operations() -> 事务内验证 fencing 并更新操作与本地消息状态

## constraints

- 所有涉及消息与 Checkpoint 写入的操作必须在持有有效租约与 Fencing Token 的短事务内完成，严禁长事务持有或跨网络 I/O
- 未完成全量扫描（full_scan_complete=False）的文件夹绝不允许执行删除对账（reconcile）或隐式推断删除
- 全系统默认限制最大外发并发连接数（8个槽位），后台归档批处理仅允许使用 slot 2-7，必须预留 slot 0-1 给前台交互与元数据流量
- 除 loopback 测试环境外，IMAP 强制启用 TLS 加密传输；连接建立后二次校验 Peer IP 防御 SSRF

## decisions

- 基于 PostgreSQL Advisory Lock (0x4B4D_0000 + slot) 控制多进程连接槽位，避免进程意外终止导致死锁
- Graph 适配器采用三阶段 OAuth 刷新与 Bearer 传输，网络交互过程不占用凭证数据库行锁
- IMAP IDLE 会话独立管理连接与消费线程，绕过任务槽位预算，通过数据新旧度动态竞争有限席位（默认 32）
- 网络 I/O 与数据库事务严格分离，所有网络操作在短事务外部完成，仅在结果写入时开启短事务验证 fencing 并提交

## evidence

- src/mail_core/providers/connection_slots.py:91-118
- src/mail_core/providers/imap.py:728-765
- src/mail_core/providers/oauth.py:160-262
- src/mail_core/sync/leases.py:36-93
- src/mail_core/sync/checkpoints.py:22-112
- src/mail_core/sync/delta.py:133-299
- src/mail_core/sync/idle_watcher.py:181-214

## uncertainties

## Findings

- [Low][95] src/mail_core/providers/remote_writeback.py:40 — compress_uids 等函数类型标注引用未导入的 Sequence 类型

    - ID: f_backend_sync_01; verification: static
    - Evidence: src/mail_core/providers/remote_writeback.py:5 仅导入了 from typing import Any; src/mail_core/providers/remote_writeback.py:40 def compress_uids(uids: Sequence[int], ...) -> list\[str\]:; src/mail_core/providers/remote_writeback.py:45 def compress_uids_chunked(uids: Sequence[int], ...) -> list\[tuple\[str, list[int]\]\]:
    - Impact: 由于声明了 from __future__ import annotations，模块常规加载与运行时执行不受影响；但若使用 typing.get_type_hints 对该模块函数进行类型内省时，会抛出 NameError: name 'Sequence' is not defined。
    - Fix: 在 src/mail_core/providers/remote_writeback.py 顶部导入语句中增加 Sequence：from typing import Any, Sequence。

- [Medium][95] src/mail_core/providers/connection_slots.py:60-70, 431-453 — 模块级反射动态别名与历史签名 Shim，违反零兼容负担铁律

    - ID: f_arch_runtime_shim_and_deprecated_aliases; verification: static
    - Evidence: src/mail_core/providers/connection_slots.py:60-70 使用 __getattr__ 动态拦截对 TOTAL_SLOTS、BACKGROUND_START_SLOT 等已废弃常量的访问并重定向至 getter; src/mail_core/system_metrics.py:58-62 保留 @property max_sync_lag_seconds 作为 last_sync_lag_seconds 的废弃别名
    - Impact: 配置重构与属性更名后，为了不修改存量调用方代码，在模块中通过反射和属性别名维持向后兼容，违背零兼容负担原则，模糊模块真实公开接口契约。
    - Fix: 物理删除 connection_slots.py 中的 __getattr__ 常量拦截与废弃别名，删除 system_metrics.py 中的 max_sync_lag_seconds 属性别名，调用方直接引用最新权威命名。

- [High][95] src/mail_core/sync/patrol.py:8-9 — 为规避数据库迁移将 STATUS 巡检基线塞入 Checkpoint Cursor JSONB，违反架构至上铁律

    - ID: f_arch_patrol_state_in_checkpoint_cursor; verification: static
    - Evidence: src/mail_core/sync/patrol.py:8-9 注释明示: 'The probe baseline lives in the checkpoint cursor JSONB (last_status / last_probe_at) — no migration.'; docs/blueprint/architecture.md:113 亦记录该妥协决策
    - Impact: 为了规避一次正规 Alembic 数据库迁移，将本用于协议同步游标（IMAP UID / deltaLink）的 cursor 字段滥用为存储探测未读数、巡检时间戳的多用途杂物箱，破坏了领域模型的单一职责与纯粹性。
    - Fix: 创建正规数据模型与 Alembic 迁移脚本，为文件夹巡检状态建立独立的巡检基准表或字段，将巡检状态从 SyncCheckpoint.cursor 中彻底剔除。

- [Medium][90] src/mail_core/sync/engine.py:386-425 — 全局优先级数值微调代替收发拓扑解耦，违反拒绝妥协铁律

    - ID: f_arch_inbox_priority_numerical_tweak; verification: static
    - Evidence: src/mail_core/sync/engine.py:386-425 为优化收件箱响应，将收件箱 delta 任务分配 priority = 55，其余文件夹分配 60; docs/pending/todo/p073_manual_refresh_inbox_latency.md 明确承认：'文件夹发现 12.5s 仍在收件箱前，前端仍等全部文件夹完成后终态/停止旋转；因此按钮空转时长不会完全消失'
    - Impact: 未能从根因重构'先全量目录发现、再同步文件夹'的强耦合拓扑，不敢解耦前端终态模型，仅通过在单一全局优先队列里微调离散数值（55 vs 60）治标，导致跨账号优先级倒挂且未解决根本卡顿。
    - Fix: 重构收件箱同步拓扑：将收件箱实时同步与全量目录发现彻底解耦，收件箱同步直连触发；前端在收件箱任务完成后立即终态收尾，目录发现转为低频异步后台任务，删除优先级数值调优补丁。

## views

```json
{
  "security": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "correctness": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "contracts": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "performance": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "design": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "robustness": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "tests": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  },
  "documentation": {
    "status": "completed",
    "reviewer": "subagent_backend_2"
  }
}
```

## files_reviewed

```json
[
  "src/mail_core/providers/__init__.py",
  "src/mail_core/providers/base.py",
  "src/mail_core/providers/connection_slots.py",
  "src/mail_core/providers/factory.py",
  "src/mail_core/providers/graph.py",
  "src/mail_core/providers/host_security.py",
  "src/mail_core/providers/http.py",
  "src/mail_core/providers/imap.py",
  "src/mail_core/providers/oauth.py",
  "src/mail_core/providers/parsing/__init__.py",
  "src/mail_core/providers/parsing/graph_delta.py",
  "src/mail_core/providers/remote_writeback.py",
  "src/mail_core/providers/stub_memory.py",
  "src/mail_core/sync/__init__.py",
  "src/mail_core/sync/checkpoints.py",
  "src/mail_core/sync/delta.py",
  "src/mail_core/sync/engine.py",
  "src/mail_core/sync/execution.py",
  "src/mail_core/sync/idle_watcher.py",
  "src/mail_core/sync/jobs.py",
  "src/mail_core/sync/leases.py",
  "src/mail_core/sync/metadata.py",
  "src/mail_core/sync/patrol.py",
  "src/mail_core/sync/reconcile.py",
  "src/mail_core/sync/remote_push.py"
]
```
