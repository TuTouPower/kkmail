# kkmail 最新审查 (`da57df7`) 切实问题与用户决策全量汇总文档

- **审查输入**：`<local-path>`（解压产物：`review_20261021_064335/`）
- **核验代码基线**：Git commit `da57df74140e0f0c0476c2e21af0cabdb99f094a`
- **核验原则**：严格执行负责人指示——“只要是有修复价值的、只要是真正的问题，不论等级、不论漏洞或缺陷，全部纳入修复；历史审查敏感信息脱敏加横幅；前端收件页增加加载更多；未经明确许可严禁擅自修改代码”。

______________________________________________________________________

## 一、 负责人核心决策记录 (User Directives & Decisions)

1. **缺陷修复准则**：
    - 彻底打破“严重级别”界限，只要属于切实存在的代码逻辑漏洞、并发隐患、类型错误、未脱敏信息、规范冲突或体验断点，**全部纳入修复范围**，杜绝遗留死角。
2. **历史审查敏感信息处置决策**：
    - 采纳“**脱敏打码 + 统一加注失效横幅**”方案：
        - 对 `docs/reviews/` 下全部历史审查报告中的 10 名贡献者真实个人邮箱（PII 隐私泄露）、示例密钥字面量进行全量星号脱敏；
        - 在全部旧审查报告头部统一增加醒目的 `> [!NOTE] SUPERSEDED / HISTORICAL REPORT` 状态横幅，明确注明报告中所列问题在当前最新代码基线（`da57df7`）中已彻底修复，避免外部工具误判。
3. **前端收件箱长列表交互决策**：
    - **收件箱增加“加载更多”**：解除当前前端 100 封邮件的硬编码阻断，通过传递与保存服务端的 `next_cursor` / `next_offset`，在邮件列表底部增加“加载更多”按钮，实现平滑游标翻页，展示“已加载 X 封 / 共 Y 封”。
4. **实施授权红线**：
    - 本文档作为唯一的修复基准，未得到负责人明确指令前，禁止在工作区或任何 worktree 中启动代码修改。

______________________________________________________________________

## 二、 最新审查发现的切实存在且有修复价值的全量问题清单

### 模块一：安全、认证与错误脱敏（8 项）

|编号|目标文件及行号|审阅级别|切实存在的技术实质|确定修复方案|
|:---|:---|:---:|:---|:---|
|**SEC-01**|`mail_core/security/auth.py:273`|**High**|`change_login_password` 调用 `_persist_db_password_hash` 时直接忽略了返回的 `bool`。若数据库故障写入失败，改密悄悄只改了内存并报告成功，重启后新密码丢失。|检查返回值，写库失败时抛出 `AuthConfigError("failed to persist password to database")`，拒绝更新内存缓存和使会话失效。|
|**SEC-02**|`mail_core/security/auth.py:35`|**High**|`_session_epoch` 为进程内内存全局变量，多进程部署不共享，且服务重启后重置为 1，导致此前已废除的旧 Cookie 重新生效。|将 `session_epoch` 持久化存储至 `auth_credentials` 表中，每次校验与改密/登出时基于数据库中的 epoch 判定。|
|**SEC-03**|`mail_core/worker/handlers.py:175`|**High**|任务执行失败写回 `accounts.config` 的 `last_sync_error` 时，直接传递了未脱敏的原始 `str(exc)`，可能将 DSN 密码或 Token 写入数据库。|统一使用 `safe_error(exc)` 脱敏后再持久化。|
|**SEC-04**|`mail_core/mail/application/remote_ops.py:152`|**High**|`mark_remote_operation` 在存储 `last_error` 时仅执行了截断，未调用脱敏函数。|在存入 `op.last_error` 前强制调用 `mail_core.security.redact.redact()`。|
|**SEC-05**|`mail_core/mail/application/remote_ops.py:85`|**High**|连续快速切换操作（如 read True 随后 False）时，若第一次操作处于 `IN_PROGRESS`，新操作未被合并，导致两个请求并发推往远端产生乱序。|对同一 `entity_key`，合并正在处理中的行与待办行，记录单调递增版本号。|
|**SEC-06**|`mail_core/mail/storage/folder_stats.py:24`|**High**|`recompute_folder_stats` 首次为新目录创建 `FolderStats` 时先 get 后 add，并发时触发数据库主键唯一约束冲突，导致标已读/删除接口报 500。|使用 savepoint 嵌套事务捕获 `IntegrityError` 并安全重载已有行。|
|**SEC-07**|`mail_core/sync/leases.py:121`|**High**|`assert_fencing` 读取 `AccountSyncLease` 时未加 `with_for_update()`，在 READ COMMITTED 隔离级别下存在短暂的并发检查与提交竞态。|在读取租约行时显式使用 `with_for_update()` 进行行级锁保护。|
|**SEC-08**|`mail_core/runtime/bootstrap.py:20`|**High**|`_read_or_create` 生成密钥时先检查文件存在再写入，多进程并发启动时可能产生密钥覆盖不一致。|文件打开使用 O_CREAT 或 O_EXCL 标志，遇已存在异常时回退重新读取。|

______________________________________________________________________

### 模块二：协议提供商与归档/存储（6 项）

|编号|目标文件及行号|审阅级别|切实存在的技术实质|确定修复方案|
|:---|:---|:---:|:---|:---|
|**PROV-01**|`mail_core/providers/imap.py:190, 534, 564`|**High**|`c.select()`、`c.status()`、`c.uid("MOVE")`、`c.uid("COPY")` 传入的文件夹名未加引号。若名称带空格（如 `Deleted Items`）或特殊符号，底层 IMAP 报文被截断导致服务器报 `BAD`。|实现 mailbox 名称的自动引号安全转义（`_quote_mailbox`），包含空格或特殊字符时自动带双引号。|
|**PROV-02**|`mail_core/providers/graph.py:234`|**High**|Graph 的 trash 逻辑捕获所有 `ProviderHttpError`（包括 5xx、403、网络临时错误）后直接降级为永久物理 `DELETE`。网络瞬断会导致邮件被不可逆硬删除。|仅在明确收到 404/Not Found 时判定为已删除，遇到 5xx/403 等异常返回 `success=False`，触发正常重试。|
|**PROV-03**|`mail_core/blobs/archive.py:598`|**High**|MIME 解析代码块使用通用 `except Exception`，发生附件写盘失败时仅记录了 `parse_error`，却依然执行 `apply_transition(st, ARCHIVE_COMPLETE)`，导致写盘失败的附件永久丢失且不再重试。|严格区分 MIME 语义解析错误与存储 I/O 错误；写盘失败时将状态退回 `ARCHIVE_PENDING` 并递增 `retry_count`。|
|**PROV-04**|`mail_core/blobs/store.py:78`|**High**|`BlobStore.put` 在文件已存在时仅读取头部版本，对截断或损坏的 blob 未进行尾部或内容完整性校验，导致损坏文件永久无法自愈。|在复用前进行完整性快速探测（或捕获解密异常），损坏时重写该 blob。|
|**PROV-05**|`mail_core/blobs/gc.py:156`|**High**|`unlink_gc_paths` 在执行文件删除前进行数据库二次检查，若查询抛出数据库异常，代码直接忽略警告并继续执行 `path.unlink()`，违背 fail-closed 原则。|改为 Fail-Closed：发生异常时跳过当前文件的 unlink，保留至下一次 GC。|
|**PROV-06**|`mail_core/accounts/service.py:42, 96, 110`|**High**|账号创建、更新和删除中，`DbCredentialStore` 凭据操作在独立的会话中提前提交，若外部账号事务回滚，会导致孤立凭据或凭据丢失。|将凭据持久化挂载为账号事务的提交后钩子（After-Commit），或在同事务内安全处理。|

______________________________________________________________________

### 模块三：前端 SPA、桌面端与构建运行（12 项）

|编号|目标文件及行号|审阅级别|切实存在的技术实质|确定修复方案|
|:---|:---|:---:|:---|:---|
|**FE-01**|`frontend/src/components/SettingsModal.tsx:172`|**High**|`npx tsc -b` 编译报错：`provider` 状态变量被推导为 `string`，未能赋值给联合类型。|显式标注 `useState<'gmail' \| 'imap' \| 'graph' \| 'memory' \| 'stub'>('imap')`。|
|**FE-02**|`frontend/src/components/SettingsModal.tsx:237`|**High**|修改密码输入框为裸 `<input>`，无 `id`、`name`、`autoComplete`，未包裹在 `<form>` 内，密码管理器无法识别且违反规范。|包裹在 `<form onSubmit=...>` 内，添加规范属性（`current-password`, `new-password`）。|
|**FE-03**|`frontend/src/components/MessageList.tsx:19`|**High**|收件箱列表硬编码 `LIST_LIMIT=100`，抛弃了返回的 `next_cursor` / `next_offset`，超过 100 封的邮件在 UI 无法翻页到达。|**按决策落实**：接入游标分页，列表底部增加“加载更多”按钮，平滑追加展示历史邮件。|
|**FE-04**|`frontend/src/components/MessageList.tsx:232`|**High**|`<article role="button">` 内部包裹了 `<button className="message-check">`，违背 ARIA 规范（可交互元素内嵌套可交互元素）。|调整 DOM 语义结构，移除外层非法 role 或将整行点击与多选框解耦。|
|**FE-05**|`frontend/src/components/MessageList.tsx:38` 等|**High**|`useMailStore()` 未使用 selector，拖动侧边栏/列表宽度时，每个 pointermove 事件都会引发列表与阅读器的全量重渲染。|改用精准 selector（`useMailStore(s => s.view)` 等），阻断拖拽过程中的不必要重渲染。|
|**FE-06**|`frontend/src/hooks/useMailCoreRealtime.ts:120`|**High**|SSE EventSource `onerror` 仅为空注释，重连后未主动使 query cache 失效；网络彻底断开时无任何 UI 状态感知。|在 EventSource 重连或重新激活时触发缓存失效，遇到不可恢复错误时暴露警告。|
|**FE-07**|`frontend/src/lib/mailBody.ts:12`|**High**|DOMPurify `FORBID_TAGS` 遗漏了 `svg`, `math`, `video`, `audio`, `source`, `track`, `details` 等非邮件标签。|补充该标签黑名单，并增加针对性 XSS 净化测试。|
|**FE-08**|`frontend/src/components/MessageReader.tsx:148`|**High**|iframe sandbox 声明了 `allow-popups-to-escape-sandbox`，导致邮件内部链接打开的新窗口脱离沙箱约束。|移除 `allow-popups-to-escape-sandbox`，并在链接 base 处确保 `rel="noopener noreferrer"`。|
|**FE-09**|`desktop/postgresManager.js:259`|**High**|`start()` 检查到 `alreadyRunning: true` 时跳过了 `ensureDatabase`。若首次启动在建库前崩溃，下次启动会误报成功但数据库实际未初始化。|在 `alreadyRunning` 分支同样安全调用具有幂等性的 `ensureDatabase`。|
|**FE-10**|`desktop/main.js:74`|**High**|桌面端寻找可用端口后直接加载 `http://127.0.0.1:<port>/health`，缺少进程身份鉴权，存在被本地随机进程抢占端口的风险。|在启动参数中传入随机生成的一次性 token，健康检查响应验证该 token。|
|**FE-11**|`scripts/fetch-pg-binaries.sh:103`|**High**|`verify_archive_sha256` 内部使用了 `exit 1`，导致主循环在第一个候选镜像校验不通过时直接终止退出，无法尝试后续镜像。|将函数内部的 `exit 1` 改为 `return 1`。|
|**FE-12**|`frontend/src/components/Sidebar.tsx:26-38`|**High**|侧边栏未读数依赖前端 React Query 缓存的第一页数据（`for (const m of inboxRows)`）计算，未接入后端统计接口。若未读邮件超出首屏（如 300 封），角标严重少报；若初始未激活统一收件箱，角标直接显示 0。|侧边栏改用后端已有的 `/api/accounts/{account_id}/folders` 统计接口读取各账户及统一收件箱的真实 `unread_count`。|

______________________________________________________________________

### 模块四：历史审查包脱敏与排障/部署文档校准（7 项）

|编号|目标文件及行号|审阅级别|切实存在的技术实质|确定修复方案|
|:---|:---|:---:|:---|:---|
|**DOC-01**|`docs/reviews/**` (全部历史审查包)|**Critical/High**|历史审查文档中包含了 10 名开发者的真实个人邮箱（PII）、示例密钥明文，且未标注“已修复”横幅，被工具持续当成活动漏洞。|**按决策落实**：全面打码个人邮箱与密钥字面量；在所有历史报告头部添加 `SUPERSEDED / FIXED at da57df7` 状态横幅。|
|**DOC-02**|`docs/troubleshooting.md:34, 35`|**Critical**|排障文档指导用户“删除本地 bcrypt 文件”或“修改环境变量”来重置忘记的密码。但在方案 A 落地后，密码以数据库为准，此操作已失效。|重写重置密码指南，明确说明通过数据库 `auth_credentials` 表重置密码的 SQL 操作与步骤。|
|**DOC-03**|`docs/deployment.md:57`|**High**|拆分进程部署指南给出的独立 worker 示例未配置从 `--data-dir` 加载密钥，启动必失败。|补全独立 worker 启动时所需的环境变量与共享密钥加载示例。|
|**DOC-04**|`docs/deployment.md:30` / `security.md:9`|**High**|文档建议在 Compose 中配置环境变量 `FORWARDED_ALLOW_IPS`，但 uvicorn 只认命令行 flag，不读取环境变量。|将文档中的环境变量写法修正为 uvicorn 的 `--forwarded-allow-ips` 参数说明。|
|**DOC-05**|`docs/api.md:10`|**High**|改密响应体文档记为 `{"ok": true}`，而实际返回的是 `{"ok": true, "success": true}`。|校准文档与 OpenAPI 响应格式一致。|
|**DOC-06**|`mail_core/api/app.py:155`|**High**|SPA fallback 路由在未构建 frontend/dist 的干净仓库下不注册，导致 `export_openapi.py --check` 在干净克隆下校验失败。|为 SPA fallback 路由显式指定 `include_in_schema=False`，解耦静态文件存在性与 API Schema。|
|**DOC-07**|`docker-compose.mail-core.yml:71` / `Dockerfile`|**High**|命名卷首次挂载时默认为 root:root 0755，容器内部以 uid 10001 (kkmail) 运行，初次写入 blob 报权限拒绝。|在 `Dockerfile.mail-core` 中预建 `/var/lib/kkmail/blobs` 并赋予 `kkmail` 用户权限。|

______________________________________________________________________

### 模块五：测试环境与断言健壮性（5 项）

|编号|目标文件及行号|审阅级别|切实存在的技术实质|确定修复方案|
|:---|:---|:---:|:---|:---|
|**TEST-01**|`tests/mail_core/test_attachment_access.py` 等|**High**|4 个测试用例未标注 `@pytest.mark.skipif(not DATABASE_URL)`，在本地未指定数据库时直接抛 `DatabaseConfigError` 崩溃。|补齐条件跳过标记，保证无数据库环境下的纯净表现。|
|**TEST-02**|`frontend/src/lib/listDate.test.ts`|**Medium**|测试期望固定的本地时间字符，未考虑不同运行机器的时区隔离，在 UTC 环境下断言失败。|使用固定时区模拟器或 UTC 对齐输入。|
|**TEST-03**|`scripts/mail-core-backup-restore-drill.sh:34`|**High**|`rm -rf -- "$OUT"` 目标路径未严格限制在 drill 专用前缀内，输入错误路径时存在误删风险。|强制校验目标目录名必须匹配 `kkmail-backup-drill*` 前缀。|
|**TEST-04**|`scripts/mail-core-chaos-lease.sh:12`|**High**|混沌测试脚本缺少对临时数据库名称的安全防护校验。|增加数据库名称包含 `test`/`chaos` 的防误伤前置校验。|
|**TEST-05**|`docs/known-limitations.md:32` / 根目录|**Medium**|无浏览器端到端测试套件，仅覆盖后端 pytest（强依赖 PG）与前端 vitest（jsdom 单元/组件测试），缺少真实浏览器环境下的全流程用户行为（登录 -> 浏览列表 -> 读信）自动化验证。|引入 Playwright 基础配置并建立核心业务流（登录、收件箱列表加载、邮件详情查看）轻量端到端冒烟测试套件。|

______________________________________________________________________

## 三、 待执行实施路线图 (待批准后按序启动)

- **阶段一（安全核心与代码边界）**：落实 SEC-01~08（改密写库错误抛出、session_epoch 入库、错误脱敏）及 PROV-01~06（IMAP 文件夹安全加引号、Graph trash 降级保护、MIME 归档存储错误区分）。
- **阶段二（前端体验与交互）**：落实 FE-01~12（收件箱“加载更多”游标分页、侧栏接入服务端真实未读角标、TS 编译修复、改密表单属性、Zustand selector 优化、DOMPurify 标签增强）。
- **阶段三（历史审查脱敏与运维文档）**：落实 DOC-01~07（全部历史审查包打码加横幅、排障指南重置密码修正、Docker 卷权限、OpenAPI 解耦）。
- **阶段四（测试与脚本安全加固）**：落实 TEST-01~05（测试用例无 DB 跳过、脚本目录与镜像校验、引入 Playwright 核心链路轻量 E2E 冒烟套件）。
