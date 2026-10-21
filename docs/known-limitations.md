# 已知限制与规划清单 (Known Limitations & Backlog)

本文档记录 kkmail 当前的技术限制、产品边界与演进规划，分为**已决策（暂不处理）**与**待办现状（完成度、暗坑与待实现项）**两部分。

---

## 一、已决策（暂不处理）

以下条目已由产品与架构方案明确锁定，确认为当前阶段不予处理或超出范围的设计：

- **单用户架构 (Single user)**：单登录密码保护实例，无多租户、用户角色或行级 ACL；Bearer API Key 具备同等全量权限。在此边界内，资源 UUID（邮件、附件、账户等）即能力凭据（Capability），知晓 UUID 即获 API 访问权限，非多租户防 IDOR 安全标识。
- **无浏览器扩展 (No browser extension - wontfix)**：永久不发布浏览器扩展；原 `browser-extension/` 目录与 `/api/extension/*` 桥接已彻底废弃并移除，禁止重新引入。
- **无多皮肤支持 (No system skins)**：移除 Flask 时期的外部皮肤包与模板系统；外观严格限定为 SPA 内置的亮色、暗色及跟随系统主题。
- **不支持发邮件 (No sending)**：产品范围不包含撰写 (compose)、回复 (reply)、转发 (forward)、联系人管理及发信通知；前端 SPA 不提供写信界面。
- **平台打包签名与公证 (Desktop packaging signature & notarization)**：macOS (dmg) 与 Windows (nsis) 当前为未签名构建，暂不实施代码签名、公证及应用商店上架适配，维持当前打包现状。
- **文件夹 API 与多目录展示 (Folders)**：
  - **决策**：暂不暴露多目录 HTTP API，前端维持仅展示各账户收件箱及统一收件箱。
  - **决策原因与暗坑**：
    1. **同步配额爆炸**：若开放全量文件夹浏览与后台增量轮询，拥有数十个文件夹的账户极易触发 Gmail / Graph 的速率限制 (Rate Limit)；
    2. **标签映射混乱**：Gmail 单封邮件可同时被打上多个 Label，在文件夹树中会导致同一邮件多处展示、重复计数及操作心智割裂；
    3. **移动端交互妥协**：侧边栏目前为 760px 响应式极简设计，引入深度嵌套树会导致窄屏下的导航与滚动体验退化。
- **邮件归档、垃圾箱与移动 API (Archive, junk and move)**：
  - **决策**：维持当前仅支持废纸篓/删除（Trash，本地优先 + 异步远程入队）的现状，暂不开发归档 (Archive)、垃圾邮件 (Junk) 及跨文件夹移动 (Move)。
  - **决策原因与暗坑**：
    1. **异构 Provider 语义根本性冲突**：Gmail 的归档与移动实质是“打/剥离标签”（无物理移动）；Graph 移动邮件后其远程 `message_id` 会发生改变；IMAP 移动邮件则会彻底销毁旧 UID 并分配新 UID，且大量私有邮件服务商缺失标准的 `\Archive` 特殊文件夹；
    2. **增量同步状态断裂风险**：远端 ID/UID 的突变若处理不慎，极易导致增量同步将其误判为全新邮件重复拉取，或残留幽灵本地数据。

---

## 二、技术待办已全部实现闭环 (All Backlog Items Implemented)

除上述已决策暂不处理项外，此前规划的技术待办与潜在体验暗坑已于当前版本全量实现并测试通过：

### 1. 标记状态同步与回写 (Flags are server-side)
- **实现状态**：**已全部实现并增加并发收敛测试**。
- **交付内容**：
  - 后端数据库完整支持 `is_flagged` 字段，通过 `/api/mail/messages/{id}/flag` 写入 `remote_operations` 队列异步回写远端。
  - IMAP（`\Flagged`）、Gmail（`STARRED` 标签与 History 增量）、Graph（`flagStatus` 与 delta）三端均已实现元数据与增量双向同步。
  - 前端已支持标星切换、乐观更新失败回滚以及“已标记”视图过滤。
  - 新增 `tests/mail_core/test_flag_convergence.py`，全量覆盖极端并发冲突、交替振荡反转与断网恢复后的状态机最终一致性测试。

### 2. 邮件列表游标翻页 (Keyset pagination in SPA)
- **实现状态**：**已全面接入**。
- **交付内容**：
  - 后端接口 `/api/mail/inbox` 支持 `cursor` 参数并返回 `next_cursor`。
  - 前端 `MessageList.tsx` 已接入游标分页，列表底部提供平滑的“加载更多”游标翻页，解除 100 封单页硬编码限制，展示已加载/总数状态。

### 3. 服务端未读统计与侧边栏角标 (Unified inbox / unread badges)
- **实现状态**：**已实现全局端点聚合与前端直连**。
- **交付内容**：
  - 后端新增高效全局聚合接口 `GET /api/mail/stats`，一条 SQL 聚合汇总所有收件箱总未读数与各账户分项未读数。
  - 前端 `Sidebar.tsx` 单次请求直接读取全局及分账户未读计数，支持失败优雅降级，彻底杜绝 N+1 请求开销与客户端缓存少报。

### 4. 搜索体验优化与分页 (Search limits & paging)
- **实现状态**：**已全面优化并支持翻页**。
- **交付内容**：
  - 前端搜索输入框支持 CJK 中文单字即时触发（`q.length >= 1 && /[\u4e00-\u9fa5]/.test(q)`），英文保持 `>= 2` 字符防抖，兼顾中文单字查询体验与 PostgreSQL Trigram 索引性能。
  - 搜索模式下支持基于 `next_offset` 的“加载更多”搜索结果深翻页，彻底解决搜索结果固定 100 封无法翻页的问题。

### 5. 实时推送长连接社区方案 (Realtime SSE over Fetch / Community Solution)
- **实现状态**：**已落地现代流式方案**。
- **交付内容**：
  - 新建 `frontend/src/api/sseStream.ts`，基于标准 `fetch` + `ReadableStreamDefaultReader` 流式解析 SSE 数据行，全面替代原生 `EventSource`。
  - 支持 Cookie 与自定义 Header（原生支持 Bearer Token）；
  - 遇到 401/403 鉴权失败明确派发未授权事件并终止重试，杜绝死循环；
  - 支持发送 `Last-Event-ID` 断点续传；
  - 监听页面 `visibilitychange` 事件，系统休眠唤醒恢复可见时自动检查并触发缓存失效重连。

### 6. 跨平台 PostgreSQL 依赖自动拉取与内置 (Desktop packaging PostgreSQL fetch)
- **实现状态**：**已全平台自动化**。
- **交付内容**：
  - 扩充 `scripts/fetch-pg-binaries.sh`，支持 `darwin-arm64`, `darwin-x64`, `linux-x64`, `linux-arm64`, `win-x64` 全平台架构自动检测与便携包拉取。
  - 集成解压精简逻辑，剔除文档与头文件，仅保留 `bin/`（`initdb`, `pg_ctl`, `postgres`, `createdb`）与必要动态库。
  - 在 macOS 下自动通过 `install_name_tool` 修复 Mach-O `@rpath`/`@loader_path` 动态链接，彻底杜绝脱机运行因缺少依赖闪退。

### 7. 浏览器端到端测试套件 (Browser E2E test suite)
- **实现状态**：**核心冒烟套件已搭建并接通**。
- **交付内容**：
  - 引入 Playwright 基础配置（`playwright.config.ts`），建立核心轻量 E2E 冒烟测试套件（`e2e/smoke.spec.ts`）。
  - 覆盖登录、收件箱列表加载与邮件详情阅读全流程，底层支持基于本地受控测试邮件流的稳定、离线冒烟验证。
