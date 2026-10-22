# Task spec

## 背景

当前邮件客户端收件箱界面点击“刷新”按钮仅使本地 TanStack Query 缓存失效重刷只读 API，未触发远端拉取，空收件箱或新账号刷新无任何邮件；新创建/导入账号未自动入队首次同步任务；同时网易 163 等 IMAP 邮箱因缺省 RFC 2971 ID 握手被服务端返回 `NO ['SELECT Unsafe Login']` 拒绝。需联动远端同步、自动入队初始任务并支持 IMAP ID 握手。

## 契约区

### 范围

- 前端 `MessageList.tsx` 刷新按钮联动调用单账号同步（`POST /api/accounts/{id}/sync`）或全量同步（`POST /api/accounts/sync-all`），展示排队反馈；
- 后端 `create_account_app` 事务提交后自动入队 `SYNC_ACCOUNT_FOLDERS` 初始同步任务；
- 后端 `ImapProvider` 支持 RFC 2971 `ID` 指令握手，解除网易等邮箱 `SELECT Unsafe Login` 拦截，并对不支持 `ID` 的服务保持静默放行兼容。

### 非范围

- 不修改现有 OAuth 协议和 Microsoft Graph Delta 解析契约；
- 不调整后台 Worker 现有轮询与 Claim 消费机制。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：前端邮件列表顶部点击刷新按钮时，若处于单账号视图则触发单账号同步 API，若处于全局收件箱或非单账号视图则触发全量同步 API，并展示排队状态。
- [ ] AC-002：通过 `create_account_app` 创建新邮箱账号后，`worker_jobs` 表中必定存在该账号对应的 `SYNC_ACCOUNT_FOLDERS` 初始任务。
- [ ] AC-003：后端 `ImapProvider._connect()` 在连接认证后发送 RFC 2971 `ID` 客户端标识命令，支持网易等需要 ID 握手的 IMAP 服务。
- [ ] AC-004：当目标 IMAP 服务不支持或拒绝 RFC 2971 `ID` 命令时，`ImapProvider._connect()` 捕获并放行，连接和后续文件夹查询正常执行。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。

## 上下文区

- 来源：`p009`（2026-10-22；确认前端刷新无后端同步、新建账号无初始入队及网易 Unsafe Login 拦截）

### 有意不测

- 无

### 测试策略

- 前端：在 `MessageList.test.tsx` 中模拟点击刷新按钮，断言对应的同步 API 请求被发送并产生状态反馈。
- 后端：在单测中验证新建账号后作业队列生成，以及使用 mock IMAP client 断言 ID 命令正常发送与不支持容错。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

无

### 风险与回退

- 风险：若个别老旧 IMAP 服务器对非法命令断开连接，已通过条件判断与异常捕获避免影响。
- 回退：`git revert` 本 task 执行提交。

### 依赖与约束

- 无

### Finalization 时更新的 blueprint

- 无
