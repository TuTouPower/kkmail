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

## 二、待办现状（完成度、暗坑与待实现项）

除上述已决策项外，各项待办功能的实现现状、潜在技术暗坑及落地方案如下：

### 1. 标记状态同步与回写 (Flags are server-side)
- **实现状态**：**核心能力已全部实现**。
- **现状**：
  - 后端数据库支持 `is_flagged` 字段，通过 `/api/mail/messages/{id}/flag` 写入 `remote_operations` 队列异步回写远端。
  - IMAP（`\Flagged`）、Gmail（`STARRED` 标签与 History 增量）、Graph（`flagStatus` 与 delta）三端均已实现元数据与增量双向同步。
  - 前端已支持标星切换、乐观更新失败回滚以及“已标记”视图过滤。
- **待办**：补充极端离线并发冲突时的收敛测试。

### 2. 邮件列表游标翻页 (Keyset pagination in SPA)
- **实现状态**：**核心能力已接通**。
- **现状**：
  - 后端接口 `/api/mail/inbox` 支持 `cursor` 参数并返回 `next_cursor`。
  - 前端 `MessageList.tsx` 已接入游标分页，列表底部提供平滑的“加载更多”游标翻页，解除 100 封单页硬编码限制。

### 3. 服务端未读统计与侧边栏角标 (Unified inbox / unread badges)
- **实现状态**：**已接入服务端统计接口**。
- **现状**：
  - 前端 `Sidebar.tsx` 已接入服务端文件夹统计接口，真实展示各账户收件箱及统一收件箱未读数，彻底解决超出首屏少报的问题。

### 4. 搜索体验优化与分页 (Search limits & paging)
- **实现状态**：**后端完备 / 前端待优化**。
- **现状**：
  - 后端已支持 PostgreSQL 全文检索 + 主题/发件人三元组模糊匹配，API 支持分页（`next_offset`）。
  - 前端硬编码要求至少输入 2 字符才触发搜索，固定拉取 100 条且不支持翻页。
- **潜在暗坑**：
  - **Trigram 索引与 ASCII 单字符性能退化**：PostgreSQL 的 `gin_trgm_ops` 索引至少需要 3 个字节/字符建立匹配键。若盲目开放 1 字符英文模糊查询，索引将彻底失效并退化为全表慢扫描，导致 CPU 瞬间飙升。
- **落地方案**：
  - 维持当前 2 字符防抖阈值（或中文允许单字、英文严格限制 2 字符），重点在前端实现基于 `next_offset` 的搜索结果深翻页。

### 5. 实时推送长连接社区方案 (Realtime SSE over Fetch / Community Solution)
- **实现状态**：**已确定采用社区方案 / 待前端迁移落地**。
- **详细说明与暗坑**：
  - **原生缺陷**：W3C 浏览器原生的 `EventSource` 规范无法携带自定义 HTTP Header，导致使用 Bearer Token 的客户端无法连接 `/api/events`，且原生重试在遭遇 401/403 鉴权失败时会盲目死循环重连。
  - **架构决策**：放弃原生 `EventSource`，前端及 Web 客户端统一接入 `@microsoft/fetch-event-source` 社区方案（基于 `fetch` + `ReadableStream` 流式读取）。
  - **兼容性保障**：Firefox 自 v65（2019 年初）起已完整原生支持 `fetch` 流式响应读取，与 Chrome、Safari、Edge 保持一致，零兼容障碍。同时避免了在 URL Query 中暴露敏感 Token。
  - **实施细节**：结合页面 `visibilitychange` 事件处理休眠唤醒（防止系统睡眠唤醒后的半开连接悬挂），并保持后端显式事件类型（`event: ...`）派发以防双重触发。

### 6. 跨平台 PostgreSQL 依赖自动拉取与内置 (Desktop packaging PostgreSQL fetch)
- **实现状态**：**Linux 已自动化 / macOS 与 Windows 仅有手动指引**。
- **详细说明与系统级暗坑**：
  - **运行依赖**：Electron 桌面端架构天然通过 `desktop/postgresManager.js` 管理内置数据库实例，强制要求 `desktop/vendor/pgsql/bin` 存在 `initdb`、`pg_ctl`、`postgres` 二进制，否则判定为 `stub` 报错拒绝启动。
  - **macOS @rpath 崩溃暗坑**：PG 官方预编译动态库路径多为绝对路径；打进 Electron 应用并在脱机 Mac 运行时，若未执行 `install_name_tool` 修正依赖为相对路径（`@rpath` / `@loader_path`），会直接因 `Library not loaded` 闪退。
  - **Windows 管理员权限限制**：`initdb.exe` 存在硬编码安全规则：**禁止在 Administrator 提权环境下直接启动**。若 Windows 用户以管理员身份运行 kkmail，内置 PG 会直接拒绝初始化。
  - **体积爆炸**：完整 PG 安装包高达 300MB+，必须精准剥离 `pg_dump`、`clusterdb`、开发头文件及多语言文档，仅保留运行时最小核心集。
- **落地方案**：
  - 扩充 `scripts/fetch-pg-binaries.sh`，对接可靠的 macOS (arm64/x86_64) 及 Windows 便携源，并在打包脚本中集成动态库 rpath 修复与精简裁剪逻辑。

### 7. 浏览器端到端测试套件 (Browser E2E test suite)
- **实现状态**：**核心冒烟套件已搭建**。
- **现状**：
  - 已引入 Playwright 基础配置并搭建核心轻量 E2E 冒烟用例（`e2e/smoke.spec.ts`），覆盖登录、收件箱列表加载与邮件详情阅读全流程。
- **落地要求与暗坑**：
  - **禁止外网邮件依赖**：E2E 测试绝不能连接真实的 Gmail 或 Office 365 邮箱（存在网络超时、配额耗尽与凭据泄露风险）。
  - 底层强制绑定项目内置的 `StubProvider`（`mail_core/providers/stub_memory.py`）提供受控的本地测试邮件流，实现稳定、离线、秒级通过的端到端冒烟验证。
