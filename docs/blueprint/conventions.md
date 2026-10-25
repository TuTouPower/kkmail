# 约定 (Conventions)

模板流程的编号与 Markdown 格式见 `.repo_template/docs/usage.md`「命名与格式」。本文定义 kkmail 架构规范、安全基线与编码约定。

## 一、 核心安全与设计基线

1. **授权模型**：UUID capability 语义以 [docs/guides/security.md](../guides/security.md)「授权模型」为准。
2. **邮件 HTML 渲染沙箱与主题边界**：
    - 邮件 HTML 正文只能经由 `src/frontend/src/lib/mailBody.ts` 进行 DOMPurify 过滤与保守主题分类；
    - 必须在带有 CSP 约束的无脚本 `iframe` 沙箱（`srcDoc`）中呈现，严禁使用 `dangerouslySetInnerHTML`；
    - 不得为了适配深色模式放宽 `script`, `style`, `meta`, `link` 等安全净化标签；
    - 显式固定浅色富文本邮件以独立纸张卡片承载并保留自身原色，无显式配色邮件自适应深色底与高对比度文字。
3. **前端语义颜色与 Token 纪律**：
    - 前端组件与样式一律引用 `src/frontend/src/design-system/tokens.css` 声明的语义 CSS 变量；
    - `npm test` 与 `src/frontend/scripts/check_css_tokens.mjs` 门禁静态扫描所有源码中的 `var(--...)` 引用，拦截未定义变量与脱离设计系统值。
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

1. **导航 Scope 隔离与列表缓存谓词规范**：

    - 前端邮件列表查询缓存必须严格按 `[scope_type, scope_id, role, filter, sort, folder_id]` 隔离；scope 至少区分全局、`group_id` 与 `account_id`，避免不同分组或分组与账号间缓存相互污染；
    - 列表缓存前缀与谓词严格限定为 `['mail-core', 'inbox', ...]` 与 `['mail-core', 'search', ...]`（经 `isMailListQueryKey` 判定），禁止使用过于宽泛的 `['mail-core']` 前缀扫描修改 `account-folders`、`stats`、`folder-stats` 等非邮件列表查询，防御非邮件对象被误传给 `mailKey`；
    - `findCachedMail` 在当前视图（`account`、`folder`、`favorite`、`group`）下必须优先命中对应 scope 的缓存数据；
    - 分组邮件范围按每次请求时数据库中的当前成员关系解析，不保存成员快照；空分组必须区别于无范围参数并返回空列表、零统计，未知分组与 `group_id` 同时搭配 `account_id` 或 `folder_id` 的歧义请求失败关闭；
    - 切换所有账号、分组、账号或文件夹导航时，自动重置选中邮件、选中项集合与搜索词；账号移组后必须清除所有分组 inbox/search 页缓存，避免重访旧分组时先显示已移出账号的邮件；账号集合新增或删除后重置全局统计，删除账号时清除邮件列表缓存；
    - 批量“全部标记已读”必须限制在当前 scope 与角色、旗标或精确 `folder_id` 范围内，禁止误触组外账号、兄弟文件夹或全账号状态。
    - `sync_enabled=false` 的账户不进入全局/分组聚合邮件列表、搜索、统计与批量已读；显式指定 `account_id` 或 `folder_id` 的直达范围保持可用。聚合空账户集合必须返回空结果，不能退化为无限制查询。侧栏隐藏禁用账户但组织布局仍保留其成员和排序。
    - 邮件列表与搜索 DTO 携带同一账户内该邮件的全部 `locations: [{folder_id, role}]`；列表的代表性 `folder_id` 继续用于定位。此集合是未读缓存增量的唯一归属依据，禁止按当前视图或文件夹名称猜测。
    - 读状态乐观更新按 `mailKey` 去重，逐文件夹更新所有已知统计；`null` 保持未知。同一邮件请求按意图顺序串行，批量“全部已读”与单封读写互斥排序；本地读状态操作期间 list/stat SSE 失效合并延后，结束后刷新权威数据。
    - 前端统计 key 的范围段显式区分 `all`、`account:{id}` 与 `group:{id}`；列表 key 继续遵守上方 scope 隔离结构。

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
    - 保持键盘导航与可访问性契约：展开折叠按钮与各级目录按钮保持原生可聚焦特性与 `:focus-visible` 轮廓可见，不全局抑制 outline，`aria-expanded` 属性必须精确同步展开状态；
    - 侧栏顶层标题（所有账号、自定义分组、账号列表）采用一致的几何对齐基准：展开折叠箭头/槽位（18px）、主图标（16px）与文本标签在浏览器真实渲染下的水平起始坐标（`boundingBox.x`）严格对齐，误差不超过 1px；
    - 树形各子层级采用统一的 24px 阶梯缩进基准：同一层级的兄弟节点（如分组展开后的分类项与账号项）对齐，展开后的子级（如账号下的文件夹项、分类下的账号项）相对于父级图标形成严格递增阶梯缩进，子级图标列严格位于父级图标列右侧；
    - 新建/重命名分组内联表单、账户加载/错误状态提示、文件夹加载/错误状态提示的左内边距与所属层级严格对齐。
    - 分组搜索按分组 ID 独立，账号列表搜索独立；只筛选本区域启用账号的邮箱、域名与 `display_name`，全局分类账号入口不受影响，搜索不改变邮件 scope、成员数或统计；
    - 侧栏账号搜索词仅保存在组件本地，不进入持久化偏好；关闭搜索清空词并恢复原展开状态，空白词不筛选；过滤期间禁用该区域账号/分组拖放，布局保存仍使用完整账号数据。

6. **邮件列表总数展示与触底自动加载规范**：

    - 列表头部展示权威邮件总数（常规视图来源于 folder-stats 的 `total`，搜索视图来源于 search 的 `total`，未读视图与未读总数一致）；未获取到统计值前回退到已拉取渲染条数；
    - 已读/未读列表头部只展示同步统计缓存值；分页已加载邮件条数不得覆盖权威未读计数。
    - 列表分页采用 `IntersectionObserver` 触底自动加载，废弃原有手动“加载更多”按钮及旧统计文本；
    - 原“加载更多”按钮分配的稳定编号 `data-ui="ML14"` 正式废弃，不再分配给新元素复用。

7. **网页与 Electron 标题栏边界**：

    - 普通浏览器只使用邮件列表标题行的侧栏按钮；`?shell=desktop` 等 URL 参数不得授予桌面能力。
    - Electron preload 是桌面平台识别的唯一来源。macOS 使用原生 `hidden` 标题栏和系统交通灯；相邻侧栏按钮必须处于 `no-drag` 区，空白标题栏保留拖动区；Windows/Linux 保留各自原生窗口控件。
    - macOS 登录、会话检查和登录后页面均保留可拖动标题栏区域。移动抽屉状态与宽屏侧栏折叠状态分别保存，不因跨越 760px 断点互相覆盖。
    - 启动前读取本地主题并以系统主题作为回退；BrowserWindow 背景色跟随系统浅/深主题，避免首帧闪白。

8. **设置工作区与编辑反馈**：

    - 设置占据邮件主侧栏右侧工作区，按账户管理、分组管理、通用三类组织；移动端分类横向排列，账户卡片保留分组与同步状态入口。
    - 同步开关只表示 `sync_enabled` 偏好；同步状态独立展示 `sync_status`，不得把启用同步等同于连接正常。
    - 批量账户操作逐项执行，显示成功数与失败明细，仅保留失败账户供重试；筛选全选只影响当前筛选结果。
    - 添加账户按需打开原生 dialog，限制焦点范围并在关闭后恢复触发按钮焦点；凭据通过命名字段输入并经既有 API 加密存储，不要求用户编辑 JSON；供应商与认证方式旁提供帮助图标和独立说明弹窗。
    - 已有账户编辑通过 `PATCH /api/accounts/{account_id}` 更新连接配置、凭据与分组；账户摘要只返回白名单 IMAP 连接字段（含独立登录名）、供应商品牌与 OAuth 客户端类型，凭据不回显，编辑表单的空凭据输入保持已有凭据不变。
    - Google OAuth 跳转登录与重新授权强制使用 PKCE `S256`、绑定当前登录会话与 `session_epoch`，回调仅暂存经 `users.getProfile` 核实的邮箱与加密凭据，必须由原会话确认保存才生效；取消或关闭弹窗立即清理未确认流程，令牌与 `code_verifier` 永不返回前端或写入浏览器持久存储與日志。
    - 外观与账号图标偏好即时保存在当前客户端；时区和拉信超时显式保存至服务端，后台刷新不得覆盖未保存草稿。操作反馈分别归属账户、分组、通用设置或登录安全区域。

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
    - 同步入口已提交后继任务时，结果必须标记 `followup_scheduled`；Worker 据此完成原任务，不再用 `fail_job` 重复排队。未标记后继的失败仍由 Worker 重试。
2. **入站同步本地字段意图保护**：
    - `metadata upsert` 与 `delta flag patch` 在应用远端字段前，必须以 `get_unconverged_field_intents` 比对本地待推送操作及 60 秒写回完成窗口；
    - 仅保护受本地意图影响的读/标字段，不冻结正文、附件、主题等其他非相关字段；无未收敛意图时允许远端后续更新正常同步。
3. **统计聚合事务可见性**：
    - 文件夹统计计算（`recompute_folder_stats`）在执行底层 SQL 聚合前必须确保 session 状态已 flush 至数据库事务，消除在 `autoflush=False` 下读到陈旧内存数据的时序缺陷。
4. **未读数未知语义**：
    - 目标账号任一 inbox FolderStats 行缺失时，账号未读数、总数及包含该账号的聚合返回 `null`；分组统计对缺失行同样返回未知；前端使用 `-` 显示未知，禁止把部分和或缺失行按零呈现；
    - 文件夹包含 `is_read: null` 邮件时，`FolderStats.unread_count` 返回 `null`；账号、分组和全局聚合传播该未知值，禁止 SQL `SUM` 忽略 null 后返回部分和。已知邮件总数保持准确，不因读状态未知而丢失；
    - 故障账号聚合排除：当账号已禁用（`sync_enabled=false`）或处于同步/认证失败状态（`sync_status in ('failed', 'auth_failed')`）且未同步生成目标角色文件夹时，全局收件箱与分组汇总排除该故障账号，按其余正常账号聚合输出，不阻断正常账号的汇总；故障账号自身单独查询仍返回 `null`（`-`）；
    - `sync_status` 仅由账号同步类任务故障更新；归档等辅助任务失败不得污染账号状态。同步任务成功后，只有账号没有带错误的待执行或执行中同步任务时，才将 `failed` 恢复为 `idle` 并清除 `last_sync_error`；`auth_failed` 不自动清除。侧栏账号根行始终显示同步失败标记，展开后即使保留旧文件夹树，也在树前显示失败提示；
    - 空文件夹统计初始化：新文件夹首次执行元数据同步（`apply_metadata_page`）且包含 0 封邮件时，立即生成 `FolderStats(total_count=0, unread_count=0)`，消除因空目录未变动导致 `FolderStats` 长期缺失的假性未知未读数；
    - IMAP `\Noselect` 节点只用于呈现父子目录结构，不是可查询邮箱；不得为其排 metadata/delta/reconcile 任务，旧任务执行时以 skipped 完成；不得显示未知未读数 `-`，其子目录保持可同步、可独立导航；
    - 侧栏与邮件列表头部统计语义保持一致：单账号或多账号缺失目标文件夹角色时，严格展示未知（`—` / `-`），禁止回退为全目录合计或静默按零填充。
5. **服务商字段缺省与显式清空**：
    - `RemoteMessageMeta.supplied_fields` 为 `None` 时表示完整快照，为字段集合时表示部分 projection；Graph delta 与 Gmail metadata 必须标明实际返回字段。upsert 只更新集合内字段，不把缺省值当清空指令。
    - 明确返回的空主题、空摘要、空收件人数组按服务商原值应用；缺省字段保持已有值。日期与状态解析得到 `None` 表示未知，不能清除已知日期/状态。
    - 同页同封邮件的 partial upsert 与 flag patch 按响应顺序合并；后续显式字段覆盖先前同字段，未提供字段保留，delete 丢弃先前 patch。保持本地未收敛 read/flag 意图保护。
    - Gmail metadata hydrate 必须返回相同 ID、列表类型 `labelIds` 和列表类型 `payload.headers`。不完整或 ID 不符的响应、GET 异常均中断该页，不把 History stub 当完整邮件成功应用；`metadata` projection 未返回 snippet 时保留已有摘要。
6. **邮件状态未知值契约**：
    - IMAP FETCH 缺少 `FLAGS` 时读/旗标保持未知；只有显式 `FLAGS ()` 才表示 false。系统旗标按完整 token 忽略大小写匹配，扩展旗标不得因包含 Seen/Flagged 字样变成系统状态。
    - `Message.is_read`、`is_flagged`、`has_attachments` 为可空布尔值；服务商缺失时新记录存 `null`，不得由数据库 false 默认值补造事实。列表、详情、API 与前端类型保留 null。
    - 只有 `is_read === false` 才展示未读样式、计入已知未读集合或触发打开邮件自动标已读；未知状态不参与这些隐式操作。用户显式设置状态可写入真实布尔值，乐观更新失败时恢复原值（包括 null）。旗标按钮以混合状态表达未知。
    - 迁移只放宽列约束与移除默认值，不根据推测重写历史 true/false。旧库无 flag 列时导入 null，原有 read/attachment 列值照存；旧默认 false 与显式 false 无法区分，不伪造来源。
    - 降级遇到未知状态或未知未读统计时拒绝执行，不为满足旧非空约束回填 false/0。

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

1. **解析错误严禁吞掉与拉取解耦**：
    - 归档解析 MIME 正文、报头或附件文件名遇到异常、解析器缺陷或有损解码失败时，必须持久记录 `MessageBody.parse_error` 并输出脱敏定位日志，禁止吞错、降级为空内容或仅记 debug；
    - 远端拉取错误严格解耦：`provider.fetch_mime` 发生网络超时、连接或限流异常时仅记入 `MessageArchiveState.last_error`，严禁写入 `MessageBody.parse_error`；未完成归档邮件的按需拉取与重试入口保持可用；
    - 尽最大努力保留可读正文：当正文存在未转义 QP、字符集局部损坏等瑕疵但包含可提取内容时，通过安全回退解码提取并保存 `text_plain` / `text_html`，不被清空为 None；
    - 同批 IMAP 归档会话复用：同一账号批次内归档多封邮件时复用单个 IMAP 连接会话，禁止每封邮件重复执行登录与登出；
    - 保持原文存储与派生解析结果分离，已保存原始 MIME 完整保留，不提交已损坏的派生结果；
2. **前端明确报错与正文并存展示**：
    - 阅读器检测到 `parse_error` 时必须展示清晰的“邮件解析失败”提示与脱敏原因；
    - 解析报错与可读正文并存：当 `detail.parse_error` 非空且同时存在非空 `detail.body` 时，阅读器在告警框下方继续正常渲染正文（HTML 沙箱或纯文本），不阻断用户阅读；仅在 `body` 为空时单独展示告警框；
    - 即使详情接口 HTTP 200 或存在正文摘要/部分内容，也必须展示解析失败提示，严禁显示“邮件正文尚未完成同步”掩盖失败；
    - 没有 `parse_error` 的合法空正文或待归档邮件保留原有同步中/空内容提示，与错误严格分离；
    - 切换邮件时必须即时清除旧邮件错误状态，跨邮件不残留。
3. **正文数据源与列表预览生成**：
    - 正文区域仅使用详情 `body`，禁止使用列表 `body_preview` / `snippet` 回退；
    - 列表优先展示服务商摘要；缺失时若邮件已归档且存在非空正文（无论是否含 `parse_error`），从已有正文计算纯文本预览（API `body_preview`），仅用于展示、不持久化；正文未归档或完全为空时预览保持空。
4. **未归档邮件按需即时同步交互契约**：
    - 当阅读器检测到 `detail.is_archived === false`（正文尚未完成同步）时，自动调用 `POST /api/mail/messages/{id}/sync-body`；接口只入队并返回 HTTP 202、`message_id` 与 `job_id`，请求内不得执行归档 Worker；
    - 详情响应以 `archive_state` 和 `archive_has_error` 提供权威状态；目标归档 SSE 事件刷新当前详情。阅读器分别呈现任务提交、排队/处理中、完成、后台失败与配额暂停状态，后台失败提供“立即重试同步”操作；
    - 网络请求本身失败时同样提供重试；合法空邮件（`is_archived === true` 且正文为空）展示空内容提示，与未同步状态严格隔离。

## 账户供应商接入（t053）

Google 提供 Gmail API OAuth 与 IMAP 应用专用密码；Microsoft 仅提供 Graph OAuth，创建、编辑、导入与 provider 构建均拒绝可识别 Microsoft IMAP。品牌按精确域名建议，显式选择优先，编辑以已有协议和连接配置为准。自定义域名允许手选托管商，Proton 仅提示 Bridge 限制。

凭据 PATCH 按非空字段合并，保留未提交字段；OAuth 凭据或客户端类型变化清除 Access Token 缓存。加密凭据行锁串行化编辑与后台令牌轮换，禁止旧快照覆盖新 Refresh Token。

## Microsoft Graph 授权约定

- Microsoft 只提供 Graph OAuth。浏览器登录使用 PKCE、Web 机密客户端或 Electron 公共客户端；设备码只使用允许公共客户端流程的自有 Client ID，不要求 Secret/回调，自动申请后台持续访问。
- 原会话最终保存前，`/me` 核实微软用户 ID 和真实邮箱，并确认邮箱可访问；重新授权不能用另一身份、客户端或租户覆盖原凭据。Access Token 保持不透明，不从 JWT 或未经核验的 UPN 猜身份。
- 设备长码不返回前端，短码仅供原会话显示及复制；验证地址限制微软官方 HTTPS 端点，不拼接含验证码的链接，不依赖 verification_uri_complete。后端持久化间隔、429/slow_down 退避与过期状态，不由浏览器控制供应商轮询。
