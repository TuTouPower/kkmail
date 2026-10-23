# Task review t027（reviewer_focus: 测试）

- task：`t027_account_group_ordering`
- spec：`docs/tasks/t027_account_group_ordering/spec.md`
- diff_anchor：`c8cee92446f9c24e7a0a2a501d52d0bd49068041`
- target：`git -C '[REDACTED_LOCAL_PATH]' diff c8cee92446f9c24e7a0a2a501d52d0bd49068041`
- round：1
- reviewed_at：2026-10-23T05:06:07+08:00

reviewed_scope: bf4b2a1ea5d38c45

## Findings

### t027_test_f001 - 分组重命名校验与非空组删除没有持久化回归测试

- 严重度：important
- 锚点：AC-001、AC-002
- 位置：`tests/mail_core/test_accounts_api_pg.py:24-48`（`test_group_and_account_lifecycle`）；`tests/mail_core/test_sidebar_group_scope.py:89-125`；`tests/mail_core/test_accounts_api_unit.py:37-41`
- 问题：现有生命周期测试先删除账号（第 45 行），再删除分组（第 47 行），因此没有覆盖“删除含账号分组后保留账号和邮件”的场景，也没有用独立会话核验。新增布局测试不删除分组。新增分组改造没有测试 PATCH 重命名、trim/空白、128 字符上限、重名、不存在目标及失败时不部分写入；现有 `test_group_create_validation_constraints` 只校验颜色长度。若删除组级联删除成员，或重命名接口接受非法名称，这些测试仍会通过。
- 建议：新增真实 PostgreSQL API 测试：先建组、账号、邮件与附件，删除非空组后用新会话核对账号/邮件/附件和总列表顺序；分别覆盖重命名成功、名称边界、重复/不存在组及失败原子性。

### t027_test_f002 - 独立排序、默认恢复与并发快照缺少测试

- 严重度：important
- 锚点：AC-004、AC-005、AC-006、AC-007、AC-008
- 位置：`tests/mail_core/test_sidebar_group_scope.py:89-125`；`tests/e2e/full_stack.spec.ts:223-291`；`tests/mail_core/test_migration_validation.py:404-438`
- 问题：布局集成测试只有一个分组账号和一个未分组账号，只核对写入后的 `master_order` / `group_order` 值及重复 ID 失败；浏览器测试覆盖总列表排序与分组先后，没有组内重排、默认域名/邮箱排序、恢复默认、手动模式新增账号追加、总列表与组内顺序互不影响等断言。全仓没有并发组织写入测试，重复/遗漏/外组/不存在 ID 等非法载荷也未完整覆盖。迁移测试只核对列增删和既有邮件/blob 数据，没有核对旧账号/分组成员与分组顺序升级前后不变。并发提交若产生半份排序或恢复默认误改成员关系，现有测试无法发现。
- 建议：为默认排序、两套账号顺序独立变更与恢复、组新增追加、迁移前后旧组织数据，以及并发/各类非法载荷原子性补真实数据库测试；用独立会话读取已提交快照。

### t027_test_f003 - 分组邮件范围只覆盖单页 inbox happy path

- 严重度：important
- 锚点：AC-010、AC-011、AC-012、AC-013、AC-014、AC-015
- 位置：`tests/mail_core/test_sidebar_group_scope.py:18-86`
- 问题：新增集成测试只为 `inbox` 建数据并取一页，搜索不带 offset，统计只断言一个未读计数；空组只核对 inbox/search，未核对零统计和零封全部已读。没有 group scope 下的 sent/drafts/trash/junk/archive、未读角色、重复多位置邮件、相同 sort_time 跨页升降序、搜索 offset/total、成员移组后重新请求或过期 cursor 场景。全部已读只检查返回 `count` 和组外邮件仍未读，没有独立读取组员已读状态或检查远端写回队列。歧义请求只测 `account_id`，未测 `folder_id`。因此新范围逻辑即使漏掉特定角色、分页或副作用，现有组测试仍会通过；既有无分组角色测试不传 `group_id`，不能证明组过滤正确。
- 建议：在同一真实 PostgreSQL 夹具中构造两个组、无组账号、空组、相同时间与多位置邮件；逐角色遍历分页与搜索 offset，核对统计、全部已读成员/组外状态及写回队列，并覆盖 folder_id 歧义和成员变更后的新请求。

### t027_test_f004 - 计数与 SSE 回归测试被删后没有替代，AC-022 无测试

- 严重度：important
- 锚点：AC-018、AC-022、AC-025
- 位置：`src/frontend/src/components/Sidebar.test.tsx:71-100`；`src/frontend/src/components/MessageList.test.tsx:124-130`；被删测试 `renders unread counts from global /api/mail/stats`、`shows unknown dash badge when account stats request fails, without showing pseudo-exact zero`
- 问题：新 Sidebar mock 提供 unread 统计数据，但断言只核对六个分类名称和组内“所有未读”选中状态；未断言任何全局、账号或分组计数。新增 MessageList 组测试核对 unread/search 请求范围，没有核对统计查询或 SSE 后计数刷新。改写 Sidebar 测试时删除了原有总数/账号数及未知计数显示测试，没有等价覆盖。若组内角标未刷新或请求失败时把未知计数显示成 0，当前测试仍会通过；AC-022 的成员变更、邮件 SSE、组和账号角标联动均无测试。
- 建议：恢复全局角标和未知值断言，并增加两个组/多个账号的计数夹具；通过真实查询失效或 SSE 事件验证成员变化后组计数、账号计数同步更新，失败时显示未知而非 0。

### t027_test_f005 - 侧栏结构断言没有验证 24px 契约及完整视口/主题范围

- 严重度：important
- 锚点：AC-017、AC-020、AC-024
- 位置：`tests/e2e/sidebar_tree.spec.ts:76-92`、`tests/e2e/sidebar_tree.spec.ts:126-166`；`src/frontend/src/components/Sidebar.test.tsx:71-99`
- 问题：侧栏组件测试只确认名称存在，没有断言“所有账号→分组→账号列表”的顺序或三区独立折叠。E2E 的水平断言为 `tree.x < account.x + 35`，无法区分 0px、24px 或 34px 缩进，也未核对箭头槽、相邻层级精确增量、图标/文本列对齐。视口只测 1200px 和 375px，没有 760px 两侧布局；没有深浅主题回归。当前布局即使偏离固定 24px 或 breakpoint/主题造成错位，测试仍可通过。
- 建议：用真实浏览器逐层读取 bounding box，断言相邻层级恰为 24px 且箭头/无箭头项对齐；补 760px、深浅主题和顶层分区顺序/独立折叠断言。

### t027_test_f006 - 分组管理与账号归属 UI 没有端到端行为覆盖

- 严重度：important
- 锚点：AC-027、AC-028、AC-029、AC-030、AC-031、AC-032、AC-033
- 位置：`src/frontend/src/components/Sidebar.test.tsx:71-124`；`src/frontend/src/components/SettingsModal.test.tsx:149-180`；`tests/e2e/full_stack.spec.ts:194-235`
- 问题：现有 SettingsModal 测试只用 fetch stub 覆盖设置里的创建分组输入；没有侧栏文件夹加号、重命名/删除菜单、取消与确认、账号分组下拉、保存失败后恢复、侧栏/设置同步、焦点返回、Escape、特殊字符显示或窄屏非拖拽移组。全栈 E2E 通过 `page.request.post/put` 直接准备组、账号和归属，绕过了这些用户操作；它不能证明 UI 控件接线正确。即使入口消失、删除误删账号、选择器未保存归属，当前新测试仍可通过。
- 建议：补组件/API 边界测试验证创建/重命名/删除/归属选择的可观察结果、取消/失败与缓存失效；用浏览器键盘和窄屏用例验证焦点、Escape 及非拖动移组。

### t027_test_f007 - 真实浏览器拖拽覆盖了主要成功路径，但未覆盖关键目标和失败矩阵

- 严重度：important
- 锚点：AC-034、AC-035、AC-036、AC-037、AC-038、AC-039、AC-040
- 位置：`tests/e2e/full_stack.spec.ts:10-23`、`tests/e2e/full_stack.spec.ts:243-291`；`src/frontend/src/components/Sidebar.test.tsx:47-52,102-115`
- 问题：全栈用例确实用 Playwright `locator.dragTo()` 执行真实鼠标拖拽，并覆盖折叠空组接收、跨组插到成员前、拖出到总列表、总列表重排保留归属和分组先后持久化；这些路径有真实交互证据。其余 AC 仍缺测试：拖到已有组标题/空区追加、组内账号重排、从组拖到账号列表标题/空区/目标账号行并同步定位总列表；没有验证整行均可拖、箭头/菜单/普通点击不误触、drop feedback 清除；没有恢复默认及保存失败回滚，也没有自身/无效目标/取消/未知外部载荷/连续快速拖动的 UI 行为。组件测试的 `dispatchDrag()` 只是合成事件，不能补足这些浏览器交互。失败或连续拖动覆盖失效时，现有成功路径测试仍可全绿。
- 建议：在真实浏览器扩展拖拽矩阵，逐项校验请求后的服务端归属与两套顺序；增加取消、非法目标、持久化失败和连续拖动用例，并断言反馈清理与恢复服务端事实。

## 结论

- 前轮 finding 复核：无，Round 1。

- 改测方向复核：未发现把旧预期改成迁就当前实现的修改；`smoke.spec.ts` 的侧栏定位器改为精确 accessible name，属于收窄定位。`Sidebar.test.tsx` 整体替换旧导航测试后，未等价恢复计数/未知值测试，见 `t027_test_f004`。

- 本轮新发现：7 条，均为 important。

- 未进表的提示：全栈 E2E 使用独立临时 PostgreSQL 数据库，并在 runner 的 `finally` 清理；测试新建的随机组/账号不会污染后续运行。危险模式扫描未发现新增 `.skip` / `.only`、断言注释、恒真断言或用 `.value =` 冒充拖拽；数据库测试的环境条件 `skipif` 是仓库既有隔离门禁。前端完整测试本轮通过：38 files / 191 tests，OpenAPI 与 CSS token 检查通过。未重跑 PostgreSQL 集成门禁及真实全栈 E2E。

- AC 复验方式：以下 `re_verified` 表示独立核对了 AC 对应的测试断言与交互路径，不表示 AC 行为运行通过；本轮只执行了前端完整单测门禁，未执行 PostgreSQL 与真实全栈门禁。

    - AC-001：`re_verified` — API 生命周期测试只创建/删除，不覆盖 rename 与名称错误。
    - AC-002：`re_verified` — 生命周期测试先删成员账号，没有非空组删除后的独立会话断言。
    - AC-003：`re_verified` — 全栈 `dragTo` 覆盖跨组和移出；布局 API 测试核对归属字段。
    - AC-004：`re_verified` — 测试核对手动 master_order 持久化；未核对域名/邮箱默认排序与新会话读取。
    - AC-005：`re_verified` — E2E 核对总列表重排保留归属；未核对两套顺序完全独立及并发事务。
    - AC-006：`re_verified` — E2E 核对分组先后刷新持久化；未覆盖新增组追加和恢复默认。
    - AC-007：`re_verified` — 布局测试只覆盖重复 ID 拒绝及无部分写入；没有并发或其他非法集合。
    - AC-008：`re_verified` — 迁移测试核对新列降级/升级；未核对旧账号与分组组织数据。
    - AC-009：`re_verified` — Sidebar 测试用自定义组名并断言不出现“工作”“个人”。
    - AC-010：`re_verified` — 新集成测试只验证 group inbox，没有逐角色和多位置去重覆盖。
    - AC-011：`re_verified` — 空组 inbox/search 有断言；未覆盖统计、全部已读空结果和同时间分页。
    - AC-012：`re_verified` — group search 核对 total=1；未验证 offset 翻页与完整组统计。
    - AC-013：`re_verified` — 测试核对全部已读返回 count 及组外邮件未读；未核对成员持久状态和写回队列。
    - AC-014：`re_verified` — 测试核对不存在组及 account_id 歧义；未核对 folder_id 歧义。
    - AC-015：`re_verified` — E2E 验证移组后 accounts 列表归属；没有紧接着验证旧 cursor/offset 与组邮件首屏。
    - AC-016：`re_verified` — 仓库原有全局、账号和 folder-role API 测试仍在；新增组参数的兼容矩阵未覆盖。
    - AC-017：`re_verified` — 测试核对分区标签存在；未核对顶层次序与三区独立折叠。
    - AC-018：`re_verified` — 测试核对六个全局标签、六个组入口和组 unread 导航；未逐一核对全部分类查询及空组导航。
    - AC-019：`re_verified` — 浏览器测试验证账号目录展开、嵌套自定义目录导航；没有验证全部内置角色与不重复呈现。
    - AC-020：`re_verified` — 浏览器核对纵向顺序和粗略水平边界；没有 24px 精确断言。
    - AC-021：`re_verified` — query-key 测试核对 group 与全局/账号 key 不同；未核对 group 间、旧响应、placeholder 和选择重置。
    - AC-022：`re_verified` — 当前无组/账号计数和 SSE 联动断言；旧计数测试已删除。
    - AC-023：`re_verified` — persistence 测试恢复分区、组和账号展开字段；未验证共享账号状态及删除后清理。
    - AC-024：`re_verified` — E2E 有键盘折叠与 1200/375 视口；未覆盖 760px、双主题及稳定 UI 编号。
    - AC-025：`re_verified` — 现有邮件列表测试仍覆盖搜索、排序、分页和操作；无完整侧栏功能回归清单，计数回归已缺失。
    - AC-026：`re_verified` — Sidebar 测试验证任意用户组名及无 demo 名称。
    - AC-027：`re_verified` — 无文件夹加号入口的交互测试。
    - AC-028：`re_verified` — 无分组重命名 UI/API 行为测试。
    - AC-029：`re_verified` — 无删除确认、取消与保留成员的 UI 测试。
    - AC-030：`re_verified` — 无设置中的账号分组选择及保存失败恢复测试。
    - AC-031：`re_verified` — SettingsModal 只测创建输入；未测设置与侧栏失效联动。
    - AC-032：`re_verified` — 无管理菜单/对话框焦点、Escape、特殊字符及窄屏移组测试。
    - AC-033：`re_verified` — 自定义组名有覆盖；空列表创建入口与特殊字符展示无覆盖。
    - AC-034：`re_verified` — 有真实浏览器行拖拽；未验证整行任意位置、点击不误拖及反馈清理。
    - AC-035：`re_verified` — 真实拖拽覆盖折叠空组与跨组插入目标账号；未覆盖有成员组标题追加。
    - AC-036：`re_verified` — 有组到总列表标题拖出；无账号列表目标行/空区及同步定位断言。
    - AC-037：`re_verified` — 总列表内重排已验证保留组归属；组内独立重排无测试。
    - AC-038：`re_verified` — 分组先后和 master 顺序分别有 E2E 断言；组内账号重排刷新持久化无测试。
    - AC-039：`re_verified` — 未找到恢复默认排序按钮/失败回滚测试。
    - AC-040：`re_verified` — 后端重复 ID 有拒绝测试；无拖拽自身、无效目标、取消、持久化失败或连续拖动用例。

    coverage = 40 / 40

- 总体判断：存在多条重要验收路径没有可信测试，且计数测试被删除未补回；修复前测试门禁不足以证明本 task 通过，FAIL。

- 系统性 follow-up：无。

verdict: FAIL

## Round 2 (2026-10-23T05:50:45+08:00)

reviewed_scope: 58434501c0c16f5d

### Findings

#### t027_test_f008 - 保存失败测试没有证明账号仍留在原列表

- 严重度：important
- 锚点：AC-040：布局保存失败后不得半移组或丢失账号。
- 位置：`src/frontend/src/components/Sidebar.test.tsx:372-385`
- 问题：测试把 `acc-2` 从总列表拖向分组，mock 返回 500。第 384 行只断言该账号不在分组；失败前该条件本来就成立。若失败处理错误地同时从总列表移除账号，该用例仍会因错误提示和分组内不存在而通过，标题所称“保持原归属”没有被验证。
- 建议：失败后断言总列表仍有 `acc-2`，并断言重新请求的原成员关系/顺序保持。

#### t027_test_f009 - 搜索 offset 测试允许连续两页返回相同邮件

- 严重度：important
- 锚点：AC-012：搜索结果保持 offset 翻页语义。
- 位置：`tests/mail_core/test_sidebar_group_scope.py:351-356`
- 问题：测试断言 `total`、`next_offset`、第二页长度和账号范围，但没有比较两页邮件 ID。若 API 忽略 offset，第二页重复第一页的两封邮件仍满足现有断言，测试会假绿。
- 建议：断言两页 ID 不相交，并核对合并后的唯一 ID 集合与夹具预期一致。

#### t027_test_f010 - 账号分组选择测试以直接赋值代替真实选择交互

- 严重度：important
- 锚点：AC-030：账号管理下拉选择当前组、其他组或不加入分组。
- 位置：`src/frontend/src/components/SettingsModal.test.tsx:265-271`
- 问题：测试直接执行 `groupSelect.value = ''` 并派发 `change`，没有通过浏览器选择控件交互；只覆盖“不加入分组”，不覆盖从当前组选择其他组。全栈 E2E 通过 `page.request` 设置初始归属，也没有用户操作路径。选择器键盘/鼠标行为或非空组选择接线错误仍可全绿。该赋值是 AC 明确要求的下拉交互，属于程序赋值替代真实交互。
- 建议：用真实浏览器 `selectOption`/键盘选择覆盖无组及另一分组，并验证 PATCH 后账号列表、组成员和邮件范围刷新。

### 前轮 finding 复核

- `t027_test_f001`：修不彻底。新增 PostgreSQL 测试已覆盖非空组删除后独立会话读取账号、邮件、附件和 `master_order`，也覆盖名称 trim、128 字符边界、空白、重名及不存在组的 HTTP 状态。但失败重命名后只断言分组列表非空，没有读取原组名确认失败未部分写入；删除夹具没有创建或核验凭据，AC-001/002 的原子性与凭据保留仍无证据。见 `tests/mail_core/test_accounts_api_pg.py:64-119`。

- `t027_test_f002`：修不彻底。新增测试已覆盖分组账号默认域排序、总列表/组内手动顺序独立、恢复默认、旧分组及成员迁移保留，以及组删除与布局保存并发。仍没有两个布局写入并发后的完整排序快照断言；当前并发用例只跑一次布局保存与一次删除，不能证明并发重排冲突不会丢成员/顺序。见 `tests/mail_core/test_sidebar_group_scope.py:149-201,239-280`。

- `t027_test_f003`：修不彻底。新增夹具覆盖 inbox/sent、cursor 分页去重、搜索 offset、统计、全部已读持久状态/写回队列、空组、组外隔离及移组后的后续查询。仍缺 group scope 下 drafts/trash/junk/archive、升序同时间分页、全部已读 flag 筛选、列表/search 的 `folder_id` 歧义，以及成员变化后旧 cursor 的拒绝/首屏重查。见 `tests/mail_core/test_sidebar_group_scope.py:283-371`；offset 页断言另见新 finding `t027_test_f009`。

- `t027_test_f004`：已消除。全局/账号角标、组角标及未知值现在有组件断言，成员变更测试验证组角标从 2 更新到 3（`Sidebar.test.tsx:122-140,212-241`）。`statsQuery` 使用 `['mail-core','stats']`，`useMailCoreRealtime` 对 `['mail-core']` 做部分匹配失效；实时事件测试覆盖 `folder.stats_updated` 触发此前缀失效（`queries.ts:75-101`、`useMailCoreRealtime.test.ts:10-18,36-58`），覆盖 stats query 所属 key。未见组计数脱离账号统计缓存的单独路径。

- `t027_test_f005`：已消除。新增浏览器用例核对顶层顺序、分区折叠、24px/48px 层级 padding、账号与文件夹文本对齐、浅深主题以及 761/760px 行为（`tests/e2e/sidebar_tree.spec.ts:199-266`）。本轮不再以“无 24px/760px/主题测试”阻断；箭头槽位的独立视觉断言可作补充。

- `t027_test_f006`：修不彻底。已有侧栏创建/删除、重命名失败重试、焦点恢复，设置删除当前组回退和账号移出分组测试（`Sidebar.test.tsx:310-370`、`SettingsModal.test.tsx:205-274`）。但成功创建/重命名后没有断言服务端重查的新组名/新组出现在导航，删除确认没有取消/保留数据验证，账号下拉仅测清空且后续 accounts mock 仍返回旧归属；Escape、特殊字符实际渲染和窄屏非拖动路径也未测。测试注入的 API 固定返回旧 groups/accounts，因而不会发现失效/回滚结果未更新 UI。

- `t027_test_f007`：修不彻底。真实 Playwright `dragTo()` 已补组内排序、已有组标题追加、组到总列表账号行移出、总列表重排、组顺序刷新和恢复默认排序（`tests/e2e/full_stack.spec.ts:247-341`）。相同账号、取消/未知外部载荷和失败回滚仍只由合成 DOM 事件组件测试覆盖；没有浏览器拖拽验证反馈清理、非法目标/取消、保存失败及连续快速拖动，因此 AC-034/040 仍缺真实交互证据。保存失败断言另见 `t027_test_f008`。

- 改测方向复核：无通过修改旧预期迁就实现。迁移版本/列断言同步新增迁移；侧栏 DOM 选择器改动保持既有可观察断言。被删的旧计数/未知值语义已有新测试替代。

- 危险模式扫描：发现 `SettingsModal.test.tsx:268` 的 select `.value =`，按 AC-030 作为 `t027_test_f010` 报告；数据库 `skipif` 仍是项目既有的 DB 环境门禁。未发现新增 `.skip` / `.only`、注释断言或恒真断言。

- 本轮新发现：3 条，均为 important。

- 未进表的提示：group scope 搜索 offset 和失败回滚的假绿已分别列为 `t027_test_f009`、`t027_test_f008`。`folder.stats_updated` 的 query-key 前缀与组 badge 统计源已由独立测试覆盖；真实 SSE 驱动的 badge 联动整合测试可补充，但本轮不阻断。

- 总体判断：分组邮件角色矩阵、失败原子性、分组管理 UI 刷新和浏览器拖拽失败路径仍有重要验收缺口；Round 1 的阻断项未全部消除，本轮另发现 offset/回滚假绿与真实下拉交互缺失，FAIL。

- AC 复验方式：`re_verified` 表示本轮独立核对测试断言并执行了前端测试；`trust_prior` 表示依赖 attempt 2 已产出的 PostgreSQL/浏览器执行结果，本 reviewer 未在当前 worktree 重跑这些门禁（此 worktree 无 `.env.test`）。

    - AC-001：`trust_prior` — 检查了名称边界与重命名 API 断言；PG 运行结果依赖 attempt 2 的 401 passed 报告，失败后名称未独立读取。
    - AC-002：`trust_prior` — 检查了独立会话保留账号/邮件/附件/顺序断言；凭据夹具缺失，PG 运行依赖 attempt 2。
    - AC-003：`trust_prior` — 检查了 API 布局和浏览器跨组/移出路径；依赖 attempt 2 全栈 E2E。
    - AC-004：`trust_prior` — 检查了默认域排序、手动顺序与重置断言；依赖 PostgreSQL 集成运行。
    - AC-005：`trust_prior` — 检查了 master 重排保留归属及顺序独立断言；并发完整快照仍缺，PG/E2E 运行依赖 attempt 2。
    - AC-006：`trust_prior` — 检查了默认恢复、分组顺序刷新断言；新增组/账号追加末尾未直接断言。
    - AC-007：`trust_prior` — 检查了重复/遗漏/外组载荷拒绝和删除/布局并发；两个布局写并发仍未覆盖。
    - AC-008：`trust_prior` — 检查了空库 E2E 与迁移升级/降级中的成员、顺序保留断言；PG 运行依赖 attempt 2。
    - AC-009：`trust_prior` — 检查了无 demo 组的组件断言；迁移/空库运行依赖 attempt 2。
    - AC-010：`trust_prior` — 检查了 group inbox/sent 与成员隔离；drafts/trash/junk/archive 的组范围未覆盖。
    - AC-011：`trust_prior` — 检查了组内 cursor 分页去重、空组统计/全部已读；升序同时间遍历未覆盖。
    - AC-012：`trust_prior` — 检查了 offset/total/账号范围断言；页间唯一性缺失，见 f009。
    - AC-013：`trust_prior` — 检查了组员已读状态、组外状态及 RemoteOperation/OutboxEvent；flag 筛选组合缺失。
    - AC-014：`trust_prior` — 检查了不存在组和 account_id/folder_id 的 mark-all-read 歧义；列表/search 的 folder_id 组合缺失。
    - AC-015：`trust_prior` — 检查了成员变更后下一次列表按新成员返回；旧 cursor 场景缺失。
    - AC-016：`trust_prior` — 检查了现有无范围 API 测试及认证/CSRF 相关测试；PG/API 运行依赖 attempt 2。
    - AC-017：`trust_prior` — 检查了浏览器顶层顺序和独立折叠测试；E2E 运行依赖 attempt 2。
    - AC-018：`re_verified` — 前端测试通过并检查六类全局/分组入口和 unread 导航断言。
    - AC-019：`re_verified` — 前端测试通过并检查真实目录展开、嵌套目录和导航测试断言。
    - AC-020：`trust_prior` — 检查了精确 CSS 层级与文本对齐 E2E；真实浏览器执行依赖 attempt 2。
    - AC-021：`re_verified` — 前端测试通过并检查 group/global/account query key 隔离及组 inbox/search 请求。
    - AC-022：`re_verified` — 前端测试通过并检查 badge 2→3、未知值及 `folder.stats_updated` 前缀失效测试。
    - AC-023：`re_verified` — 前端测试通过并检查分区、组、账号展开偏好重建 store 后恢复。
    - AC-024：`trust_prior` — 检查了 keyboard、760px 与浅深主题浏览器断言；E2E 运行依赖 attempt 2。
    - AC-025：`re_verified` — 前端完整测试通过；搜索、筛选、排序、分页、消息操作既有断言仍在。
    - AC-026：`re_verified` — 前端测试通过并检查用户组名渲染及无 demo 名称断言。
    - AC-027：`re_verified` — 前端测试通过并检查“新建分组”入口及 POST groups 路径；重查后出现组的断言仍缺。
    - AC-028：`re_verified` — 前端测试通过并检查失败输入保留/重试；成功后新标题断言仍缺。
    - AC-029：`re_verified` — 前端测试通过并检查删除当前组后的 view/selection 清理；确认取消与成员保留 UI 断言仍缺。
    - AC-030：`re_verified` — 前端测试通过并检查清空归属 mutation；直接 `.value` 赋值且未测选择另一组，见 f010。
    - AC-031：`re_verified` — 前端测试通过并检查创建输入和账号保存请求；设置/侧栏数据刷新一致性仍缺。
    - AC-032：`re_verified` — 前端测试通过并检查创建取消焦点恢复；Escape、HTML 特殊字符和窄屏移组 UI 测试仍缺。
    - AC-033：`re_verified` — 前端测试通过并检查自定义名称和不预置 demo 组；空组创建入口/特殊字符实际渲染仍缺。
    - AC-034：`trust_prior` — 检查了真实浏览器成功拖拽及合成事件负例；整行任意位置/不误触/反馈清理的真实 E2E 依赖 attempt 2。
    - AC-035：`trust_prior` — 检查了真实浏览器空组、已有组追加和跨组前插测试；浏览器运行依赖 attempt 2。
    - AC-036：`trust_prior` — 检查了组到总列表标题和目标账号行拖出；空区目标路径未覆盖，运行依赖 attempt 2。
    - AC-037：`trust_prior` — 检查了总列表重排保留组归属及组内重排请求；真实浏览器运行依赖 attempt 2。
    - AC-038：`trust_prior` — 检查了组顺序/总列表顺序拖动和刷新断言；运行依赖 attempt 2。
    - AC-039：`trust_prior` — 检查了浏览器恢复默认排序响应和字段清除断言；失败回滚仍无测试，运行依赖 attempt 2。
    - AC-040：`trust_prior` — 检查了真实浏览器正向拖拽与合成事件负例；保存失败假绿见 f008，浏览器取消/连续拖动仍缺，运行依赖 attempt 2。

    coverage = 14 / 40
    建议合并前人工抽查 trust_prior 项。

- 系统性 follow-up：无。

verdict: FAIL

## Round 3 (2026-10-23T06:34:22+08:00)

reviewed_scope: c2e68903705cd66c

### Findings

本轮无新增 finding。

### 前轮 finding 复核

- `t027_test_f001`：已消除。失败重命名后独立查询仍确认原组名；非空组删除后独立会话确认账号、凭据引用、邮件、附件与 `master_order` 保留（`tests/mail_core/test_accounts_api_pg.py:64-119`）。

- `t027_test_f002`：已消除。新增并发完整快照测试要求两个相同 revision 的布局写入恰有一个成功、一个冲突，并逐字段核对服务端快照等于胜出提交（`tests/mail_core/test_sidebar_group_scope.py:376-423`）。

- `t027_test_f003`：阻断缺口已消除。现有新增测试覆盖 drafts/trash/junk/archive、升降序同时间 cursor、旗标筛选、列表与搜索的 `folder_id` 歧义及 offset 页 ID 唯一性（`test_sidebar_group_scope.py:154-197,465-599`）；前端测试检查 group unread 请求带 `group_id` 与 `is_read=false`（`MessageList.test.tsx:134-145`）。移组后旧 cursor 的直接复用仍未单独断言，但成员变化后的请求及 group 页面缓存清理均有测试；仅作为非阻断扩展提示。

- `t027_test_f004`：已消除。全局/账号/组 badge、未知计数、成员改变后组 badge 2→3、`folder.stats_updated` 对 stats query key 的前缀失效均有断言，见 Round 2。

- `t027_test_f005`：已消除。浏览器用例仍核对 24px/48px 缩进、层级对齐、主题与 760px 两侧行为，见 Round 2。

- `t027_test_f006`：修不彻底，仍为 important。侧栏创建与重命名后新名称可见、删除取消保留成员、菜单 Escape 与特殊字符均已补测；真实浏览器也覆盖设置下拉移入另一组及清空。仍没有测试设置页创建/删除后侧栏同步同一服务端结果。`SettingsModal.test.tsx:151-183` 创建 mock 成功后仍让 `GET /api/groups` 固定返回空组，只断言提示与输入清空；删除用例 `:204-240` 也保留静态 groups，且只检查 store 回退。若设置入口遗漏 groups/sidebar-layout invalidation，两项仍可全绿；侧栏自身创建/删除测试不能验证设置入口的跨组件失效行为（AC-031）。建议在同一测试会话中经设置入口创建/删除，再断言侧栏重查并与服务端列表一致。

- `t027_test_f007`：已消除。真实浏览器 E2E 现覆盖失败保存及服务端归属/布局保持、同账号无效拖放、外部拖放、菜单/箭头操作后的拖放状态清理，以及保存 pending 时拒绝第二次拖动（`tests/e2e/full_stack.spec.ts:404-588`）；此前缺少真实浏览器负例与失败路径的阻断问题消除。拖动过程中目标反馈出现时刻未单独断言，作为非阻断提示。

- `t027_test_f008`：已消除。组件用例现在断言失败后账号仍在 master、未进目标组（`Sidebar.test.tsx:527-541`）；真实浏览器 500 用例进一步读取布局与账号 API，确认服务端归属未变（`full_stack.spec.ts:404-458`）。

- `t027_test_f009`：已消除。搜索 offset 用例比较两页全部 ID，要求无重复且唯一集合等于四封夹具邮件（`test_sidebar_group_scope.py:580-588`）。

- `t027_test_f010`：已消除。虽然组件 helper `changeSelect` 仍通过原生 setter 和合成 change 事件测试状态更新，真实 Playwright 测试改用 `selectOption` 分别移入另一组、清空，并检查 PATCH、界面组名及服务端归属（`full_stack.spec.ts:344-402`），不再以程序赋值替代唯一交互证据。

- 改测方向复核：无。检查既有测试删改，旧导航与计数语义由新的组件、query/store、真实目录浏览器测试替代；迁移 revision 断言同步新增迁移，没有发现就地修改旧预期迁就实现。

- 危险模式扫描：未发现新增 `.skip` / `.only`、断言注释、恒真断言、条件跳过断言或 mock 被测逻辑。`pytest.mark.skipif` 仅在数据库 URL 缺失时跳过 PostgreSQL 集成用例；`MessageList.test.tsx:122` 的 `.value` 赋值用于 IME 合成输入测试，不冒充鼠标/键盘操作。设置下拉现有 setter helper 不作为 AC-030 的唯一证据，真实 E2E 已补。

- 本轮新发现：0。

- 未进表的提示：成员改变后直接携带旧 cursor 再查的场景、拖动中途目标反馈的正向可见断言仍可补充；当前分别有首屏缓存清理/新成员请求、真实拖放与取消后反馈清理覆盖，不阻断。独立执行 `npm test -- --run`（`src/frontend`）：38 files / 213 tests passed，OpenAPI 与 CSS token 检查通过。当前环境 `MAIL_CORE_DATABASE_URL` 未设置，未重跑 PostgreSQL 集成与全栈 E2E；不据此声明本轮新增数据库/浏览器测试已执行通过。

- 总体判断：Round 1 的服务端事务、分页、分类、计数和真实拖拽阻断缺口已补齐；设置入口创建/删除与侧栏结果同步（AC-031）仍无可信跨组件测试，FAIL。

- 系统性 follow-up：无。

- AC 复验方式：以下 `re_verified` 表示独立检查生产测试路径与断言；本轮前端完整测试已执行，PostgreSQL/全栈 E2E 只做静态证据审查，未重跑。

    - AC-001：`re_verified` — rename trim/长度/空白/重名/不存在错误及失败后原名断言，`test_accounts_api_pg.py:64-84`。
    - AC-002：`re_verified` — 删除后独立会话核对账号、凭据、邮件、附件和 `master_order`，`test_accounts_api_pg.py:86-119`。
    - AC-003：`re_verified` — API 完整布局和真实浏览器设置移组覆盖无组到组及清空，`test_sidebar_group_scope.py:199-236`、`full_stack.spec.ts:344-402`。
    - AC-004：`re_verified` — 域名排序、手动顺序持久化及默认恢复断言，`test_sidebar_group_scope.py:243-296`。
    - AC-005：`re_verified` — master/group 顺序独立与归属保持，并发胜出快照核对，`test_sidebar_group_scope.py:243-296,376-423`。
    - AC-006：`re_verified` — 默认排序恢复、组顺序刷新及新项末尾浏览器/API 断言，`test_sidebar_group_scope.py:243-296`、`full_stack.spec.ts:187-341`。
    - AC-007：`re_verified` — 缺组、外组成员、重叠载荷原子拒绝及并发 stale revision 冲突，`test_sidebar_group_scope.py:298-423`。
    - AC-008：`re_verified` — 迁移升降级后组织数据保留，`test_migration_validation.py`。
    - AC-009：`re_verified` — 无 demo 组、自定义名称与已有组迁移断言，`Sidebar.test.tsx:189-226`、`test_migration_validation.py`。
    - AC-010：`re_verified` — inbox/sent/drafts/trash/junk/archive 组员集合、重复位置去重与 group unread 请求，`test_sidebar_group_scope.py:465-578`、`MessageList.test.tsx:134-145`。
    - AC-011：`re_verified` — 空组列表/搜索/统计/全部已读及相同时间升降序 cursor 遍历，`test_sidebar_group_scope.py:33-120,553-563`。
    - AC-012：`re_verified` — 搜索 total、offset、页间 ID 唯一集合与组范围，`test_sidebar_group_scope.py:580-588`。
    - AC-013：`re_verified` — group、role、flag 组合只改匹配组员并产生 RemoteOperation，`test_sidebar_group_scope.py:154-197`。
    - AC-014：`re_verified` — 不存在组、group/account 与 group/folder 列表/搜索/全部已读歧义错误，`test_sidebar_group_scope.py:90-114,573-575`。
    - AC-015：`re_verified` — 移组后新请求使用当前成员，且 group cursor/offset cache helper 会清空页面，`test_sidebar_group_scope.py:599-608`、`queries.cache.test.ts:14-23`；旧 cursor 直接复用未独立覆盖。
    - AC-016：`re_verified` — 原无范围 API 测试保留，新增 API 与 OpenAPI 类型/CSRF 测试路径存在；本轮 OpenAPI check 通过。
    - AC-017：`re_verified` — 顶层顺序、三区折叠与浏览器布局断言，`sidebar_tree.spec.ts:199-266`。
    - AC-018：`re_verified` — 六个全局/组入口、空组与账号成员导航，`Sidebar.test.tsx:189-226`。
    - AC-019：`re_verified` — 真实目录展开、嵌套目录与账号行导航，`sidebar_tree.spec.ts:59-168`。
    - AC-020：`re_verified` — 浏览器精确层级 padding、文字对齐和视口边界，`sidebar_tree.spec.ts:199-266`。
    - AC-021：`re_verified` — group/global/account/folder query key 隔离和切换状态测试，`queries.scope.test.ts`、`MessageList.test.tsx`。
    - AC-022：`re_verified` — badge 未知值、成员变更 2→3 及 stats SSE 前缀失效，`Sidebar.test.tsx:279-317`、`useMailCoreRealtime.test.ts:10-58`。
    - AC-023：`re_verified` — 分区、组、账号展开偏好重建 store 后恢复，`persistence.test.ts`。
    - AC-024：`re_verified` — 键盘、aria-expanded、浅深主题与 760px 两侧布局，`sidebar_tree.spec.ts:169-266`。
    - AC-025：`re_verified` — 旧邮件列表分类、搜索、筛选、排序、分页和操作测试保留，前端套件 213 tests passed。
    - AC-026：`re_verified` — 任意组名和无 demo 名称断言，`Sidebar.test.tsx:189-226,472-512`。
    - AC-027：`re_verified` — 侧栏加号可创建分组且新组出现，`Sidebar.test.tsx:472-499`。
    - AC-028：`re_verified` — 侧栏重命名成功显示新值、失败保留输入并可重试，`Sidebar.test.tsx:421-446,501-512`。
    - AC-029：`re_verified` — 删除确认取消保留组员，确认删除当前组后回到所有收件箱，`Sidebar.test.tsx:472-499,514-525`。
    - AC-030：`re_verified` — 真实 browser selectOption 移入其他组/清空并核对 PATCH 与服务端成员，`full_stack.spec.ts:344-402`。
    - AC-031：`re_verified` — 仅核对了 Settings create/delete 自身请求；跨侧栏一致性无测试，见 `t027_test_f006`，构成未解决阻断。
    - AC-032：`re_verified` — 菜单 Escape/焦点恢复、`<自定义>` 普通文本及设置移组路径有测试；窄屏尺寸下选择流程未独立运行，`Sidebar.test.tsx:448-470`、`full_stack.spec.ts:344-402`。
    - AC-033：`re_verified` — 自定义分组输入、空组和无预置 demo 组断言，`Sidebar.test.tsx:189-226,472-499`。
    - AC-034：`re_verified` — 浏览器整行拖动、箭头/菜单点击不写布局、自拖与外部拖放后的反馈清理，`full_stack.spec.ts:187-341,463-509`。
    - AC-035：`re_verified` — 真实浏览器空组、折叠组、组标题追加、跨组插入与组顺序请求，`full_stack.spec.ts:247-320`。
    - AC-036：`re_verified` — 组拖至账号行/账号列表标题移出并核对服务端成员，`full_stack.spec.ts:282-315`。
    - AC-037：`re_verified` — master 重排保留归属、组内重排独立保存，`full_stack.spec.ts:265-341`。
    - AC-038：`re_verified` — 组顺序和总列表顺序分别持久化并 reload 验证，`full_stack.spec.ts:319-341`。
    - AC-039：`re_verified` — 恢复默认排序请求及服务端 order 字段清除，`full_stack.spec.ts:330-341`。
    - AC-040：`re_verified` — 真实浏览器失败回滚、自拖/外部拖放及 pending 时拒绝第二次拖动，`full_stack.spec.ts:404-588`。

    coverage = 40 / 40

    建议合并前人工抽查 PostgreSQL 与全栈 E2E 执行结果；本轮 reviewer 环境未重跑。

verdict: FAIL

## Round 4 (2026-10-23T06:43:59+08:00)

reviewed_scope: d8010a2b6a03ba40

### Findings

本轮无新增 finding。

### 前轮 finding 复核

- `t027_test_f001`：已消除。名称错误后原组名与删除后凭据、账号、邮件、附件、总列表顺序均有独立会话断言。

- `t027_test_f002`：已消除。相同 revision 的并发完整布局写入要求一成一冲突，并逐字段检查胜出快照。

- `t027_test_f003`：已消除阻断项。角色、相同时间升降序分页、flag 筛选、folder_id 歧义、offset 唯一 ID、成员变化后查询和 group 页面缓存清理均有覆盖；旧 cursor 直接复用仍可作为非阻断扩展。

- `t027_test_f004`：已消除。角标、未知计数、成员变化和 SSE stats 前缀失效断言仍在。

- `t027_test_f005`：已消除。浏览器布局 E2E 覆盖 24px/48px 层级、主题和 760px 两侧尺寸。

- `t027_test_f006`：修不彻底，仍为 important。新增 `SettingsModal.test.tsx:186-240` 在同一 QueryClient 下通过设置页创建/删除分组，动态 mock 并断言侧栏组名出现/消失及 `/api/groups` 重查；这修复了 Round 3 指出的“设置操作与侧栏组列表完全没有联测”。但 fixture 的 `/api/accounts` 始终返回空列表，测试未断言 `/api/sidebar/layout` 重查或新组行变为可拖状态。若设置成功路径漏掉 `sidebarLayout` invalidation，侧栏仍可显示新组名，但旧 layout 与新 groups 不一致，`Sidebar.tsx:344-354` 的 `layoutReady` 为 false，账号/组拖动会被禁用；该测试仍全绿。删除侧同样没有成员账号，不能验证旧归属刷新。建议 fixture 加一个成员账号，并断言布局 revision/成员快照刷新及移组后的侧栏成员状态。该 AC-031 失效路径仍未被当前测试验证。

- `t027_test_f007`：已消除。真实浏览器 E2E 覆盖拖动成功矩阵、保存失败、无效/外部拖放及保存期间拒绝第二次拖动。

- `t027_test_f008`：已消除。失败保存同时断言账号仍在 master、目标组无账号，且真实浏览器读取服务端归属。

- `t027_test_f009`：已消除。offset 两页 ID 不相交且合并 ID 集合等于预期夹具。

- `t027_test_f010`：已消除。真实浏览器 `selectOption` 覆盖选择另一组和清空；组件 setter helper 不再是唯一 AC 证据。

- 改测方向复核：无。Round 4 新增测试，不改旧断言预期；Round 1–3 的测试替换与迁移断言仍有新语义覆盖。

- 危险模式扫描：未发现新增 `.skip` / `.only`、注释断言、恒真断言、静默错误抑制或程序赋值替代 AC 真实交互。数据库 `skipif` 仍只保护缺少 PostgreSQL URL 的集成环境；`.value` 的 IME 测试与 `toMatchObject` 用法未用于弱化本 task AC。

- 本轮新发现：0。

- 未进表的提示：Round 4 的设置跨组件用例已验证 groups 查询结果同步；布局 snapshot/成员账号断言仍缺，已并入 f006。其他剩余项为旧 cursor 直接复用和拖动中途反馈可见时刻，均属可选扩展。前端完整套件本轮独立运行通过：38 files / 216 tests，OpenAPI 与 CSS token 检查通过。父任务报告全栈 E2E 8/8；本 reviewer 未重跑 PostgreSQL/E2E。

- 总体判断：本轮补测证明设置入口可刷新侧栏组列表，但未证明布局与成员查询同步；Round 3 的 f006 AC-031 阻断路径仍可假绿，FAIL。

- 系统性 follow-up：无。

- AC 复验方式：`re_verified` 表示独立检查生产测试路径与断言；本轮前端完整套件已运行。PostgreSQL 与真实浏览器 E2E 未由本 reviewer 重跑，执行结果按父任务提供的 401 PG passed（前轮）及 full-stack E2E 8/8 记录披露。

    - AC-001：`re_verified` — rename trim、128 字符边界、空白/重复/不存在错误及失败后原名断言，`test_accounts_api_pg.py:64-84`。
    - AC-002：`re_verified` — 独立会话核对凭据、账号、邮件、附件和 `master_order`，`test_accounts_api_pg.py:86-119`。
    - AC-003：`trust_prior` — 账号无组、跨组和清空路径由全栈 E2E 覆盖；父任务报告 full-stack 8/8。
    - AC-004：`re_verified` — 域名默认排序、手动顺序、重新请求和恢复默认断言，`test_sidebar_group_scope.py:243-296`。
    - AC-005：`re_verified` — master/group 顺序独立与并发胜出快照检查，`test_sidebar_group_scope.py:243-296,376-423`。
    - AC-006：`trust_prior` — 新组/组成员末尾、恢复默认及重载由 E2E/API 断言，依赖父任务 full-stack 8/8。
    - AC-007：`re_verified` — 非法完整载荷原子失败与并发 revision 冲突快照，`test_sidebar_group_scope.py:298-423`。
    - AC-008：`re_verified` — 迁移升降级后已有成员与顺序保留，`test_migration_validation.py`。
    - AC-009：`re_verified` — 无预置 demo 组及合法组名迁移/渲染断言，`Sidebar.test.tsx:189-226`、`test_migration_validation.py`。
    - AC-010：`re_verified` — 六类支持角色的组员集合、重复位置去重及 inbox unread 请求，`test_sidebar_group_scope.py:465-578`、`MessageList.test.tsx:134-145`。
    - AC-011：`re_verified` — 空组列表/搜索/统计/已读和相同时间升降序分页唯一性，`test_sidebar_group_scope.py:33-120,553-563`。
    - AC-012：`re_verified` — 搜索 total、offset、唯一页 ID 和组员范围，`test_sidebar_group_scope.py:580-588`。
    - AC-013：`re_verified` — group/role/flag 已读范围与远端写回队列，`test_sidebar_group_scope.py:154-197`。
    - AC-014：`re_verified` — group/account 与 group/folder 组合错误及不存在组错误，`test_sidebar_group_scope.py:90-114,573-575`。
    - AC-015：`re_verified` — 成员变化后新请求读取当前归属，前端重置 group 页面缓存，`test_sidebar_group_scope.py:599-608`、`queries.cache.test.ts:14-23`；旧 cursor 直接复用未单测。
    - AC-016：`re_verified` — 原无范围 API 测试保留，OpenAPI 生成类型检查本轮通过。
    - AC-017：`trust_prior` — 顶层顺序、三区折叠的真实浏览器断言，E2E 执行依赖父任务结果。
    - AC-018：`re_verified` — 全局/组六类入口、空组与账号成员导航，`Sidebar.test.tsx:189-226`。
    - AC-019：`re_verified` — 账号真实目录、嵌套目录与行导航，`sidebar_tree.spec.ts:59-168`。
    - AC-020：`trust_prior` — 24px/48px 布局、文字对齐的浏览器断言，E2E 执行依赖父任务结果。
    - AC-021：`re_verified` — query key 范围隔离、选择重置和空 placeholder 策略，`queries.scope.test.ts`、`MessageList.test.tsx`。
    - AC-022：`re_verified` — badge 未知值、成员变化和 SSE stats 前缀失效，`Sidebar.test.tsx:279-317`、`useMailCoreRealtime.test.ts:10-58`。
    - AC-023：`re_verified` — 本地偏好恢复与删除末账号后的 mail/stats 清理，`persistence.test.ts`、`SettingsModal.test.tsx:243-291`。
    - AC-024：`trust_prior` — 鼠标/键盘、主题与 760px 两侧布局的浏览器断言，E2E 执行依赖父任务结果。
    - AC-025：`re_verified` — 既有邮件分类、搜索/筛选/排序/分页/操作回归；前端 216 tests 通过。
    - AC-026：`re_verified` — 用户组名与无 demo 组断言，`Sidebar.test.tsx:189-226,472-512`。
    - AC-027：`re_verified` — 侧栏入口创建后新组出现在导航，`Sidebar.test.tsx:472-499`。
    - AC-028：`re_verified` — rename 成功标题刷新、失败保留输入/重试和 pending 防重，`Sidebar.test.tsx:421-446,501-512`。
    - AC-029：`re_verified` — 删除取消保留成员及删除当前组后返回所有收件箱，`Sidebar.test.tsx:472-499,514-525`。
    - AC-030：`trust_prior` — 真实设置下拉移入另一组及清空，并核对 PATCH/UI/API，执行依赖父任务 full-stack 8/8。
    - AC-031：`re_verified` — 设置创建/删除后的侧栏组名刷新有集成断言；布局 snapshot 与成员账号刷新未验证，见 f006，`SettingsModal.test.tsx:186-240`。
    - AC-032：`re_verified` — 菜单 Escape/焦点恢复、特殊字符文本与设置移组路径测试存在；窄屏尺寸未单独设置，`Sidebar.test.tsx:448-470`。
    - AC-033：`re_verified` — 用户自定义名称、空组和无 demo 名称断言，`Sidebar.test.tsx:189-226,472-499`。
    - AC-034：`trust_prior` — 真实浏览器整行拖动、误触隔离及结束后反馈清理，执行依赖父任务 E2E 8/8。
    - AC-035：`trust_prior` — 浏览器空组/折叠组/有成员组追加与跨组插入，执行依赖父任务 E2E 8/8。
    - AC-036：`trust_prior` — 组账号拖至 master 标题/目标账号行并核验服务端成员，执行依赖父任务 E2E 8/8。
    - AC-037：`trust_prior` — master 内重排保留组归属、组内顺序独立，执行依赖父任务 E2E 8/8。
    - AC-038：`trust_prior` — 分组与 master 排序 reload 持久化，执行依赖父任务 E2E 8/8。
    - AC-039：`trust_prior` — 恢复默认排序 API 与服务端 order 清除，执行依赖父任务 E2E 8/8。
    - AC-040：`trust_prior` — 真实浏览器保存失败、无效/外部拖放与 pending 拒绝第二次拖动，执行依赖父任务 E2E 8/8。

    coverage = 27 / 40
    建议合并前人工抽查 trust_prior 项。

verdict: FAIL

## Round 5 (2026-10-23T06:49:28+08:00)

reviewed_scope: 18514639e6c252b7

### Findings

本轮无新增 finding。

### 前轮 finding 复核

- `t027_test_f001`：已消除。名称校验失败后原组名未变；删除非空组后独立会话核对凭据、账号、邮件、附件及顺序。

- `t027_test_f002`：已消除。并发完整快照测试验证一写成功、一写冲突，并核对胜出布局全部字段。

- `t027_test_f003`：已消除阻断缺口。分组角色、cursor/offset 分页、旗标筛选、folder_id 歧义、空组及成员变化有覆盖；旧 cursor 直接复用仍是非阻断扩展项。

- `t027_test_f004`：已消除。计数、未知值、组成员变化及 SSE stats 前缀失效断言保留。

- `t027_test_f005`：已消除。浏览器布局断言覆盖层级间距、主题与 760px 两侧视图。

- `t027_test_f006`：已消除。Round 5 扩展 `SettingsModal.test.tsx:186-283`：同一 QueryClient 下同时挂载 `Sidebar` 与 `SettingsPage`，动态 mock 账号归属、分组及布局快照；设置创建后断言新组可拖，账号移入后检查 account/layout 查询读到新归属且组内账号可拖，删除后检查账户 query group_id 清空、侧栏回到 master 可拖并且 account/layout 均重新读取。`Sidebar.tsx:344-354,660-663` 中 `layoutReady` 控制拖动可用；这些断言能发现漏掉 sidebarLayout/account invalidation 导致的 stale snapshot。此前 f006 的 AC-031 阻断缺口已修复。

- `t027_test_f007`：已消除。真实浏览器拖动成功、失败、无效/外部目标及 pending 时阻止第二次保存均有 E2E。

- `t027_test_f008`：已消除。失败布局保存后组件仍保留原列表归属，浏览器测试也核对服务端布局和账号。

- `t027_test_f009`：已消除。offset 分页两页 ID 唯一且等于夹具集合。

- `t027_test_f010`：已消除。真实浏览器 selectOption 覆盖改组与清空；组件 setter helper 只作状态测试。

- 改测方向复核：无。Round 5 新增联动场景，没有改旧测试预期或迁就实现。

- 危险模式扫描：未发现新增 `.skip` / `.only`、断言删除/反转、恒真断言、静默错误抑制或 mock 被测逻辑。`.value` 仅出现在 IME 合成输入测试；数据库 `skipif` 仍按环境隔离 PostgreSQL 用例；设置组选择的真实用户交互仍由 Playwright E2E 覆盖。

- 本轮新发现：0。

- 未进表的提示：旧 cursor 直接复用与拖动过程中的目标反馈出现时刻仍可补充，均属非阻断扩展。前端完整套件本轮独立通过：38 files / 217 tests，OpenAPI 与 CSS token 检查通过。父任务前轮报告 full-stack E2E 8/8；本 reviewer 未重跑 PostgreSQL/真实浏览器套件。

- 总体判断：Round 5 已用账号归属和布局快照验证设置操作与侧栏联动，所有未解决 important test finding 已消除，PASS。

- 系统性 follow-up：无。

- AC 复验方式：`re_verified` 表示独立检查测试路径与断言；本轮前端完整套件已运行。PostgreSQL 和真实浏览器 E2E 未由本 reviewer 重跑，相关执行结果依赖前轮 PG 401 passed 与父任务 full-stack E2E 8/8 记录。

- AC-001：`re_verified` — 名称 trim、长度、空白/重复/不存在错误与失败后原名，`test_accounts_api_pg.py:64-84`。

- AC-002：`re_verified` — 删除后独立读取凭据、账号、邮件、附件和 master 顺序，`test_accounts_api_pg.py:86-119`。

- AC-003：`trust_prior` — 真实 E2E 覆盖无组移入、跨组及清空，父任务报告 full-stack 8/8。

- AC-004：`re_verified` — 域名顺序、手动排序持久化和默认恢复，`test_sidebar_group_scope.py:243-296`。

- AC-005：`re_verified` — master/group 顺序独立及并发胜出快照，`test_sidebar_group_scope.py:243-296,376-423`。

- AC-006：`trust_prior` — 新分组/账号追加、默认恢复和刷新顺序由 API/E2E 断言覆盖，执行依赖父任务结果。

- AC-007：`re_verified` — 非法布局原子拒绝与并发 stale revision，`test_sidebar_group_scope.py:298-423`。

- AC-008：`re_verified` — 迁移升降级保留已有组织数据，`test_migration_validation.py`。

- AC-009：`re_verified` — 无 demo 组、自定义名称与旧组迁移断言，`Sidebar.test.tsx:189-226`、`test_migration_validation.py`。

- AC-010：`re_verified` — 六类邮件角色组员范围、重复位置去重及 unread 参数，`test_sidebar_group_scope.py:465-578`、`MessageList.test.tsx:134-145`。

- AC-011：`re_verified` — 空组行为与相同时间升降序逐页去重，`test_sidebar_group_scope.py:33-120,553-563`。

- AC-012：`re_verified` — 搜索 total/offset 页 ID 唯一及组范围，`test_sidebar_group_scope.py:580-588`。

- AC-013：`re_verified` — 组/角色/flag 全部已读范围及写回队列，`test_sidebar_group_scope.py:154-197`。

- AC-014：`re_verified` — 不存在组、group/account 与 group/folder 歧义错误，`test_sidebar_group_scope.py:90-114,573-575`。

- AC-015：`re_verified` — 成员变化后新请求与 group 页面缓存重置，`test_sidebar_group_scope.py:599-608`、`queries.cache.test.ts:14-23`；旧 cursor 直接复用未单测。

- AC-016：`re_verified` — 原全局/账号/folder 范围测试保留，OpenAPI 检查通过。

- AC-017：`trust_prior` — 真实浏览器顶层顺序与折叠断言，执行依赖父任务 E2E 结果。

- AC-018：`re_verified` — 六类全局/组入口、空组和账号成员导航，`Sidebar.test.tsx:189-226`。

- AC-019：`re_verified` — 真实目录及嵌套文件夹导航，`sidebar_tree.spec.ts:59-168`。

- AC-020：`trust_prior` — 24px/48px 与文字对齐真实浏览器断言，执行依赖父任务结果。

- AC-021：`re_verified` — query key 隔离、状态重置与无 placeholder，`queries.scope.test.ts`、`MessageList.test.tsx`。

- AC-022：`re_verified` — 未知计数、成员变化和 SSE stats 前缀失效，`Sidebar.test.tsx:279-317`、`useMailCoreRealtime.test.ts:10-58`。

- AC-023：`re_verified` — 本地偏好恢复、删除末账号后 stats/mail cache 清理，`persistence.test.ts`、`SettingsModal.test.tsx:285-324`。

- AC-024：`trust_prior` — 鼠标/键盘、主题与 760px 两侧浏览器断言，执行依赖父任务结果。

- AC-025：`re_verified` — 邮件分类/搜索/筛选/排序/分页/操作回归，前端 217 tests 通过。

- AC-026：`re_verified` — 任意组名及无 demo 组断言，`Sidebar.test.tsx:189-226,472-512`。

- AC-027：`re_verified` — 侧栏加号创建后新组出现，`Sidebar.test.tsx:472-499`。

- AC-028：`re_verified` — rename 成功刷新、失败保留输入和 pending 防重，`Sidebar.test.tsx:421-446,501-512`。

- AC-029：`re_verified` — 删除取消保留组员与当前组删除回退，`Sidebar.test.tsx:472-499,514-525`。

- AC-030：`trust_prior` — 真实下拉选择另一组/清空并核对 UI/API，执行依赖父任务 full-stack 8/8。

- AC-031：`re_verified` — Settings create/move/delete 后组名、account query、layout query 与 master/group 拖动状态更新，`SettingsModal.test.tsx:186-283`。

- AC-032：`re_verified` — Escape/焦点恢复、特殊字符和非拖动移组路径，`Sidebar.test.tsx:448-470`、`full_stack.spec.ts:344-402`。

- AC-033：`re_verified` — 用户组输入、空组及无 demo 名称，`Sidebar.test.tsx:189-226,472-499`。

- AC-034：`trust_prior` — 整行浏览器拖动、误触隔离及反馈清理，执行依赖父任务 E2E 8/8。

- AC-035：`trust_prior` — 空/折叠/有成员组追加与跨组插入，执行依赖父任务 E2E 8/8。

- AC-036：`trust_prior` — 拖出组到 master 标题/账号行，核对成员归属，执行依赖父任务 E2E 8/8。

- AC-037：`trust_prior` — master 重排保留归属、组内顺序独立，执行依赖父任务 E2E 8/8。

- AC-038：`trust_prior` — 分组与 master 排序 reload 持久化，执行依赖父任务 E2E 8/8。

- AC-039：`trust_prior` — 恢复默认排序请求和服务端 order 清除，执行依赖父任务 E2E 8/8。

- AC-040：`trust_prior` — 真实浏览器失败回滚、无效/外部拖放与 pending 拒绝第二次拖动，执行依赖父任务 E2E 8/8。

coverage = 27 / 40
建议合并前人工抽查 trust_prior 项。

verdict: PASS
