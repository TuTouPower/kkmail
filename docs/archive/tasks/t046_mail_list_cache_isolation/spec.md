# Task spec

## 背景

前端 `queries.ts` 将 `MAIL_LIST_PREFIX` 定义为宽泛的顶层 `['mail-core']`，而侧栏 `AccountFolders` 将账号文件夹统计数组缓存在 `['mail-core', 'account-folders', accountId]` 下（元素为无 `id` 的 `FolderStatsItem`）。只要用户展开过任一侧栏账号节点，`patchCachedMail`、`removeCachedMail`、`findCachedMail` 就会把文件夹数组当成 `MailItem[]` 遍历并调用 `mailKey(m)`，立即抛出 `Error: mailKey requires a non-empty message id`，导致点击未读邮件自动标已读、手动标已读/未读、加旗标、全部已读、删除邮件全部报错中断，甚至在 `MessageReader` 渲染期触发页面崩溃。

## 契约区

### 范围

- 严格限定邮件列表缓存匹配范围：仅对 `['mail-core', 'inbox', ...]` 与 `['mail-core', 'search', ...]` 查询执行邮件列表项读取、乐观更新与删除清理，排除 `account-folders`、`stats`、`folder-stats` 等非邮件列表缓存。
- 在遍历、提取、更新缓存项及 `setReadOptimistic` 过滤时统一校验有效邮件主键（非空字符串 `id`），防御非邮件对象或异常空 ID。
- 修复 `findCachedMail` 的当前视图 scope 优先匹配逻辑，完整覆盖 `account`、`folder`、`favorite`（带 `accountId`）与 `group` 视图，避免误判为全局 `__all__` 或误命中非列表查询。
- 收窄 `MessageReader` 的 QueryCache 订阅触发条件，仅在邮件列表查询（`inbox` / `search`）变更时重算选中邮件快照。

### 非范围

- 不改变后端邮件已读、旗标或删除 API 契约。
- 不改变侧栏文件夹统计查询的数据结构。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：当 QueryCache 中同时存在 `['mail-core', 'account-folders', accountId]`（及 `stats`、`folder-stats`）与邮件列表缓存时，执行 `findCachedMail`、`markReadOptimistic`、`setReadOptimistic`、`flagOptimistic`、`setCachedReadState`、`removeCachedMail` 均不触碰非邮件列表缓存，不抛出 `mailKey requires a non-empty message id`，且 `account-folders` 缓存数据保持原样不被篡改。
- [ ] AC-002：在侧栏展开账号文件夹并进入任意目录后，点击未读邮件打开、切换已读/未读、切换旗标、批量全部已读、移到废纸篓均正常向后端发起请求并完成前端乐观状态更新，阅读器正常渲染不崩溃。
- [ ] AC-003：`findCachedMail` 在 `account`、`folder`、`favorite`（含 `accountId`）与 `group` 视图下均优先命中当前视图对应 scope（`accountId` 或 `group:{groupId}`）的邮件列表缓存。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试。

## 上下文区

- 来源：`p028`（2026-10-23 核实：`src/frontend/src/api/queries.ts:63, 199-288` 与 `src/frontend/src/components/MessageReader.tsx:26-31` 中 `MAIL_LIST_PREFIX` 碰撞缺陷仍存在，`.scratch/repro_mailkey_error.test.tsx` 3 个复现用例均命中）

### 有意不测

- 无

### 测试策略

- 在 `src/frontend/src/api/queries.cache.test.ts` 与 `src/frontend/src/api/mailCore.mutations.test.ts` 补充 `account-folders` / `folder-stats` 与 `inbox` / `search` 共存时的乐观更新、删除、查找及多视图 scope 优先级单元测试。
- 在组件测试中补充 `<Sidebar />` 展开文件夹后与 `<MessageList />` / `<MessageReader />` 联动点击未读邮件、切换状态的集成回归测试。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：收窄列表缓存匹配谓词若遗漏某类合法列表 queryKey，会导致该列表乐观更新失效。
- 回退：通过统一的 `isMailListQueryKey` 辅助函数精确匹配 `queryKey[0] === 'mail-core' && (queryKey[1] === 'inbox' || queryKey[1] === 'search')`，覆盖全部列表与搜索查询。

### 依赖与约束

- 须符合 `docs/blueprint/conventions.md` §五.1「导航 Scope 隔离」约定。

### Finalization 时更新的 blueprint

- `docs/blueprint/conventions.md`：在 §五.1 补充邮件列表缓存前缀隔离（`inbox`/`search` 与 `account-folders`/`stats` 严格区分）规则。
