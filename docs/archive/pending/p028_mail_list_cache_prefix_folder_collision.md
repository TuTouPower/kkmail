# p028 展开侧栏账号文件夹后邮件缓存操作误扫文件夹数组触发 mailKey requires a non-empty message id

- 现象：
    1. 在侧栏展开任意账号文件夹树并进入目录（如 `[REDACTED_EMAIL] · 垃圾邮件`）后，点击未读邮件打开时，列表顶部弹出红色报错 `标记已读失败：mailKey requires a non-empty message id`，邮件未读圆点不消失且未向后端发起 `POST /api/mail/messages/{id}/read` 请求。
    2. 同一状态下执行右键菜单/阅读器工具栏的“标为已读/未读”、“标记/取消旗标”、“全部已读”、“移到废纸篓”，或在已选中邮件时展开侧栏账号文件夹，均会抛出 `Error: mailKey requires a non-empty message id`。
- 影响：
    - 只要用户展开过任一侧栏账号节点（且 `expandedSidebarAccounts` 持久化于 `localStorage` 的 `mail-ui-storage`，刷新后依然保持展开），TanStack Query 缓存中即存在 `['mail-core', 'account-folders', accountId]`。
    - 此后全局所有邮件状态乐观更新（点击未读邮件自动标已读、手动切换已读/未读、切换旗标、全部已读、删除邮件清理缓存）均在前端缓存遍历阶段直接抛错中断，无法发出写请求或完成后续 UI 状态收敛。
    - 当 `['mail-core', 'account-folders', accountId]` 的 `dataUpdatedAt` 新于当前邮件列表缓存（例如先选中邮件、再点击侧栏展开账号目录）或查找的 `selectedKey` 不在更早的查询中时，`findCachedMail` 在 `MessageReader` 渲染期同步抛错，导致整个页面崩溃进入 `ErrorBoundary`。
- 根因：
    1. 邮件列表缓存前缀过宽与非列表数组碰撞（产品缺陷，`src/frontend/src/api/queries.ts:63, 157-244`、`src/frontend/src/components/Sidebar.tsx:168-176`）：
        - `queries.ts:63` 将 `MAIL_LIST_PREFIX` 定义为顶层 `['mail-core']`，注释假定该前缀下仅有 `inbox` 与 `search` 邮件列表；
        - 但 `Sidebar.tsx:169` 的 `AccountFolders` 使用 `queryKey: ['mail-core', 'account-folders', accountId]` 缓存 `FolderStatsItem[]`（纯数组 `[{ folder_id, name, role, unread_count, total_count }, ...]`，无 `id` 字段）；
        - `patchCachedMail`（`queries.ts:229-236`）、`removeCachedMail`（`queries.ts:239-244`）调用 `queryClient.setQueriesData({ queryKey: MAIL_LIST_PREFIX }, ...)`，以及 `findCachedMail`（`queries.ts:211`）调用 `findAll({ queryKey: MAIL_LIST_PREFIX })` 时，均未按 `queryKey[1] === 'inbox' || queryKey[1] === 'search'` 过滤；
        - `extractItemsFromCache` 与 `updateItemsInCache` 遇到 `Array.isArray(data)` 为 `true` 的 `FolderStatsItem[]` 时直接当作 `MailItem[]` 交给回调，回调对 `FolderStatsItem` 调用 `mailKey(m)`（`src/frontend/src/lib/mailKey.ts:12-15`），因 `m.id` 为 `undefined` 立即抛出 `Error('mailKey requires a non-empty message id')`。
    2. 已确认同类位点清单：
        - 位点 1（`patchCachedMail` / `setCachedReadState` / `setReadOptimistic` / `markReadOptimistic` / `flagOptimistic`，`src/frontend/src/api/queries.ts:229-236, 246-288`）：对 `MAIL_LIST_PREFIX` 全量 `setQueriesData` 且未校验 `isMailListQuery` 与 `hasMailId(m)`；`setReadOptimistic` 第 252 行仅用 `items.filter((m) => m.id)` 而非 `hasMailId`（未过滤空白字符串 ID）。
        - 位点 2（`removeCachedMail`，`src/frontend/src/api/queries.ts:239-244`）：删除单封或多封邮件（`MessageList.tsx:371, 441`、`MessageReader.tsx:127`）后调用 `removeCachedMail`，同样因遍历到 `['mail-core', 'account-folders', accountId]` 抛出 `mailKey requires a non-empty message id`，导致服务端已移入废纸篓但前端报错并中断选中态清理与 `invalidateQueries`。
        - 位点 3（`findCachedMail` 查询过滤与当前视图 scope 判定，`src/frontend/src/api/queries.ts:199-227`）：① `findAll({ queryKey: MAIL_LIST_PREFIX })` 未限定 `inbox` / `search`，且 `items.find((m) => mailKey(m) === key)` 未用 `hasMailId(m)` 守卫；② 第 205 行 `const accountId = view.type === 'account' ? view.accountId : undefined` 遗漏了 `view.type === 'folder'`、`view.type === 'favorite'`（含 `accountId`）与 `view.type === 'group'`，导致在文件夹/分组视图下 `currentScope` 被误算为 `'__all__'`，且 `a.queryKey.includes(currentScope)` 在 `view.type === 'account'` 时还会误命中 `['mail-core', 'account-folders', accountId]`。
        - 位点 4（`MessageReader` 缓存订阅过滤，`src/frontend/src/components/MessageReader.tsx:26-31`）：`useSyncExternalStore` 订阅判断 `qk[0] === 'mail-core'`，在 `account-folders` / `stats` / `folder-stats` 更新时也会触发 `findCachedMail(selectedKey)` 重算。
- 测试缺口：
    - `src/frontend/src/api/mailCore.mutations.test.ts` 与 `src/frontend/src/api/queries.cache.test.ts` 在测试 `markReadOptimistic`、`flagOptimistic`、`findCachedMail` 时，仅向 `queryClient` 写入了 `queryKeys.inbox(...)` 与 `queryKeys.search(...)`，从未同时写入同处于 `['mail-core']` 前缀下的 `['mail-core', 'account-folders', accountId]`（数组型非邮件数据）。
    - `src/frontend/src/components/MessageList.test.tsx` 与 `Sidebar.test.tsx` 各自独立渲染单组件，缺乏展开侧栏文件夹树后在列表中点击未读邮件、切换旗标、全部已读、删除邮件及 `MessageReader` 联动渲染的组合测试。
    - 应补测层级：在 `queries.cache.test.ts` / `mailCore.mutations.test.ts` 补充 `['mail-core', 'account-folders', accountId]` 共存时的 `findCachedMail`、`markReadOptimistic`、`flagOptimistic`、`setCachedReadState`、`removeCachedMail` 回归测试（含 `folder` / `group` 视图 scope 优先级与空白 ID 防御）；在组件测试补充 `<Sidebar />` 展开账号目录与 `<MessageList />` / `<MessageReader />` 同屏交互测试。
- 线索：
    - `.scratch/repro_mailkey_error.test.tsx`：最小复现测试（3 个用例全部复现：`<Sidebar /> + <MessageList />` 点击未读邮件出现 `标记已读失败：mailKey requires a non-empty message id` 且 `POST /read` 0 次调用；`markReadOptimistic` / `flagOptimistic` / `setCachedReadState` / `removeCachedMail` / `findCachedMail` 抛错；选中邮件后更新 `account-folders` 触发 `<MessageReader />` 渲染崩溃）。
- 处理：t046
