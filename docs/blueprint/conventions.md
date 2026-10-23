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
    - 前端邮件列表查询缓存必须严格按 `[scope_type, scope_id, role, filter, sort, folder_id]` 隔离；scope 至少区分全局、`group_id` 与 `account_id`，避免不同分组或分组与账号间缓存相互污染；
    - 分组邮件范围按每次请求时数据库中的当前成员关系解析，不保存成员快照；空分组必须区别于无范围参数并返回空列表、零统计，未知分组与 `group_id` 同时搭配 `account_id` 或 `folder_id` 的歧义请求失败关闭；
    - 切换所有账号、分组、账号或文件夹导航时，自动重置选中邮件、选中项集合与搜索词；账号移组后必须清除所有分组 inbox/search 页缓存，避免重访旧分组时先显示已移出账号的邮件；账号集合新增或删除后重置全局统计，删除账号时清除邮件列表缓存；
    - 批量“全部标记已读”必须限制在当前 scope 与角色、旗标或精确 `folder_id` 范围内，禁止误触组外账号、兄弟文件夹或全账号状态。
2. **账号分组与侧栏排序**：
    - 分组名称、顺序和成员只来自服务端数据及用户操作；不预置 demo 分组，不将分组与个人收藏分类混为一套；
    - 每个账号最多属于一个分组；账号总列表顺序与各组顺序独立持久化，拖拽来源列表决定操作语义；跨组归属与排序使用完整布局快照原子保存；快照读取返回 revision，布局保存与恢复默认必须携 expected_revision，旧版本返回 409；组织变更事务共用 PostgreSQL advisory lock，防止并发产生过期或半份布局；
    - 账号默认排序按大小写不敏感的邮箱域名，再按完整邮箱地址升序；恢复默认只重置账号顺序，不改变组顺序或成员关系。
3. **侧栏完全隐藏与恢复入口规范**：
    - 桌面侧栏折叠时完全从网格轨与 DOM 移除，释放全部横向宽度，消除 48px 残留轨与隐藏键盘焦点陷阱；
    - 侧栏展开入口固定于列表标题（以及设置页标题）左侧，折叠时呈现、展开后不重复占位；
    - 移动端导航通过同一左侧按钮唤起独立抽屉，760px 响应式断点两侧状态与行为相互独立。
4. **账号图标偏好与域名匹配规则**：
    - 账号图标模式分为 `none` (不展示)、`brand` (品牌标识，默认)、`initials` (首字母) 三种模式，存入本地前端偏好（`mail-ui-storage`）；
    - 品牌识别以邮箱域名精确匹配为准（Gmail、Outlook/Hotmail/Live、163/126、QQ），禁止子串误判；仅在域名未知且显式配置为 gmail/graph 时回退到 provider，其余显示通用邮箱图标；
    - 首字母模式取邮箱用户名首个 Unicode 字符并转为大写，空或异常值回退到通用图标；
    - 品牌图标与样式资源随前端包离线分发，严禁在运行时向外部第三方发起头像或网络资源请求。
5. **侧栏账号标题与文件夹树布局规范**：
    - 账号行模板（`data-ui="SB10"`）采用标准块级流式排版，禁止使用固定高度或横向 flex 限制子树；
    - 展开的文件夹树与状态提示（加载、错误）必须垂直渲染在所属账号标题正下方，后续账号必须顺延位于整棵树正下方，杜绝横向错排与纵向遮挡；
    - 保持键盘导航与可访问性契约：展开折叠按钮与各级目录按钮保持原生可聚焦特性与 `:focus-visible` 轮廓可见，不全局抑制 outline，`aria-expanded` 属性必须精确同步展开状态。
6. **网页与 Electron 标题栏边界**：
    - 普通浏览器只使用邮件列表标题行的侧栏按钮；`?shell=desktop` 等 URL 参数不得授予桌面能力。
    - Electron preload 是桌面平台识别的唯一来源。macOS 使用原生 `hidden` 标题栏和系统交通灯；相邻侧栏按钮必须处于 `no-drag` 区，空白标题栏保留拖动区；Windows/Linux 保留各自原生窗口控件。
    - macOS 登录、会话检查和登录后页面均保留可拖动标题栏区域。移动抽屉状态与宽屏侧栏折叠状态分别保存，不因跨越 760px 断点互相覆盖。
    - 启动前读取本地主题并以系统主题作为回退；BrowserWindow 背景色跟随系统浅/深主题，避免首帧闪白。

## 六、 UI 稳定编号与引用规范

1. **固定编号分区与声明**：
    - 采用两字母分区前缀 + 两位数字在源码中通过 `data-ui="XXNN"` 显式声明：
        - `LG`：登录分区 (Login)
        - `SB`：侧栏导航 (Sidebar)
        - `ML`：邮件列表 (Message List)
        - `MR`：邮件详情与阅读器 (Message Reader)
        - `ST`：设置模态窗 (Settings)
    - 重复列表项（邮件行、账户行等）统一标记在行模板与子区域模板上，不根据业务数据主键或渲染索引动态变化；
    - 编号一经分配具有长期稳定性，对应元素移除后编号废弃不复用；
    - 快捷键开启/关闭：Windows/Linux `Ctrl + Shift + .`，macOS `⌘ + Shift + .`；点击编号浮标复制结构化引用 `[UI:XXNN] 区域 · 描述`，不含运行时数据或凭据；`Esc` 仅退出引用模式并阻断级联关闭。

## 七、 状态收敛与统计可见性规范

1. **写回任务续跑与唤醒守卫**：
    - 去重键命中运行中 `claimed` 任务时，必须在任务载荷标记后续唤醒，在任务完成（`complete_job`）后原子派生后续待处理任务，严禁首批完成后丢失调度；
    - 针对批次余量、CAS 较新版本冲突及限流/瞬时错误，必须依据实际操作到期时间排期延迟任务，杜绝紧密空转。
2. **入站同步本地字段意图保护**：
    - `metadata upsert` 与 `delta flag patch` 在应用远端字段前，必须以 `get_unconverged_field_intents` 比对本地待推送操作及 60 秒写回完成窗口；
    - 仅保护受本地意图影响的读/标字段，不冻结正文、附件、主题等其他非相关字段；无未收敛意图时允许远端后续更新正常同步。
3. **统计聚合事务可见性**：
    - 文件夹统计计算（`recompute_folder_stats`）在执行底层 SQL 聚合前必须确保 session 状态已 flush 至数据库事务，消除在 `autoflush=False` 下读到陈旧内存数据的时序缺陷。
4. **未读数未知语义**：
    - 目标账号任一 inbox FolderStats 行缺失时，账号未读数、总数及包含该账号的聚合返回 `null`；分组统计对缺失行同样返回未知；前端使用 `-` 显示未知，禁止把部分和或缺失行按零呈现。

## 八、 桌面文本复制与日志安全规范

1. **可信顶层写剪贴板与邮件 Frame 隔离**：
    - 桌面端仅允许受信任的顶层应用页面（`appOrigin` 且 `isMainFrame === true`）触发 `clipboard-sanitized-write`，用于 UI 稳定编号引用复制与错误边界诊断日志导出；
    - 邮件 `iframe`、不可信外部网页及子 frame 严禁获得任何剪贴板写入能力；
    - 剪贴板读取能力（`clipboard-read`）全局禁止，杜绝应用或渲染进程窥探系统剪贴板内容。
2. **复制反馈与异常兜底**：
    - 前端所有复制操作均须使用 `try...catch` 包裹 `navigator.clipboard.writeText`，在 API 缺失（非安全上下文）或授权被拒时呈现明确的失败反馈（如「复制失败：剪贴板不可用或未获授权」），禁止误报成功；
    - UI 引用编号浮标点击事件必须执行 `preventDefault` 与 `stopPropagation`，杜绝穿透触发下方业务组件。
3. **桌面主进程日志规范**：
    - 主进程关键生命周期与未捕获异常统一写入 `userData/desktop.log`；
    - 日志时间戳强制使用带时区的 ISO 8601 格式；日志单文件超过 10MB 自动轮转并最多保留 3 份历史归档。

## 九、 MIME 解析与错误可见性规范

1. **解析错误严禁吞掉**：
    - 归档解析 MIME 正文、报头或附件文件名遇到异常、解析器缺陷或有损解码失败时，必须持久记录 `MessageBody.parse_error` 并输出脱敏定位日志，禁止吞错、降级为空内容或仅记 debug；
    - 保持原文存储与派生解析结果分离，已保存原始 MIME 完整保留，不提交已损坏的派生结果；
2. **前端明确报错与状态分离**：
    - 阅读器检测到 `parse_error` 时必须展示清晰的“邮件解析失败”提示与脱敏原因；
    - 即使详情接口 HTTP 200 或存在正文摘要/部分内容，也必须展示解析失败提示，严禁显示“邮件正文尚未完成同步或内容为空”掩盖失败；
    - 没有 `parse_error` 的合法空正文或待归档邮件保留原有同步中/空内容提示，与错误严格分离；
    - 切换邮件时必须即时清除旧邮件错误状态，跨邮件不残留。
