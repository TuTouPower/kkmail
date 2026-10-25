# p041 邮件标记已读或点击阅读后收件箱及侧栏未读计数徽标未即时更新

- 现象：
    1. 用户在邮件列表中点击打开一封未读邮件（`openMessage` 自动触发 `markReadOptimistic`）、或在阅读器工具栏中点击“标为已读”、或通过邮件右键菜单“标为已读”后，邮件行本身的未读状态（蓝点）虽然消失，但收件箱列表顶部的未读计数（如 `1 封邮件 · 1 封未读`）、侧栏分类（“所有收件箱”、“所有未读”）、所属分组、以及账号和文件夹节点的未读徽标（unread badge）数字完全没有立刻减少。
    2. 反向操作（将已读邮件标为未读）时，收件箱列表头部与侧栏各处未读徽标同样没有立刻增加。
    3. 即使后台 `POST /api/mail/messages/{id}/read` 成功返回，在缺乏 SSE 推送（或 SSE 连接处于重连、延迟、未就绪等状态）时，侧栏与列表未读数长久保持旧值，直到用户手动点击刷新按钮。
- 影响：
    - 核心邮件已读/未读交互的即时反馈（Optimistic UI）断裂，用户无法直观确认未读邮件已被处理完毕，导致用户困惑并重复点击。
    - 在弱网、离线、或 SSE 延迟/断开的环境下，未读计数与实际邮件状态长时间严重不同步。
    - 列表顶部的未读数、侧边栏全域（全局总收件箱、各分组、各账号节点、展开的具体文件夹）受同一未读统计机制影响，全线处于陈旧状态。
- 根因：
    1. 统计查询缺乏乐观更新机制（产品缺陷，`src/frontend/src/api/queries.ts:276-306`）：
        - `setReadOptimistic` / `markReadOptimistic` 仅更新了列表查询（`isMailListQueryKey`）内部条目的 `is_read` 字段，并未对全局统计（`queryKeys.stats`，即 `['mail-core', 'stats']`）、账号文件夹统计（`['mail-core', 'account-folders', accountId]`）、列表文件夹统计（`['mail-core', 'folder-stats', ...]`）进行任何乐观计算与同步调整。
    2. 突变完成后缺失对统计 Query 的主动失效刷新（产品缺陷，`src/frontend/src/api/queries.ts:283-300`）：
        - `postMailCoreMessageRead` 成功完成后，没有调用 `queryClient.invalidateQueries` 刷新 `queryKeys.stats`、`folder-stats`、`account-folders` 等相关查询，而是完全被动等待服务端的 PostgreSQL LISTEN/NOTIFY + SSE 推送 `folder.stats_updated`。
    3. 邮件列表头部未读数推导逻辑锁定旧值（产品缺陷，`src/frontend/src/components/MessageList.tsx:272`）：
        - `const unreadCount = unreadUnknown ? null : Math.max(serverUnread ?? 0, raw.filter((m) => m.is_read === false).length)`
        - 由于采用 `Math.max(serverUnread ?? 0, ...)`，在 `serverUnread` 仍为服务端旧值时，即便本地列表中的未读邮件已被标为已读，`Math.max` 仍锁定在旧的大值，导致列表头部在本地状态变更后永远无法即时递减。
    4. 已确认同类位点清单：
        - 位点 1（标为未读反向路径，`src/frontend/src/components/MessageReader.tsx:121`、`src/frontend/src/components/MessageList.tsx:370`）：`setReadOptimistic([m], false)` 同样只改列表条目，不更新 stats，且被 `Math.max` 影响无法正确反映。
        - 位点 2（移到废纸篓乐观阶段，`src/frontend/src/components/MessageList.tsx:389-392`、`src/frontend/src/components/MessageReader.tsx:132-137`）：删除未读邮件在网络请求前仅调了 `removeCachedMail`，在网络返回并执行 `invalidateQueries` 之前，未读统计徽标同样无乐观递减。
        - 位点 3（展开账号节点的 `AccountFolders`，`src/frontend/src/components/Sidebar.tsx:170-178`）：`['mail-core', 'account-folders', accountId]` 未在已读/未读变更时得到更新或失效处理。
- 测试缺口：
    - `src/frontend/src/api/mailCore.mutations.test.ts` 中的 `markReadOptimistic` 测试仅对 `queryKeys.inbox(...)` 中的 `item.is_read` 进行了断言，完全未断言 `queryKeys.stats`、`account-folders`、`folder-stats` 等统计查询的缓存更新或失效状态。
    - `src/frontend/src/components/MessageList.test.tsx` 和 `Sidebar.test.tsx` 缺乏“点击未读邮件触发标记已读后，列表头部未读数与侧栏未读徽标即时递减”的组件联动与断言。
    - 应补测层级：
        1. 在 `mailCore.mutations.test.ts` 补充 `setReadOptimistic` 对 `queryKeys.stats`、`folder-stats`、`account-folders` 缓存的乐观增减断言及突变后 query 失效断言；
        2. 在 `MessageList.test.tsx` 补充点击未读邮件后 `.list-count` 即时反映未读数递减的组件测试；
        3. 在 `Sidebar.test.tsx` 补充邮件已读/未读状态变更后全局/分组/账号/文件夹 badge 即时联动的组件测试。
- 线索：
    - `.scratch/repro_unread_badge_stale.test.tsx`：最小复现测试，验证点击未读邮件后，邮件行自身乐观变为已读，但侧栏所有收件箱徽标（仍为1）、分组徽标（仍为1）、列表头部 `.list-count`（仍为1 封未读）均未即时改变，且 `queryKeys.stats` 突变后未被触发失效。
- 处理：8a80186
