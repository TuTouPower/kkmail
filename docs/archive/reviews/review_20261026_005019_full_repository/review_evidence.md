# 全仓审阅：验证与复现证据

本文件记录 [全仓审阅报告](review_report.md) 的执行结果、探针设计和证据边界。适用基准、严重级别及问题完整分析以主报告为准。以下是已完成审阅的历史证据，不代表文档落盘时重新执行了一轮全量测试。

## 运行环境与版本

|项目|本轮事实|
|---|---|
|审阅日期|`2026-10-26`，时区 `Asia/Shanghai`|
|后端全量开始时间|JUnit：`2026-10-26T00:31:09.776926+08:00`|
|全仓初轮基准|`e825147f`|
|补审终点|`6f6605b6ab08eb26eb1c375d0e76db3482a66811`|
|补审提交|`3e142b97`：剪贴板回退；`6f6605b6`：对应 pending 归档|
|操作系统/架构|macOS / arm64|
|Python|仓库 `.venv`，`3.14.7`|
|Node.js|`v24.21.0`|
|数据库|项目测试运行器分配的独占 PostgreSQL 临时库|
|远端邮箱|未使用真实供应商账号/OAuth 凭据|
|浏览器|既有 Chromium 冒烟套件；ego-browser 原生 dialog 探针|

CI 中 Python `3.13`、Node.js `22` 与上述环境不同。本轮证明本机结果；没有据此宣称跨版本、跨平台全部通过。

## 门禁执行结果

命令未标注子目录时，工作目录均为仓库根。完整数据库命令要求项目专用测试服务已启动，且专用测试凭据来自本地测试配置；本文件不提供默认密码、不复制 `.env.test`。环境安装和服务启动不是本次重新执行内容。

|检查|实际入口/工作目录|结果|解释|
|---|---|---|---|
|后端全量|`scripts/run-mail-core-tests.sh run`|947 passed、7 failed、2 skipped|共收集 956 项；失败与跳过均保留，不计为全量通过|
|后端失败定向重跑|同一运行器，`-k` 选择下表 7 个失败用例，`--no-cov`|7 failed、949 deselected|独立新测试库中仍失败；14.65 秒|
|数据库缺陷探针|同一运行器追加本机探针文件，`-k review_probe --no-cov -s`|6 passed、956 deselected|探针断言用于确认缺陷仍存在，不能作为修复绿测|
|前端单元/组件：初轮|`npm test`，`src/frontend/`|43 文件、378 tests passed|后续 OpenAPI 阶段失败，整个命令退出 1|
|前端单元/组件：补审终点|`npm test`，`src/frontend/`|44 文件、386 tests passed|后续 OpenAPI 阶段仍失败，整个命令退出 1|
|前端 lint|`npm run lint`，`src/frontend/`|失败|`App.tsx:109`，`react/set-state-in-effect`|
|TypeScript|`npx tsc -b`，`src/frontend/`|通过|补审终点再次检查通过|
|CSS|`npm run css:check`，`src/frontend/`|通过|9 项检查测试通过；CSS 变量与语义色检查通过|
|生产 SPA 构建|`npm run build`，`src/frontend/`|通过|补审终点再次构建通过|
|后端 OpenAPI|`.venv/bin/python scripts/export_openapi.py --check`|通过|36 个路径与已提交 JSON 一致|
|前端 OpenAPI|`npm test` 内的 `npm run openapi:check`|失败|生成 TypeScript 与 JSON 不一致|
|浏览器轻量冒烟|`npm run test:e2e`，`src/frontend/`|18 passed，24.6 秒|基于既有 stub API，属于轻量 UI 验证；不是完整真实后端 E2E|
|桌面基础测试|`npm test`，`src/desktop/`|通过|包含现有 Electron 剪贴板集成；专用 OAuth 集成提示跳过|
|模板契约|`.venv/bin/pytest .repo_template/tests -q -m contract`|149 passed、1 skipped、374 deselected|1.91 秒；不等于执行了全部模板测试|

后端全量 pytest 用时 `754.05` 秒，运行器 tests 阶段为 `755.539` 秒。JUnit testsuite 记录 `754.013` 秒；差异来自计时层级，报告未把不同计时口径混为同一数值。

前端最终测试摘要与失败阶段：

```text
Test Files  44 passed (44)
Tests       386 passed (386)
src/frontend/src/api/generated/schema.ts is out of date with schemas/openapi.json
```

由于 `npm test` 使用 `&&` 串联，OpenAPI 阶段失败后，命令中的 CSS 阶段没有执行；表中 CSS 通过来自单独运行。前端构建、类型通过也不能覆盖 lint 失败。

## 后端 7 项失败：分类与下一步

以下分类依据失败断言与现行实现/契约交叉核对；尚未修改任何用例或生产代码。后续修复应先确定目标语义，不能就地把预期改成实现输出来消除红测。

|用例|观测到的关键失败|分类|下一步|
|---|---|---|---|
|`tests/mail_core/test_dispatcher_nonblocking.py::test_listener_requires_subscribers_for_initial_notify_and_idle_dispatch`|预期仅 `LISTEN mail_core_outbox`，实际额外监听 `mail_core_session_revoked`|旧测试未覆盖新增会话撤销通道|保留旧测试原有订阅者要求，按项目测试规则重建新增通道行为覆盖|
|`tests/mail_core/test_outbox_listen.py::test_listen_thread_dispatches_on_notify`|期望收到事件，实际 `seen=[]`|用例没有注册 subscriber，与当前仅有本地订阅者时 dispatch 的行为冲突|在明确订阅语义后验证真实 LISTEN/NOTIFY；不能借此绕开“无订阅者不偷事件”的契约|
|`tests/mail_core/test_imap_provider_live.py::test_imap_list_and_metadata_page`|`IMAP peer is a private or loopback address (SSRF protection)`|本机 fixture 测试未显式启用私网测试配置|只在受控测试环境配置允许本机 fixture；保留生产 SSRF 拒绝回归|
|`tests/mail_core/test_imap_remote_id.py::test_imap_provider_quotes_folder_in_commands`|`response("COPYUID")` 解包失败：`expected 2, got 0`|IMAP 替身返回形状不符合当前调用要求|补真实协议返回形状及 COPYUID/缺失 COPYUID 两类覆盖，原引号断言仍须保留|
|`tests/mail_core/test_medium_providers_sync_blobs.py::test_update_account_sync_status`|预期原始 timeout 文本，实际 `ProviderError`|旧预期与安全摘要语义冲突|核对脱敏契约，保留“敏感原文不落库”与必要诊断字段验证|
|`tests/mail_core/test_sync_hardening_a27_a28_a29.py::test_a27_sync_folder_delta_sanitizes_errors`|期望新 `payload.detail`，实际为 `None`|去重入队丢失新载荷，对应 P2-01|修复后继载荷语义，并覆盖 PENDING/CLAIMED 命中与错误摘要保留|
|`tests/scripts/test_start_mail_core_imap.py::test_pymap_fallback_passes_private_passfile_and_cleans_it_up`|临时 passfile 仍存在|本机 `rm` 包装器与测试 PATH 替身冲突|把环境干扰单列，先确定环境/测试隔离方案；不据此断言生产脚本有相同清理缺陷|

定向重跑仍为以上同一组失败，未发现“偶发重跑即通过”证据。重跑日志来自独立运行，不复用全量测试库。

### 本机 `rm` 包装器干扰

本机非交互 shell 中 `rm` 可命中 `~/.local/bin/rm`；该入口经 `#!/usr/bin/env python3` 启动。用例在 PATH 前部放置 fake `python3` 以模拟 pymap，连带截获 `rm` 包装器的解释器解析。该 fake 对包装器调用退出非零，passfile 清理失败。

诊断核对了 PATH 解析、包装器 shebang 和测试替身分支。没有修改或绕过本机配置，也没有把该失败合并为生产删除逻辑漏洞。原始 passfile 内容不复制进本报告。

## 后端 2 项跳过

|用例|跳过条件|
|---|---|
|`test_google_oauth_callback.py::test_electron_real_spa_cookie_free_loopback_callback_and_save`|需独占 PG、编译 SPA，以及显式 Electron 集成模式|
|`test_microsoft_oauth.py::test_microsoft_electron_dynamic_localhost_and_cookie_free_callback_pg`|需独占 PG、生产 SPA，以及显式 Electron 集成模式|

这两条跳过不能解释为真实供应商 OAuth 或 Electron OAuth 已验证。桌面 npm 测试中的 OAuth 条目也提示缺少专用测试参数。

## 非数据库探针：方法、结果和边界

原始探针位于本机 `.scratch/review_all/reproduce.py`。该脚本使用真实生产函数，必要处以替身阻断真实数据库恢复或指标查询；所有文件实验限制在 `.scratch/`。合成标记不是可用令牌或配置默认值。

|关联问题|实际方法|观测结果|证据没有证明什么|
|---|---|---|---|
|P1-01|构造合法 manifest/checksum、占位 dump 与含 `blobs//absolute/path` 成员的真实 tar；真实执行校验和 Blob 解包；仅替换 `pg_restore` 查找/进程执行|目标 Blob 根之外的预置哨兵文件被覆盖；函数返回成功|没有实际运行 pg_restore；没有验证系统级链接替换竞态；占位 dump 不能证明备份可恢复|
|P1-02|向生产 `_restore_database_identity` 输入相同 host/port/database、不同用户名的两个 URL|两个身份结果不相等，源库拒绝分支不会因数据库相同而触发|没有对真实源库执行恢复；实际破坏仍取决于角色权限与调用参数|
|P2-01|Session 替身保存调度结果，调用真实 `enqueue_job` 和 `_evaluate_result`|请求 `poll_round=1, priority=75`，后继仍为 `poll_round=0, priority=60`|未运行完整 20 轮网络轮询；计数无法推进由该结果和调度分支共同支持|
|P2-05|无 Cookie/Bearer 的真实 TestClient 访问两条路由；指标服务和 Session 工厂为无数据库替身|两个路径均返回 200|没有连接部署实例，也没有实际读取用户业务指标；暴露字段来自真实 DTO/聚合代码|
|P1-05|真实 ProviderHttpError、LogRecord、RedactingTraceFormatter；异常消息放入合成通用 token 字段|格式化结果仍含输入 token 标记|没有使用真实秘密；没有审计所有第三方日志 handler 或所有异常类型|

关键输出摘录：

```text
RESTORE_ESCAPE: True overwrote file outside target_blobs_dir
FOLLOWUP: requested poll_round=1 priority=75; actual poll_round=0 priority=60
UNAUTHENTICATED_METRICS: [200, 200]
SOURCE_DATABASE_GUARD: same host/port/database accepted as different when username changes
LOG_REDACTION: generic token value remains in formatted provider exception traceback
```

### P1-01 复现结构

1. 在本轮独占 `.scratch/` 子目录创建 `package/`、`blobs/` 与位于 `blobs/` 外的哨兵文件。
2. tar 成员名由 `"blobs/" + str(哨兵绝对路径)` 构成，因此包含两个连续 `/`。
3. 计算 tar/dump 的 SHA-256，写入真实 manifest 及 manifest checksum；确认 `verify_backup_package` 返回通过。
4. 以替身阻断 `pg_restore`，调用生产 `restore_backup_package`。
5. 读取哨兵，确认内容已变成 tar 成员内容。

这组实验验证的是路径隔离，不是备份完整性或 PostgreSQL 恢复能力。后续修复回归应要求步骤 4 在写出根外文件前拒绝，并保持哨兵原样。

## 真实 PostgreSQL 探针

本轮通过项目运行器建立独占数据库，执行生产 Alembic 迁移后再运行探针。每组运行结束后由运行器清理数据库。探针使用真实 SQLAlchemy Session 和生产函数；只在“精确交错”处控制调用时机，不 mock PostgreSQL 的锁或事务行为。

原始探针位于本机 `.scratch/review_all/test_review_probes.py`，共 6 个；**当前断言均用于确认缺陷存在**。如果缺陷修复，这些诊断断言应变红；后续正式回归应按主报告验收条件新建正确语义覆盖，不能把诊断通过当作修复通过。

### 多位置已读统计：P2-02

- 建立一个账号、INBOX 和 ALL 两个目录；同一未读 Message 在两个目录各有一个位置。
- 用生产 `recompute_folder_stats` 初始化，两个目录未读数均为 1。
- 使用相同合法租约，依次对两个目录调用生产 `apply_delta_page`，均传入同一邮件 `is_read=True` 的 flag patch；每次真实提交。
- 重新读取数据库，未读数为 `[0, 1]`，而共享 Message 已读。
- 结论：第二个位置的同值 patch 不再产生 touched，目录统计不会因为邮件共享状态已改变而自行刷新。

### 移除位置统计：P2-03

- 使用同一多位置结构，初始化两个目录各 1 封。
- 对 INBOX 执行该邮件显式 delete delta，保留 ALL 位置。
- 提交并重新读取：INBOX 的 MessageLocation 数为 0，FolderStats.total_count 仍为 1。
- 结论：整个 Message 未删除时，目录变化没有进入当前统计刷新条件。

### 成功同步时间：P2-07

- 写入生产合法状态 `done` 的 SyncRun 和非空 finished_at。
- 调用生产 `get_system_health_metrics`，由真实数据库执行聚合。
- 返回 `last_sync_success_at=None`。
- 独立核对生产枚举及引擎写入均为 `done`，而聚合条件为 `success`。

### IMAP 废纸篓目标：P2-04

- 为测试账号建立 `remote_id=INBOX.Deleted, role=trash` 的文件夹。
- 调用生产 `trash_message`，读取实际生成的 RemoteOperation。
- `desired_state.trash_folder_remote_id` 仍为 `Trash`。
- 结论：实际发现的目标没有进入出站载荷。该探针没有连接远端 IMAP；远端拒绝/成功与目录真实存在性有关，应由协议回归继续验证。

### Outbox 提交顺序：P1-04

|顺序|事务 A|事务 B|回放观察|
|---|---|---|---|
|1|新增事件并 flush，取得较小 ID，不提交|尚未写入|较小 ID 尚不可见|
|2|保持未提交|新增较大 ID 并提交|仅较大 ID 可见|
|3|保持未提交|已提交|生产 `_build_replay` 返回较大 ID，游标推进|
|4|提交较小 ID|已提交|较小 ID 此时进入数据库可见集|
|5|已提交|已提交|从步骤 3 游标重放，frames 为空|

这组实验直接验证 durable replay 缺口。在线流额外存在 `eid <= cursor_local` 过滤，依据源码可推导同类交付问题；本轮未单独维持一个真实浏览器 SSE 连接来重复该交错。

### 去重任务完成竞争：P1-03

1. 建立任务并真实认领为 CLAIMED，认领者为本轮合成 Worker ID。
2. 新请求 Session 调用生产 `enqueue_job`。控制其 `scalar` 返回已读取行之后、继续执行入队标记之前的时点。
3. 另一真实 Session 读取同任务，调用生产 `complete_job` 并提交。
4. 新请求继续执行原函数，flush/commit `_followup_needed`。
5. 新 Session 查询该 dedupe_key：只有一条 DONE 行，其 payload 存在 `_followup_needed=True`，没有 PENDING 后继。

调用时机通过替换第 2 步 Session 的 `scalar` 方法来控制；方法仍先调用真实查询，再用第二个真实 Session 完成任务。不以“数据库已被 mock”为证据，亦不需要线程时间碰撞来制造偶发失败。

真实数据库探针关键输出：

```text
REVIEW_PROBE_FLAGS: unread counters remain [0, 1] after both folders synced read=True
REVIEW_PROBE_DELETE: empty folder retains total_count=1
REVIEW_PROBE_METRICS: completed SyncRun ignored, last_sync_success_at=None
REVIEW_PROBE_TRASH: discovered INBOX.Deleted ignored; outgoing MOVE targets Trash
REVIEW_PROBE_OUTBOX: later commit with lower event id is absent from cursor replay
REVIEW_PROBE_WAKEUP: wake marker persisted onto DONE job, no pending successor exists
6 passed, 956 deselected, 2 warnings in 2.18s
```

## Clipboard 原生 dialog 探针：P2-10

浏览器探针使用 ego-browser 新建独立任务空间，在空白页面中转译并执行当前生产 `clipboard.ts`。页面构造原生 `<dialog>`，调用 `showModal()`，先聚焦对话框按钮，再使 `navigator.clipboard` 不可用以进入回退分支。

探针把 `document.execCommand` 替换为“观察 activeElement 与 textarea、然后返回 false”的函数。没有执行真实系统剪贴板读写，避免改写用户剪贴板。实际 DOM 观察为：

```json
{
  "activeElement": "probe-button",
  "textareaFocused": false,
  "parent": "BODY",
  "modalOpen": true,
  "rejected": true
}
```

能够确认的事实：生产 helper 把 textarea 放在 body，原生 modal 打开时，该 textarea 没有获得焦点。

不能据此确认的事实：原生 `execCommand('copy')` 实际返回值、系统剪贴板最终内容，以及真实用户点击下的完整成功/失败行为。JSON 中 `rejected=true` 来自命令替身返回 false，不能作为原生命令失败证据。

因此主报告将该条记为“焦点障碍已确认、实际复制结果待验证”。后续应使用隔离剪贴板或保持用户原值的浏览器测试补齐真实复制和粘贴断言，再确定最终功能结论。

浏览器任务空间已关闭。没有留下用户需要接管的页面，也没有执行工具升级。

## 静态证据项与未执行范围

### CI 打包前提：P1-06

交叉核对了独立 `desktop-quality` job、新 checkout 后的安装/下载步骤、Git 跟踪清单和 `packaged-smoke.js` 对真实前端资源的断言。缺少前端构建或 artifact 下载不是远端运行结果；结论是当前 job 没有满足冒烟所需资产前提。

没有触发 GitHub Actions，没有为验证文档下载 Electron/PG 产物，也没有在本机预先存在 dist 时把本地通过写成干净 CI 通过。后续应以干净 runner 实测关闭该条。

### Worker 健康心跳：P2-06

核对了 `run` 在 `_tick` 前记录业务健康心跳、`_tick` 串行处理任务、独立 `_heartbeat_claims` 只更新任务锁时间，以及 healthcheck 默认 60 秒阈值。没有用墙钟等待长任务，也没有触发编排重启。

能够支持“任务执行期间健康心跳不持续刷新”的代码结论；目标环境何时 unhealthy、运维系统是否据此重启，仍需对应环境验证。任务锁续期正确不等于进程健康心跳也续期。

### 本轮未执行

- 真实 FastAPI、Worker、PG、Dovecot 与生产 SPA 组合的完整全栈 E2E。
- 真实 Google/Microsoft 账号授权、管理员同意、2FA 与真实供应商网络冒烟。
- 专用 Electron OAuth 集成模式、严格桌面打包冒烟。
- Windows/Linux 原生窗口、macOS 系统交互及跨平台人工验收。
- 生产数据恢复、部署、发布、外部通知或远端 CI 触发。
- 第三方依赖源码审计与完整公网漏洞数据库审计。

## 原始产物索引与保留策略

下列路径是本机辅助证据，位于 Git 忽略目录，不随本报告提交。它们可能被正常清理；本文已内嵌结论所需关键结果。

|原始产物|用途|
|---|---|
|`.scratch/test_runs/28dfa14f794646b58862f4b38e5b9e93/test_summary.json`|后端全量 956 项的收集、通过、失败与跳过汇总|
|同目录 `junit.xml`|逐用例结果、失败堆栈、时间戳；不将原始长日志复制入库|
|同目录 `coverage.xml` / `coverage.json`|本轮生产 mail_core 覆盖产物；不以覆盖率代替行为验收|
|`.scratch/review_all/backend_failures_rerun.log`|7 项失败定向重跑|
|`.scratch/review_all/pg_probes.log`|6 个 PostgreSQL 诊断探针|
|`.scratch/review_all/probes.log`|非数据库隔离探针|
|`.scratch/review_all/frontend_final.log`|最终 386 项前端测试和 OpenAPI 失败|
|`.scratch/review_all/frontend_final_build.log`|补审终点生产构建|
|`.scratch/review_all/frontend_e2e.log`|18 项轻量 UI 冒烟|
|`.scratch/review_all/template_tests.log`|模板契约结果|
|`.scratch/review_all/schema_fresh.ts`|与提交生成类型比较的临时生成文件|
|`.scratch/review_all/clipboard_dialog_probe.json`|原生 modal 下焦点观察|
|`.scratch/review_all/reproduce.py` / `test_review_probes.py`|一次性诊断源码，不属于生产或正式回归测试|

最后一轮 PostgreSQL 诊断运行 ID 为 `766e978b09a64596ae0c6b4ca179ba3e`；失败定向重跑 ID 为 `05d0fe2816a745cf9d5c8411bb369aba`。二者与全量运行 ID 不同，数据库均由运行器清理。

## 本机重放入口与限制

以下仅适用于原始探针仍存在、本机测试服务已按 [测试规范](../../blueprint/testing.md) 就绪，且检出报告适用基准的情况。命令从仓库根执行。运行器会分配和清理独占测试库；遇到所有权/实例校验失败时停止，不手工改环境绕过保护。

```bash
.venv/bin/python .scratch/review_all/reproduce.py
scripts/run-mail-core-tests.sh run .scratch/review_all/test_review_probes.py -k review_probe --no-cov -s
```

第一条以临时文件实验和替身阻断真实 pg_restore；第二条运行诊断探针，当前预期是确认缺陷的断言通过。两者均不能直接作为修复验收命令。仓库新克隆没有 `.scratch/` 源码时，应按本文步骤重建隔离诊断或在正式 task 内编写生产回归，不声称上述路径天然存在。

修复后的质量验证以项目 [testing.md](../../blueprint/testing.md) 为准，并增加主报告逐项验收条件。此次文档落盘仅检查 Markdown 格式、链接和记录完整性，没有因为改文档重新运行 12 分钟后端套件。
