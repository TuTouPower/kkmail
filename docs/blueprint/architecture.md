# 架构 (Architecture)

kkmail 是基于 `mail-core` 的现代化自托管多账号邮件客户端，采用前后端分层与单用户全生命周期设计。

更详尽的历史架构规范见 [`docs/archive/legacy_architecture/mail-core-architecture.md`](../archive/legacy_architecture/mail-core-architecture.md)。

## 系统拓扑与进程划分

1. **后端核心 (`src/mail_core/`)**：
    - 框架：FastAPI + SQLAlchemy 2.0 (psycopg) + Alembic。
    - 职责：提供统一 REST API、事务性 Outbox 事件分发、多协议邮件增量同步引擎与工作进程 (Worker)。
    - 进程模型：支持单进程模式（API 嵌入 Worker 线程）或生产拆分模式（独立的 API 容器与 Worker 容器）。
2. **前端界面 (`src/frontend/`)**：
    - 技术栈：React 19 + TypeScript + Vite + TanStack React Query + Lucide Icons。
    - 特点：单页应用 (SPA)，由 `mail-core` 同源托管提供；基于 `useInfiniteQuery` 实现游标深翻页，原生集成 SSE 流式状态同步。侧边栏个人收藏提供「所有收件箱」、「所有未读」、「所有已发邮件」三折叠树导航，支持全局与按账号维度多路分类切换。邮件详情工具栏操作居中显示并支持已读/未读状态双向响应；邮件列表支持右键上下文菜单（Context Menu）。
3. **桌面集成 (`src/desktop/`)**：
    - 运行环境：Electron 主进程。
    - 职责：进程生命周期管理，启动内置 PostgreSQL 实例与 `mail_core` sidecar 进程，支持 macOS/Linux/Windows 跨平台运行。

## 模块分层与数据流

- **API 接入层 (`src/mail_core/api/`)**：
    - 路由声明：统一 `response_model`，输入经 Pydantic 校验。
    - 安全鉴权：Cookie Session 签名与防篡改、Session Epoch 全局失效、CSRF 严格校验、反向代理受信与登录防爆破。
- **业务领域与应用层 (`src/mail_core/mail/application/`, `src/mail_core/accounts/`)**：
    - 账户生命周期、邮件查询、聚合收件箱游标检索与全文搜索。`/api/mail/inbox` 支持通过 `folder_role`（默认 `inbox`，支持 `sent`/`drafts`/`trash`/`junk`/`archive` 等）或精确 `folder_id` 联合 `account_id` 实现多账号统一/单账号分类及特定文件夹邮件检索，保证多位置邮件去重与 keyset 翻页一致性。前端侧栏支持六大个人收藏分类与账号入库文件夹树导航。
    - 出站写回状态机：基于 `remote_operations` 队列与单调递增 `revision` 的乐观并发控制 (CAS)；支持多批次自动续跑、瞬时错误与限流退避延迟唤醒、跨同步边界的本地字段意图保护与孤儿任务安全对账恢复。
- **同步引擎与协议适配 (`src/mail_core/sync/`, `src/mail_core/providers/`)**：
    - 适配器：IMAP (带 TLS 校验与特殊文件夹转义)、Gmail REST (repeated historyTypes + History hydration)、Microsoft Graph v1.0 (well-known 收件箱别名与子目录递归)。
    - 并发保护：基于数据库的租约锁 (`AccountSyncLease`) 与递增 fencing token。
- **存储与加密层 (`src/mail_core/blobs/`, `src/mail_core/mail/storage/`)**：
    - 原文存储：内容寻址分块 AES-256-GCM 流式加密 (`KKMS`)，支持多版本密钥轮换。
    - 附件与垃圾回收：严格追踪 `MessageBlobLink` 与 `Attachment.blob_id` 双重引用，Fail-Closed 二次校验防误删。
    - MIME 解析错误传递链路：Worker 归档期解析正文、报头或附件文件名失败时，保存 raw MIME 至 BlobStore 确保可恢复性，并持久记录脱敏 `MessageBody.parse_error`；详情 API (`/api/mail/messages/{id}`) 完整返回该字段；前端 `mailCoreToMailDetail` 转换透传至 `MailDetail.parse_error`，`MessageReader` 以可访问 alert 横幅明确提示解析失败及原因，即使存在摘要或部分内容亦不被静默吞掉或伪报为空正文。
