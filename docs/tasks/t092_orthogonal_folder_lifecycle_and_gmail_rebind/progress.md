---
tid: "t092"
slug: "orthogonal_folder_lifecycle_and_gmail_rebind"
title: "重构目录正交状态模型、IMAP角色收口与Gmail系统目录重绑定合并"
status: "done"
branch: "t092_orthogonal_folder_lifecycle_and_gmail_rebind"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "71585e7b130e65f9d00fa5f5948692b0b52901ef"
spec_source_sha: "71585e7b130e65f9d00fa5f5948692b0b52901ef"
depends_on: ""
conflicts_with: ""
note: "来源 p100；按开发铁律彻底废除 folders.sync_status，拆分 selectable/remote_state，修复 IMAP \\Important 角色与中英系统目录同实体合并及迁移洗净"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 根因与架构拆解：按开发铁律废除过载 `folders.sync_status` 与 `SyncStatus`，拆分正交属性 `kind`（`container`/`view`）、`selectable`（布尔，表示 `\Noselect` 层级节点）与 `remote_state`（`active`/`missing`，统一表达 `container` 与 `view` 远端存续）；补齐 `FolderRole`（`flagged`/`important`）、`ImapProvider` `\Important` 与 `[Gmail]/` 前缀剥离，并新增 `src/mail_core/sync/folder_rebind.py` 负责系统角色 1-to-1 原位重绑定与物理容器内嵌 IMAP `Message.remote_id` / 在途 `RemoteOperation` 路径重写（含冲突去重合并）。
- 历史数据迁移：新增可逆迁移 `20261126_0007_orthogonal_folder_state_and_dedupe.py` 并更新 `CURRENT_HEAD_REVISION = "20261126_0007"`，修正 Gmail Important 视图误存 `role='other'`，合并双语重复系统目录（重写关联物理容器 `messages.remote_id` / `remote_operations`，保留已完成 `sync_checkpoints`，按未知读状态保留 `NULL` 重算 `folder_stats`）并删除 `folders.sync_status`。
- 旧测试改写说明：因 `SyncStatus`、`Folder.sync_status` 及 API `AccountFolderStatsItemOut.sync_status` 已破坏性移除，对依赖上述已删除契约的既有测试按新正交模型重写并加注 `# t092:`；依赖旧 `folders.sync_status` 列的 `0004` / `0006` 历史迁移测试分别隔离至目标历史 revision 库验证，保留原迁移校验语义。
- Round 1 修复落地：全部 8 条 `review_code.md` finding（`t092_code_f001`~`t092_code_f008`）及 `MessageList.tsx` `selectable` 过滤观察均已修复并补充针对性自动化测试，随后重新执行全量无过滤门禁通过。
- Round 2 收口落地：`review_code.md` Round 2（`t092_code_f009`~`f011`）与 `review_test.md` Round 1（`t092_test_f001`~`f005`）全部修复；拆解 `0007`、`folder_rebind.py`、`engine.py`、`mutations.py` 高复杂度函数，对齐 `_query_inbox_stats` 与文档口径，并拆分为 `test_t092_orthogonal_folder_lifecycle.py` 与 `test_t092_downstream_isolation_and_api.py` 补全全部实库/HTTP/前端/E2E 覆盖，重跑全量无过滤门禁通过并重新勾选全部 AC。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-26T13:56:59+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t092_code_f001|critical|已修|为物理容器 1-to-1 重绑定与 0007 合并同步重写 IMAP Message.remote_id（含冲突行合并）及在途 RemoteOperation 路径，并补 reconcile 与迁移断言|`src/mail_core/sync/folder_rebind.py:211-265`, `src/mail_core/sync/engine.py:341-348`, `src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:194-252`|
|t092_code_f002|important|已修|0007 重算 folder_stats 改为统计 is_read IS NULL 并按 unknown_read > 0 写入 NULL，对齐 recompute_folder_stats|`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:366-389`|
|t092_code_f003|important|已修|0007 合并同角色目录时在 survivor 为未完成基线而 donor 为兼容 UIDVALIDITY 已完成基线时保留并提升 donor checkpoint|`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:318-347`|
|t092_code_f004|important|已修|在 \_FOLDER_ROLE 补齐 Gmail "Sent Mail"、"已发邮件" 与 "Bin" 映射并补无 SPECIAL-USE 测试|`src/mail_core/providers/imap.py:240-258`|
|t092_code_f005|important|已修|mutations 严格只从可同步物理容器解析主写回位置，当持久化位置全为 missing/view/selectable=false 时不回退发起 RemoteOperation|`src/mail_core/mail/application/mutations.py:73-102,161-167,208-214,280-328,438-452`|
|t092_code_f006|important|已修|移除 Sidebar.tsx 对 notSelectable 的 role === 'other' 限定并同步在 MessageList 头部统计过滤 selectable !== false|`src/frontend/src/components/Sidebar.tsx:293`, `src/frontend/src/components/MessageList.tsx:211,238`|
|t092_code_f007|minor|已修|find_system_rebind_pairs 优先独立归桶本次失活的 active 行，避免历史 missing 行阻断 Gmail 1-to-1 重绑定|`src/mail_core/sync/folder_rebind.py:42-67`|
|t092_code_f008|minor|已修|预建 \_FOLDER_ROLE_LOWER 并提取 \_strip_gmail_prefix 降低 \_match_known_folder_role 复杂度，抽取 folder_sync_skip_reason 消除三处同步守卫重复|`src/mail_core/providers/imap.py:261,781-815`, `src/mail_core/mail/domain/folder_views.py:73-81`, `src/mail_core/sync/engine.py:522`, `src/mail_core/sync/delta.py:382`, `src/mail_core/sync/reconcile.py:171`|

### Round 2 (2026-11-26T18:32:04+08:00)

|finding_id|severity|status|action_summary|fix_ref|
|---|---|---|---|---|
|t092_code_f009|minor|已修|拆分 migration 0007、folder_rebind、engine、mutations 的高分支辅助函数，抽取 `_resolve_batch_writeback_folder_remote` 消除重复主容器解析，全新增/重构函数圈复杂度均降至 15 以下|`src/mail_core/db/alembic/versions/20261126_0007_orthogonal_folder_state_and_dedupe.py:198-445`, `src/mail_core/sync/folder_rebind.py:29-111`, `src/mail_core/sync/engine.py:326-335`, `src/mail_core/mail/application/mutations.py:102-117,447-455`|
|t092_code_f010|minor|已修|从 `mail_sync_and_storage.md` 与决策文档的重绑定角色列举移除 `inbox`，与代码 `REBINDABLE_SYSTEM_ROLES` 保持完全一致|`docs/specs/mail_sync_and_storage.md:21`, `docs/blueprint/decisions/20261126_orthogonal_folder_lifecycle_and_gmail_rebind.md:8`|
|t092_code_f011|minor|已修|`_query_inbox_stats` 与 `Sidebar.tsx` 主容器选择补充 `Folder.selectable` 过滤，并增加不可选 `sent` 分组统计实库测试|`src/mail_core/mail/application/queries.py:556-562`, `src/frontend/src/components/Sidebar.tsx:108`, `tests/mail_core/test_t092_downstream_isolation_and_api.py:63-118`|

### Round 1 (2026-11-26T18:33:46+08:00)

|finding_id|severity|status|action_summary|fix_ref|
|---|---|---|---|---|
|t092_test_f001|important|已修|提交并断言 `req_custom` 与 `req_all_view` 失活收敛（`folder_deleted`）、校验 `FolderPatrolStatus` 存续与增量恢复不重扫，并覆盖容器与 `view` 实库复活及调度分化|`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:324-409`|
|t092_test_f002|important|已修|为 `test_primary_location.py` 增加 SQL 编译谓词断言，并在实库覆盖 `_resolve_imap_trash_folder`/`trash_message`/`unified_inbox(folder_role=...)`/跨优先级回退与 HTTP `/folder-stats` 契约|`tests/mail_core/test_primary_location.py:48-55`, `tests/mail_core/test_t092_downstream_isolation_and_api.py:42-199`|
|t092_test_f003|minor|已修|为 `test_domain_sync_statuses.py` 改用 10 角色全集合相等断言，补充 `ImapProvider`->DB 集成用例、全部 Gmail 无标志系统夹及 `\\Important` 覆盖自定义名称用例|`tests/mail_core/test_domain_sync_statuses.py:18-30`, `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:54-162`|
|t092_test_f004|minor|已修|为 `Sidebar.test.tsx` 补齐 `kind`/`selectable` 夹具及带关键词 `role='other'` 负例，为 `stubApi.ts` 与 `sidebar_tree.spec.ts` 增加 Gmail 扁平化、不可选禁点及同角色多活跃目录 E2E 断言|`src/frontend/src/components/Sidebar.test.tsx:180-202,1419-1445`, `tests/e2e/stubApi.ts:114-124,517-531`, `tests/e2e/sidebar_tree.spec.ts:628-669`|
|t092_test_f005|minor|已修|清理未使用导入与 `# type: ignore`、拆分为两份单文件 \<410 行的测试套件，并补充 `0007` `FolderPatrolStatus` 迁移、非 Gmail 隔离及降级 `sync_status` 回填断言|`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:165-320`, `tests/mail_core/test_t092_downstream_isolation_and_api.py:1-199`|

### Round 3 (2026-11-26T19:28:15+08:00)

|finding_id|severity|status|action_summary|fix_ref|
|---|---|---|---|---|
|t092_code_f012|minor|遗留|清理 `sync/engine.py:29` 与 `sync/patrol.py:29` 重构残留未用导入；因零行为影响且为保持已验 `review_scope` 不可变性，登记至独立微清理条目|p101|

### Round 2 (2026-11-26T19:26:50+08:00)

Round 2 (`review_test.md`) 零 finding，全部 Round 1 finding 已验证消除。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：后端全量 PostgreSQL 套 `./scripts/run-mail-core-tests.sh run` 2282 passed, 2 skipped（coverage 86%）；前端 Vitest 56 files / 599 passed + `openapi:check` + `css:check`（9 + 2 node tests），`tsc -b`、`vite build` 与 `oxlint --deny-warnings`（121 files, 0 warnings, 0 errors）通过；桌面端 `npm test` 12 项脚本通过；模板契约 `.repo_template/tests` 389 passed, 1 skipped；`export_openapi.py --check`（46 paths）、`check_doc_sensitive.py`（36 files）、`check_dep_locks.py --check` 与 `git diff --check` 全通过。
- 黑盒：全量 Playwright E2E `npm --prefix src/frontend run test:e2e` 26 passed（含 `sidebar_tree.spec.ts` 新增 Gmail `[Gmail]` 扁平化、不可选目录禁点无未知角标与同角色多活跃目录消歧用例）。
- review：Code Review Round 3 `verdict: PASS`（`reviewed_scope: 359e82c02f56729d`，Round 2 3 项全已修，1 项非阻断 minor `t092_code_f012` 转 `p101`）；Test Review Round 2 `verdict: PASS`（`reviewed_scope: 359e82c02f56729d`，Round 1 5 项全消除，0 新 finding）。AC-001~AC-006 全部 `TICK-VALID`。
- AC 判定：见 `task.md` 行内打勾

### 结果摘要

- 废除过载 `folders.sync_status`，以正交列 `kind`（`container` / `view`）、`selectable`（布尔）与 `remote_state`（`active` / `missing`）落地 `Folder` 模型及基线，并提供可逆 Alembic 迁移 `20261126_0007` 洗净历史 Gmail Important `role='other'` 误值与双语重复系统目录（保留消息归属、重写路径、合并冲突并提升兼容已完成检查点与巡检基线）。
- 补齐 `FolderRole.FLAGGED` / `IMPORTANT`，统一 IMAP `\Important` 与剥离 `[Gmail]/` 前缀后的标准角色识别、`folder_views` 隔离判定、1-to-1 系统目录重绑定原子合并、`container`/`view` 消失（`folder_deleted`）与复活调度，以及统计/查询/写回/标签回填全下游活跃与可选过滤；同步升级 OpenAPI / TS 契约并移除前端 `Sidebar` 关键词启发式猜测。
- 遗留：`p101`（非阻断 minor 死导入 `t092_code_f012` 与 `docs/specs/account_connection.md:31` 过时描述同步）。

### 长期文档闭环

- `docs/specs/mail_sync_and_storage.md`（已于 front matter `tasks` 清单登记 `t092`，无需额外 `not_applicable`）；同步更新 `docs/blueprint/architecture.md`、`docs/blueprint/domain.md`、`docs/blueprint/conventions.md` 与 `docs/blueprint/decisions/20261126_orthogonal_folder_lifecycle_and_gmail_rebind.md`。
