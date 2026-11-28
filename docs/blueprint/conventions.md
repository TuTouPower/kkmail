# 约定 (Conventions)

模板流程的编号与 Markdown 格式见 `.repo_template/docs/usage.md`「命名与格式」。本文定义 kkmail 架构规范、安全基线与编码约定。

## 一、 核心安全与设计基线

1. **授权模型**：UUID capability 语义以 [docs/guides/security.md](../guides/security.md)「授权模型」为准。
2. **邮件 HTML 渲染沙箱与主题边界**：
    - 邮件 HTML 正文只能经由 `src/frontend/src/lib/mailBody.ts` 进行 DOMPurify 过滤与保守主题分类；
    - 必须在带有 CSP 约束的无脚本 `iframe` 沙箱（`srcDoc`）中呈现，严禁使用 `dangerouslySetInnerHTML`；
    - 不得为了适配深色模式放宽 `script`, `style`, `meta`, `link` 等安全净化标签；
    - 显式固定浅色富文本邮件以独立纸张卡片承载并保留自身原色，无显式配色邮件自适应深色底与高对比度文字；
    - 邮件文档渲染契约由 `buildMailSrcdoc()` 独占：srcdoc 必须自带 viewport meta，并对固定宽度容器/表格施加 `width:auto !important; max-width:100% !important` 收敛，保证窄屏内容完整进入视口；宿主页面 viewport 不作用于 srcdoc；
    - 视口与宽度适配不得放松 CSP/sandbox/`no-referrer`/代理重写；选型与回退见 `docs/blueprint/decisions/20261120_mail_document_rendering_contract.md`。
3. **前端语义颜色与 Token 纪律**：
    - 前端组件与样式一律引用 `src/frontend/src/design-system/tokens.css` 声明的语义 CSS 变量；
    - `npm test` 与 `src/frontend/scripts/check_css_tokens.mjs` 门禁静态扫描所有源码中的 `var(--...)` 引用，拦截未定义变量与脱离设计系统值。
4. **HTTP 传输与状态机**：
    - 前端写操作一律走 `src/frontend/src/api/client.ts` 的 `apiRequest` / `postJson`；
    - 不安全请求自动带 `X-CSRF-Token`，缺失立即 Fail-Closed；
    - 移动端响应式断点的唯一来源为 `src/frontend/src/design-system/breakpoints.ts`，由 `viewport.ts` 复用；CSS 媒体查询值必须经 `check_layout_contracts.mjs` 校验一致，禁止手工同步注释；导航统一走 Zustand store。
5. **工具栏布局契约**：
    - 所有顶部工具栏（阅读页、列表、设置）使用共享 `.app-toolbar` 原语：主信息槽 `.app-toolbar-primary` 为 `flex:1; min-width:0` 并省略溢出文本，操作槽 `.app-toolbar-actions` 为常规 flex 项 `flex:0 0 auto`；
    - 严禁以绝对定位把操作按钮覆盖到主信息之上；窄屏（≤断点）时保持 36px 点击目标，次要信息省略或换行，不得切掉账号地址等主信息；
    - `npm run css:check` 的 `check_layout_contracts.mjs` 同时校验断点单一来源与操作槽不使用绝对定位。
6. **密钥与凭据规范**：
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
    - 品牌识别以邮箱域名精确匹配为准（Gmail、Outlook/Hotmail/Live、163/126、QQ），禁止子串误判；仅在域名未知且显式配置为 graph 时回退到 provider，其余显示通用邮箱图标；
    - 首字母模式取邮箱用户名首个 Unicode 字符并转为大写，空或异常值回退到通用图标；
    - 品牌图标与样式资源随前端包离线分发，严禁在运行时向外部第三方发起头像或网络资源请求。

5. **侧栏账号标题与文件夹树布局规范**：

    - 账号行模板（`data-ui="SB10"`）采用标准块级流式排版，禁止使用固定高度或横向 flex 限制子树；
    - 展开的文件夹树与状态提示（加载、错误）必须垂直渲染在所属账号标题正下方，后续账号必须顺延位于整棵树正下方，杜绝横向错排与纵向遮挡；
    - 保持键盘导航与可访问性契约：展开折叠按钮与各级目录按钮保持原生可聚焦特性与 `:focus-visible` 轮廓可见，不全局抑制 outline，`aria-expanded` 属性必须精确同步展开状态；
    - 侧栏顶层标题（所有账号、自定义分组、账号列表）采用一致的几何对齐基准：展开折叠箭头/槽位（18px）、主图标（16px）与文本标签在浏览器真实渲染下的水平起始坐标（`boundingBox.x`）严格对齐，误差不超过 1px；
    - 树形各子层级采用统一的 24px 阶梯缩进基准：同一层级的兄弟节点（如分组展开后的分类项与账号项）对齐，展开后的子级（如账号下的文件夹项、分类下的账号项）相对于父级图标形成严格递增阶梯缩进，子级图标列严格位于父级图标列右侧；
    - 新建/重命名分组内联表单、账户加载/错误状态提示、文件夹加载/错误状态提示的左内边距与所属层级严格对齐。
    - 分组搜索按分组 ID 独立，账号列表搜索独立；只筛选本区域启用账号的邮箱、域名、`display_name` 与接收别名/收件人地址，全局分类账号入口不受影响，搜索不改变邮件 scope、成员数或统计；
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
    - 同步开关只表示 `sync_enabled` 偏好；账号健康状态必须按 `credential_state`、`connectivity_state`、`sync_activity` 三维分别独立展示（链路诊断见 `last_connectivity_error`），不设单值状态枚举映射，不得把启用同步等同于凭据有效或连接正常，也不得用单一状态混合表达凭据与链路。
    - 批量账户操作逐项执行，显示成功数与失败明细，仅保留失败账户供重试；筛选全选只影响当前筛选结果。
    - 添加账户按需打开原生 dialog，限制焦点范围并在关闭后恢复触发按钮焦点；凭据通过命名字段输入并经既有 API 加密存储，不要求用户编辑 JSON；供应商与认证方式旁提供帮助图标和独立说明弹窗。
    - 已有账户编辑通过 `PATCH /api/accounts/{account_id}` 更新连接配置、凭据与分组；账户摘要只返回白名单 IMAP 连接字段（含独立登录名）、供应商品牌与 OAuth 客户端类型，凭据不回显，编辑表单的空凭据输入保持已有凭据不变。
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

## 六·一、 下拉控件规范（t085）

1. 应用源码禁止原生 `<select>` / `<datalist>`；单选与建议输入统一使用 `src/frontend/src/design-system/Select.tsx` 的 `Select` / `Combobox` 原语。
2. 弹出层必须由应用内 DOM 渲染，不接受 `appearance:none` 或只美化关闭态；表面、边框、圆角、选中高亮、悬停与焦点环仅引用 `--dropdown-*` 语义 token，双主题分别验证。
3. 原语必须支持方向键导航、Enter 提交、Escape 关闭并恢复焦点、外部点击关闭、disabled 与无障碍名称；建议输入保留自由文本能力。
4. `check_native_select.mjs` 作为静态门禁禁止新增原生控件，并经 `npm run css:check` 纳入 `test_cmd`。

## 七、 状态收敛与统计可见性规范

0. **同步请求完成与失败文案**：

    - 请求完成由真实任务推进的数据决定，关联只读真实 WorkerJob；严禁绑定预分配代际或把「执行不存在」作为请求失败原因；
    - 面向用户的同步失败文案必须可理解、可操作；内部调度术语（执行代际、绑定、execution_lost 等）不得出现在 API `safe_message` 或前端错误横条。

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
    - 账号健康状态机三维正交：`credential_state`（`valid` / `invalid`，`invalid` 时 `sync_enabled=false`）只由认证结果决定，`connectivity_state`（`connected` / `degraded` / `unreachable`）只由传输可达性决定，`sync_activity`（`idle` / `syncing`）只表示是否有同步任务执行中，链路诊断写由 `StructuredFailure` 白名单投影（保留受控 `phase` / `error_type` / `status` / `errno`，不经二次文本摘要剥离，且将 `redact()` 收窄于不可信自由文本与凭据拦截，杜绝 `code=[REDACTED]` 误杀与裸 `"OSError"` 退化）生成的 `last_connectivity_error`；三者互不推导、互不覆盖，传输层网络抖动、超时与限流不得污染 `credential_state`，后台静默同步故障不外溢为账号凭据失效或侧栏全局报警（由非空一等公民列 `WorkerJob.execution_origin` 显式声明并在派生/重试/重建链路自动继承，周期轮询、`patrol`、`idle_watcher`、`remote_push` 目录兜底与常规批归档必须声明 `background`，禁止依赖缺省或 JSON payload 猜谜）；连接态熔断须在 5 分钟滑动窗口内累计 5 次传输失败且跨度达到 5 分钟才置 `unreachable`（窗口外失败开启新 streak，跨天累计绝不升级，仅传输成功清零），任一次链路成功即复位 `connected`，单次抖动只置 `degraded`；`unreachable` 在 15 分钟内无新失败时由 Worker 复核降级为 `degraded`，所有连接态迁移通过 `account.updated` 事件广播；故障分类与 `StructuredFailure` 共用单一事实来源，只按异常类型、受控阶段、HTTP status 与网络 `errno` 判定，禁止对自由文本做 marker 匹配，非网络 `OSError`（ENOSPC/EMFILE/EACCES）与自由文本错误不得计入连接健康；
    - 故障账号聚合排除：当账号已禁用（`sync_enabled=false`）或 `credential_state==='invalid' || connectivity_state==='unreachable'` 且未同步生成目标角色文件夹时，全局收件箱、分组汇总与 MessageList folder-stats 汇总排除该故障账号，按其余正常账号聚合输出，不阻断正常账号的汇总；故障账号自身单独查询仍返回 `null`（`-`）；
    - 前端按结构化状态精确呈现：`credential_state==='invalid'` 显示「凭据已失效，请重新授权或检查账户设置」与设置页「认证失败」，`connectivity_state==='unreachable'` 提示网络不可用、系统正在重试（链路诊断见脱敏 `last_connectivity_error`），`degraded` 提示「网络异常，正在重试」，二者不得显示「请检查账户设置」也不得触发侧栏全局报警；归档等辅助任务失败不得污染账号状态。原过载 `folders.sync_status` 已拆除（t092），文件夹状态由正交三轴 `kind`（`container` / `view`）、`selectable`（`bool`，对应 `\Noselect` 层级节点）与 `remote_state`（`active` / `missing`，统一表达 `container` 与 `view` 在远端的存续）表达；仅 `kind='container' AND selectable=true AND remote_state='active'` 进入同步队列，派生视图 `kind='view'` 与 `\Noselect` 节点永不入队，查询与侧栏统计过滤 `remote_state='active'`；
    - 空文件夹统计初始化：新文件夹首次执行元数据同步（`apply_metadata_page`）且包含 0 封邮件时，立即生成 `FolderStats(total_count=0, unread_count=0)`，消除因空目录未变动导致 `FolderStats` 长期缺失的假性未知未读数；
    - IMAP `\Noselect` 节点只用于呈现父子目录结构，不是可查询邮箱；不得为其排 metadata/delta/reconcile 任务，旧任务执行时以 skipped 完成；不得显示未知未读数 `-`，其子目录保持可同步、可独立导航；
    - 侧栏与邮件列表头部统计语义保持一致：单账号或多账号缺失目标文件夹角色时，严格展示未知（`—` / `-`），禁止回退为全目录合计或静默按零填充。

5. **服务商字段缺省与显式清空**：

    - `RemoteMessageMeta.supplied_fields` 为 `None` 时表示完整快照，为字段集合时表示部分 projection；Graph delta 必须标明实际返回字段。upsert 只更新集合内字段，不把缺省值当清空指令。
    - 明确返回的空主题、空摘要、空收件人数组按服务商原值应用；缺省字段保持已有值。日期与状态解析得到 `None` 表示未知，不能清除已知日期/状态。
    - 同页同封邮件的 partial upsert 与 flag patch 按响应顺序合并；后续显式字段覆盖先前同字段，未提供字段保留，delete 丢弃先前 patch。保持本地未收敛 read/flag 意图保护。

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
    - 前端所有复制操作统经 `copyTextToClipboard`（优先调用 `navigator.clipboard.writeText`；在 API 缺失的非安全上下文自托管 Web 环境安全降级至 `document.execCommand('copy')`）；彻底不可用或授权被拒时呈现明确的失败反馈（如「复制失败：剪贴板不可用或未获授权」），禁止误报成功；
    - 邮箱复制共用 `CopyAddress`：普通邮箱文本可点击复制；已有导航、展开或选择行为的侧栏行必须以独立兄弟按钮复制，禁止嵌套按钮；复制纯地址，成功提示约 2 秒，重复点击重置计时，组件卸载清理计时器；
    - 阅读器归属账号、发件人、结构化收件人/抄送人、侧栏账号入口与设置账号地址使用该控件；正文 iframe 不提供复制入口。邮件详情保留 `to`/`cc` 原文本，并提供 `{name, address, text?}` 结构化项；不可可靠解析的文本仅展示，不创建复制按钮；
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

## 十、 账户供应商接入与协议路由

Google 仅提供 IMAP 应用专用密码（`imap.gmail.com`），不提供 Gmail API 或 Google OAuth；Microsoft 仅提供 Graph OAuth，创建、编辑、导入与 provider 构建均拒绝可识别 Microsoft IMAP。品牌按精确域名建议，显式选择优先，编辑以已有协议和连接配置为准。自定义域名允许手选托管商，Proton 仅提示 Bridge 限制。

凭据 PATCH 按非空字段合并，保留未提交字段；OAuth 凭据或客户端类型变化清除 Access Token 缓存。加密凭据行锁串行化编辑与后台令牌轮换，禁止旧快照覆盖新 Refresh Token。

## 十一、 Microsoft Graph 授权与令牌约定

- Microsoft 只提供 Graph OAuth。浏览器登录使用 PKCE、Web 机密客户端或 Electron 公共客户端；设备码只使用允许公共客户端流程的自有 Client ID，不要求 Secret/回调，自动申请后台持续访问。
- 原会话最终保存前，`/me` 核实微软用户 ID 和真实邮箱，并确认邮箱可访问；重新授权不能用另一身份、客户端或租户覆盖原凭据。Access Token 保持不透明，不从 JWT 或未经核验的 UPN 猜身份。
- 设备长码不返回前端，短码仅供原会话显示及复制；验证地址限制微软官方 HTTPS 端点，不拼接含验证码的链接，不依赖 verification_uri_complete。后端持久化间隔、429/slow_down 退避与过期状态，不由浏览器控制供应商轮询。

## 十二、 远程图片安全代理与内联图片渲染约定 (t066/t068/t069)

1. **远程图片默认拦截与双轨放行持久化**：
    - 邮件正文中的远程外链图片（`http:`, `https:`, `//`）默认拦截并展示防追踪提示条；纯文本或仅含内联图片邮件不显示提示；
    - 单封放行记录与发件人白名单统一由服务端数据库持久化；单封放行在邮件删除时级联清理，发件人白名单跨账号全局生效；
    - 发件人地址必须在服务端收敛进行标准校验与规范化（去首尾空白与全小写），前端仅提交邮件 UUID 由后端提取结构化地址，禁止客户端自报或从展示文本/Reply-To 自行截取；
    - 放行成功后自动重新拉取含 `remote_images` 代理映射列表的详情，重写并流式加载。
2. **服务端安全图片代理 (Image Proxy)**：
    - 外部图片统一通过服务端安全端点 `/api/mail/messages/{id}/remote-images?url=...&token=...` 代为拉取；
    - 维持主应用 SPA、桌面端及正文沙箱统一的 `img-src 'self' data: cid:` 策略，全站零外部出网；
    - 正文 URL 提取必须使用 HTML5 属性解析语义（标准库 `html.parser`），支持无引号/单双引号属性、字符引用解码与协议相对 URL 补全，禁止用手写正则匹配 `src=...`；前端重写必须使用同一规范化语义匹配映射 key；
    - 安全图片白名单：`image/png`, `image/jpeg`, `image/gif`, `image/webp`，以及经静态安全扫描的 `image/svg+xml`；严格按文件头校验；SVG 含脚本、事件处理器、外部引用或嵌入对象时拒绝（415），且不超过 64 KiB；
    - 严格实施 SSRF 防护（排除私网、回环、链路本地、云元数据、保留段，直连校验安全 IP 防 DNS Rebinding，限 3 跳重定向，限 10 MiB 单图上限，限 5s/15s 超时）；DNS 多 IP 时按 IPv4 优先逐个回退；
    - 代理错误必须可区分：400 非法目标 / 401 Token / 403 未放行 / 404 消息缺失 / 502 上游或网络失败 / 504 超时 / 413 超限 / 415 格式；响应体不得回显内部 IP、异常栈或完整目标 URL；
    - 服务端访问日志对 `token` 与目标 `url` 自动脱敏。
3. **内联图片 Signed URL 预览机制**：
    - 维持正文 `iframe sandbox` 不变，严禁添加 `allow-same-origin` 和 `allow-scripts`；
    - 独立挂载专用预览路由 `/api/mail/attachments/{id}/preview`，仅凭有效的短期 HMAC-SHA256 签名 Token 放行并流式返回二进制，不依赖也不回退到 Cookie 认证；
    - 响应头强制附带 `X-Content-Type-Options: nosniff` 和 `Content-Disposition: inline`。
4. **单信深色视图覆盖会话级内存隔离**：
    - 单信深色视图覆盖（`viewModeOverrides`）提升至应用全局内存 store（`mailStore`），按邮件 ID 字典管理，跨阅读器切信及设置页往返完整保留；
    - 排除在 `localStorage` 持久化之外，页面刷新重置为全局偏好；未单独覆盖的邮件遵循全局深色偏好。

## 十三、 统一出站网络、代理与端点熔断约定 (t089)

1. **统一建连与禁裸连约定**：所有邮件协议（`ImapProvider` 含 `open_idle_session`）、安全图片代理与 OAuth HTTP 传输策略须通过 `src/mail_core/net/` 统一解析出站代理与执行建连；禁止在协议适配器内部直接调用裸 `imaplib.IMAP4_SSL` 或 `socket.create_connection`，禁止使用建连后 `sock.getpeername()` 补丁充当 SSRF 门禁。
2. **代理策略与零凭据泄漏**：代理配置按 `proxy_mode="direct"` → 账号 `outbound_proxy` → `NO_PROXY` / `MAIL_CORE_NO_PROXY` → `MAIL_CORE_OUTBOUND_PROXY` → `HTTPS_PROXY` → `HTTP_PROXY` → `ALL_PROXY` 解析（含小写环境变体）；支持 `http`/`https`/`socks5`/`socks5h`，`ProxyConfig` 与异常/日志仅暴露脱敏 `safe_key()`，禁止包含代理账号口令；`remote_image_proxy.py` 强制直连禁代理，维持既有 SSRF 零外泄边界。
3. **两段式超时与双栈错误保留**：建连与代理/TLS 握手全程受共享 `connect_timeout`（默认 10s，单尝试 5s）约束，完成后才切换为 `io_timeout`（默认 60s）；多 IP 解析强制 IPv4 优先尝试，禁止本地无 IPv6 路由触发的 `ENETUNREACH` 覆盖先前的远端 `TimeoutError` 或对端拒绝错误。
4. **端点熔断与槽位隔离**：`EndpointBulkhead` 按 `(proxy_safe_key, host, port)` 对连续建连期传输失败开启有界冷却窗口与单探针半开恢复；开启期间在 `ConnectionPermit` 申请前快速失败或立即释放，认证拒绝对话不计入熔断计数。

## 十四、 单机运行时、探针与提交耐久性约定 (t095)

1. **单一并发预算**：DB 连接池、IDLE 配额与 Worker 执行槽位的默认值只由 `mail_core/runtime_budget.py` 派生，禁止在多模块重复硬编码；数据面连接池默认 `DEFAULT_DB_POOL_SIZE = 4`、`DEFAULT_DB_MAX_OVERFLOW = 4`（共 8 条），加 `LISTEN` 直连（Outbox 与 Job 唤醒各 1 条，共 2 条）与维护/迁移余量（6 条）组成 `MAX_CLIENT_CONNECTIONS = 16`；另加控制面 `DedicatedSlotPermitFactory` 每持有 1 个全局槽位独立占用的 `pg_try_advisory_lock` 连接（`DEFAULT_TOTAL_SLOTS = 8`），单进程嵌入式最坏连接峰值为 `24`，稳妥落在 Compose PostgreSQL `max_connections = 40` 上限内；IDLE 配额默认 8（线程上界 `2 × 8 = 16`）。
2. **探针与业务读分离**：`/ready` 的 DB、schema、LISTEN、Worker 就绪读取一律走 Core Connection（`AUTOCOMMIT`），禁止打开 ORM Session（避免每次探针发送 `ROLLBACK`）；只缓存 worker 派生信号（短 TTL），DB/schema/LISTEN 每次读新值；生效 Worker 模式为嵌入式（见本节第 6 条）或显式配置 `MAIL_CORE_LIVENESS_STAMP` 时，本地存活戳缺失、不可读、损坏或过期均判定 worker 未就绪，分布式未配置显式戳时保持数据库心跳判定；`/ready` 任意失败早返回及 `OutboxListenThread` 断开/停止时必须立即调用 `get_readiness_probe().invalidate()` 清除缓存，防止跨故障恢复沿用旧状态；容器存活性由 Worker 主循环刷新的 `/tmp` tmpfs 戳文件判定，探针不冷启解释器查库，写入异常限频记入 warning；`WorkerHeartbeatLoop` 主循环看门狗超时（`MAIL_CORE_WORKER_WATCHDOG_TIMEOUT`）时主动非零退出，交由 `restart: unless-stopped` 自动重启，其他持久 `unhealthy` 场景由外部编排/systemd/运维负责。
3. **单机默认编排互斥边界**：`docker-compose.embedded.yml` 与 `docker-compose.mail-core.yml` 固定 `container_name`、`5433`/`37281` 宿主端口及共用数据卷名不做环境变量参数化；分布式 `api` 硬编码锁死 `MAIL_CORE_EMBEDDED_WORKER="0"` 与 `MAIL_CORE_SKIP_MIGRATIONS="1"`，禁止通过环境变量同库双启 Worker；部署脚本先构建后仅摘除冲突计算容器，保留 PostgreSQL 数据卷。
4. **巡检账号级门禁与半开真探活**：全夹巡检在无调用方外层事务时不跨网络探测持有 DB 事务，冷却键写入走 PostgreSQL JSONB 原子更新并先抢占跨进程半开租约，不覆盖并发提交的其他 `Account.config` 字段；全夹巡检的冷却与 `connectivity_state` 正交；后台传输失败继续隔离（t090）；永久认证失败走凭据状态；单目录错误只影响该目录；共享端点上其他账号不受牵连；`Worker` 周期巡检对满 15 分钟窗口的 `UNREACHABLE` 账号在无事务下发起轻量半开真探活并按结果直收 `CONNECTED`/`INVALID`/刷新 `UNREACHABLE`，消除仅 INBOX 或无基线账号黑洞。
5. **提交耐久性白名单**：仅独立心跳等可丢弃状态允许异步提交；邮件入库、checkpoint、Outbox、同步请求结算及带远端副作用的业务事务必须同步提交；禁止用 `synchronous_commit=off` 代替检查点调优。
6. **生效 Worker 模式与存活戳路径单一来源（t098）**：内嵌 Worker 是否启用只由 `mail_core.config.loader.resolve_embedded_worker()` 一处裁决——CLI `--no-worker` 优先，其次 `MAIL_CORE_EMBEDDED_WORKER != "0"`（默认启用）；`python -m mail_core` 在启动边界合并 CLI 与环境变量后把生效值回写 `MAIL_CORE_EMBEDDED_WORKER`，线程启动、配置加载与 `/ready` 探针共用同一生效模式，禁止任何模块再自行解析 CLI 或环境变量判定模式；直接启动 ASGI 与独立 Worker 进程仍以环境变量为配置入口。存活戳路径只由 `mail_core.liveness.stamp_path()` 解析——显式 `MAIL_CORE_LIVENESS_STAMP` > `MAIL_CORE_DATA_DIR/worker-liveness.json` > 进程默认路径；Worker 写入、API 校验与 Worker 健康检查共用该规则；戳是否必需由 `mail_core.liveness.stamp_required()` 按生效模式与显式路径统一判定。

## 十五、 同步水位单一权威与瞬态队列约定 (t094)

1. **状态属检查点、过程属队列**：周期增量轮询的唯一权威水位为 `sync_checkpoints.last_delta_settled_at`（只读检查点并遵循三状态首次排期契约：无完整基线或重建中不排 delta、基线就绪且水位为空立即到期、水位已置按轮询间隔判定）；禁止在调度查询中扫描 `worker_jobs` 终态行反推同步时间。仅执行链真实结算态在结算事务内单调推进水位并受 `fencing_token` 约束，中间态不推进。
2. **瞬态队列短保留与回收资格**：终态 `worker_jobs` 与已发布 `outbox` 固定保留 24 小时（代码常量 `COMPLETED_JOB_RETENTION` / `PUBLISHED_OUTBOX_RETENTION`，无产品级开关），每批回收上限 5,000 行；`worker_jobs` 回收必须排除仍关联 `queued`/`running` 同步请求目标的终态行；`outbox` 仅删除连续前缀中的超窗已发布行并同事务推进 `OutboxPublicationState.pruned_through_seq`，未发布行受保护，落后游标经 `client.resync_hint` 触发重同步收敛。
3. **索引唯一性与按需统计刷新**：同表同列同操作符类禁止并存重复索引（`message_search.from_text` 仅保留唯一 `gin_trgm_ops` 索引）；`worker_jobs` 终态回收与活跃去重分别使用部分索引 `ix_worker_jobs_terminal_cleanup` 与 `ix_worker_jobs_dedupe_active`；大批量清理（单批 `>= 1000` 行）及大批量消息写入（累计 `>= 1000` 行且进程内受 300 秒最小间隔限频）按需执行 `ANALYZE`，禁止日常短 delta 重复刷新统计。
