# p027 账号同步失败时侧栏仅展示虚拟未读入口且单账号缺收件箱将全局未读角标置为横杠

- 现象：
    1. 展开 `[REDACTED_EMAIL]` 账号节点时，下方仅出现一项「未读邮件」，无「收件箱」「已发送」「草稿箱」「废纸篓」「垃圾邮件」等真实目录，且无任何同步失败或空目录提示，造成“126 邮箱只能拿到未读邮件”的假象。
    2. 侧栏顶层「所有收件箱」、`[REDACTED_EMAIL]` 账号行及其下「未读邮件」右侧未读角标均显示为蓝色横杠 `-`。
- 影响：
    1. 任何初始文件夹发现（`sync_account_folders`）失败或尚未落库真实文件夹的账号，在侧栏展开后都只展示前端硬编码的虚拟快捷项「未读邮件」，掩盖账号认证/同步失败真相。
    2. 只要实例或分组内存在任一未落库 `role='inbox'` 文件夹的账号（含登录失败账号及已被 `PermanentAuthError` 设为 `sync_enabled=false` 的失效账号），全局「所有收件箱」与所属分组的未读角标即被传染为 `null`（显示 `-`），31 个正常已同步账号的真实未读汇总完全不可见；同时 `MessageList` 对缺失 `inbox` 的账号按 `0` 计入总数，造成侧栏 `-` 与列表头部邮件总数语义矛盾。
    3. 网易 126/163 密码或授权码错误返回 `LOGIN Login error or password error` 时未被识别为永久认证失败，触发无意义 8 次退避重试且残留 `sync_status='failed'`，后台跟进任务重入队又因丢失 `payload` 触发 `KeyError: 'folder_id'`。
- 根因：
    1. 实例数据/凭据层（环境与配置事实）：`[REDACTED_EMAIL]`（`[REDACTED_UUID]`）在 `imap.126.com:993` 登录时返回 `imaplib.IMAP4.error: LOGIN Login error or password error`（当前保存口令长 13 位，非有效 16 位网易客户端授权码或口令错误），导致 `sync_account_folders` 8 次重试全部失败，数据库 `folders` 与 `messages` 表均为 0 行（并非只拉取了未读邮件）。另有 `[REDACTED_EMAIL]`、`[REDACTED_EMAIL]` 因 `[AUTHENTICATIONFAILED] Login fail` 同样为 0 文件夹。
    2. 前端文件夹树渲染缺陷（产品缺陷，`src/frontend/src/components/Sidebar.tsx:164-236, 649-687`）：
        - `AccountFolders` 请求 `/api/mail/accounts/{id}/folder-stats` 得到 `folders: []`（HTTP 200 空数组）时，仅判断了 `isLoading` 与 `isError || !foldersQuery.data`，未处理 `folders.length === 0`；
        - 组件在 `Sidebar.tsx:226-232` 无条件渲染硬编码虚拟筛选按钮「未读邮件」（切换到 `category: 'unread'`，即 `folder_role=inbox&is_read=false`），而 `renderTree(roots)` 为空，且 `renderAccount`（`Sidebar.tsx:649-687`）未展示 `account.sync_status`（`failed` / `auth_failed`）错误态，导致用户看到账号下仅有「未读邮件」一项。
    3. 未读统计未知值（`-`）计算与聚合传染机制（产品设计/实现耦合，`src/mail_core/mail/application/queries.py:380-442`、`src/frontend/src/components/Sidebar.tsx:93-103, 231, 630, 642, 681, 691-695, 833`）：
        - `query_global_inbox_stats`（`queries.py:401`）与 `query_group_inbox_stats`（`queries.py:434`）按 `unread_count=int(r[3]) if r[1] > 0 and r[1] == r[5] else None` 计算单账号未读数；当账号无 `role='inbox'` 文件夹（`r[1] == 0`，如 126 与两个 QQ 失败账号）时返回 `None`；
        - 聚合逻辑 `total_unread = None if any(account.unread_count is None for account in accounts) else sum(...)`（`queries.py:406, 439`）未排除 `sync_enabled=false` 或 `sync_status in ('failed', 'auth_failed')` 且尚未建出收件箱的故障账号，只要任一账号为 `None`，全局 `total_unread` 即返回 `None`；
        - 前端 `Sidebar.tsx` 将 `unread === null` / `allInboxUnread === null` 渲染为 `<span className="side-count unread-badge unread-badge-unknown">-</span>`，故「所有收件箱」「126 邮箱」及其下「未读邮件」均显示 `-`。
    4. 已确认同类位点清单：
        - `src/frontend/src/components/Sidebar.tsx:691-695, 833`：分组未读统计 `groupUnread` 对组内任一 `count == null` 成员同样传染返回 `null` 并渲染 `-`。
        - `src/frontend/src/components/Sidebar.tsx:642`：「所有收件箱」「所有未读」分类展开后的单账号子行在 `unread === null` 时同样渲染 `-` 且无同步失败提示。
        - `src/frontend/src/components/MessageList.tsx:185-216` vs `src/frontend/src/components/Sidebar.tsx:100-102`：`MessageList` 在单账号或全账号遍历 `/folder-stats` 时，若 `targetFolder`（如 `role='inbox'`）不存在，按 `0` 计算 `accountTotal` / `accountUnread`（`MessageList.tsx:192-193, 209-210`），而分组分支（`MessageList.tsx:178-183`）及 `Sidebar` / `queries.py` 按 `null`（`-` / `—`）处理，跨组件对“账号无目标文件夹”语义不一致。
        - `src/mail_core/providers/imap.py:326-332`：`ImapProvider._connect` 仅匹配 `"basic authentication is disabled"` 与 `"authenticationfailed"` 抛出 `PermanentAuthError`，遗漏网易 126/163 的 `"login error or password error"`，导致永久密码错误被重试 8 次且未标记 `auth_failed`。
        - `src/mail_core/sync/metadata.py:168-201`：`apply_metadata_page` 仅在 `o.location_created` 或 `touched` 非空时调用 `recompute_folder_stats`；空文件夹首次同步完成（`page.items` 为空）时未初始化 `FolderStats` 行，在 `reconcile_folder` 运行前 `list_folder_stats_for_account` 返回 `unread_count: null`（渲染 `-`）。
    5. 扫描中发现的关联后台缺陷（单列待确认是否合并或独立立项）：
        - `src/mail_core/worker/handlers.py:34-42`：`_evaluate_result` 在处理 `followup` / `_followup_needed` 时以硬编码 `payload={}` 重新入队，丢失 `sync_folder_delta` / `sync_folder_metadata` / `reconcile_folder` 必需的 `folder_id`，导致跟进任务全部以 `KeyError: 'folder_id'` 失败（当前库内已累积 212 条失败任务并把 26 个正常账号标为 `sync_status='failed'`）。
- 测试缺口：
    1. `src/frontend/src/components/Sidebar.test.tsx`：仅有文件夹正常返回与请求报错测试，缺少 `folders: []`（空数组）及 `account.sync_status === 'failed' | 'auth_failed'` 时不单独裸露虚拟「未读邮件」误导用户、应展示空/错误状态的组件测试。
    2. `tests/mail_core/test_global_stats.py` 与 `Sidebar.test.tsx`：t039/t041 测试将“缺 `FolderStats` 返回 `null` 并渲染 `-`”作为正向断言，未覆盖“单个认证失败/禁用账号（0 文件夹）不应永久遮蔽其余正常账号收件箱未读汇总”或“Sidebar 与 MessageList 对缺目标文件夹语义一致性”的场景。
    3. `tests/mail_core/test_imap_provider.py`：仅测试了 `[AUTHENTICATIONFAILED]` 与 `Basic authentication is disabled` 映射为 `PermanentAuthError`，未覆盖网易 IMAP 返回 `LOGIN Login error or password error` 的认证失败分类，也未覆盖空文件夹 `apply_metadata_page` 立即生成 `FolderStats(0, 0)`。
- 线索：
    - `.scratch/repro_126_unread_and_hyphen_stats.py`
    - `src/frontend/src/components/Sidebar.tsx:164-236, 629-644, 681, 691-695, 833`
    - `src/frontend/src/components/MessageList.tsx:178-216`
    - `src/mail_core/mail/application/queries.py:380-442`
    - `src/mail_core/providers/imap.py:326-332`
    - `src/mail_core/sync/metadata.py:168-201`
    - `src/mail_core/worker/handlers.py:34-42`
- 处理：t045
