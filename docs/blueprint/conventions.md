# 约定 (Conventions)

模板流程的编号与 Markdown 格式见 `.repo_template/docs/usage.md`「命名与格式」。本文定义 kkmail 架构规范、安全基线与编码约定。

## 一、 核心安全与设计基线

1. **单用户 · UUID 即能力凭据 (Capability-based)**：
    - 实例无多租户角色或行级用户 ACL。
    - 在已认证的 Session / API Key 边界内，掌握资源 UUID 即可访问该资源；不得将其作为“多租户防 IDOR”缺陷处理。详见 `docs/guides/security.md`。
2. **邮件 HTML 渲染沙箱与主题边界**：
    - 邮件 HTML 正文只能经由 `src/frontend/src/lib/mailBody.ts` 进行 DOMPurify 过滤与保守主题分类；
    - 必须在带有 CSP 约束的无脚本 `iframe` 沙箱（`srcDoc`）中呈现，严禁使用 `dangerouslySetInnerHTML`；
    - 不得为了适配深色模式放宽 `script`, `style`, `meta`, `link` 等安全净化标签；
    - 显式固定浅色富文本邮件以独立纸张卡片承载并保留自身原色，无显式配色邮件自适应深色底与高对比度文字。
3. **前端语义颜色与 Token 纪律**：
    - 前端组件与样式一律引用 `src/frontend/src/design-system/tokens.css` 声明的语义 CSS 变量；
    - `npm test` 与 `scripts/check_css_tokens.mjs` 门禁静态扫描所有源码中的 `var(--...)` 引用，拦截未定义变量与脱离设计系统值。
4. **HTTP 传输与状态机**：
    - 前端写操作一律走 `src/frontend/src/api/client.ts` 的 `apiRequest` / `postJson`；
    - 不安全请求自动带 `X-CSRF-Token`，缺失立即 Fail-Closed；
    - 移动端 760px 响应式断点（`src/frontend/src/lib/viewport.ts`），导航统一走 Zustand store。
5. **密钥与凭据规范**：
    - 不预设弱口令或示例密钥，缺失时拒绝启动；
    - 凭据仅经 `CredentialStore` 存储并由 blob keyring 派生加密；
    - 日志与 `last_error` 必须经 `mail_core.security.redact` 脱敏。

## 二、 Schema 与类型落点

|类型|例子|落点|
|:---|:---|:---|
|**跨服务契约**|`OpenAPI` JSON 模式|`schemas/openapi.json`|
|**前端生成契约**|OpenAPI 生成的 TypeScript 接口|`src/frontend/src/api/generated/schema.ts`|
|**代码内契约**|Pydantic model、TypeScript 领域类型|后端跟模块走（`src/mail_core/api/`, `src/mail_core/mail/domain/`）；前端在 `src/frontend/src/api/schemaTypes.ts`|
|**数据库迁移**|Alembic 数据库版本脚本|`src/mail_core/db/alembic/versions/`|
|**环境配置模板**|环境变量说明与示例|`config/.env.example`（根目录保留 `.env.example` 软链）|

## 三、 原子写与状态防损

- 写入权威状态、派生索引（`docs/tasks_index.json`、`docs/pending/` 等）必须通过临时文件 + fsync + `os.replace` 原子替换，防止进程异常中断留下半写入文件。
- 工具链内部公共 helper：`from repo_task.documents import atomic_write_text`。

## 四、 邮件协议与报头编码规范

1. **IMAP 报头保真与回退顺序**：
    - IMAP 报头元数据扫描必须保持原始字节，严禁在 MIME 解析前全局通过 UTF-8 `replace` 解码；
    - 报头字段解码顺序：优先遵守有效 RFC 2047 charset；无声明或未知字节按严格 UTF-8 → 严格 GB18030（兼容 GBK/GB2312）→ UTF-8 有损替换（`replace`）顺序确定性回退；
    - 损坏或未知字段采用独立降级，不得阻断整页同步，不得污染相邻字段。

## 五、 导航 Scope 与缓存隔离规则

1. **导航 Scope 隔离**：
    - 前端邮件列表查询缓存必须严格按 `[scope, role, filter, sort, folder_id]` 隔离，避免跨账户、跨角色或具体文件夹间缓存相互污染；
    - 切换导航视图（收藏/账户/文件夹）时，自动重置选中邮件、选中项集合与搜索词，防止残留旧查询条件或幽灵选中状态；
    - 批量“全部标记已读”在具体文件夹视图下必须限制在该 `folder_id` 范围内，禁止误触兄弟文件夹或整账号全量状态。
2. **侧栏完全隐藏与恢复入口规范**：
    - 桌面侧栏折叠时完全从网格轨与 DOM 移除，释放全部横向宽度，消除 48px 残留轨与隐藏键盘焦点陷阱；
    - 侧栏展开入口固定于列表标题（以及设置页标题）左侧，折叠时呈现、展开后不重复占位；
    - 移动端导航通过同一左侧按钮唤起独立抽屉，760px 响应式断点两侧状态与行为相互独立。
3. **账号图标偏好与域名匹配规则**：
    - 账号图标模式分为 `none` (不展示)、`brand` (品牌标识，默认)、`initials` (首字母) 三种模式，存入本地前端偏好（`mail-ui-storage`）；
    - 品牌识别以邮箱域名精确匹配为准（Gmail、Outlook/Hotmail/Live、163/126、QQ），禁止子串误判；仅在域名未知且显式配置为 gmail/graph 时回退到 provider，其余显示通用邮箱图标；
    - 首字母模式取邮箱用户名首个 Unicode 字符并转为大写，空或异常值回退到通用图标；
    - 品牌图标与样式资源随前端包离线分发，严禁在运行时向外部第三方发起头像或网络资源请求。
