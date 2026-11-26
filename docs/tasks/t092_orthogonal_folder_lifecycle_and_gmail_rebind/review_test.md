# Task review t092（reviewer_focus: 测试）

- task：`t092_orthogonal_folder_lifecycle_and_gmail_rebind`
- spec：`docs/tasks/t092_orthogonal_folder_lifecycle_and_gmail_rebind/task.md`
- diff_anchor：`71585e7b130e65f9d00fa5f5948692b0b52901ef`
- target：`git diff 71585e7b130e65f9d00fa5f5948692b0b52901ef`
- round：1
- reviewed_at：2026-11-26T18:33:46+08:00

## Findings

### t092_test_f001 - AC-003 关键路径未测：开放同步目标 `folder_deleted` 事务未提交且未断言，`view` 消失收敛、不重扫与实库复活均无有效覆盖

- 严重度：important
- 锚点：违反 `AC-003`（「原地重绑定并原子合并既有消息位置、检查点与巡检基线，不产生双份重复系统目录也不触发全量重扫；对确认不再存在于服务端的目录统一覆盖 `container` 与 `view` 将其收敛为 `remote_state='missing'` 并失败收敛开放同步目标（`folder_deleted`），后续服务端重新出现时恢复为 `active` 并按需恢复调度」）
- 位置：`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:458-494`、`tests/mail_core/test_a320_folder_pause_revival.py:68-137`
- 问题：
    1. **开放同步目标 `folder_deleted` 实为死代码未测**：`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:458-466` 调用 `req_custom, _ = create_sync_request(Session(), ...)`；由于 `create_sync_request` 内部仅执行 `session.flush()` 而不调用 `commit()`（见 `src/mail_core/mail/application/sync_requests.py:515`），直接传入临时 `Session()` 且未在 `with` 块内提交导致该同步请求在会话对象销毁时直接回滚，且变量 `req_custom` 在全测试文件中再未被查询或断言。全仓库 `tests/` 目录下没有任何测试校验 `SyncRequestTarget.state == "failed"` 与 `error_code == "folder_deleted"`。
    2. **`kind='view'` 消失收敛与复活完全无测试**：`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:468` 注释写明 `# Language switched to English & CustomTemp deleted; also drop CustomView simulation next`，但 `en_catalog`（369-375 行）保留了全部视图目录（`[Gmail]/All Mail` 与 `[Gmail]/Important`），全测试套件中没有任何用例覆盖 `kind='view'` 从远端消失后置为 `remote_state='missing'`、失败收敛其开放同步目标以及重新出现后恢复为 `active`。
    3. **不触发全量重扫、巡检基线保留与实库复活恢复调度缺覆盖**：470-483 行切换语言重绑定后仅校验了 `SyncCheckpoint.full_scan_complete is True`，未查验 `WorkerJob` 是否仅入队 `sync_folder_delta` 而未触发 `sync_folder_metadata` 全量重扫；`test_ac001` 与 `test_ac003_ac004` 均未构造或断言 `FolderPatrolStatus`（巡检基线）在合并与重绑定后的留存；`CustomTemp` 消失后也未在真实 PostgreSQL 中再次出现以验证恢复 `active` 并按需恢复调度（`tests/mail_core/test_a320_folder_pause_revival.py:68-137` 使用内存 `_Harness` 假会话并 `monkeypatch` 掉 `fail_open_targets` 与 `enqueue_job`，未覆盖实库与 `view`）。
- 建议：在 `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py` 中通过 `with Session() as session:` 提交针对待删除 `container` 与 `view` 的开放同步请求，在 `sync_account_folders` 后真实查询 `SyncRequestTarget` / `SyncRequest` 断言 `state == "failed"` 与 `error_code == "folder_deleted"`；补全 `view` 消失收敛与复活、重绑定后 `WorkerJob` 仅入队 delta（无 metadata 全扫）、`FolderPatrolStatus` 留存及消失目录重现后恢复 `active` 并恢复调度的实库断言。

### t092_test_f002 - AC-004 关键 SQL 过滤存在 `MagicMock` 绕过与缺失目录查询/回退覆盖盲区

- 严重度：important
- 锚点：违反 `AC-004`（「按角色收件箱查询及出站写回主位置解析严格仅纳入 `remote_state='active'`（写回/同步且要求 `kind='container'` 与 `selectable=true`），不因失效历史目录存在而暴露重名条目、毒化聚合计数或向已消失远端目录发起写回」）及危险模式「mock 误用」
- 位置：`tests/mail_core/test_primary_location.py:37-62`、`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:23,530-601`
- 问题：
    1. **`_resolve_imap_trash_folder` 仅由 `MagicMock` 覆盖，真实 SQL 过滤未触达**：`tests/mail_core/test_primary_location.py:45-62` 本轮将夹具更新为 `selectable=True, remote_state="active"`，但仍通过 `mock_session = MagicMock()` 预设 `mock_session.scalars.return_value.all.return_value`，完全绕过了生产代码 `_resolve_imap_trash_folder`（`src/mail_core/mail/application/mutations.py:249-254`）改用的 `*syncable_folder_clauses()` SQL 过滤；同时 `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:23` 虽然导入了 `_resolve_imap_trash_folder` 却从未调用（599 行 `trash_message(session, ghost_only.id)` 因无任何可同步主位置提前返回 `operation_id=None` 也未触达该分支）。若生产代码在 `_resolve_imap_trash_folder` 漏掉 `remote_state='active'` 或 `selectable=True`，当账号并存历史 `missing` 废纸篓与当前活跃废纸篓时 `trash_message` 将因 `multiple ambiguous trash folders` 报错，现有测试无法检出。
    2. **按角色收件箱查询与写回主位置跨优先级回退未覆盖 `missing`/`selectable=false`**：全测试套件没有任何用例在存在 `remote_state='missing'`（或 `selectable=false`）同名角色目录时调用 `unified_inbox(..., folder_role=...)`（`src/mail_core/mail/application/queries.py:399`）、`mark_all_messages_read(..., folder_role=...)`（`src/mail_core/mail/application/mutations.py:367`）或校验消息列表中 `locations` 排除 `missing` 目录；也未验证同时位于较高优先级 `missing` `INBOX` 与较低优先级 `active` `Other`/`Archive` 容器的邮件在 `set_message_read` / `set_message_flagged` / `trash_message` / `mark_all_messages_read` 时跳过失效 `INBOX` 而选择活跃容器写回。
- 建议：在 `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py` 补充真实 PostgreSQL 集成用例：(1) 同一 IMAP 账号并存 `missing`/`selectable=false`/`view` 的 `role='trash'` 与唯一 `active, selectable=true, container` 的 `role='trash'` 时，`_resolve_imap_trash_folder` 与 `trash_message` 准确解析活跃废纸篓；(2) 仅位于 `missing` 目录（未在活跃目录）的邮件不会出现在 `unified_inbox(..., folder_role="inbox")`、消息 `locations` 投影及 `mark_all_messages_read(..., folder_role="inbox")` 中；(3) 同时位于 `missing` `INBOX` 与 `active` `Archive`/`Other` 的邮件写回准确选用后者作为 `folder_remote_id`。

### t092_test_f003 - AC-002 缺少 `ImapProvider` 入库全链路与部分 Gmail 无标志系统夹回退/优先级用例

- 严重度：minor
- 锚点：`AC-002` 覆盖扩展建议
- 位置：`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:65-106,378-383`、`tests/mail_core/test_domain_sync_statuses.py:19`
- 问题：`test_ac002_folder_role_enum_and_imap_important_and_prefix_mapping` 仅在内存级别校验 `ImapProvider.list_folder_catalog()`（91 行使用 `# type: ignore[method-assign]` 覆盖实例私有方法 `_connect_with_permit`，经核查仅用于替换外部 IMAP 连接边界，未掩盖被测解析逻辑，但可通过 `monkeypatch.setattr` 消除抑制注解），而 `test_ac003_ac004` 在 `build_provider` 直接注入硬编码好 `role` 的 `RemoteFolder` 列表，未串联 `ImapProvider.list_folder_catalog()` → `sync_account_folders` → PostgreSQL `Folder.role`；同时未覆盖无 SPECIAL-USE 标志时的 `[Gmail]/Drafts` / `[Gmail]/草稿` / `[Gmail]/Spam` / `[Gmail]/垃圾邮件` / `[Gmail]/Starred` / `[Gmail]/已加星标` 名称回退与 `\Important` 等 SPECIAL-USE 标志覆盖自定义名称的优先级。另 `tests/mail_core/test_domain_sync_statuses.py:19` 仅用 `issubset` 校验 `FolderRole`。
- 建议：补充通过真实 `ImapProvider`（用 `monkeypatch.setattr` 替掉 `_connect_with_permit`）经 `sync_account_folders` 落库验证 `Folder.role` 的测试，并补全无标志系统夹名称回退、SPECIAL-USE 优先级断言及 `FolderRole` 全量枚举集合精确断言。

### t092_test_f004 - AC-005 契约覆盖边界：Playwright E2E/`stubApi.ts` 未同步 `kind`/`selectable` 及侧栏关键词负例缺失

- 严重度：minor
- 锚点：`AC-005` 与 `task.md`「测试策略」覆盖扩展建议
- 位置：`tests/e2e/stubApi.ts:114-122,515-529`、`tests/e2e/sidebar_tree.spec.ts:30-56`、`src/frontend/src/components/Sidebar.test.tsx:180-202,1413-1448`、`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:503-510`
- 问题：
    1. `tests/e2e/stubApi.ts` 中的 `StubFolder` 接口及默认 `/folder-stats` 响应尚未补齐 `kind` 与 `selectable`（未对齐 `AccountFolderStatsItemOut` 契约），且 `tests/e2e/sidebar_tree.spec.ts` 未按 `task.md` 测试策略追加 Playwright E2E 用例覆盖 `selectable=false` 节点禁点、Gmail `[Gmail]` 扁平化与真实多活跃同名目录消歧（上述场景目前由 Vitest `Sidebar.test.tsx` 覆盖）。
    2. `Sidebar.test.tsx:1413-1448` 未包含如 `[Gmail]/重要客户` / `Sent Backup` 等携带系统关键词的 `role='other'` 目录负例，以直观证明前端已移除关键词猜角色兜底；`Sidebar.test.tsx:180-202` 部分旧测试夹具仍省略 `kind`/`selectable`。
    3. 后端 `test_t092_orthogonal_folder_lifecycle.py:503-510` 仅调用 `list_folder_stats_for_account` 应用层函数，未通过 `TestClient` 对 `GET /api/mail/accounts/{id}/folder-stats` HTTP 响应 JSON 显式断言无 `sync_status` 及 `selectable=false` 计数为 `null`。
- 建议：补齐 `tests/e2e/stubApi.ts` 的 `kind`/`selectable` 字段并在 `tests/e2e/sidebar_tree.spec.ts` 增加侧栏正交状态与 Gmail 扁平化 E2E 校验；在 `Sidebar.test.tsx` 增加含系统关键词的 `role='other'` 负例并同步旧夹具字段；补充一条 HTTP `/folder-stats` 契约断言。

### t092_test_f005 - 新增测试存在多处未使用导入，且 `test_ac001` 缺降级回填与非 Gmail 隔离边界校验

- 严重度：minor
- 锚点：测试代码整洁性与 `AC-001` 边界扩展建议
- 位置：`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:7,23,33,45,47,332-338`
- 问题：`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py` 顶部导入的 `datetime`、`timezone`（7 行）、`_resolve_imap_trash_folder`（23 行）、`resolve_sync_targets`（33 行）、`MetadataPage`、`RemoteMessageMeta`（45 行）、`acquire_lease`、`apply_metadata_page`（47 行）均未使用；此外 `test_ac001_migration_0007_replaces_sync_status_and_coalesces_duplicates`（332-338 行）在 `downgrade("20261125_0006")` 后未断言 `sync_status` 回填值（如 `selectable=False` / `missing` 容器回填为 `'paused'`），也未构造非 Gmail 账号下两条同 `role` 自定义目录验证 `0007` 不误合并与 `folder_patrol_status` 留存。
- 建议：清理冗余导入（或在补齐 `AC-003`/`AC-004` 用例时实际调用对应接口），并在 `test_ac001` 补充 `downgrade` 回填值、非 Gmail 同角色多目录不误合并及 `folder_patrol_status` 迁移留存断言。

## 结论

- 改测方向复核：无「迁就实现」的改测。逐项核实全部 27 个被修改测试文件：
    - `tests/mail_core/test_domain_sync_statuses.py`：因规范要求破坏性移除 `SyncStatus` 与 `Folder.sync_status`，删除旧 `SyncStatus` 断言并重写为校验 `SyncStatus` 不存在及 `FolderRemoteState` / `FolderRole` 新枚举，属合法语义退役。
    - `tests/mail_core/test_a320_folder_pause_revival.py`：因「不可选」与「远端消失」正交解耦，将 `SyncStatus.PAUSED/IDLE` 迁移为 `FolderRemoteState.MISSING/ACTIVE` 与 `selectable is False`，并完整保留 `assert harness.enqueued == []` 不排发同步作业核心意图及 `# t092:` 注记，非迁就弱化。
    - `tests/mail_core/test_gmail_label_views.py`：`0004` 迁移幂等测试因 `0007` 删除了 `folders.sync_status` 而在现行 `head` 库无法运行，遂改为在隔离 PostgreSQL 临时库升至 `20261123_0004` 原位执行并完整保留原全部断言，其余用例机械替换 `remote_state="active"`，属合法隔离保真。
    - `tests/mail_core/test_t090_migration_0006.py`：因 Alembic `head` 推进至 `20261126_0007`，将 `0005 <-> 0006` 边界往返测试固定升级至 `20261125_0006` 并保持全部 `0006` 列/约束/回填断言不变，合法。
    - `tests/mail_core/test_sync_retry_queue.py`：将 `\Noselect` 与远端消失断言同步更新为正交字段 `selectable is False, remote_state == "active"` 与 `remote_state == "missing"`，原有消息/检查点/Outbox/`WorkerJob` 去重断言全部保留，合法。
    - `tests/mail_core/test_primary_location.py` 及其他 18 个后端测试文件：仅将已移除的 `Folder.sync_status` / `SyncStatus` 夹具字段机械替换为 `remote_state` / `selectable`（`test_primary_location.py` 自身的 `MagicMock` 绕过问题另以 `t092_test_f002` 立项）。
    - `src/frontend/src/components/Sidebar.test.tsx` 与 `src/frontend/src/components/MessageList.test.tsx`：将旧 `sync_status` 夹具更新为 `kind` / `selectable` 并保留原交互、缩进、禁用与徽标断言，同时新增 `t092` 英文 Gmail 与非 `other` 角色 `selectable=false` 测试，合法。
- 本轮新发现：5 条（critical 0、important 2、minor 3）
- 未进表的提示：
    - **测试文件规模提示（达到阈值且本 task 净增）**：`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py`（602 行，新建，≥600）、`src/frontend/src/components/Sidebar.test.tsx`（1449 行，净增 +21，≥1200）、`src/frontend/src/components/MessageList.test.tsx`（1319 行，净增 +19，≥1200）、`tests/mail_core/test_t061_status_patrol.py`（735 行，净增 +1，≥600）；`tests/mail_core/test_t061_idle_watcher.py`（1433 行，+7/-7 无净增）。
    - **独立复跑实测结果**：
        - 前端门禁：`(cd src/frontend && npm test && npx tsc -b && npm run build && npm run lint)` 通过（Vitest 56 文件 599 passed、`openapi:check` 通过、`css:check` 通过、`tsc -b` 无错误、`vite build` 成功、`oxlint` 0 warnings）；Playwright 快速 E2E `npm --prefix src/frontend run test:e2e` 25 passed；OpenAPI `scripts/export_openapi.py --check` 通过；文档扫描 `scripts/check_doc_sensitive.py docs --check` 通过（36 文件 0 违规）；模板契约 `pytest .repo_template/tests -q -m contract` 389 passed, 1 skipped；桌面单测 `(cd src/desktop && npm test)` 12 项通过（`oauth_integration` 与 `postgresManager` 实启停按设计 skip）。
        - 真实 PostgreSQL 定向套件：`scripts/run-mail-core-tests.sh run -k "test_t092 or test_gmail_label_views or test_a320_folder_pause_revival or test_t090_migration_0006 or test_sync_retry_queue or test_primary_location or test_domain_sync_statuses"` 30 passed（2250 deselected）；补充 `scripts/run-mail-core-tests.sh run -k "test_migration_validation or test_gmail_label_backfill or test_openapi_contract or test_folder_role_inbox_api or test_fts_inbox_api"` 32 passed（2248 deselected）；两轮均已执行 `session-end` 清理。
- 总体判断：存在 2 个 `important` 测试阻断缺陷（`AC-003` 的 `folder_deleted` 目标收敛因未提交事务与未断言沦为死设置且缺少 `view` 消失/复活与不重扫校验；`AC-004` 的 `_resolve_imap_trash_folder` 仅被 `MagicMock` 覆盖且缺少按角色收件箱查询与写回优先级回退测试），判定不通过。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。独立复跑真实 PostgreSQL 迁移测试 `test_ac001_migration_0007_replaces_sync_status_and_coalesces_duplicates`（所在定向套件 30 passed）与 `test_migration_validation`（所在定向套件 32 passed，含零漂移与升降级循环）全部通过，核实列结构、双语去重合并、消息路径重写、检查点提升与未知未读统计均获实库断言支撑。
- AC-002：TICK-VALID，re_verified。独立复跑 `test_ac002_folder_role_enum_and_imap_important_and_prefix_mapping` 与 `test_folder_role_and_remote_state_enums` 均通过，核实 `FolderRole` 含 `flagged`/`important`、`\Important` 与 `[Gmail]/` 前缀剥离及中英文重要/已发/Bin 与防误判用例有真实断言支撑。
- AC-003：TICK-VOID，re_verified。核查与复跑 `test_t092_orthogonal_folder_lifecycle.py` 及 `test_a320_folder_pause_revival.py` 发现：`req_custom` 开放同步请求未提交事务且从不断言（全库零 `folder_deleted` 断言）、`kind='view'` 消失收敛与复活完全未测、重绑定后不入队 `SYNC_FOLDER_METADATA` 与巡检基线及实库复活恢复调度均无有效校验（`t092_test_f001`）。
- AC-004：TICK-VOID，re_verified。核查与复跑 `test_t092_orthogonal_folder_lifecycle.py`、`test_primary_location.py`、`test_gmail_label_views.py` 与 `test_gmail_label_backfill.py` 确认 Important 视图与 `folder-stats`/`global_stats` 隔离已测，但 `_resolve_imap_trash_folder` 仍用 `MagicMock` 绕过真实 SQL 过滤（且在 `test_t092` 仅导入未调用），且 `unified_inbox(folder_role=...)` / 跨优先级 `missing` 回退均缺实库测试（`t092_test_f002`）。
- AC-005：TICK-VALID，re_verified。独立复跑 `export_openapi.py --check`、`openapi:check`、`tsc -b`、Vitest（56 文件 599 passed，含 `Sidebar.test.tsx` 与 `MessageList.test.tsx` 新增 `t092` 用例）与 `test_openapi_contract` 全部通过，核实 OpenAPI/TS 类型移除 `sync_status` 及侧栏 `selectable=false` 禁点、去 `-`、`[Gmail]` 扁平化与消歧均有真实断言。
- AC-006：TICK-VALID，trust_prior。独立复验 `docs/specs/mail_sync_and_storage.md` 与 `docs/blueprint/` 及决策文档更新、敏感扫描（36 文件 0 违规）、模板契约（389 passed, 1 skipped）、前端构建/单测/lint/E2E 冒烟（25 passed）、桌面单测与 62 项真实 PostgreSQL 定向测试均通过；其余约 2218 项非本次定向筛选的后端 PostgreSQL 套件及打包/全栈 E2E 未在本轮重跑，采信实施方在 `progress.md:31` 记录的全量门禁先验结果。

coverage = 5 / 6

reviewed_scope: d0f96daec29a5ebd

verdict: FAIL

## Round 2 (2026-11-26T19:26:50+08:00)

- diff_anchor：`71585e7b130e65f9d00fa5f5948692b0b52901ef`
- target：`git diff 71585e7b130e65f9d00fa5f5948692b0b52901ef`
- round：2
- reviewed_at：2026-11-26T19:26:50+08:00

### 前轮 Finding 复核

- `t092_test_f001`（important）：**已消除**。`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:378-490` 已改为在 `with Session() as session:` 内持久化提交 `req_custom`（`create_sync_request`）与 `req_all_view`（显式 `SyncRequestTarget` 挂在 `kind='view'` 的 `[Gmail]/&YkBnCZCuTvY-`），在 `en_omit_both_catalog` 同时省略 `CustomTemp`（`container`）与 `[Gmail]/&YkBnCZCuTvY-`（`view`）后查询实库确认两者均收敛为 `remote_state == "missing"` 且 `SyncRequestTarget.state == "failed"` / `error_code == "folder_deleted"`（434-465 行）；同时验证 `FolderPatrolStatus` 保留（418, 455 行）、重绑定后仅入队 `SYNC_FOLDER_DELTA` 而未入队 `SYNC_FOLDER_METADATA` 全量重扫（457-460 行）、`Message.remote_id` 与 `RemoteOperation` 路径重写及 `reconcile_folder(..., sent_id)["deleted"] == 0`（467-474 行），并在 `revived_catalog` 重现两类目录后校验实库恢复 `remote_state == "active"` 且仅容器入队 `SYNC_FOLDER_METADATA`、视图不排发作业（480-490 行）。
- `t092_test_f002`（important）：**已消除**。`tests/mail_core/test_t092_downstream_isolation_and_api.py:141-170` 新增真实 PostgreSQL 集成用例 `test_ac004_resolve_imap_trash_folder_and_trash_message_real_pg`，并存 `missing`、`selectable=False`、`kind='view'` 与唯一可同步 `Deleted` 废纸篓验证 `_resolve_imap_trash_folder` 与 `trash_message` 精确选中活跃容器且失效后抛 `UnaddressableMessageError`（`tests/mail_core/test_primary_location.py:52-55` 同步补充了 SQL 编译谓词断言）；`tests/mail_core/test_t092_downstream_isolation_and_api.py:48-138` 覆盖 `unified_inbox(..., folder_role="inbox")` 及 `locations` 过滤 `missing`、分组/全局统计排除 `missing` 与 `selectable=False`（`f_sent_nosel`）、四条写回路径对仅 `missing`/`view` 邮件不入队 `RemoteOperation`、`mark_all_messages_read(..., folder_role="inbox")` 及 `INBOX` 失活后跨优先级回退 `Archive`。
- `t092_test_f003`（minor）：**已消除**。`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:57-165` 已移除 `# type: ignore[method-assign]` 改用 `monkeypatch.setattr(provider, "_connect_with_permit", ...)`，补齐中英文无标志 Gmail 系统夹名称回退（`Drafts`/`草稿`、`Spam`/`垃圾邮件`、`Starred`/`已加星标`、`Sent Mail`/`已发邮件`、`Bin`）、`\Important` 覆盖自定义名称及防误判负例，并新增 `test_ac002_imap_catalog_persists_roles_and_orthogonal_fields` 串联真实 `ImapProvider` → `sync_account_folders` → PostgreSQL 落库；`tests/mail_core/test_domain_sync_statuses.py:18-30` 已改为 10 角色精确集合相等断言。
- `t092_test_f004`（minor）：**已消除**。`tests/e2e/stubApi.ts:114-124,518,530` 已补全 `StubFolder` 与默认 `/folder-stats` 的 `kind`/`selectable`；`tests/e2e/sidebar_tree.spec.ts:628-670` 新增 Playwright E2E 用例覆盖 `[Gmail]` 扁平化、`ArchiveParent`（`role='archive', selectable=false`）禁点与无 `.unread-badge-unknown`、以及多活跃同角色消歧（`收件箱 · INBOX` / `收件箱 · AltInbox`）；`src/frontend/src/components/Sidebar.test.tsx:180-202,1413-1454` 已补齐旧夹具字段、关键词 `role='other'` 负例（`[Gmail]/重要客户`、`Sent Backup`）与非 `other` 不可选角色校验；`tests/mail_core/test_t092_downstream_isolation_and_api.py:173-205` 新增 `TestClient` HTTP `/folder-stats` 契约与计数校验。
- `t092_test_f005`（minor）：**已消除**。新增测试拆分为 `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py`（490 行）与 `tests/mail_core/test_t092_downstream_isolation_and_api.py`（205 行），AST 检查无任何未使用导入；`test_ac001_migration_0007_replaces_sync_status_and_coalesces_duplicates`（`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:168-374`）已补充 `folder_patrol_status` 迁移留存（335-336 行）、`is_read IS NULL` 目录统计保持 `unread_count is None`（340-341 行）、非 Gmail 账号同 `role` 自定义目录 `NonGmailA`/`NonGmailB` 不误合并（347 行）、非法 `remote_state='paused'` 约束拒绝（349-351 行）及 `downgrade("20261125_0006")` `sync_status` 回填值校验（353-367 行）。

### Findings

本轮零 finding。

### 结论

- 前轮 finding 复核：`t092_test_f001`（important）、`t092_test_f002`（important）、`t092_test_f003`（minor）、`t092_test_f004`（minor）、`t092_test_f005`（minor）共 5 条均已在测试代码与实库/前端/E2E 验证中彻底消除。
- 改测方向复核：无「迁就实现」的改测。`test_domain_sync_statuses.py`、`test_a320_folder_pause_revival.py`、`test_gmail_label_views.py`、`test_t090_migration_0006.py`、`test_sync_retry_queue.py`、`test_primary_location.py`、`Sidebar.test.tsx`、`MessageList.test.tsx` 与其余 19 份机械更新夹具字段的后端测试均按新正交契约或隔离历史 revision 保真语义修改，全部危险模式扫描（恒真断言、弱化断言、删 expect、`.skip`/`.only`、`# type: ignore`/`@ts-ignore`/`eslint-disable`、mock 绕过核心逻辑）均无命中。
- 本轮新发现：0 条
- 未进表的提示：
    - **测试文件规模提示（达到阈值且本 task 净增）**：`src/frontend/src/components/Sidebar.test.tsx`（1455 行，净增 +27，≥1200）、`src/frontend/src/components/MessageList.test.tsx`（1319 行，净增 +19，≥1200）、`tests/mail_core/test_t061_status_patrol.py`（735 行，净增 +1，≥600）；新建的两份 `t092` 测试文件分别控制在 490 行与 205 行（均 \<600），`tests/mail_core/test_t061_idle_watcher.py`（1433 行）无净增。
    - **可选覆盖与既有测试整洁度提示**：`src/mail_core/sync/folder_rebind.py:138-253` `_merge_duplicate_message_rows` 的运行时重绑定目标 `remote_id` 碰撞合并分支目前由迁移 `0007` 碰撞合并用例间接验证对应 SQL 语义，后续可补充一条运行时 `sync_account_folders` 冲突消息合并用例；另 `test_delta_archive_integration.py`、`test_gmail_sync_strategy_and_timeout.py`、`test_sync_background_lineage.py`、`test_t091_structured_failure_and_diagnostics.py` 存在既有未用导入（均非本 task 引入）。
    - **独立复跑实测结果**：
        - 真实 PostgreSQL 定向套件 1（`./scripts/run-mail-core-tests.sh run -k "test_t092 or test_domain_sync_statuses or test_primary_location or test_gmail_label"`）：`25 passed, 2259 deselected`（35.30s），`session-end` 正常回收。
        - 真实 PostgreSQL 定向套件 2（`./scripts/run-mail-core-tests.sh run -k "test_migration_validation or test_a320_folder_pause_revival or test_t090_migration_0006 or test_sync_retry_queue or test_openapi_contract or test_folder_role_inbox_api or test_sync_requests_paused_folder"`）：`41 passed, 2243 deselected`（60.58s），`session-end` 正常回收。
        - 前端与契约门禁：`Sidebar.test.tsx` 单跑 1 文件 `52 passed`（5.55s）；全量 `(cd src/frontend && npm run openapi:check && npx tsc -b && npm run lint && npm test && npm run build)` 通过（Vitest 56 文件 `599 passed`、`css:check` 9+2 通过、`oxlint` 0 warnings 0 errors、`vite build` 152ms）；`scripts/export_openapi.py --check` 通过（46 paths）。
        - Playwright E2E：`sidebar_tree.spec.ts` 单跑 `12 passed`（16.5s）；全量 `npm --prefix src/frontend run test:e2e` `26 passed`（33.6s）。
        - 桌面/文档/模板门禁：`(cd src/desktop && npm test)` 12 项通过（`postgresManager` 实库启停与 `oauth_integration` 按设计 skip）；`scripts/check_doc_sensitive.py docs --check` 36 文件 0 违规；`pytest .repo_template/tests -q -m contract` `389 passed, 1 skipped`（30.89s）。
- 总体判断：Round 1 全部 5 条 finding（含 2 条 `important` 阻断项）均已在测试代码中真实修复并通过独立实库、前端与 E2E 复跑验证，全部 6 条 AC 均获可靠测试/门禁支撑，判定通过。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。独立复跑真实 PostgreSQL 用例 `test_ac001_migration_0007_replaces_sync_status_and_coalesces_duplicates` 与 `test_migration_validation`（分别所在定向套件 `25 passed` 与 `41 passed`）全部通过，核实 `0007` 升降级循环、ORM 零漂移、Important `role` 修正、双语去重与 `Message.remote_id`/`RemoteOperation`/`SyncCheckpoint`/`FolderPatrolStatus`/`FolderStats` 保留重算及非 Gmail 隔离均获实库断言支撑。
- AC-002：TICK-VALID，re_verified。独立复跑 `test_ac002_folder_role_enum_and_imap_important_and_prefix_mapping`、`test_ac002_imap_catalog_persists_roles_and_orthogonal_fields` 与 `test_folder_role_and_remote_state_enums` 全部通过，核实 10 角色枚举、`\Important` 与 `[Gmail]/` 前缀剥离、全量中英文无标志 Gmail 系统夹、SPECIAL-USE 优先级及经 `sync_account_folders` 落库全链路均获真实断言支撑。
- AC-003：TICK-VALID，re_verified。独立复跑真实 PostgreSQL 用例 `test_ac003_rebind_patrol_delta_view_disappearance_and_revive` 及 `test_sync_retry_queue`/`test_a320_folder_pause_revival` 全部通过，核实 1-to-1 重绑定、保留巡检基线与不重扫（delta 入队且无 metadata 全扫）、`Message.remote_id`/`RemoteOperation` 重写与对账不误删、`container`/`view` 消失收敛（`missing` + `folder_deleted`）及实库复活恢复调度均获真实断言支撑。
- AC-004：TICK-VALID，re_verified。独立复跑 `test_t092_downstream_isolation_and_api.py`、`test_gmail_label_views.py`、`test_gmail_label_backfill.py`、`test_primary_location.py` 与 `test_folder_role_inbox_api` 全部通过，核实 `\Important` 视图隔离、统计/收件箱查询/位置投影过滤 `active` 与 `selectable`、四条出站写回路径防退化与跨优先级回退及实库 `_resolve_imap_trash_folder`/`trash_message` 均获真实断言支撑。
- AC-005：TICK-VALID，re_verified。独立复跑 `export_openapi.py --check`、`openapi:check`、`test_openapi_contract`、`test_ac004_http_folder_stats_schema_excludes_sync_status`、`tsc -b`、Vitest（56 文件 `599 passed`，含 `Sidebar.test.tsx` 52 项与 `MessageList.test.tsx` 50 项）及 Playwright `sidebar_tree.spec.ts`（`12 passed`）全部通过，核实前后端移除 `sync_status`、`selectable=false` 禁点且无 `-`、去启发式猜角色、`[Gmail]` 扁平化与多活跃目录消歧均获真实断言支撑。
- AC-006：TICK-VALID，trust_prior。独立复验 `docs/specs/mail_sync_and_storage.md`、`docs/blueprint/` 及决策文档更新、敏感扫描（36 文件 0 违规）、模板契约（`389 passed, 1 skipped`）、前端构建/单测/lint/OpenAPI/样式门禁（`599 passed`）、Playwright E2E 全套（`26 passed`）、桌面端单测（12 项通过）与 66 项真实 PostgreSQL 定向测试均通过；其余未纳入本次 `-k` 筛选的约 2218 项后端 PostgreSQL 套件、全栈 E2E 与桌面打包冒烟采信实施方在 `progress.md:32` 记录的全量无过滤门禁先验通过结论。

coverage = 5 / 6

reviewed_scope: 359e82c02f56729d

verdict: PASS
