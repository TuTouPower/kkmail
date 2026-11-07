# bundle_local_backend_core

## responsibilities

- 提供 mail-core 核心 HTTP 路由与中间件防护层（FastAPI 应用、双重认证模式、安全头、CORS、SPA 静态文件托管）
- 维护系统会话（Session Cookie + CSRF Header）与 API Key 鉴权机制，支持会话代际递增强制登出
- 管理多账号配置、分组归属与侧边栏拖拽排序布局，通过数据库咨询锁保障全局一致性
- 驱动 Microsoft OAuth2 授权码流程（PKCE）与设备码流程生命周期，完成重定向令牌安全交换与邮箱验证
- 实现基于 PostgreSQL LISTEN/NOTIFY 与 Outbox 序列的 Server-Sent Events (SSE) 实时推送及增量重放
- 维护 Alembic 数据库版本迁移链（0001~0030）与 PostgreSQL 事务钩子（NOTIFY 投递管理）

## interfaces

- HTTP /health, /ready, /api/system/health (健康与就绪检查)
- HTTP /api/auth/login, /api/auth/logout, /api/auth/me, /api/auth/password (认证管理)
- HTTP /api/accounts, /api/accounts/{account_id}, /api/accounts/{account_id}/sync, /api/accounts/sync-all (账号管理与同步触发)
- HTTP /api/groups, /api/groups/{group_id}, /api/sidebar/layout, /api/sidebar/layout/default-order (分组与侧边栏布局)
- HTTP /api/accounts/oauth/metadata, /active, /start, /exchange-redirect-url, /flows/{id}, /poll, /cancel, /callback/{provider} (OAuth 生命周期)
- HTTP /api/events (SSE 实时事件流与重放)
- HTTP /api/mail/... (统一收件箱、文件夹统计、搜索、邮件详情、标记已读/星标/删除、内联图片预览与远程图片代理)
- Python mail_core.accounts.service: create_account, update_account, delete_account, list_accounts, save_sidebar_layout
- Python mail_core.accounts.credentials: get_credential_store, credential_edit, load_json_secret, save_json_secret
- Python mail_core.accounts.oauth_flow: start_oauth_flow, complete_oauth_callback, poll_device_flow
- Python mail_core.db.session: get_engine, get_session_factory, database_url
- Python mail_core.db.events: install_session_wake_hooks

## dependencies

- fastapi
- starlette
- pydantic
- sqlalchemy
- alembic
- psycopg
- cryptography
- mail_core.mail.application
- mail_core.mail.storage
- mail_core.security
- mail_core.realtime

## flows

- 请求过滤流：HTTP 请求 -> SecurityHeadersMiddleware (HSTS/CSP/XFO/nosniff) -> TraceIdMiddleware (X-Request-ID) -> require_auth 依赖注入校验 Bearer 或 Session Cookie + 非幂等请求 CSRF Token
- 账号与布局变更流：API 请求 -> 校验输入模型 -> 获取 SIDEBAR_LAYOUT_LOCK_ID 事务级咨询锁 -> 加载目标行并加行级锁 -> 校验 expected_revision 乐观锁 -> 执行变更 -> 提交事务
- OAuth 认证流：客户端请求 /api/accounts/oauth/start -> 生成 PKCE verifier 与 state 记录到凭据存储 -> 重定向到微软登录 -> 回调端点完成授权码交换 -> 严格核验 /me 邮箱与收件箱有效性 -> 暂存凭据供前端保存
- SSE 事件流：客户端发起 GET /api/events -> 校验 session_epoch -> 申请并发槽位 (上限128) -> 异步读取历史 Outbox 帧构建重放计划 -> 订阅 Dispatcher 队列进行 live-tail 监听 -> 定期校验代际并发送 keepalive -> 优雅断开并回收槽位

## constraints

- 严禁在 API 响应或日志中明文输出密码、OAuth 刷新令牌或 Client Secret 等机密信息
- 侧边栏布局保存必须传入精确匹配的 expected_revision，否则返回 409 冲突
- 账号与分组的所有写操作必须持有统一咨询锁 SIDEBAR_LAYOUT_LOCK_ID，严格单向加锁杜绝死锁
- 对微软域名邮箱或主机配置明确禁止使用 IMAP，强制拦截并引导使用 Graph OAuth
- SSE 连接实施软上限保护（默认 128），超限返回 503 Service Unavailable

## decisions

- 坚守架构至上与零兼容负担：彻底推倒历史遗留架构，构建 FastAPI + SQLAlchemy 2.0 纯净接口层
- 安全优先设计：凭据一律经 HKDF 派生密钥 AES-256-GCM 加密落盘于 credential_secrets，会话密码变更全局递增 session_epoch 吊销旧会话
- 性能极致考量：侧边栏布局采用无联结分步查询并本地组装，规避笛卡尔积开销；账号列表单次计算统计总数

## evidence

- src/mail_core/api/app.py:57-78
- src/mail_core/api/app.py:105-145
- src/mail_core/api/deps.py:26-81
- src/mail_core/api/sse.py:255-369
- src/mail_core/accounts/service.py:27-80
- src/mail_core/accounts/service.py:275-291
- src/mail_core/accounts/credentials.py:348-401
- src/mail_core/accounts/device_oauth.py:56-141
- src/mail_core/db/session.py:79-102
- src/mail_core/db/events.py:120-150

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
  "src/mail_core/accounts/__init__.py",
  "src/mail_core/accounts/connection.py",
  "src/mail_core/accounts/credentials.py",
  "src/mail_core/accounts/device_oauth.py",
  "src/mail_core/accounts/microsoft_oauth.py",
  "src/mail_core/accounts/oauth_flow.py",
  "src/mail_core/accounts/service.py",
  "src/mail_core/accounts/settings_store.py",
  "src/mail_core/api/__init__.py",
  "src/mail_core/api/accounts.py",
  "src/mail_core/api/app.py",
  "src/mail_core/api/auth_routes.py",
  "src/mail_core/api/deps.py",
  "src/mail_core/api/http_headers.py",
  "src/mail_core/api/mail.py",
  "src/mail_core/api/oauth_routes.py",
  "src/mail_core/api/sse.py",
  "src/mail_core/db/alembic.ini",
  "src/mail_core/db/alembic/env.py",
  "src/mail_core/db/alembic/script.py.mako",
  "src/mail_core/db/alembic/versions/20261020_0001_baseline.py",
  "src/mail_core/db/alembic/versions/20261020_0002_mail_core_unified_schema.py",
  "src/mail_core/db/alembic/versions/20261021_0003_message_fts.py",
  "src/mail_core/db/alembic/versions/20261021_0004_jobs_dedupe_folder_index.py",
  "src/mail_core/db/alembic/versions/20261021_0005_groups_settings.py",
  "src/mail_core/db/alembic/versions/20261021_0006_search_attachment_indexes.py",
  "src/mail_core/db/alembic/versions/20261021_0007_credential_secrets.py",
  "src/mail_core/db/alembic/versions/20261021_0008_blob_gc_eligible_at.py",
  "src/mail_core/db/alembic/versions/20261021_0009_inbox_keyset_indexes.py",
  "src/mail_core/db/alembic/versions/20261021_0010_message_blob_links_blob_id_index.py",
  "src/mail_core/db/alembic/versions/20261021_0011_remote_operations_next_attempt_at.py",
  "src/mail_core/db/alembic/versions/20261021_0012_auth_credentials.py",
  "src/mail_core/db/alembic/versions/20261021_0013_auth_credentials_session_epoch.py",
  "src/mail_core/db/alembic/versions/20261022_0014_indexes_archive_thread_search.py",
  "src/mail_core/db/alembic/versions/20261022_0015_blob_quota_and_attachment_part.py",
  "src/mail_core/db/alembic/versions/20261023_0016_sidebar_account_order.py",
  "src/mail_core/db/alembic/versions/20261023_0017_nullable_message_sort_time.py",
  "src/mail_core/db/alembic/versions/20261023_0018_nullable_message_remote_id.py",
  "src/mail_core/db/alembic/versions/20261023_0019_nullable_message_status.py",
  "src/mail_core/db/alembic/versions/20261025_0020_worker_job_failure_attempts.py",
  "src/mail_core/db/alembic/versions/20261025_0021_account_email_lower_unique.py",
  "src/mail_core/db/alembic/versions/20261026_0022_outbox_publication_seq.py",
  "src/mail_core/db/alembic/versions/20261026_0023_sync_requests_and_targets.py",
  "src/mail_core/db/alembic/versions/20261026_0024_archive_claim_revision.py",
  "src/mail_core/db/alembic/versions/20261026_0025_sync_execution_tracking.py",
  "src/mail_core/db/alembic/versions/20261026_0026_outbox_retention_watermark.py",
  "src/mail_core/db/alembic/versions/20261027_0027_search_recipient_and_account_recipients.py",
  "src/mail_core/db/alembic/versions/20261027_0028_rebuild_recipient_search_text.py",
  "src/mail_core/db/alembic/versions/20261027_0029_check_constraints_core.py",
  "src/mail_core/db/alembic/versions/20261031_0030_remote_image_allowlists.py",
  "src/mail_core/db/base.py",
  "src/mail_core/db/events.py",
  "src/mail_core/db/session.py"
]
```
