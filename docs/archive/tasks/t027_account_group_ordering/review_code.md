# Task review t027（reviewer_focus: 代码）

- task：`t027_account_group_ordering`
- spec：`docs/tasks/t027_account_group_ordering/spec.md`
- diff_anchor：`c8cee92446f9c24e7a0a2a501d52d0bd49068041`
- target：`git -C '[REDACTED_LOCAL_PATH]' diff c8cee92446f9c24e7a0a2a501d52d0bd49068041`
- round：1
- reviewed_at：2026-10-23T05:11:04+08:00

reviewed_scope: bf4b2a1ea5d38c45

## Findings

### t027_code_f001 - 删除分组与保存布局采用反向锁顺序

- 严重度：important
- 锚点：AC-007；并发保存布局与删除含成员分组时应有明确冲突处理，不应因竞争返回未处理的服务端错误。
- 位置：`src/mail_core/accounts/service.py:210`、`src/mail_core/accounts/service.py:278`
- 问题：`save_sidebar_layout` 先锁全部 `AccountGroup`，再锁 `Account`；`delete_group` 先锁组员 `Account`，最后删除 `AccountGroup`。当分组至少有一个账号时，并发事务可形成“保存布局持有分组锁、等待账号锁；删除分组持有账号锁、等待分组锁”的死锁。数据库会中止其中一方，但路由未将死锁映射为明确冲突响应，调用方收到 500。
- 建议：所有组织写操作按同一顺序锁分组与账号；将删除事务改为先锁分组再锁成员账号，并把可重试冲突映射为明确响应。

### t027_code_f002 - 连续拖拽用旧查询快照覆盖前一次保存

- 严重度：important
- 锚点：AC-040；同一页面连续拖动不能让旧布局覆盖新操作。
- 位置：`src/frontend/src/components/Sidebar.tsx:321`、`src/frontend/src/components/Sidebar.tsx:336`、`src/frontend/src/components/Sidebar.tsx:468`
- 问题：每次拖放都从当前 React Query 的 `groups`/`accounts` 组装完整布局，再并行发送保存请求。请求完成并重新查询前，界面仍允许再次拖拽；第二个请求基于旧快照，只包含第二次操作。若两次请求依次提交，第二个完整快照会撤销第一次排序或移组，最终后端状态丢失一次有效操作。
- 建议：对布局写入串行化，并基于最近一次乐观布局计算下一次拖放；或在保存期间禁用新的拖放。

### t027_code_f003 - 取消分组拖动后保留旧拖动载荷

- 严重度：important
- 锚点：AC-040；取消拖动或未知外部载荷不应改变分组顺序。
- 位置：`src/frontend/src/components/Sidebar.tsx:607`、`src/frontend/src/components/Sidebar.tsx:704`
- 问题：分组拖动开始时写入 `dragPayload.current`；分组容器的 `onDragEnd` 只移除高亮 class，没有清除该 ref。取消后拖入外部文本或文件，`allowDrop` 仍因旧 ref 调用 `preventDefault`，分组目标 `onDrop` 再按残留的 `{type:'group', groupId}` 调用 `dropGroupOn`，实际重排旧分组。
- 建议：分组 `onDragEnd` 调用统一的 `clearDropState`，并在 drop 时校验当前 `DataTransfer` 与本次拖动来源。

### t027_code_f004 - 组内账号拖到自身会被移动到末尾

- 严重度：important
- 锚点：AC-040；拖到自身应保持状态不变。
- 位置：`src/frontend/src/components/Sidebar.tsx:459`、`src/frontend/src/components/Sidebar.tsx:464`
- 问题：组内拖放没有检查 `targetAccountId === payload.accountId`。拖动组内非末尾账号到自身时，代码先从源列表移除，再以已移除自身的列表调用 `moveBefore`；目标找不到，账号被插入末尾并持久化，排序发生变化。
- 建议：在构造布局前统一拒绝拖到自身，并覆盖组内非末尾账号的自拖放。

### t027_code_f005 - 设置页删除当前分组后仍停留在已删除分组视图

- 严重度：important
- 锚点：AC-029、AC-031；确认删除当前分组后应返回所有收件箱，设置入口需与侧栏入口结果一致。
- 位置：`src/frontend/src/components/SettingsModal.tsx:258`、`src/frontend/src/components/SettingsModal.tsx:261`
- 问题：设置页删除成功后只失效分组、账号和邮件查询，没有清理 `useMailStore.view`。若删除前正在浏览该组，关闭设置后 `MessageList` 仍用已删除的 `group_id` 请求 `/api/mail/inbox`，后端返回 404，用户停留在失效视图。侧栏删除路径已在 `Sidebar.tsx:383` 回退到所有收件箱，两个入口行为不一致。
- 建议：设置页删除成功后复用侧栏删除的当前视图回退与选择清理逻辑。

### t027_code_f006 - 成员变更后阅读器仍显示已移出分组的邮件

- 严重度：important
- 锚点：AC-021、AC-022；成员变更后列表、选择和邮件详情必须与新分组范围一致。
- 位置：`src/frontend/src/components/Sidebar.tsx:324`、`src/frontend/src/components/SettingsModal.tsx:147`、`src/frontend/src/components/MessageReader.tsx:40`
- 问题：拖放布局或设置页移组成功后会失效邮件列表缓存，但不清空 `selectedKey`/`selectedIds`。若当前分组中选中的邮件来自被移出账号，列表刷新会隐藏该邮件，阅读器仍按全局消息 ID 缓存继续显示详情；详情 query key 也不含组范围（`MessageReader.tsx:42`）。当前分组视图因此同时呈现不属于其成员的邮件。
- 建议：成员变更成功后清空选中邮件和批选；确保被移出邮件的详情缓存不继续作为当前分组阅读器内容。

### t027_code_f007 - 每个分组各发一条统计请求并扫描未索引成员列

- 严重度：important
- 锚点：行为缺陷：分组数量增长时，侧栏初始化产生与组数成正比的统计请求和数据库扫描。
- 位置：`src/frontend/src/components/Sidebar.tsx:578`、`src/frontend/src/components/Sidebar.tsx:694`、`src/mail_core/mail/application/queries.py:352`
- 问题：`groups.map` 为每个组挂载一个无条件启用的 `useQuery`，包括折叠组；每组调用一次 `/api/mail/stats?group_id=...` 并单独执行聚合。`Account.group_id` 没有索引（`src/mail_core/mail/storage/models.py:96`），因此例如 100 个组会在侧栏加载时触发约 100 个统计请求及成员列扫描。
- 建议：提供批量分组统计查询，在一次服务端聚合中返回所有组计数；为 `accounts.group_id` 增加匹配查询的索引。

### t027_code_f008 - 账号标题点击没有切换展开状态

- 严重度：important
- 锚点：AC-019；账号标题与箭头均应切换展开，邮件视图由其子项选择。
- 位置：`src/frontend/src/components/Sidebar.tsx:563`、`src/frontend/src/components/Sidebar.tsx:567`
- 问题：箭头按钮调用 `toggleExpandedAccount`，账号标题按钮却只调用 `setView({type:'account', ...})`。点击标题不会展开真实目录，也不能通过标题折叠目录；这与本 AC 明确要求不符。
- 建议：让账号标题也切换展开状态，并确保收件箱等邮件视图仍可从账号子项进入。

### t027_code_f009 - 分组重命名请求期间仍可重复提交

- 严重度：important
- 锚点：AC-028；重命名进行中不得重复提交。
- 位置：`src/frontend/src/components/Sidebar.tsx:360`、`src/frontend/src/components/Sidebar.tsx:711`
- 问题：重命名处理器没有进行中状态，输入框和保存按钮也未禁用。请求未返回时可以再次提交；用户修改名称后再按 Enter 会并发发送两个不同名称，提交顺序与完成顺序可能不同，最终名称可能回退到较早输入。
- 建议：增加单一 `isSavingRename` 守卫；请求完成前禁用输入和提交按钮，失败后保留输入并恢复重试。

### t027_code_f010 - 新建分组取消后焦点落到文档

- 严重度：minor
- 锚点：AC-032；取消操作应关闭表单并把焦点还给触发控件。
- 位置：`src/frontend/src/components/Sidebar.tsx:638`、`src/frontend/src/components/Sidebar.tsx:654`
- 问题：点击“取消创建”会卸载当前按钮，但处理器没有把焦点移回“新建分组”触发按钮；只有 Escape 路径执行焦点恢复。键盘或屏幕阅读器用户通过取消按钮关闭表单后失去操作位置。
- 建议：取消按钮关闭表单后调用与 Escape 相同的触发按钮焦点恢复逻辑。

### t027_code_f011 - 名称长度在 trim 前被 Pydantic 拒绝

- 严重度：minor
- 锚点：AC-001；128 字符上限应应用于 trim 后名称。
- 位置：`src/mail_core/api/accounts.py:88`、`src/mail_core/api/accounts.py:93`、`src/mail_core/accounts/service.py:174`
- 问题：创建和重命名 DTO 在服务层 trim 前先对原始字符串执行 `max_length=128`。例如首尾含空格、trim 后恰为 128 字符的名称会被 Pydantic 直接以 422 拒绝，尽管服务层契约会接受该规范化名称。设置页输入未限制长度，可直接触发此边界。
- 建议：先规范化名称，再校验规范化结果长度；保留服务层校验作为统一边界。

### t027_code_f012 - 新增布局保存函数圈复杂度超过阈值

- 严重度：minor
- 锚点：代码质量规则：新函数 CC≥15。
- 位置：`src/mail_core/accounts/service.py:202`
- 问题：`save_sidebar_layout` 新增函数手算近似 CC≈17，完整成员校验、排序载荷校验和数据库赋值集中在一个控制流中。
- 建议：将完整性校验与已验证布局写入拆为两个小函数，保持事务边界在应用层。

### t027_code_f013 - 账号更新函数分支数从阈值以下升至 CC≥15

- 严重度：minor
- 锚点：代码质量规则：task 新增分支后 CC≥15。
- 位置：`src/mail_core/accounts/service.py:92`
- 问题：按 prompt 的 McCabe 近似计数，`update_account` 从基线 CC≈14 增至 CC≈19；本 task 增加组存在性、目标顺序分配和清组分支。
- 建议：把分组归属和顺序更新提取为局部操作，保留账号更新事务逻辑清晰。

### t027_code_f014 - 批量已读函数新增组范围后 CC≥15

- 严重度：minor
- 锚点：代码质量规则：task 新增分支后 CC≥15。
- 位置：`src/mail_core/mail/application/mutations.py:211`
- 问题：按 prompt 的 McCabe 近似计数，`mark_all_messages_read` 从基线 CC≈15 增至 CC≈21；新增组存在性、精确文件夹归属和成员过滤分支叠加在既有标记状态机中。
- 建议：提取组/账号/文件夹范围解析，保持批量已读事务和远端写回过程独立。

## 结论

- 本轮新发现：14 条（critical 0，important 9，minor 5）。
- 未进表的提示：达到文件规模阈值且本 task 有净增的源码：`src/frontend/src/components/Sidebar.tsx` 720 行（+160）、`src/frontend/src/components/MessageList.tsx` 690 行（+8）、`src/frontend/src/components/SettingsModal.tsx` 424 行（+24）、`src/frontend/src/design-system/tokens.css` 1593 行（+350）、`src/mail_core/api/mail.py` 425 行（+22）、`src/mail_core/mail/storage/models.py` 412 行（+2）；依 prompt 仅列提示，不单独进 finding。生成类型 `src/frontend/src/api/generated/schema.ts` 与 OpenAPI JSON 排除。另有 `create_account` CC≈11，仅作复杂度提示。代码差异覆盖本 task 已批准合并的组织 API、范围查询和侧栏交付，没有发现额外越界功能。
- 七视角扫描：安全、实现正确性、契约与 Breaking、性能、架构维护、健壮性可观测、文档规格；发现项见上表。未发现新增注入、凭据暴露、危险 HTML 渲染或静默吞错问题。测试质量不在本代码 reviewer 范围。
- AC 复验方式：

|AC|类别|证据|
|---|---|---|
|AC-001|`re_verified`|`accounts/service.py:173-198` 检查 trim、空值、长度、重名与不存在组；另发现 API 长度边界 finding f011。|
|AC-002|`trust_prior`|代码仅清空分组归属、不删除账号；独立数据库会话持久性未由本 reviewer 重跑，依赖 `task.md` attempt 2 记载的 PostgreSQL 全套件结果。|
|AC-003|`re_verified`|`update_account` 校验目标组；完整布局拒绝缺失/重复账号并在一次 session 提交。|
|AC-004|`re_verified`|`list_accounts` 按小写域名、完整邮箱排序；`reset_sidebar_account_order` 清空手动顺序字段。|
|AC-005|`re_verified`|布局 API 分别写 `master_order`、`group_order` 与 `group_id`；前端总列表分支只更新总列表序列。|
|AC-006|`re_verified`|创建组取最大 `sort_order + 1`；新增/移入账号取目标列表最大顺序；恢复默认不更新组先后或归属。|
|AC-007|`re_verified`|布局服务检查组、账号全集及唯一成员关系；锁序与删除锁序会造成死锁，见 f001。|
|AC-008|`trust_prior`|迁移只增加可逆 nullable 列，生成 OpenAPI/类型在 diff 中；旧库迁移和降级再升级依赖 `task.md` 报告的 PG 测试结果。|
|AC-009|`re_verified`|检查生产实现与迁移，没有示例分组名称或 seed；分组来自数据库列表。|
|AC-010|`re_verified`|`api_unified_inbox` 将当前组成员传入统一查询，按任意角色及 inbox 未读筛选；列表按 Message 主键分组去重。|
|AC-011|`re_verified`|keyset 同 sort_time 时用 message ID 作升降序游标；空 account ID 列表不会退回全局范围。|
|AC-012|`re_verified`|搜索与 count 共用同一 account ID 过滤；组统计由 FolderStats 聚合，不读前端已加载邮件页。|
|AC-013|`re_verified`|批量已读同时按 group、folder role、flag 过滤，再走既有远端写回队列。|
|AC-014|`re_verified`|inbox/search/mark-all-read 拒绝范围歧义；未知组在各组范围路径返回 404。|
|AC-015|`re_verified`|组员 ID 在每次 API 请求时从 Account.group_id 查询；成员写入后前端失效组与邮件缓存，详情选中未清理见 f006。|
|AC-016|`re_verified`|无组参数时 `account_ids=None` 保留全局，单账号与精确 folder_id 仍由原查询分支处理。|
|AC-017|`trust_prior`|JSX 顺序为所有账号、组、账号列表且折叠状态分开；实际边界对齐依赖 `task.md` 的浏览器 E2E 结果。|
|AC-018|`re_verified`|`CATEGORY_ITEMS` 保留六类全局与分组入口；账号列表取全部账号，组成员通过 group_id 筛选。|
|AC-019|`re_verified`|真实目录由 folder-stats 构建且未造目录；账号标题未展开，见 f008。|
|AC-020|`trust_prior`|JSX 与 CSS 使用 24px 层级偏移和固定箭头槽；bounding box、长邮箱及主题渲染未由本 reviewer 实跑，依赖浏览器 E2E 记录。|
|AC-021|`re_verified`|inbox/search query key 纳入 group ID；`setView` 清理选中邮件、批选与搜索。成员变更仍留下旧选中详情，见 f006。|
|AC-022|`trust_prior`|成员变更路径失效 group/accounts/mail 查询；SSE 角标与计数联动依赖 `task.md` 记载的全栈 E2E。|
|AC-023|`re_verified`|Zustand 持久化分区、组、类别、账号展开偏好；侧栏删组时清理组偏好且导航数据来自当前查询结果。|
|AC-024|`trust_prior`|aria-expanded 与 760px 规则可从代码确认；深浅主题和鼠标/键盘实际操作依赖实施侧浏览器 E2E 结果。|
|AC-025|`trust_prior`|未发现邮件操作、搜索、筛选、分页、分类路径被删除；全量既有功能回归依赖 `task.md` 所记前端套件结果。|
|AC-026|`re_verified`|生产导航只渲染 fetchGroups 返回值，无示例名称及空占位。|
|AC-027|`re_verified`|账号列表头含具名“新建分组”按钮，调用 createGroup 并失效组织缓存。|
|AC-028|`re_verified`|创建/重命名服务端校验 trim、长度和唯一性；进行中重复提交未防护，见 f009。|
|AC-029|`re_verified`|删除确认文案保留账号邮件；侧栏删除会回退当前视图，设置页删除遗漏此行为，见 f005。|
|AC-030|`re_verified`|设置选择器发起组更新，成功后失效账号、组与邮件缓存；选项仅来自服务端 groups。|
|AC-031|`re_verified`|设置与侧栏复用相同 create/delete API；设置页删除当前分组视图不回退，见 f005。|
|AC-032|`re_verified`|组名作为 React 文本渲染，Escape 关闭并恢复焦点；新建表单取消按钮不恢复焦点，见 f010。|
|AC-033|`re_verified`|组名与选项来源为服务端数据，代码无工作/个人等专用行为。|
|AC-034|`trust_prior`|账号/组 DOM 行使用 draggable、no-drag 控件和 drop feedback；原生拖拽交互依赖实施侧浏览器 E2E。|
|AC-035|`trust_prior`|目标组与目标账号通过 `moveBefore` 构造位置；空组、折叠组及真实浏览器落点依赖实施侧 E2E。|
|AC-036|`trust_prior`|组来源拖到账号列表会清组并更新总序；真实拖动矩阵依赖实施侧 E2E。|
|AC-037|`trust_prior`|payload 的 sourceList 区分总列表重排与分组成员排序；持久化拖拽结果依赖实施侧 E2E。|
|AC-038|`trust_prior`|组行可拖动、两个固定区标题不可拖动，完整布局 API 持久化；刷新后浏览器验证依赖实施侧 E2E。|
|AC-039|`re_verified`|重置请求失败时不做本地乐观排序，并显示明确错误；服务端事务 rollback 可从应用层调用确认。|
|AC-040|`trust_prior`|静态审查确认自拖放、取消分组拖动和连续拖拽存在缺陷（f002–f004）；实际原生拖拽要求依赖实施侧全栈 E2E 报告，未由本 reviewer 重跑。|

`coverage = 27 / 40`

建议合并前人工抽查 trust_prior 项。

- 总体判断：存在 9 条未解决 important finding，当前不能通过代码 review。
- 系统性 follow-up：无；本轮问题均在 t027 已批准范围内。

verdict: FAIL

## Round 2 (2026-10-23T05:53:49+08:00)

- task：t027_account_group_ordering
- spec：docs/tasks/t027_account_group_ordering/spec.md
- diff_anchor：c8cee92446f9c24e7a0a2a501d52d0bd49068041
- target：git -C '[REDACTED_LOCAL_PATH]' diff c8cee92446f9c24e7a0a2a501d52d0bd49068041
- round：2
- reviewed_at：2026-10-23T05:53:49+08:00

reviewed_scope: 58434501c0c16f5d

## Findings

### t027_code_f015 - 过期的完整布局快照可静默覆盖并发提交

- 严重度：important
- 锚点：AC-007；两个浏览器会话并发整理后，冲突必须明确处理，不能静默丢失已提交状态。
- 位置：src/mail_core/accounts/service.py:215-218、src/mail_core/accounts/service.py:231-249、src/mail_core/api/accounts.py:246-257、src/frontend/src/components/Sidebar.tsx:339-344
- 问题：布局 PUT 是完整快照替换。可复现序列：会话 A、B 均先读到布局 S0；A 拖动后提交 SA 并收到 204；B 基于旧 S0 再拖动并提交 SB。数据库锁会让两次保存串行，但第二次只校验 ID 集合、重复项和成员互斥，不核对客户端读取的布局版本；SB 因仍是合法完整布局而覆盖 SA，接口仍返回 204。最终数据库快照仍满足单组归属和排序完整性，因此这不是数据库不变量冲突，而是合法但过期的全量提交未作冲突处理。
- 建议：为读取到的完整布局提供一致 revision，并要求 PUT 携 expected_revision 或 If-Match；在同一事务中比较并递增 revision，过期时返回 409，前端重新读取布局后再让用户确认/重做。若现有账号与分组读取接口不能提供同一快照版本，增加布局快照读取或等效的一致版本契约。同步更新 OpenAPI、生成类型及前端请求/409 处理。

### t027_code_f016 - 账号移入正被删除的组时可返回未处理的数据库错误

- 严重度：important
- 锚点：AC-003、AC-007；目标组并发消失时，移组应整体失败并返回可识别错误。
- 位置：src/mail_core/accounts/service.py:132-140、src/mail_core/accounts/service.py:302-309、src/mail_core/api/accounts.py:168-182
- 问题：PATCH 先用不加锁的 session.get 检查目标组，再计算顺序并 flush 账号外键；并发 DELETE 可在检查后锁定并删除该组。若删除先提交，PATCH 的外键写入会抛出 IntegrityError；API 只将 LookupError 映射为 404，没有将该竞态转换为可识别的冲突，客户端收到未处理的 500。
- 建议：移组时在写账号前锁定目标组行并持有到事务结束，遵循组后账号的锁顺序；锁等待后发现组已删除则返回 404/409。对剩余约束冲突也应映射为明确错误。

### t027_code_f017 - 布局成员比较在可支持规模上呈二次增长

- 严重度：important
- 锚点：行为缺陷：支持的大账号集合内进行普通排序时，客户端可能长时间卡顿后才发送保存请求。
- 位置：src/frontend/src/components/Sidebar.tsx:150-154、src/frontend/src/components/Sidebar.tsx:332-335、src/frontend/src/api/queries.ts:115-125
- 问题：每次拖动保存都先调用 sameMembership，即使拖动只改变顺序也要比较成员集合。sameIds 使用 left.every(id => right.includes(id))，相同的 n 项列表仍需最坏 O(n²) 查找；账号加载器允许最多 100 页、每页 200 个，即 20,000 个账号，单个 20,000 项列表会触发约 2 亿次元素比较，阻塞 UI 主线程。
- 建议：对较长列表用 Set 做一次性成员比较，使整体比较为线性；或在拖动命令中明确标记是否改变归属，避免纯排序执行全量集合比较。

### t027_code_f018 - 全局统计遗漏账号后把未知未读数显示成零

- 严重度：important
- 锚点：AC-022；未知计数必须与已知零区分。
- 位置：src/mail_core/mail/application/queries.py:321-345、src/frontend/src/components/Sidebar.tsx:274-278、src/frontend/src/components/Sidebar.tsx:584-592、src/frontend/src/components/Sidebar.tsx:599-634
- 问题：全局统计从 FolderStats INNER JOIN Folder 起查，只返回已有 inbox FolderStats 的账号。尚无 inbox 目录统计行的账号不会出现在 accounts 数组中。侧栏 Map.get 因而返回 undefined，但账号行和快捷分类只对 null 显示未知标记；undefined 落入“不显示角标”的分支，与已知 0 相同。total_unread 同时只累加已返回账号，遗漏账号时仍显示一个看似完整的总数。
- 建议：统计响应为每个账号明确返回已知数或 null，并让缺行进入未知状态；前端把缺失 ID 归一为 null。只要存在未知项，全局总数也应标明未知或显式标记不完整，不能用部分和冒充完整值。

### t027_code_f019 - 设置页删除当前组时切换范围却保留搜索

- 严重度：important
- 锚点：AC-021；切换账号/组/文件夹范围时必须清空搜索。
- 位置：src/frontend/src/components/SettingsModal.tsx:261-269、src/frontend/src/store/mailStore.ts:62-100
- 问题：设置页删除当前组后直接 setState 切到 allInbox、清选中项，却没有清 search。关闭设置后，MessageList 仍按旧搜索词执行全局搜索；这与删除组后回到所有收件箱的范围不一致，也违反 AC-021。其他导航通过 setView，而 setView 会调用 navigationReset 并清空 search；设置页这条独立删除路径绕过了该规则。
- 建议：活动组删除成功时复用统一导航重置路径并设置 allInbox/listFilter；若该原子更新需留在设置页 store 操作，则显式清 search，保持所有范围切换入口一致。

### t027_code_f020 - 可展开的账号标题按钮缺少 aria-expanded

- 严重度：minor
- 锚点：AC-024；折叠控件的 aria-expanded 必须与展开状态一致。该标题按钮也会切换展开状态。
- 位置：src/frontend/src/components/Sidebar.tsx:618-631
- 问题：Round 1 为满足 AC-019，账号标题按钮改为调用 toggleExpandedAccount；相邻箭头按钮有 aria-expanded，但标题按钮自身没有。键盘/屏幕阅读器聚焦标题时无法得知该按钮控制子目录，也无法读取当前展开状态。
- 建议：给标题按钮添加与箭头相同的 aria-expanded 状态，或调整交互语义，使标题按钮不再承担 disclosure 切换。

## 结论

- 前轮 finding 复核：f001 已消除（布局与删除均先锁组再锁账号，src/mail_core/accounts/service.py:215-218、302-309）；f002 已消除（同页面保存期间通过 layoutSaveInFlight 阻止第二次拖动并等待查询失效，Sidebar.tsx:332-354）；f003 已消除（拖放校验当前 DataTransfer 且拖动结束清理状态，Sidebar.tsx:472-485、Sidebar.tsx:778-779）；f004 已消除（makeLayoutWithAccountMove 拒绝拖到自身，Sidebar.tsx:495-497）；f005 已消除（设置页删除当前组后回到 allInbox 并清选中，SettingsModal.tsx:261-269）；f006 已消除（成员变化清理选中邮件与批选，Sidebar.tsx:332-348、SettingsModal.tsx:151-155）；f007 已消除（改为从全局统计映射推导组计数并增加 accounts.group_id 索引，Sidebar.tsx:639-652、src/mail_core/mail/storage/models.py:97-101）；f008 已消除（账号标题现在切换展开，Sidebar.tsx:628）；f009 已消除（重命名有进行中守卫并禁用表单控件，Sidebar.tsx:263-267、771-785）；f010 已消除（取消新建组时恢复触发按钮焦点，Sidebar.tsx:381-385）；f011 已消除（Pydantic 在长度校验前 trim，src/mail_core/api/accounts.py:87-103）；f012 已消除（布局校验与应用逻辑拆分，src/mail_core/accounts/service.py:207-275）；f013 已消除（账号组更新提取到局部 helper，src/mail_core/accounts/service.py:93-140）；f014 已消除（批量已读的范围查询拆分为 helper，src/mail_core/mail/application/mutations.py:相关函数）。f005 的原 404 场景已修复；设置页新发现的搜索残留单列为 f019。
- 本轮新发现：6 条（critical 0，important 5，minor 1）。
- 未进表的提示：达到文件规模阈值且本 task 仍净增的源码：src/frontend/src/components/Sidebar.tsx 794 行（+234）、src/frontend/src/components/MessageList.tsx 690 行（+8）、src/frontend/src/components/SettingsModal.tsx 430 行（+30）、src/frontend/src/design-system/tokens.css 1593 行（+350）、src/mail_core/api/mail.py 425 行（+22）、src/mail_core/mail/storage/models.py 413 行（+3）；按 prompt 仅列提示，不单独进 finding。生成 OpenAPI/TS 类型排除。新增或扩展函数中未见 CC≥15；create_account（约 11）、\_validate_sidebar_layout（约 12）、\_update_account_group（约 10）、\_mark_all_read_query（约 14）只作复杂度提示。diff 范围与已批准的组织 API、邮件范围查询和侧栏交付一致。静态扫描未发现新增注入、凭据暴露、不安全 HTML 渲染或静默吞错；测试质量不在本代码 reviewer 范围。
- AC 复验方式：以下逐条对照本轮完整 diff 与实现；trust_prior 项依赖 task.md attempt 2 的运行记录，非本 reviewer 重跑。

|AC|状态|证据|
|---|---|---|
|AC-001|re_verified|创建/重命名先 trim 再校验 1–128 字符与唯一名；api/accounts.py:87-103、accounts/service.py:178-204。|
|AC-002|trust_prior|删除只清 group_id/group_order 并提交，不删账号及其引用；独立会话持久性依赖 task.md attempt 2 的 PostgreSQL 测试记录。|
|AC-003|re_verified|允许设置/清空 group_id 并校验目标组；并发删除竞态见 f016。|
|AC-004|re_verified|默认列表按域名及完整邮箱排序，手动排序字段从数据库读取；accounts/service.py:75-90。|
|AC-005|re_verified|布局提交分别写 master_order、group_order 与 group_id；同一数据库事务 flush/commit。|
|AC-006|re_verified|新组取末尾顺序、移入组取目标末尾；默认恢复只清账号手动顺序，不改组序或归属。|
|AC-007|re_verified|当前完整 ID 集合和单组校验可拒绝非法载荷；未绑定 revision 的并发旧快照与移组/删组竞态见 f015、f016。|
|AC-008|trust_prior|迁移增列可逆且 OpenAPI/TS 在 diff；旧库升级及降级再升级依赖 task.md attempt 2 的迁移测试记录。|
|AC-009|re_verified|生产代码、迁移与配置未预置组名/ID，分组从数据库及用户输入生成。|
|AC-010|re_verified|组成员范围进入统一邮件查询，现有 folder role 与去重路径保留；mail/application/queries.py 组范围实现。|
|AC-011|re_verified|keyset 游标用稳定消息 ID 作为排序时间相同的次级键；空组不退回全账号查询。|
|AC-012|re_verified|搜索结果与 total 使用组员过滤；服务端统计独立于前端已加载邮件页，未知全局账号统计见 f018。|
|AC-013|re_verified|全部已读按组、角色及旗标过滤后走既有写回状态机；组外邮件不会进入目标查询。|
|AC-014|re_verified|范围解析拒绝 group 与 account/folder 歧义，未知组映射明确不存在错误。|
|AC-015|re_verified|组员在每次请求时按当前 group_id 查询；成员保存后失效邮件缓存并从首屏取数。|
|AC-016|re_verified|无组参数保留原全局、单账号及精确 folder_id 路径；新增 API 仍通过既有认证/CSRF 中间件。|
|AC-017|trust_prior|顶层顺序与三段独立折叠从组件可见；实际间距、主题及浏览器布局依 task.md attempt 2 的 E2E 记录。|
|AC-018|re_verified|全局和组导航均保留六类分类入口；账号列表包含全部账号，组成员按 group_id 过滤。|
|AC-019|re_verified|目录按服务器返回的真实 folders 构建；账号标题与箭头均切换展开，Sidebar.tsx:599-635。|
|AC-020|trust_prior|CSS/JS 使用 24px 层级增量及固定箭头槽；bounding box 与长邮箱布局依 task.md attempt 2 的 E2E 记录。|
|AC-021|re_verified|一般 setView 经 navigationReset 清选择和搜索；设置页删除当前组绕过该路径而保留搜索，见 f019。|
|AC-022|re_verified|组计数由全局账号 map 汇总，成员变化会失效组与邮件查询；缺失账号统计成为 undefined 并被当作无角标，见 f018。|
|AC-023|re_verified|组/账号展开偏好本地持久化，导航只渲染服务端现存实体；删除路径清理当前选择与相关缓存。|
|AC-024|re_verified|侧栏箭头 aria-expanded 与状态一致；账号标题也切换展开但缺状态属性，见 f020。|
|AC-025|trust_prior|diff 未删除现有分类、真实目录、搜索筛选、分页或邮件操作；完整既有功能回归依 task.md attempt 2 的前端测试记录。|
|AC-026|re_verified|仅渲染服务端分组数据，无固定“工作/个人”名称或空占位。|
|AC-027|re_verified|账号列表提供具名“新建分组”控件，成功后失效账号/分组查询并展示新组。|
|AC-028|re_verified|菜单支持重命名/删除；校验错误保留输入，保存期间控件禁用且防重复提交。|
|AC-029|re_verified|删除确认明确保留账号和邮件；当前组删除后视图回退并清选择，设置页实现见 SettingsModal.tsx:261-269。|
|AC-030|re_verified|设置选择器可归组/移组/清组，成功后失效组织及邮件查询，失败保留服务端状态。|
|AC-031|re_verified|设置页与侧栏调用相同组织 API；删除当前组时的搜索残留见 f019。|
|AC-032|re_verified|Escape/取消逻辑恢复对应触发按钮焦点，组名以普通 React 文本渲染，窄屏可使用设置选择器移组。|
|AC-033|re_verified|组名、选择项均来自数据库及用户输入，没有按示例名称分支。|
|AC-034|trust_prior|拖动绑定整行、交互控件标记 no-drag 且目标增加反馈；原生拖拽取消/落点依 task.md attempt 2 的 E2E 记录。|
|AC-035|trust_prior|布局构造覆盖组标题、账号行及空组追加；跨浏览器拖放矩阵依 task.md attempt 2 的 E2E 记录。|
|AC-036|trust_prior|组来源拖到总列表清除归属并更新总序；真实拖动目标覆盖依 task.md attempt 2 的 E2E 记录。|
|AC-037|trust_prior|DragPayload 携来源列表区分总列表重排与组成员排序；真实拖动持久化场景依 task.md attempt 2 的 E2E 记录。|
|AC-038|trust_prior|组标题可排序，两个固定区域不允许拖动；刷新后浏览器验证依 task.md attempt 2 的 E2E 记录。|
|AC-039|re_verified|默认恢复事务只清账号手动顺序；前端失败路径显示保存错误并失效缓存。|
|AC-040|trust_prior|代码已复核自拖/失效来源/保存中保护；真实原生拖动和刷新后持久化依 task.md attempt 2 的 E2E 记录。|

coverage = 27 / 40

trust_prior = 13 / 40（32.5%），超过 30% 提示阈值；合并前需人工抽查这些依赖运行记录的 AC。

- 总体判断：仍有 5 条未解决 important finding，且 1 条 minor；当前不能通过代码 review。
- 系统性 follow-up：无。

verdict: FAIL

## Round 3 (2026-10-23T06:36:05+08:00)

- task：t027_account_group_ordering
- spec：docs/tasks/t027_account_group_ordering/spec.md
- diff_anchor：c8cee92446f9c24e7a0a2a501d52d0bd49068041
- target：git -C '[REDACTED_LOCAL_PATH]' diff c8cee92446f9c24e7a0a2a501d52d0bd49068041
- round：3
- reviewed_at：2026-10-23T06:36:05+08:00

reviewed_scope: c2e68903705cd66c

## Findings

### t027_code_f021 - 成员变更后受影响组的旧邮件缓存仍可短暂展示

- 严重度：important
- 锚点：AC-015、AC-021；成员变更後按新成员范围从首屏查询，旧范围邮件不能继续显示。
- 位置：src/frontend/src/components/SettingsModal.tsx:151-158、src/frontend/src/components/Sidebar.tsx:383-387、src/frontend/src/api/queries.ts:109-115、src/frontend/src/components/MessageList.tsx:208-222
- 问题：Settings 移组与侧栏拖动成功后，只在当前 view 是 group 时 reset 该 group 的 inbox/search 缓存；其余受影响组仅经 invalidateQueries 标记失效。若用户在所有收件箱视图中把账号 X 从 A 移到 B，A/B 已缓存的 query 数据仍留在 cache。之后进入 A 或 B 时，MessageList 从同一 group ID 的缓存先渲染旧页面并后台重取；它会短暂显示已不属于该组的邮件。删除 keepPreviousData 不能清除同 key 的旧缓存。
- 建议：比较移组前后的源组与目标组，对每个成员变化的 group scope 执行 resetQueries/removeQueries，再刷新数据；确保进入受影响组时首屏加载前不会渲染旧成员缓存。

### t027_code_f022 - 账号列表超过 20,000 条后静默截断

- 严重度：important
- 锚点：AC-018；账号列表应始终列出全部账号，不能隐去超过客户端固定页数的账号。
- 位置：src/frontend/src/api/queries.ts:115-126、src/frontend/src/components/Sidebar.tsx:343-354、src/frontend/src/components/Sidebar.tsx:787-790
- 问题：fetchAccounts 最多读取 100 页、每页 200 条，循环结束后无论最后一页 has_more 是否为 true 都直接返回现有数组。数据库有 20,001 个账号时，侧栏与设置页只收到 20,000 个且不显示截断错误；侧栏布局快照仍含完整账号集，layoutReady 因 ID 数量不等而禁用全部拖动。后端分页接口本身通过 has_more 表示还有结果，没有 20,000 的产品限制。
- 建议：持续读取到 has_more=false，或实现明确分页 UI 并显示尚未加载的账号；不要把固定轮数结束当作成功完整响应。

### t027_code_f023 - 设置页删除账号后全局未读总数保留旧账号数据

- 严重度：important
- 锚点：AC-022；账号集合变化后账号角标与全局统计应反映当前账号集合。
- 位置：src/frontend/src/components/SettingsModal.tsx:167-171、src/frontend/src/components/Sidebar.tsx:277-291、src/frontend/src/components/Sidebar.tsx:337-338、src/frontend/src/api/queries.ts:75-80
- 问题：删除账号成功后，Settings 的 run 只失效 queryKeys.accounts，随后只失效 sidebarLayout；没有失效 queryKeys.stats 或 mail-core。Sidebar 的统计 query key 固定为 mail-core/stats，缓存值仍包含已删账号；allInboxUnread 直接使用旧 totalUnread。删除一个有未读邮件的账号（包括最后一个账号）后，“所有收件箱”仍显示删除前总数，且删除接口不会触发 MessageList 中用于刷新 stats 的 SSE 处理。
- 建议：账号删除成功后同时失效 queryKeys.stats（或 mail-core 前缀），并清理受删除账号影响的邮件缓存，使全局及组统计基于最新账号集合重查。

### t027_code_f024 - 获取布局快照按组数乘账号数反复扫描

- 严重度：minor
- 置信度：中
- 锚点：性能与资源：大量合法用户分组和账号时，布局读取请求的工作量不应按两者乘积增长。
- 位置：src/mail_core/accounts/service.py:241-257、src/frontend/src/components/Sidebar.tsx:261
- 问题：get_sidebar_layout 对每个 group 都重新遍历完整 accounts 列表筛选成员，再分别排序。该端点在侧栏初始化读取；组数 G、账号数 A 时筛选工作为 O(G×A)，且分组数无上限。大量空组或每组单账号的数据会让一次布局加载反复扫描同一批账号，拖延侧栏进入 layoutReady 状态。
- 建议：先单次遍历 accounts 建立 group_id 到成员列表的映射，再分别排序各组成员，使筛选总成本降为 O(A)，排序成本与各组规模相关。

## 结论

- 前轮 finding 复核：f015 已消除（布局读取提供 revision，保存与恢复默认在组织 advisory lock 下比较 expected_revision；过期返回 409，src/mail_core/accounts/service.py:223-238、353-362、src/mail_core/api/accounts.py:261-299）；f016 已消除（账号移组先取得组织事务锁并锁定目标组，删除组共享组织锁，组先删除时返回 404，src/mail_core/accounts/service.py:103-140、381-395）；f017 已消除（成员比较使用 Set，Sidebar.tsx:150-155）；f018 已消除（统计逐账号返回 nullable 计数及 nullable 总数，前端将缺项设为未知，src/mail_core/mail/application/queries.py:310-349、Sidebar.tsx:281-292、638-686）；f019 已消除（设置页删除当前组时清空 search，SettingsModal.tsx:266-275）；f020 已消除（账号标题按钮 aria-expanded 与 expanded 同步，Sidebar.tsx:683）。
- 本轮新发现：4 条（critical 0，important 3，minor 1）。
- 未进表的提示：达到文件规模阈值且本 task 仍净增的实现源码：src/frontend/src/components/Sidebar.tsx 851 行（+291，超过 800 行 important 提示阈值）、src/frontend/src/components/MessageList.tsx 706 行（+24）、src/frontend/src/components/SettingsModal.tsx 437 行（+37）、src/frontend/src/design-system/tokens.css 1593 行（+350）、src/mail_core/api/mail.py 427 行（+24）、src/mail_core/mail/storage/models.py 413 行（+3）、src/mail_core/accounts/service.py 422 行（+224）；按 prompt 仅列提示，不单独进 finding。生成 OpenAPI/TS 类型排除。未见新增/扩展函数 CC≥15；get_sidebar_layout 及统计汇总函数约 CC 10 以下，较高复杂度只作提示。七视角扫描覆盖安全、正确性、契约与 Breaking、性能资源、架构维护、健壮性可观测、文档规格；除列出的缓存/分页/复杂度问题外，未发现新的注入、凭据暴露、不安全 HTML 渲染或静默吞错。测试层质量不在本代码 reviewer 范围。
- AC 复验方式：逐条对照本轮完整 diff 与实现；trust_prior 项依赖 task.md attempt 2 的浏览器/迁移运行记录，本 reviewer 未重跑相关环境验证。

|AC|状态|证据|
|---|---|---|
|AC-001|re_verified|API 在字段长度校验前 trim；service 校验空白、长度及重名。api/accounts.py:87-103、accounts/service.py:192-220。|
|AC-002|trust_prior|删除组事务只清账号 group_id/group_order 并提交，不删除账号及邮件引用；独立会话验证依 task.md attempt 2 的 PostgreSQL 运行记录。|
|AC-003|re_verified|账号可移入/移出；目标组行锁和并发事务锁避免删除竞态变成 500。accounts/service.py:103-140。|
|AC-004|re_verified|服务端默认按不区分大小写域名、邮箱排序，手动顺序读数据库 order 字段。accounts/service.py:75-90。|
|AC-005|re_verified|完整布局事务分别写 group sort_order、master_order、group_id/group_order；冲突 revision 不会覆盖已提交快照。accounts/service.py:223-238、327-350。|
|AC-006|re_verified|新组追加末尾、手动移入追加末尾、恢复默认清除两套账号手动顺序而保留组顺序和归属。accounts/service.py:192-204、353-362。|
|AC-007|re_verified|完整载荷校验加 expected_revision、组织 advisory lock；过期快照返回 409，完整性错误整体拒绝。accounts/service.py:223-324、api/accounts.py:266-285。|
|AC-008|trust_prior|迁移可逆且 OpenAPI/生成类型同步；旧库及 downgrade/upgrade 依 task.md attempt 2 的迁移运行记录。|
|AC-009|re_verified|源码、迁移及配置未预置示例分组，导航只按服务端组数据渲染。|
|AC-010|re_verified|邮件范围查询由当前 group_id 成员集合约束，保留角色查询和消息去重。mail/api.py 与 mail/application/queries.py 组范围路径。|
|AC-011|re_verified|keyset 查询使用稳定 message ID 次级排序；空组的空成员集合不会退回全局。mail/application/queries.py:list_messages_keyset、unified_inbox。|
|AC-012|re_verified|搜索结果与 total 共享 account/folder 范围；组统计独立查询服务端完整统计，缺失统计为 null。mail/application/search.py、search/index.py、mail/application/queries.py。|
|AC-013|re_verified|全部已读同时应用 group、role、flag 条件，再入既有写回状态机。mail/application/mutations.py。|
|AC-014|re_verified|inbox/search/mark-all-read 拒绝 group 与 account/folder 歧义；未知组返回 404。mail/api.py:190-370。|
|AC-015|re_verified|组成员每次查询时按当前归属解析，但只有当前 view 组缓存被 reset，其他受影响组可能先显示旧缓存，见 f021。|
|AC-016|re_verified|无 group_id 时原全局、单账号及精确 folder_id 路径保留；写 API 仍用既有认证/CSRF 客户端。|
|AC-017|trust_prior|三个顶层区域顺序与独立偏好可从代码确认；实际 24px 对齐和折叠区域布局依 task.md attempt 2 的 E2E 记录。|
|AC-018|re_verified|六类全局/分组入口及账号列表结构存在，但 fetchAccounts 过 20,000 项静默截断，见 f022。|
|AC-019|re_verified|账号真实目录由文件夹服务数据构建，标题与箭头均切换目录展开。Sidebar.tsx:654-690。|
|AC-020|trust_prior|CSS/JS 使用固定 24px 层级及箭头占位；bounding box、长邮箱和主题布局依 task.md attempt 2 的 E2E 记录。|
|AC-021|re_verified|query key 区分范围和文件夹且移除跨 key placeholder；成员变化后的旧同 key 组缓存仍可能显示，见 f021。|
|AC-022|re_verified|未知统计用 null 表示；设置页删账号未失效固定 stats query，旧全局总数可残留，见 f023。|
|AC-023|re_verified|展开偏好本地持久化，导航按现存实体渲染；已删除组/账号不再形成导航项。|
|AC-024|re_verified|disclosure aria-expanded 与当前展开状态同步，主题及窄屏交互的实际体验依 E2E 记录。|
|AC-025|trust_prior|diff 未移除既有邮件分类、搜索、筛选、分页及邮件操作；完整回归依 task.md attempt 2 的前端运行记录。|
|AC-026|re_verified|组名和成员仅来自服务端/用户数据，无“工作”“个人”专用逻辑。|
|AC-027|re_verified|账号列表提供具名新建分组按钮并刷新组织数据。Sidebar.tsx:772-790。|
|AC-028|re_verified|菜单提供组重命名和删除；请求中禁用控件、失败保留输入。Sidebar.tsx:432-453、801-850。|
|AC-029|re_verified|删除确认说明保留账号邮件，删除当前组回到所有收件箱并清搜索/选择。SettingsModal.tsx:266-275、Sidebar.tsx:456-470。|
|AC-030|re_verified|设置页可选当前组、其他组或不加入；保存后刷新账号、组、布局及邮件数据。SettingsModal.tsx:144-159。|
|AC-031|re_verified|设置页创建/删除组和添加/删除账号入口仍在；删除账号后的全局统计失效遗漏见 f023。|
|AC-032|re_verified|Escape/取消会恢复焦点，组名按 React 普通文本显示，窄屏可通过设置下拉移组。|
|AC-033|re_verified|分组名与选项仅来自数据库/用户输入，没有示例组特判。|
|AC-034|trust_prior|行级拖动、交互控件 no-drag 和 drop feedback 可从 JSX 确认；原生拖拽矩阵依 task.md attempt 2 的 E2E 记录。|
|AC-035|trust_prior|布局构造覆盖空组、组行和账号行；真实浏览器目标落点矩阵依 task.md attempt 2 的 E2E 记录。|
|AC-036|trust_prior|组成员拖到总列表会清归属并更新 master order；原生拖动依 task.md attempt 2 的 E2E 记录。|
|AC-037|trust_prior|DragPayload 保留来源列表，区分总列表排序和组内排序；刷新持久化验证依 task.md attempt 2 的 E2E 记录。|
|AC-038|trust_prior|组行可排序且固定顶层区域不可拖动；跨会话读取依 task.md attempt 2 的 E2E 记录。|
|AC-039|re_verified|恢复默认排序要求当前 revision，失败显示错误并失效服务端事实。Sidebar.tsx:475-498、accounts/service.py:353-362。|
|AC-040|trust_prior|当前实现有保存中保护、revision 冲突处理和无效/自拖逻辑；完整原生拖拽及失败回滚依 task.md attempt 2 的 E2E 记录。|

coverage = 27 / 40

trust_prior = 13 / 40（32.5%），超过 30% 提示阈值；建议合并前人工抽查 trust_prior 项。

- 总体判断：仍有 3 条未解决 important finding；当前不能通过代码 review。
- 系统性 follow-up：无。

verdict: FAIL

## Round 4 (2026-10-23T06:44:51+08:00)

- task：t027_account_group_ordering
- spec：docs/tasks/t027_account_group_ordering/spec.md
- diff_anchor：c8cee92446f9c24e7a0a2a501d52d0bd49068041
- target：git -C '[REDACTED_LOCAL_PATH]' diff c8cee92446f9c24e7a0a2a501d52d0bd49068041
- round：4
- reviewed_at：2026-10-23T06:44:51+08:00

reviewed_scope: d8010a2b6a03ba40

## Findings

### t027_code_f025 - 新增账号后全局未读统计仍使用旧缓存

- 严重度：important
- 锚点：AC-022；账号集合变化后，尚无统计数据的账号不能让全局总数继续显示为已知完整值。
- 位置：src/frontend/src/components/SettingsModal.tsx:259-266、src/frontend/src/components/SettingsModal.tsx:170-174、src/frontend/src/components/Sidebar.tsx:277-292、src/frontend/src/components/Sidebar.tsx:337-338、src/frontend/src/api/queries.ts:45-53、src/frontend/src/api/queries.ts:75-80
- 问题：新增账号成功后只失效 accounts 与 sidebarLayout，不失效固定 query key mail-core/stats。可复现路径：已有统计缓存后删除最后一个账号，删除处理把 stats cache 写为 totalUnread=0（SettingsModal.tsx:170-172）；随后在五分钟 staleTime 内添加新账号，添加成功路径只刷新账号及布局查询。Sidebar 的 stats 查询重新启用时仍可复用新鲜的 0 缓存，query function 不会因为 accounts 列表改变而自动重跑；“所有收件箱”因而把新账号统计未知的状态显示为 0。已有账号后再添加第二个账号同样会保留只覆盖旧账号集合的 totalUnread，直到后续 SSE 刷新。
- 建议：添加账号成功时同时失效 queryKeys.stats；或把账号集合版本纳入 stats query key，确保账号集合变化后重查完整统计。

## 结论

- 前轮 finding 复核：f021 已消除（任意成员变更后按 query key predicate reset 所有 group inbox/search 缓存；Settings 与拖放路径均调用，src/frontend/src/api/queries.ts:109-119、SettingsModal.tsx:151-157、Sidebar.tsx:383-387）；f022 已消除（账号分页持续读取到 has_more=false，服务端仍声明有更多却返回空页时明确失败，queries.ts:141-151）；f023 已消除（删除末个账号后把全局统计置零，其他删除则 reset stats 并清空邮件列表查询，SettingsModal.tsx:167-180、queries.ts:122-128）；f024 已消除（布局读取先按 group_id 单次分桶再排序，accounts/service.py:241-260）。
- 本轮新发现：1 条（critical 0，important 1，minor 0）。
- 未进表的提示：达到文件规模阈值且本 task 仍净增的源码：src/frontend/src/components/Sidebar.tsx 851 行（+291，达到 800 行 important 提示阈值）、src/frontend/src/components/MessageList.tsx 706 行（+24）、src/frontend/src/components/SettingsModal.tsx 447 行（+47）、src/frontend/src/design-system/tokens.css 1593 行（+350）、src/mail_core/api/mail.py 427 行（+24）、src/mail_core/mail/storage/models.py 413 行（+3）、src/mail_core/accounts/service.py 424 行（+226）；按 prompt 仅列提示，不单独进 finding。生成 OpenAPI/TS 类型排除。未见新增/扩展函数 CC≥15；文件与复杂度观察不作为 finding。安全、正确性、契约与 Breaking、性能资源、架构维护、健壮性可观测、文档规格七视角均已检查；除 f025 外未发现新的安全或实现缺陷。测试层质量不在本代码 reviewer 范围。
- AC 复验方式：逐条对照本轮完整 diff 与实现；trust_prior 项依赖 task.md attempt 2 的迁移及浏览器运行记录，本 reviewer 未重跑真实环境。

|AC|状态|证据|
|---|---|---|
|AC-001|re_verified|API 在字段长度校验前 trim；service 校验空白、长度和重名。api/accounts.py:87-103、accounts/service.py:192-220。|
|AC-002|trust_prior|删除组事务只清账号 group_id/group_order 并提交；独立会话持久性依赖 task.md attempt 2 的 PostgreSQL 测试记录。|
|AC-003|re_verified|账号可移入/移出；目标组锁和组织事务锁处理并发删除。accounts/service.py:103-140、381-395。|
|AC-004|re_verified|默认按域名、完整邮箱排序，手动顺序按持久化 order 字段读取。accounts/service.py:75-90。|
|AC-005|re_verified|完整布局事务分别写 group、master 及成员顺序；revision 冲突阻止覆盖新快照。accounts/service.py:223-238、327-350。|
|AC-006|re_verified|新组与手动移入追加末尾；恢复默认仅清账号顺序字段，保留组顺序与归属。accounts/service.py:192-204、353-362。|
|AC-007|re_verified|排序载荷检查完整 ID 集合，revision 与 advisory lock 处理并发写冲突，整体事务回滚。accounts/service.py:223-324。|
|AC-008|trust_prior|迁移可逆、OpenAPI/生成类型同步；旧库 upgrade 与 downgrade/upgrade 依 task.md attempt 2 迁移运行记录。|
|AC-009|re_verified|实现、迁移、默认配置没有示例分组 seed 或硬编码分支。|
|AC-010|re_verified|分组成员范围约束当前邮件查询，保留角色筛选和多位置去重。src/mail_core/api/mail.py、src/mail_core/mail/application/queries.py。|
|AC-011|re_verified|keyset 查询以消息 ID 作同时间次级排序；空成员集合不会回退全局。queries.py:list_messages_keyset、unified_inbox。|
|AC-012|re_verified|搜索结果和 total 共享账号/文件夹过滤；组统计来自服务端完整数据，未知计数为 null。application/search.py、search/index.py、application/queries.py。|
|AC-013|re_verified|全部已读按 group、role、flag 限定后进入既有远端写回状态机。mail/application/mutations.py。|
|AC-014|re_verified|inbox/search/mark-all-read 拒绝 group 与 account/folder 歧义，未知组返回 404。src/mail_core/api/mail.py。|
|AC-015|re_verified|每次请求按最新 group_id 解析成员；任意成员变化会 reset 所有 group inbox/search 缓存。queries.ts:109-119、Sidebar.tsx:383-387。|
|AC-016|re_verified|无 group_id 时原全局、单账号和精确 folder_id 查询保留，写请求继续走既有认证/CSRF。|
|AC-017|trust_prior|顶层区域顺序与独立折叠状态可由组件确认；实际像素布局依 task.md attempt 2 的 E2E 记录。|
|AC-018|re_verified|六类全局/组入口及全部账号导航存在；fetchAccounts 读取至 has_more=false，不再设置 20,000 上限。queries.ts:141-151。|
|AC-019|re_verified|真实文件夹按服务器 folder 数据构造，账号标题与箭头均控制展开。Sidebar.tsx:654-690。|
|AC-020|trust_prior|CSS/JS 固定 24px 层级与箭头槽位；bounding box、长邮箱及主题布局依 task.md attempt 2 的 E2E 记录。|
|AC-021|re_verified|query key 区分范围/文件夹，无跨 key placeholder；成员改变后清空所有组列表与搜索缓存。|
|AC-022|re_verified|缺失统计以 null 表示；新增账号路径未失效固定 stats cache，未知总数仍可显示为旧值，见 f025。|
|AC-023|re_verified|展开偏好持久化，导航只渲染仍存在的组和账号。|
|AC-024|re_verified|aria-expanded 与 disclosure 状态一致；真实深浅主题、窄屏和键盘操作依 E2E 记录。|
|AC-025|trust_prior|diff 未删除原有邮件分类、真实目录、搜索筛选、分页或邮件操作；完整既有功能回归依 task.md attempt 2 前端测试记录。|
|AC-026|re_verified|分组仅由服务端数据和用户输入驱动，无示例组名特判。|
|AC-027|re_verified|账号列表提供可访问的新建分组控件并刷新组织数据。Sidebar.tsx:772-790。|
|AC-028|re_verified|菜单支持重命名与删除；请求中禁用重命名控件，失败保留输入。Sidebar.tsx:432-453、801-850。|
|AC-029|re_verified|删除确认说明保留账号和邮件；当前组删除后回所有收件箱并清选择/搜索。SettingsModal.tsx:266-275、Sidebar.tsx:456-470。|
|AC-030|re_verified|设置选择器支持归组、移组、清组并刷新账号、组、布局及邮件查询。SettingsModal.tsx:144-159。|
|AC-031|re_verified|设置页保留创建/删除组和账号添加/删除入口；新增账号统计未刷新见 f025。|
|AC-032|re_verified|Escape/取消会恢复焦点，组名按普通文本显示，窄屏可通过设置下拉移组。|
|AC-033|re_verified|分组名和归属选项只来自服务端及用户数据。|
|AC-034|trust_prior|整行可拖动，菜单/箭头标记 no-drag 且目标有反馈；原生拖动矩阵依 E2E 运行记录。|
|AC-035|trust_prior|布局构造覆盖空组、组标题和账号行目标；真实浏览器拖动落点依 E2E 记录。|
|AC-036|trust_prior|从组拖到总列表会清归属并更新总顺序；原生拖动依 E2E 记录。|
|AC-037|trust_prior|DragPayload 携来源列表区分总列表与组内排序；刷新持久化依 E2E 记录。|
|AC-038|trust_prior|组标题可拖，固定区域不拖；跨会话持久化依 E2E 记录。|
|AC-039|re_verified|默认恢复需当前 revision，失败显示错误并重查服务端状态。Sidebar.tsx:475-498、accounts/service.py:353-362。|
|AC-040|trust_prior|保存中保护、revision 冲突、自拖与无效 payload 处理可由代码确认；真实原生拖动与失败回滚依 task.md attempt 2 E2E 记录。|

coverage = 27 / 40

trust_prior = 13 / 40（32.5%），超过 30% 提示阈值；建议合并前人工抽查 trust_prior 项。

- 总体判断：仍有 1 条未解决 important finding，当前不能通过代码 review。
- 系统性 follow-up：无。

verdict: FAIL

## Round 5 (2026-10-23T06:49:16+08:00)

- task：t027_account_group_ordering
- spec：docs/tasks/t027_account_group_ordering/spec.md
- diff_anchor：c8cee92446f9c24e7a0a2a501d52d0bd49068041
- target：git -C '[REDACTED_LOCAL_PATH]' diff c8cee92446f9c24e7a0a2a501d52d0bd49068041
- round：5
- reviewed_at：2026-10-23T06:49:16+08:00

reviewed_scope: 18514639e6c252b7

## Findings

Round 5 零 finding。

## 结论

- 前轮 finding 复核：f021 已消除（成员变化时 reset 所有 group inbox/search 查询，queries.ts:109-119，设置移组和侧栏布局保存均调用）；f022 已消除（fetchAccounts 读取至 has_more=false，空页仍有后续数据时明确报错，queries.ts:141-151）；f023 已消除（删除账号后清理全局统计和邮件列表缓存，SettingsModal.tsx:167-180、queries.ts:122-128）；f024 已消除（布局读取先单次按 group_id 分桶，accounts/service.py:241-260）；f025 已消除（添加账号成功后等待账号列表和布局刷新，再 reset 全局 stats query，SettingsModal.tsx:259-267；查询重启后从服务器读取包含新账号的统计）。
- 本轮新发现：0 条。
- 未进表的提示：达到文件规模阈值且本 task 仍净增的源码：src/frontend/src/components/Sidebar.tsx 851 行（+291，达到 800 行 important 提示阈值）、src/frontend/src/components/MessageList.tsx 706 行（+24）、src/frontend/src/components/SettingsModal.tsx 448 行（+48）、src/frontend/src/design-system/tokens.css 1593 行（+350）、src/mail_core/api/mail.py 427 行（+24）、src/mail_core/mail/storage/models.py 413 行（+3）、src/mail_core/accounts/service.py 424 行（+226）；依 prompt 仅列提示，不单独进 finding。生成 OpenAPI/TS 类型排除。未见新增/扩展函数 CC≥15；文件规模与复杂度观察不作为 finding。七视角已检查，未发现新的安全、正确性、契约与 Breaking、性能资源、架构维护、健壮性可观测或文档规格问题；测试层质量不在本代码 reviewer 范围。
- AC 复验方式：40 条 AC 逐条对照完整 diff 和实现。迁移独立会话、浏览器像素及原生拖动依 task.md attempt 2 已产出的 PostgreSQL/E2E 记录，本 reviewer 未重跑这些真实环境场景。

|AC|状态|证据|
|---|---|---|
|AC-001|re_verified|API 字段在长度检查前 trim；service 校验空白、长度和唯一名。api/accounts.py:87-103、accounts/service.py:192-220。|
|AC-002|trust_prior|删除组只清 group_id/group_order；独立会话持久性依 task.md attempt 2 的 PostgreSQL 测试记录。|
|AC-003|re_verified|账号可移入/移出；目标组锁和组织事务锁处理并发删除。accounts/service.py:103-140、381-395。|
|AC-004|re_verified|默认按域名、完整邮箱排序，手动顺序读取持久化字段。accounts/service.py:75-90。|
|AC-005|re_verified|完整布局事务分别写 group、master 和成员顺序；revision 冲突阻止覆盖新快照。accounts/service.py:223-238、327-350。|
|AC-006|re_verified|新组与移入账号追加末尾；恢复默认只清账号手动顺序，不改变组顺序和归属。accounts/service.py:192-204、353-362。|
|AC-007|re_verified|完整 ID 校验、expected_revision 及 advisory lock 提供并发冲突处理，事务整体提交或回滚。accounts/service.py:223-324。|
|AC-008|trust_prior|迁移可逆且 OpenAPI/生成类型同步；旧库升级与 downgrade/upgrade 依 attempt 2 迁移运行记录。|
|AC-009|re_verified|实现、迁移和配置无示例分组 seed/硬编码，组由服务端数据和用户输入产生。|
|AC-010|re_verified|组邮件查询按当前组员过滤，保留 folder role 与消息去重。src/mail_core/api/mail.py、src/mail_core/mail/application/queries.py。|
|AC-011|re_verified|keyset 查询以消息 ID 作稳定次级排序；空成员集合不回退全局。queries.py:list_messages_keyset、unified_inbox。|
|AC-012|re_verified|搜索结果与 total 共享账号/文件夹范围；组统计独立使用服务端完整数据且未知计数为 null。application/search.py、search/index.py、application/queries.py。|
|AC-013|re_verified|批量已读按 group、role、flag 过滤后进入既有远端写回状态机。mail/application/mutations.py。|
|AC-014|re_verified|inbox/search/mark-all-read 拒绝 group 与 account/folder 歧义，未知组返回 404。src/mail_core/api/mail.py。|
|AC-015|re_verified|每次请求按最新 group_id 解析成员；所有 group inbox/search 缓存随成员改变 reset。queries.ts:109-119、Sidebar.tsx:383-387。|
|AC-016|re_verified|无 group_id 时原全局、单账号、精确 folder_id 路径保留，写请求使用既有认证/CSRF。|
|AC-017|trust_prior|顶层顺序及折叠状态可从组件确认；实际 24px 布局依 attempt 2 E2E 记录。|
|AC-018|re_verified|六类全局/组入口保留，账号分页读取至 has_more=false。Sidebar.tsx:110-117、queries.ts:141-151。|
|AC-019|re_verified|真实目录使用服务器 folder 数据，账号标题和箭头控制展开。Sidebar.tsx:654-690。|
|AC-020|trust_prior|CSS/JS 固定 24px 层级与箭头槽位；bounding box、长邮箱和主题布局依 attempt 2 E2E 记录。|
|AC-021|re_verified|query key 区分范围/文件夹且无跨范围 placeholder；成员变化清空所有 group 页面缓存。|
|AC-022|re_verified|全局 stats 对缺失账号返回未知；新增账号成功后重置 stats 查询，刷新后包含当前账号集合。SettingsModal.tsx:259-267、Sidebar.tsx:277-292。|
|AC-023|re_verified|展开偏好持久化，导航只渲染当前存在的组和账号。|
|AC-024|re_verified|aria-expanded 与 disclosure 状态一致；真实主题、窄屏与键盘验证依 E2E 记录。|
|AC-025|trust_prior|diff 未删既有邮件分类、真实目录、搜索、筛选、分页或邮件操作；全量回归依 attempt 2 前端运行记录。|
|AC-026|re_verified|分组只由服务端和用户数据驱动，无示例组特判。|
|AC-027|re_verified|账号列表提供可访问的新建分组入口并刷新组织数据。Sidebar.tsx:772-790。|
|AC-028|re_verified|菜单提供重命名/删除；进行中禁用表单，失败保留输入。Sidebar.tsx:432-453、801-850。|
|AC-029|re_verified|删除确认承诺保留账号/邮件；删除当前组后回到所有收件箱并清理搜索/选择。SettingsModal.tsx:266-275、Sidebar.tsx:456-470。|
|AC-030|re_verified|设置选择器支持归组、移组、清组并刷新账号/组/布局/邮件查询。SettingsModal.tsx:144-159。|
|AC-031|re_verified|设置页保留组和账号创建/删除；新增账号后 stats 查询同步重置。SettingsModal.tsx:259-267。|
|AC-032|re_verified|Escape/取消恢复焦点，组名作为普通文本渲染，窄屏可由设置下拉完成移组。|
|AC-033|re_verified|组名与归属选项仅来自服务端数据及用户输入。|
|AC-034|trust_prior|整行可拖动，子控件 no-drag 且目标有反馈；原生拖放矩阵依 attempt 2 E2E 记录。|
|AC-035|trust_prior|布局构造覆盖空组、组标题与账号行；浏览器实际落点依 attempt 2 E2E 记录。|
|AC-036|trust_prior|从组拖到总列表会清归属并更新总顺序；原生拖动依 attempt 2 E2E 记录。|
|AC-037|trust_prior|DragPayload 区分总列表与组内顺序；刷新持久化依 attempt 2 E2E 记录。|
|AC-038|trust_prior|组标题可拖，固定区域不可拖；跨会话持久化依 attempt 2 E2E 记录。|
|AC-039|re_verified|恢复默认要求当前 revision，失败显示错误并失效服务端状态。Sidebar.tsx:475-498、accounts/service.py:353-362。|
|AC-040|trust_prior|保存中保护、revision 冲突、自拖与无效 payload 由代码确认；原生拖放/失败回滚依 attempt 2 E2E 记录。|

coverage = 27 / 40

trust_prior = 13 / 40（32.5%），超过 30% 提示阈值；建议合并前人工抽查 trust_prior 项。

- 总体判断：Round 3–4 finding 均已修复，本轮无新的 critical / important；代码 review 通过。
- 系统性 follow-up：无。

verdict: PASS
