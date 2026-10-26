# 当前仓库审阅

审阅基线：`main`，`2e29508c05810fba8c5e29e0f903e9bb05f0d04d`。开始时工作区干净。记录时间：2026-10-26T18:31:00+08:00。

## 范围与结论

覆盖后端 API、安全认证、账户凭据、IMAP/Graph、同步任务与请求状态机、Outbox/SSE、Blob/恢复、前端缓存与交互、Electron 进程和权限边界、构建部署脚本、迁移、测试及生效文档。采用模块静态审查、现有门禁、隔离 PostgreSQL 并发复现及前端独立探针；不将覆盖模块等同于逐行证明全部文件正确。

核对既有审阅与修复记录后，独立确认下列当前仍成立问题。只新增审阅报告及被 gitignore 的复现材料，未修生产代码、未提交、未部署。

|优先级|问题|
|---|---|
|P1|R01 Graph 特殊文件夹分类失效；R02 并发撤销丢失 session epoch；R08 多 API 首批 SSE 事件丢失|
|P2|R03 轮换覆盖新凭据；R04 重建提前报告完成；R05 旗标迟到回滚；R06 无 MODSEQ 时旗标不收敛；R07 删除与结算死锁；R09 测试契约与挂起门禁|

## 问题

### R01 [P1] Graph 特殊文件夹依赖不存在的响应字段，Inbox 之外分类失效

位置：[graph.py](../../../src/mail_core/providers/graph.py)，`graph_folder_role` 第 50–64 行、`list_folders` 第 116–122 行。

`list_folders` 只通过 well-known endpoint 核实 Inbox ID，其余分类依赖响应中的 `role` / `wellKnownName`。标准 Graph `mailFolder` 资源不提供这两个属性。真实已发送、草稿、垃圾邮件、废纸篓及归档目录因此被持久化为 `other`；按 `Folder.role` 查询的对应聚合列表、统计与范围同步匹配不到它们。真实目录直达仍可用。

独立依据：[Microsoft Graph v1.0 mailFolder 官方契约](https://learn.microsoft.com/en-us/graph/api/resources/mailfolder?view=graph-rest-1.0) 列出了资源属性及跨语言稳定的 well-known endpoint。符合该契约的中文目录夹具经生产 `GraphProvider.list_folders` 后，Inbox 为 `inbox`，Sent/Drafts/DeletedItems 均为 `other`。未使用真实微软账号登录。

修复方向：通过各 well-known endpoint 获取稳定 ID，按 ID 映射角色；测试使用真实资源字段，避免用虚构的 `wellKnownName` 掩盖问题。

### R02 [P1] 改密与退出并发丢失 epoch 增量，旧密码登录会话在改密后仍有效

位置：[auth.py](../../../src/mail_core/security/auth.py)，`_persist_db_password_hash` 第 224–235 行，`invalidate_all_sessions` 同类读改写路径。

两条路径都先普通读取 `AuthCredential.session_epoch`，再在 Python 中加一。没有行锁或数据库原子递增。改密事务读取 epoch=1 后，如果另一退出事务先提交 epoch=2，期间使用旧密码登录得到 epoch=2 Cookie，原改密事务最终仍写 epoch=2。新密码已经生效，旧密码签发的 Cookie 却继续通过 `read_session`。

真实 PostgreSQL 复现：暂停改密的凭据读取，完成一次退出和旧密码登录，再放行改密提交；确认旧密码已不能登录、新密码可登录，但期间 Cookie 仍被接受。此处不是仅有进程内 epoch 缓存延迟，而是数据库权威 epoch 本身少递增一次。

修复方向：在统一事务锁下验证/更新密码与撤销代际，或使用数据库原子递增并读取实际返回值；补并发改密、退出及登录回归。

### R03 [P2] 密钥轮换可用旧凭据快照覆盖新 Refresh Token

位置：[rotate.py](../../../src/mail_core/blobs/rotate.py)，`_rewrap_credential_secrets` 第 44–60 行。

轮换读取 `CredentialSecret` 时没有加行锁，随后解密旧快照并重写 nonce/ciphertext。该路径未参与编辑和 OAuth 刷新的凭据行锁协议。若后台刷新在读取与写回之间提交新 Refresh Token，轮换会恢复旧 Token；当服务商使旧 Token 失效时，账号失去后台同步能力，需重新授权。并发修改 IMAP 密码也会被同样覆盖。

真实 PostgreSQL 复现：先创建 v1 加密凭据，在轮换 SELECT 返回后通过生产 `DbCredentialStore` 提交新 Token，再让轮换写 v2；最终解密读出旧 Token。没有打印任何真实凭据。

修复方向：轮换与 `credential_edit` 共用行锁，在锁内读取最新密文并重加密；补刷新和编辑并发回归。

### R04 [P2] 增量游标失效时请求提前完成，重建失败无法反馈原请求

位置：[delta.py](../../../src/mail_core/sync/delta.py)，第 398–422 行；[execution.py](../../../src/mail_core/sync/execution.py)，`settle_job_bindings`。

`CursorInvalidError` 分支清空 baseline 并排入 metadata 重建，却只返回 `followup_scheduled=True`。新 metadata 作业没有绑定原请求，也未通过 `await_initialization` 转移观察关系。`complete_job` 将 delta binding 结算为成功，原请求立即进入 `complete`；后台重建尚未运行，后续失败也不能改变这个成功结果。

真实应用链路复现：创建 delta 请求，由真实 `claim_jobs` / `handle_job` 执行抛出 410 的 provider；最终 checkpoint 的 `full_scan_complete=False`、metadata 作业仍为 `pending`，请求报告已为 `complete`。

修复方向：将原 target 绑定实际重建执行及其后续阶段，直到重建完成或终态失败再结算。

### R05 [P2] 迟到旗标失败回滚后续成功操作

位置：[queries.ts](../../../src/frontend/src/api/queries.ts)，`flagOptimistic` 第 678–689 行。

同一邮件旗标写入既不按意图排序，也不检查请求代际。每个失败请求无条件恢复自己的旧快照。阅读器旗标按钮可连续点击，较早失败因此能够覆盖较晚已经成功的状态；成功路径也没有最终权威刷新保证收敛。

前端复现：初始 false，连续提交 true → false → true，先完成后两次成功，再返回第一次 503；缓存从已成功的 true 回滚为 false。现有测试仅覆盖单请求回滚。

修复方向：按邮件串行提交旗标意图，回滚前校验代际；结束后刷新权威状态，并覆盖连续切换及迟到失败。

### R06 [P2] 不提供 MODSEQ 的 IMAP 服务器无法同步已有邮件旗标变化

位置：[imap.py](../../../src/mail_core/providers/imap.py)，`delta_changes` 第 871–897 行、第 987–996 行。

没有 `HIGHESTMODSEQ` 时，回退路径只调用 `fetch_metadata_page` 从 `uid_next` 扫新增 UID；已有 UID 的 `FLAGS` 从不读取。因此其他客户端改变已读/未读或旗标后，常规增量轮询无法反映。本地读状态与统计持续陈旧。周期 reconcile 只对账远端 ID 和删除，不补这些旗标。

生产适配器夹具复现：服务器只有 UID 1，checkpoint 的 `uid_next=2`，STATUS 返回 UIDVALIDITY 而无 MODSEQ；执行增量返回 exhausted、空 changes，整个过程没有 FLAGS FETCH。此条件不限定具体供应商，未推断任何线上邮箱能力。

修复方向：为无 MODSEQ 服务器增加有界现存 UID 旗标对账及持久化进度；测试须覆盖已完成 baseline 后的远端读/旗标变化。

### R07 [P2] 删除账号与任务结算之间存在 binding/target 锁序反转

位置：[execution.py](../../../src/mail_core/sync/execution.py)，`fail_open_targets` 第 479–501 行；同文件 `settle_job_bindings` 第 324–365 行。

任务结算先锁 `SyncRequestTargetJob`，再锁 `SyncRequestTarget`；删除账号及消失目录路径通过 `fail_open_targets` 先锁 target，随后 flush 更新 binding。两者并发可形成循环等待。既有结算路径的全 target 排序修复未覆盖删除入口。

真实 PostgreSQL 双事务复现：在结算已持有 WorkerJob 与 binding 锁时启动生产 `fail_open_targets`，待删除路径持有 target 锁后继续生产 `complete_job`；稳定观察到 SQLSTATE `40P01`。PostgreSQL 中止其中一笔事务，账号删除可能返回 500，或结算回滚进入重试。

修复方向：将删除、结算、claim/reclaim 与巡检入口纳入统一锁序，覆盖删除与结算竞争，不仅测试两个结算事务。

### R08 [P1] 空流启动的 API dispatcher 会跳过另一进程首次发布事件

位置：[dispatcher.py](../../../src/mail_core/realtime/dispatcher.py)，第 211–212 行。

`_last_dispatched_seq=0` 同时表示“已建立空流基线”和“尚未初始化”。两个 API 进程先在空流上建立订阅后，进程 A 发布第一批事件；进程 B 的本地游标仍为 0，但它本次 `batch.count=0`，代码将游标直接推进到新 head。随后读取 `after_seq=head`，跳过应交付其现有订阅者的首批事件，也没有发 resync hint。已建立的 SSE 连接不会通过 replay 自动补回。

真实 PostgreSQL、两个独立 `OutboxDispatcher` 复现：先让两者在空表上执行一次 dispatch，然后提交一条 `message.upserted`；A 发布并收到事件，B dispatch 返回 0、订阅队列为空，本地游标却变为 1。现有 `test_two_dispatchers_with_established_baselines_both_receive_events` 同样失败；此项属于生产缺陷，不能作为测试预期过时消除。

修复方向：独立记录初始化状态，使合法的 0 游标继续从序列 1 读取；补空流启动、多发布进程及已有订阅者回归。

### R09 [P2] 当前门禁仍有未迁移测试契约和无法结束的 SSE 用例

位置：[test_flag_convergence.py](../../../tests/mail_core/test_flag_convergence.py) 第 38 行、[test_outbox_listen.py](../../../tests/mail_core/test_outbox_listen.py) 第 36 行、[test_sse_medium_remaining.py](../../../tests/mail_core/test_sse_medium_remaining.py) 第 214–235 行、[sidebar_tree.spec.ts](../../../tests/e2e/sidebar_tree.spec.ts) 第 315 行。

大量 PG 用例的 provider 替身仍拒绝生产新增的 `traffic_class` 参数，测试未进入待验证业务路径即失败。LISTEN 测试仍将 `v2:epoch:seq` 强转 `int`；账号生命周期仍期待旧 200/job_id；retention 用例依赖前例留下 watermark，而共享 fixture 每例清空数据库。另有归档 claim、重试到期时间及事件数量预期未与当前契约核对。这些失败不能作为功能修复通过的证据，亦不能直接将预期改为当前输出。

完整运行停在 `test_cursor_ahead_of_head_emits_resync_hint`。该测试通过 `publication_head` 在空表创建 epoch 后，退出 Session 却未提交；SSE 请求创建另一个 epoch，首帧变成 `epoch_mismatch`。测试只在看到 `cursor_ahead` 或累计 3 个事件后退出，但首帧之后只有 keepalive，没有有效超时。单独补跑的 8 秒 faulthandler 栈确认卡在该测试第 229 行 `resp.iter_text()`，随后主动中断并由运行时清理隔离库。其余曾保守排除的 malformed-cursor 和 3 个 SSE replay 用例已补跑，全部通过；不能将它们归为挂起用例。

浏览器 E2E 则在旧 `关闭` 按钮定位上超时；设置已改为工作区，导致该用例后半段响应式断言未执行。R08 的 dispatcher 失败应修生产逻辑，与上述测试迁移问题分别处理。

修复方向：按当前契约整体迁移失效用例，保留原行为覆盖；为 SSE 设置受控结束与超时，再重跑完整门禁。

## 验证记录

|检查|本轮结果|
|---|---|
|后端快速门禁|799 passed、271 skipped、1 failed；失败为下述既有本机包装器干扰|
|后端完整尝试|收集 1071 项；在 cursor-ahead SSE 用例挂起，主动中断；进度输出记录 20 项失败、2 项 Electron 集成跳过；运行 `2a2335602b5247ce87ce8d57650a4578` 已清理|
|前段失败专项重跑|20 failed、1 passed、1050 deselected；`c25ff727e6ab47b2850de3379f240f1c`，全部 20 项失败确认可复现|
|后段分段补跑|192 passed、28 failed、851 deselected；`1adc08297bbe4da18c7d4623aa9e9203`，已清理|
|SSE 补跑|malformed-cursor 1 passed；3 个 replay 用例 3 passed；cursor-ahead 单独再次挂起并取得栈证据|
|前端完整测试|47 文件、442 passed；含 OpenAPI TypeScript 与 CSS token 检查|
|前端构建、类型、lint、live OpenAPI|通过；live OpenAPI 为 41 个路径|
|桌面基础测试|通过；真实 OAuth Electron 集成按入口条件跳过，未宣称已验证|
|快速浏览器 E2E|17 passed、1 failed；旧“关闭”按钮定位超时|
|真实全栈 E2E|8 passed；真实 FastAPI、Worker、Dovecot、PG 与生产 SPA；测试进程及 `kkmail_e2e_344b5e91218d` 已清理|
|模板契约|149 passed、1 skipped、374 deselected|

分段与专项 JUnit 共确认 **48 个不同失败用例**；其中 R08 是已独立确认的生产问题，其他失败须按原行为契约逐项修复或迁移测试。完整门禁未通过，不能把分段结果包装为一次完整运行通过。初次运行中断时没有生成 JUnit，不据其进度字符推算最终全套通过数。

本机配置问题：`test_pymap_fallback_passes_private_passfile_and_cleans_it_up` 的失败来自已有 `~/.local/bin/rm` 包装器经 `env python3` 启动，被测试 PATH 中的 fake Python 截获。历史证据见 [此前审阅证据](../review_20261026_005019_full_repository/review_evidence.md)。本轮未修改或绕过包装器；残留测试口令文件只保留路径，不读取或复制内容。该项与生产缺陷分开。

复现命令均在仓库根目录执行，前提为已有 `.venv`、前端依赖及用户提供的 `.env.test` 测试凭据，使用项目测试运行时创建独占数据库：

```bash
scripts/run-mail-core-tests.sh unit
scripts/run-mail-core-tests.sh run --no-cov
scripts/run-mail-core-tests.sh run .scratch/current_review/test_review_current.py -k 'test_cursor_rebuild_request_finishes_before_rebuild or test_rotation_overwrites_committed_refresh or test_password_change_loses_epoch_increment_to_logout or test_account_deletion_inverts_settlement_binding_target_locks or test_empty_stream_dispatcher_skips_other_process_first_publication' --no-cov
scripts/run-mail-core-tests.sh unit .scratch/current_review/test_review_current.py -k 'test_graph_standard_folder_resources_lose_non_inbox_roles or test_imap_without_modseq_never_fetches_existing_flags' --no-cov
src/frontend/node_modules/.bin/vitest run --config .scratch/current_review/vite.config.mts
npm --prefix src/frontend test
npm --prefix src/frontend run build
npm --prefix src/frontend run lint
.venv/bin/python scripts/export_openapi.py --check
npm --prefix src/frontend run test:e2e
.venv/bin/python scripts/run_full_stack_e2e.py
npm --prefix src/desktop test
.venv/bin/python -m pytest .repo_template/tests -q -m contract
```

完整门禁命令当前会遇到上述失败和 SSE 挂起，不是成功操作指南。分段选择表达式见 `.scratch/current_review/remaining_selection.txt`；48 项失败列表及各轮汇总见 `.scratch/current_review/backend_combined_summary.json`。测试运行时会清理独占测试库，不连接业务数据库。

独立复现位于 `.scratch/current_review/`。探针中的 passed 表示缺陷被确认，不能解释为产品通过。

- `test_review_current.py`：真实 PostgreSQL 复现 R02、R03、R04、R07、R08；provider 夹具复现 R01、R06。7 个 Python 探针与 1 个前端探针均确认预期缺陷。
- `review_frontend.test.ts` 与 `vite.config.mts`：前端缓存复现 R05。
- 原始门禁日志：`.scratch/current_review_backend.log`、`current_review_full_backend.log`、`current_review_frontend.log`、`current_review_desktop.log`、`current_review_build.log`、`current_review_e2e.log`、`current_review_contract.log`。

## 边界

没有执行生产发布、业务数据库写入、真实供应商 OAuth、真实供应商压力测试、跨平台桌面人工操作或严格桌面打包。恢复路径审查包含实现及既有测试；不将静态审查等同于本轮真实跨卷恢复演练。
