---
tid: "t046"
slug: "mail_list_cache_isolation"
title: "隔离邮件列表缓存前缀并补齐视图范围匹配"
status: "done"
branch: "t046_mail_list_cache_isolation"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "2a5fabadae189b5498a80320cf64a7b12aded81e"
depends_on: ""
conflicts_with: ""
note: "来源 p028；防止 account-folders 等非列表查询被当成 MailItem 数组触发 mailKey 抛错。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 诊断与复现：
   - 根因在于 `queries.ts` 中 `MAIL_LIST_PREFIX` 声明为过于宽泛的 `['mail-core']`，导致 `patchCachedMail`、`removeCachedMail`、`findCachedMail` 在遍历缓存时扫描并篡改了 `['mail-core', 'account-folders', accountId]`、`stats` 等非邮件列表查询。
   - 当侧栏加载账号文件夹后，这些缓存中包含的是无 `id` 的 `FolderStatsItem` 对象，调用 `mailKey(m)` 即抛出 `Error: mailKey requires a non-empty message id`，破坏了标已读/旗标/删除链路，并在 `MessageReader` 订阅响应时导致阅读器崩溃。
   - `findCachedMail` 仅判断 `view.type === 'account'`，遗漏了 `folder`、`favorite`（含 `accountId`）与 `group`（`group:${groupId}`）视图的优先 scope 匹配。
2. 修复方案：
   - 提取并导出统一谓词 `isMailListQueryKey(key)`，严格匹配 `['mail-core', 'inbox', ...]` 与 `['mail-core', 'search', ...]` 查询，收窄 `setQueriesData`、`findCachedMail` 与 `MessageReader` 订阅范围。
   - 在 `extractItemsFromCache`、`updateItemsInCache`、`setReadOptimistic` 中加入防御性非空字符串 `id` 校验，杜绝非邮件对象传递给 `mailKey`。
   - 在 `findCachedMail` 中补齐 `folder`、`favorite` 与 `group` 视图当前的 scope 匹配优先级。
3. 验证与规范：
   - 在 `queries.cache.test.ts` 与 `MessageReader.test.tsx` 补充非邮件列表查询共存时的查找、乐观更新、删除与多视图优先级测试，并在 `docs/blueprint/conventions.md` §五.1 固化该列表缓存谓词隔离规范。

## Review 处置

### Round 1 (2026-10-23T22:30:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`(cd src/frontend && npm test && npx tsc -b && npm run build && npm run lint)` 39 文件 265 项全通；`(cd src/desktop && npm test)` 全通；`pytest .repo_template/tests -q -m contract` 150 项全通；`scripts/run-mail-core-tests.sh unit` 309 项全通。
- 黑盒：`npm --prefix src/frontend run test:e2e`（14 项全部通过）；`python3 scripts/run_full_stack_e2e.py`（8 项全栈真实端到端测试全通）。
- review：`docs/tasks/t046_mail_list_cache_isolation/review_general.md` 单轮 PASS，0 finding。
- AC 证据：见 `handoff.json`

### 结果摘要

- 严格隔离邮件列表查询缓存范围至 inbox/search 前缀，防御非邮件对象误调 mailKey，补齐多视图优先 scope 匹配并收窄阅读器订阅，解决侧栏展开文件夹后标记已读报错与阅读器崩溃。遗留：无。
