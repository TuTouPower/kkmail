# 架构 (Architecture)

kkmail 是基于 `mail-core` 的现代化自托管多账号邮件客户端，采用前后端分层与单用户全生命周期设计。

更详尽的历史架构规范见 [`docs/archive/legacy_architecture/mail-core-architecture.md`](../archive/legacy_architecture/mail-core-architecture.md)。

## 系统拓扑与进程划分

1. **后端核心 (`src/mail_core/`)**：
    - 框架：FastAPI + SQLAlchemy 2.0 (psycopg) + Alembic。
    - 职责：提供统一 REST API、事务性 Outbox 事件分发、多协议邮件增量同步引擎与工作进程 (Worker)。提交即 NOTIFY 由 SQLAlchemy Session 统一保证：任何写入 `OutboxEvent` 并提交的事务，由 session 事件在 `before_commit` 向 `mail_core_outbox` 发出单次 NOTIFY，避免分散手工调用遗漏。
    - 进程模型：支持单进程模式（API 嵌入 Worker 线程）或生产拆分模式（独立的 API 容器与 Worker 容器）。Worker 采用按连接预算并发执行器（执行位数量等于 `total_slots`，后台批量归档限制在途数不超过 `total_slots - background_start_slot`，前台保留至少 `background_start_slot` 槽位即刻消费用户交互与元数据任务；同账号租约任务认领期互斥；单次执行持有唯一 execution_owner 避免租约 fencing 与归档认领冲突；统一全局心跳为在途任务续期；停机在超时内等待在途任务优雅结算）。Worker 内部启动 `JobWakeListener` 监听 `mail_core_jobs` 通道，任务入队事务提交即唤醒空闲等待（1 秒内抢占认领）；监听连接抖动或断开时基于指数退避自动重连，断连期间 Worker 主循环退化为基于空闲退避的定时轮询，保障调度连续性。
2. **前端界面 (`src/frontend/`)**：
    - 技术栈：React 19 + TypeScript + Vite + TanStack React Query + Lucide Icons。
    - 特点：单页应用 (SPA)，由 `mail-core` 同源托管提供；基于 `useInfiniteQuery` 实现游标深翻页，原生集成 SSE 流式状态同步。侧栏按“所有账号／用户自定义分组／账号列表”组织导航，保留六类全局分类、分组分类、每账号分类与真实文件夹访问。邮件详情工具栏操作居中显示并支持已读/未读状态双向响应；邮件列表支持右键上下文菜单（Context Menu）。邮件正文在深色模式下支持智能反转（CSS 滤镜将浅色白底反转为深底，媒体元素二次反转还原色彩，微光轮廓保护透明暗色 Logo），工具栏提供单信原样/深色切换按钮（`MR11`），通用设置支持正文深色偏好持久化。网页壳的侧栏按钮固定在邮件列表标题行；Electron macOS 使用原生标题栏交通灯，侧栏按钮放在其旁边，Windows/Linux 保留系统窗口框架。
3. **桌面集成 (`src/desktop/`)**：
    - 运行环境：Electron 主进程。
    - 职责：进程生命周期管理，启动内置 PostgreSQL 实例与 `mail_core` sidecar 进程，支持 macOS/Linux/Windows 跨平台运行；窗口选项按平台选择原生框架，macOS 自定义标题栏只覆盖网页内容区，不接管系统交通灯。

## 模块分层与数据流

- **API 接入层 (`src/mail_core/api/`)**：

    - 路由声明：统一 `response_model`，输入经 Pydantic 校验。
    - 安全鉴权：Cookie Session 签名与防篡改、Session Epoch 全局失效、CSRF 严格校验、反向代理受信与登录防爆破。

- **业务领域与应用层 (`src/mail_core/mail/application/`, `src/mail_core/accounts/`)**：

    - 账户生命周期、用户自定义单层分组、邮件查询、聚合收件箱游标检索与全文搜索。分组顺序、账号总列表顺序与组内顺序持久化在 PostgreSQL；`GET /api/sidebar/layout` 返回完整布局与 revision，`PUT /api/sidebar/layout` 和默认顺序恢复携 expected_revision，在事务锁下拒绝过期快照并原子保存；账号、分组与布局写入共用 PostgreSQL advisory lock，默认账号顺序按邮箱域名及完整地址确定。
    - `/api/mail/inbox` 支持通过 `folder_role`（默认 `inbox`，支持 `sent`/`drafts`/`trash`/`junk`/`archive` 等）或精确 `folder_id` 联合 `account_id` 或 `group_id` 实现多账号统一、单账号、分组分类及特定文件夹检索；`/api/mail/search` 同样支持全局、单账号、分组或精确文件夹范围，拒绝分组与账号/文件夹混用，保证搜索统计和邮件列表隔离。批量已读按当前分组成员解析；空组保持空结果，不存在分组或歧义范围请求失败关闭。
    - `sync_enabled=false` 的账户不进入全局/分组聚合邮件列表、搜索、统计与批量已读；显式账号/文件夹查询保持直达语义。列表和搜索响应返回每封邮件在所属账号内的全部文件夹位置，按页批量读取，支持准确乐观更新同角色多文件夹计数。
    - 邮件详情保留原始 `to`/`cc` 展示文本，并通过标准邮件地址解析器返回结构化 `to_addresses`/`cc_addresses`；可靠地址单独提供邮箱，无法可靠解析的片段保留文本且不生成复制目标。
    - 批量标记已读在请求开始时固定分组成员集，按 `Message.id` 升序 keyset 每批最多 500 封独立事务提交；中途失败保留已完成批次，重试只处理余下未读邮件，每封远端操作仍经 `remote_operations` 与事务性 Outbox 收敛。
    - 远端文件夹身份由 `remote_id` 确定，`role` 只用于分类查询；同账号多个文件夹即使共享 role，也必须保持独立可访问并在侧栏显示可区分名称。Graph 已取得 well-known Inbox ID 时以该 ID 为准，不将同名自定义文件夹回退为第二个收件箱。
    - 出站写回状态机：基于 `remote_operations` 队列与单调递增 `revision` 的乐观并发控制 (CAS)；支持多批次自动续跑、瞬时错误与限流退避延迟唤醒、跨同步边界的本地字段意图保护与孤儿任务安全对账恢复。推送采用批量管道（一次最多 500 条）：IMAP 单连接复用登录，按（源文件夹，操作类型，目标值）分组发送 UID 集合 STORE/MOVE 并做 1000 字符区间分块；Graph 使用 JSON batching（单批上限 20 个子请求）；执行期间不设人为时间合并窗口，推送完成后逐条按 revision CAS 独立结算，中途并发变更的操作回到 PENDING 重推。

- **同步引擎与协议适配 (`src/mail_core/sync/`, `src/mail_core/providers/`)**：

    - 适配器：IMAP (带 TLS 校验与特殊文件夹转义；默认 Socket 超时放宽至 60s；`\NonExistent` 过滤，`\Noselect` 保留为不可选择的树节点且不排邮件同步任务；Gmail 账号下 `\All` 与 `\Important` 等虚拟全量标签默认置为 `paused`，避免收件箱与已发送邮件全量重复拉取；RFC 6154 支持 `\All` 映射为 `all` 与 `\Flagged` 映射为 `flagged`)、Microsoft Graph v1.0 (well-known 收件箱别名与子目录递归；默认共享 OAuth JSON transport 对 GET/HEAD 的 503/504、网络断连与 TLS EOF 最多重试 3 次，等待按 1/2/3 秒线性递增；正数 `Retry-After` 可覆盖 503/504 等待，最高 10 秒，其他方法不重放)。
    - 并发保护与容错：基于数据库的租约锁 (`AccountSyncLease`) 与递增 fencing token；Worker 捕获瞬态网络超时（`TimeoutError`、`SSLEOFError` 等）进行指数退避重试，未达重试上限时不污染账户为 `failed` 状态。
    - 同步分批：`sync_folder_metadata` 默认单任务最大页数控制在 10 页（约 500 封），避免大目录单次长时间霸占连接与 Worker 队列。
    - 元数据保真：provider 通过 `RemoteMessageMeta.supplied_fields` 区分完整快照与部分返回字段，metadata upsert 按字段存在性应用；同页 partial/flag 按响应顺序合并，缺省字段不清空本地事实。Graph 内容字段显式空值仍可清空。
    - 未知状态：邮件 read/flag/attachment 使用 nullable 布尔契约贯穿 PostgreSQL、查询 DTO、API 与前端；新建邮件不补 false。文件夹存在未知读状态时未读统计为 null，账号/分组/全局聚合传播未知而保留可知总数。旧库仅迁移已有状态列，无 flag 来源时保留 null。

- **存储与加密层 (`src/mail_core/blobs/`, `src/mail_core/mail/storage/`)**：

    - 原文存储：内容寻址分块 AES-256-GCM 流式加密 (`KKMS`)，支持多版本密钥轮换。
    - 附件与垃圾回收：严格追踪 `MessageBlobLink` 与 `Attachment.blob_id` 双重引用，Fail-Closed 二次校验防误删。
    - MIME 解析错误传递链路：Worker 归档期解析正文、报头或附件文件名失败时，保存 raw MIME 至 BlobStore 确保可恢复性，并持久记录脱敏 `MessageBody.parse_error`；详情 API (`/api/mail/messages/{id}`) 完整返回该字段；前端 `mailCoreToMailDetail` 转换透传至 `MailDetail.parse_error`，`MessageReader` 以可访问 alert 横幅明确提示解析失败及原因，即使存在摘要或部分内容亦不被静默吞掉或伪报为空正文。

## 桌面主进程与安全复制边界

1. **桌面主进程日志基础设施 (`desktop.log`)**：
    - 主进程启动时在 `userData` 目录下建立 `desktop.log` 文件日志并接入 `RotatingLogStream` 轮转；
    - 捕获主进程启动阶段（PID、平台、架构、Electron/Node 版本）、关键生命周期事件及未捕获异常（`uncaughtException` / `unhandledRejection`），并在应用退出时优雅 flush 与 close；
    - 解决桌面端无控制台环境下主进程报错无从排查的缺口。
2. **桌面剪贴板授权与安全边界**：
    - 文本复制授权遵循最小权限原则：Electron 会话加固仅对受信任的本地顶层应用页面（`details.isMainFrame === true` 且请求 URL 匹配 `appOrigin`）开放 `clipboard-sanitized-write` 权限；
    - 邮件内容沙箱隔离：邮件正文所在的无脚本 `iframe` 显式属于子 frame（`isMainFrame === false`），其剪贴板写入请求被严格拒绝，无法写入系统剪贴板；
    - 权限降级与防范：剪贴板读取（`clipboard-read`）、媒体设备（`media`）、定位及通知等无关系统权限无条件保持拒绝；
    - 前端显式入口调用：UI 编号浮标（`UiReferenceOverlay`）、错误边界（`ErrorBoundary`）与邮箱复制控件（`CopyAddress`）均由用户点击后通过标准 `navigator.clipboard.writeText` 写入；缺失或被拒时提供明确失败反馈，不新增 IPC，也不使错误边界二次崩溃。

## 按需邮件正文同步与归档调度治理

1. **按需即时正文归档链路**：
    - 当客户端显式触发（`POST /api/mail/messages/{id}/sync-body`）且正文未归档时，系统将该邮件在 `MessageArchiveState` 的优先级提升为最高（`priority = 0`），并向任务队列入队最高优先级即时归档任务（`priority = 10`，去重键 `archive_msg:{id}`）；`GET /api/mail/messages/{id}` 只读，不改变归档状态或创建任务；
    - `POST /api/mail/messages/{id}/sync-body` 只负责入队并返回 HTTP 202、`message_id` 与 `job_id`；请求进程不执行 MIME 拉取。Worker 完成后更新 `MessageArchiveState` 并保存正文/附件，详情 API 返回 `archive_state` 与脱敏错误是否存在的布尔值；带目标 `message_id` 的 `archive.progress` / `archive.paused_quota` SSE 事件使阅读器刷新状态；
    - 网络拉取失败写入 `MessageArchiveState.last_error`，MIME 解析失败写入 `MessageBody.parse_error`，两类错误在详情与阅读器中保持区分。阅读器呈现排队、处理中、完成、失败或配额暂停状态，失败时允许重新提交任务。
2. **Worker 任务调度优先级治理与并发执行器 (t063)**：
    - 针对文件夹定时空转轮询导致的归档饥饿，调整任务优先级分层：按需归档任务为 **10**，出站写回操作为 **40**，初次目录扫描为 **50**，后台批量正文归档续批为 **60**，文件夹定时空转增量轮询为 **75**，定期对账任务为 **80**；
    - 执行器由原单线程串行执行改为大小等于 `total_slots` 的并发执行池，彻底消除单账号慢网络长任务堵死全队列的队头阻塞缺陷；
    - 严格匹配连接槽 8/6 规则：后台批量归档任务（`archive_mime_batch` 无 `message_id`）最多同时占用 `total_slots - background_start_slot` 个执行位，剩余执行位永久为前台即时任务（按需即时归档、写回、元数据扫描）保留；
    - 租约任务认领期排他：同账号在途执行租约类任务（`sync_account_folders`、`sync_folder_metadata`、`sync_folder_delta`、`reconcile_folder`、`remote_operation_push`）时，该账号其他租约任务跳过认领，绝不引发同账号内部 `lease_busy` 自锁或争抢；不同账号并行执行；同账号非租约归档任务可与租约任务安全并行。
    - 定时增量空转轮询增加去重键（`delta:{account_id}:{folder_id}`），防止单个文件夹在短时间内重复入队堆积，彻底解除增量轮询对后台批量正文归档的压制。

## 供应商账户配置与 Microsoft OAuth 授权

供应商品牌存于 `Account.config.provider_profile`，协议仍由 `imap`/`graph` 路由；设置页共享添加/编辑表单，品牌预设不覆盖用户连接参数。账户 DTO 只返回白名单连接信息，OAuth 秘密不回显。Microsoft IMAP 在账户入口及 provider factory 被拒绝。`DbCredentialStore` 的 `credential_edit` 在当前事务锁定加密行，账户局部更新与 OAuth 刷新共用该锁。

Google 账户仅通过标准 IMAP 接入：服务器 `imap.gmail.com`，凭据为 Google 账户的应用专用密码。不提供 Gmail API 或 Google OAuth 路径，不存在 `gmail` 协议。

OAuth 最终保存统一按 sidebar 组织锁 → 账户（编辑）→ 流程 → 凭据/活跃指针顺序取锁，新增与重新授权均先取组织锁。活跃指针写入及条件清空共用引用 advisory lock；授权码以相同锁原子领取，避免缺行锁竞争。

Microsoft Graph 同时提供授权码 + PKCE 和设备码流程，复用相同 `oauth_flow` 会话绑定、加密状态与最终消费。供应商协议位于 `microsoft_oauth.py`，设备码步骤在 `device_oauth.py`；不新增第二套账户提交或令牌缓存。Microsoft 桌面回调使用 `localhost` 动态端口（仅该主机名享有微软忽略端口规则），Web 回调继续来自可信 HTTPS Origin。

设备码仅通过原认证会话带 CSRF 的 `POST /api/accounts/oauth/flows/{id}/poll` 驱动；服务端在同一跨进程流程锁内判断 `next_poll_at` 并执行到期的一次请求，多次前端查询不会增加供应商轮询频率。等待、slow_down/429、拒绝、取消及期限均由后端收敛，有效期取供应商期限与 10 分钟较短值。长 device_code 只存在加密流程中，短 user_code 与官方验证 URI 返回原会话，所有 OAuth 响应禁止缓存。

两种微软方式均申请 Graph 委托 Mail.ReadWrite、User.Read 和 offline_access；不解析 Access Token。通过 `/me` 的 `id` 与 `mail` 及 inbox 可访问性核实身份，不用 UPN 猜邮箱。成功暂存后必须显式保存；重新授权精确核对原邮箱、已存微软用户 ID、客户端及租户，旧 Graph 无用户 ID 时以真实邮箱建立身份，保留分组与同步偏好。远端身份与租户保存在账户 config，不改邮件身份或恢复 Microsoft IMAP。

## 收件箱定时轮询调度与增量正文自动存库 (t057)

1. **Worker 独立错峰巡检调度器**：
    - 废除任务执行尾部的 30 秒自调度逻辑，由 Worker 主循环的 `_schedule_periodic_sync_once` 每 60 秒定期巡检；
    - 对所有 `sync_enabled=True` 账号的有效收件箱（`role="inbox"` 且非 paused），若距离上次成功同步超过设定阈值（默认 1200 秒 / 20 分钟，环境变量 `MAIL_CORE_INBOX_POLL_INTERVAL_S` 可调），且无在途任务，自动入队 `SYNC_FOLDER_DELTA`（`priority = 75`）；
    - 批量超期任务采用时间窗口错峰打散（Stagger），将各任务的 `run_after` 均匀分散在轮询周期内，避免多账号（如 300 邮箱）并发触发服务商连接风控与本地队列雷暴。
2. **增量收信连带正文自动存库流水线**：
    - 增量同步（`sync_folder_delta`）拉取新邮件元数据并持久化入库后（`upserted > 0`），自动在同事务中入队 `ARCHIVE_MIME_BATCH`（`priority = 60`，去重键 `archive_mime_batch:{account_id}`）；
    - Worker 消费该归档任务拉取完整 RFC 822 MIME 数据流，加密落入 Blob 存储并解析正文，直接将提取出的 HTML/纯文本持久化写入 PostgreSQL `message_bodies` 表，彻底闭环自动收信并提取具体内容存库链路。

## IDLE 收件箱实时监听与全文件夹 STATUS 周期巡检 (t061)

1. **IDLE 唤醒通道（信号与拉取分离）**：
    - Worker 进程内 `IdleWatcherManager` 为符合条件的 IMAP 账号维持至多一条收件箱 IDLE 长连接；IDLE 只作新邮件到达信号，唤醒后入队既有 `SYNC_FOLDER_DELTA`（去重键 `delta:{account_id}:{folder_id}`），实际拉取仍走 delta 流水线（基线门禁、账号租约、fencing 不变），watcher 不直接读写邮件数据；
    - 长连接走独立配额（集中配置默认 32，与账号总数无关），不占用 `connection_slots` 的 8 个任务槽位；配额席位只按邮件数据分配：以收件箱内现存邮件的服务器到达时间（INTERNALDATE）最大值倒序为主序，空收件箱账号整体居后（组内按其他文件夹到达时间、账号创建时间、账号 id 定序），同组内带滞回防抖；持有 IDLE 的账号跳过 t057 收件箱轮询、让位后恢复轮询；
    - 无 IDLE 能力、永久认证失败、反复断线退避中的账号自动降级为纯轮询，watcher 异常不影响调度主循环，也不把账号标记为永久 failed；watcher 状态经 `AppSetting` 的 `worker:idle_state` 记录暴露。
2. **全文件夹 STATUS 周期巡检**：
    - Worker 调度周期内对全部非收件箱、非 paused 文件夹做短连接 STATUS 探测（IMAP STATUS 不 SELECT 不 FETCH；Graph 以文件夹计数接口探测），探测连接走任务槽位预算；
    - 探测基线快照存 `SyncCheckpoint.cursor` 的 `last_status`（总数 / UIDNEXT / 未读 / modseq），不新增数据库迁移；仅双方均有值的维度参与变化判定，无变化零入队，变化才以 `priority = 75` 入队 delta；单轮上限与最久未探测轮转治理规模，单夹失败隔离不影响其余文件夹；
    - 集中配置提供 IDLE 与巡检两个独立开关，两者都关即回到 t057 现状。

## 同步模式边界治理与新账号全量隔离

1. **新账号全量基线约束**：新账户首次接入必须通过 `SYNC_ACCOUNT_FOLDERS` 识别目录，对无 `full_scan_complete` Checkpoint 的文件夹触发 `SYNC_FOLDER_METADATA` 全量历史拉取，建立完整基线。
2. **日常同步接口 100% 增量化**：`/api/accounts/sync-all` 与 `/api/accounts/{account_id}/sync` 的 `mode` 严格收敛为 `"delta"`；文件夹发现层若检测到该目录已具备基线，自动流转为 `SYNC_FOLDER_DELTA`，几秒内秒级完成，彻底杜绝日常操作误触历史全量扫描而阻断新邮件发现。
3. **全量重扫异常自愈隔离**：全量历史重新拉取仅限远端游标失效（`CursorInvalidError`）时触发自愈重建，禁止暴露为日常常规触发路径。

## 远程图片放行存储与正文内联图片 Signed URL 预览 (t066)

1. **远程图片放行模型**：
    - `message_remote_image_allows`：主键 `message_id` 外键关联 `messages.id`（`ondelete="CASCADE"`），记录用户针对单封邮件的放行授权；
    - `sender_remote_image_allows`：唯一索引 `from_address`，记录全局跨账号的发件人白名单；
    - 邮件详情接口根据上述两表联合计算返回 `remote_images_allowed: bool` 与 `can_allow_sender: bool`。
2. **正文内联附件 Signed URL 架构**：
    - 后端通过 `sign_inline_image_preview_token` 为内联位图签发确定性 HMAC-SHA256 Token（绑定 `version`、`purpose`、`attachment_id`、时间戳，15 分钟失效）；
    - 挂载独立无 Cookie 预览端点 `GET/HEAD /api/mail/attachments/{id}/preview`，仅凭有效 Token 鉴权放行流式响应；响应强制设置 `Content-Disposition: inline`、`X-Content-Type-Options: nosniff`，严格校验真实位图魔数（排除 SVG 及可执行文件）；
    - 前端在离线 DOM 解析正文将 `<img src="cid:...">` 重写为此签名 URL，浏览器在严格沙箱 iframe（无 `allow-same-origin`）内原生流式拉取图片，彻底杜绝前端 Base64 内存膨胀。

## 服务端安全图片代理与零外部出网架构 (t068)

1. **零外部出网安全基线与彻底消解 CSP 继承死锁**：
    - 根据 HTML Standard policy container 与 CSP3 规范（`d003`），沙箱 `srcdoc` 强制继承宿主应用 CSP，且 Electron 桌面端对全 session 响应强制下发 `img-src 'self' data: blob:`；
    - 采用现代 Webmail 工业级标准架构（Gmail / ProtonMail / Fastmail 等）：宿主 SPA、桌面端及邮件沙箱 iframe 的 CSP 统一且永久定格为 `'self' data: cid:`，全站全程零浏览器直连外部出网，第三方追踪器无法探知用户真实 IP、浏览器指纹或网络环境。
2. **服务端安全图片代理 (Image Proxy)**：
    - 独立挂载无 Cookie 代理端点 `GET/HEAD /api/mail/messages/{id}/remote-images`，使用 `itsdangerous`（专用 salt）强绑定 `version=1`、`purpose="remote-image"`、`message_id`、`url` 与时间戳；
    - 每次代理请求实时核验目标邮件在数据库中的放行状态（单封放行或发件人白名单），撤销白名单立即生效（403）；
    - 严密 SSRF 防护门禁：严格排除私网、回环、链路本地、云元数据（169.254.169.254）、CGNAT、保留段与 IPv4-mapped IPv6；直连安全 IP 且保留 TLS SNI 证书核验，彻底免疫 DNS Rebinding；限制最多 3 跳重定向且逐跳重新安全核验；
    - 资源边界与魔数核验：限制最大读取 10 MiB（超限立即断开）、5s 连接 / 15s 总读取超时；严格按真实文件头魔数校验受控安全位图（PNG/JPEG/GIF/WebP），拒绝 SVG、HTML、JS 及可执行格式。
3. **正文外链 URL 代理重写**：
    - 服务端详情接口在已放行状态下提取正文外链 URL，签发 `remote_images: [{ url, proxy_url }]`（上限 200 个）；
    - 前端 `prepareMailHtml` 在放行后将正文中的 `img[src]` 及行内样式 `background-image: url(...)` 安全重写为本站代理 URL，在严格沙箱内流式加载解码。
