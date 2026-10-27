---
tid: "t055"
slug: "microsoft_oauth_callback"
title: "支持 Microsoft OAuth 跳转与设备码登录"
status: "done"
branch: "main"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "e1dee2549e35486fbb36172579bf0d6564f2dedc"
depends_on: "t054"
conflicts_with: ""
note: "来源：用户明确增加设备码；Microsoft 支持跳转回调与设备码两条新增/重新授权路径，统一获取并加密保存令牌；复用 t054 会话绑定与最终保存；不做 Microsoft IMAP 或迁移; 2026-10-25T02:00:57+08:00 用户明确授权补归档；直接 main 执行提交 87d69ac75d781bc0337f2f746291868b799f8329；历史双路 Review 指纹 42658742333b6b92 已核实；无 attempt，不伪造 ledger/handoff"
---

> **归档勘误（2026-10-27 补，不改写历史正文）**：本文复用 t054 的部分中，仅 Microsoft 侧仍有效；Google OAuth / Gmail API 已由 p055 于 2026-10-26 整体下线，当前唯一 Google 路径为 IMAP 应用专用密码，权威位置见 `docs/specs/account_connection.md` 的 2026-10-26 节。

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- `2026-10-24`：官方确认 Microsoft 支持授权码跳转回调；Client ID 来自 Entra 注册，Refresh Token 由回调换取。复用 t054，full review。当前运行 DB 无 Microsoft IMAP，用户确认不考虑迁移。
- `2026-10-24`：用户明确要求增加设备码流程。范围扩展为浏览器回调和设备码两条新增/重新授权路径，补充轮询/取消/过期与公共客户端配置 AC；“离线权限”由程序自动处理，界面使用后台同步说明。
- 创建期仅写本批 task 与派生索引；不 start、不改生产代码，创建 commit 待用户确认。
- 2026-10-24：沿用用户直接 main 顺序执行授权；t054 执行 commit `e1dee25` 为 diff anchor，preflight --allow-backlog --require-verified PASS。不伪造 worktree/attempt，保留真实 front matter。
- 先建立 Microsoft metadata、PKCE、Graph 身份、旧账户重新授权、设备码间隔/取消/竞争测试，原实现 8 failed / 3 passed（`.scratch/t055_red.log`）；随后接通两条流程。保留 Google 原测试，发现跨供应商回调误删 state 时修复实现，未修改其预期。
- 协议核实：微软官方设备码、回调登记和 Graph /me 文档；localhost 忽略端口规则不适用于 127.0.0.1；设备码无 verification_uri_complete，Access Token 不透明。
- 实现分工：共享 oauth_flow 生命周期/会话绑定/保存；Google 协议抽至 google_oauth，Microsoft 身份与授权码在 microsoft_oauth，设备码申请/到期轮询在 device_oauth。复用现有 HTTP、加密凭据和事务边界，不引入第二套 OAuth SDK 缓存或独立后台调度框架。
- 设备轮询由原认证会话带 CSRF 的 POST 驱动；同一持久化流程锁覆盖间隔检查与 HTTP 请求，slow_down/429 调整到期时间。取消/退出/过期/迟到成功拒绝；长码不回显，所有 OAuth API no-store。
- 真实 API/PG/供应商 HTTP 与独立 Electron 验证两家动态 loopback、无 Cookie 回调、系统外链、焦点恢复及最终保存；真实外部应用注册、账号登录和管理员同意未执行。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-24T19:15:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t055_code_f001|important|已修|metadata 默认仅用于新账户；已有账户不自动改类型，提交只写用户显式选择。Graph/Gmail 原样保存、移组、显式升级组件测试与真实 PG 回归闭环；未弱化后端 Secret 校验。|`src/frontend/src/components/settings_account_form.tsx`、`microsoft_account_form.test.tsx`、`tests/mail_core/test_microsoft_oauth.py`|

### Round 2 (2026-10-24T23:48:02+08:00)

Round 2 零 finding；code/test 均 PASS，最终指纹 `12e66374e938defc`，独立重算一致。

### Round 3 (2026-10-24T23:49:39+08:00)

Round 3 零 finding；仅补齐 account_connection spec 索引关联，code/test 均 PASS，最终指纹 `42658742333b6b92`，其余交付与 Round 2 完全一致。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：AC-001 至 AC-016 全部满足。真实 Microsoft/Google 账号授权未执行。
- 测试：最终 OAuth 定向后端 39 passed，含真实 API/隔离 PG/供应商 HTTP 与 Google/Microsoft 独立 Electron；最终前端 42 文件 302 passed，TypeScript/build/lint/OpenAPI/CSS token 检查通过；桌面测试与 packaged PG 冒烟通过；模板契约 149 passed / 1 skipped。完整后端 560 passed（收集早于晚补项），后续新增边界由最终定向 39 passed 及旧账户 PG 2 passed 覆盖。
- 黑盒：账户专项 UI 5 passed、默认 UI 16 passed；最终账户专项 UI 5 passed、真实全栈 8 passed（最终修复后串行复跑）。微软桌面使用真实生产 SPA、localhost 动态端口、生产外链处理器、无 Cookie 回调、焦点恢复与最终保存。
- review：Round 3 code/test 均 PASS，0 未解决 finding；最终指纹 `42658742333b6b92`。
- 流程：用户授权直接 main，状态 front matter 保留真实 backlog；未虚构 worktree/attempt，不执行要求登记 worktree 的 finish/cleanup。不部署、不 push，不操作真实外部应用或账号。

|AC|实际证据|
|---|---|
|AC-001|新增/编辑浏览器与设备码入口、组件/E2E POST/PATCH、旧 Graph 重新授权 PG 测试|
|AC-002|客户端类型/Secret/租户校验；设备码无 Secret/回调组件/API 测试|
|AC-003|微软 localhost 动态端口元数据、真实 Electron/API/PG/HTTP 回调测试|
|AC-004|官方 authority、PKCE、Graph scopes、设备 grant 请求形状断言|
|AC-005|Graph /me id+mail 与 inbox 访问验证；缺邮箱/ID/邮箱许可拒绝测试|
|AC-006|同邮箱异 ID 拒绝、旧 Graph 无 ID/旧凭据撤销后重授权、客户端/租户不符拒绝|
|AC-007|共享会话/epoch/状态/原子保存；跨供应商、重复消费、设备并发与迟到成功拒绝|
|AC-008|拒绝/管理员同意/invalid client/回调/租户错误脱敏，混合手动凭据拒绝且结果不消费|
|AC-009|新增/编辑帮助组件测试、Entra 注册步骤、Secret value 与注册权限/管理员说明|
|AC-010|帮助区分 Client ID/Refresh Token，设备码用户操作步骤及后台访问自动申请|
|AC-011|既有 provider_account_forms Microsoft IMAP 拒绝回归，新增仅 Graph|
|AC-012|320px 浏览器交互、白名单/no-store/错误脱敏、旧账户分组与同步偏好保留|
|AC-013|设备码短码/验证地址/复制/打开/取消/倒计时；无 Origin 配置成功测试|
|AC-014|interval、pending、slow_down、HTTP429 Retry-After、过期/epoch/取消/迟到成功、同轮并发单次交换|
|AC-015|受信验证地址白名单与无长码响应断言；设备码新增和重新授权身份核对|
|AC-016|公共客户端配置拒绝指引、切换方式 UI、同一 Client ID 多邮箱与自动 offline_access 帮助|

### 结果摘要

- Microsoft Graph 浏览器授权码/PKCE 与设备码登录接通统一加密状态、身份核实及最终确认保存；保留合法命名凭据更新和所有既有账户。
- 微软 Web/桌面回调与设备码配置帮助、客户端/账号类型/租户、错误反馈及短码复制操作。
- 无数据库表结构变更；身份和租户使用 Account.config，短期秘密使用现有加密 CredentialSecret。不迁移邮件身份，不恢复 Microsoft IMAP。

## 直接 main 执行归档补记（2026-10-25T02:00:57+08:00）

- 用户本轮明确要求已完成任务归档。本次将状态由 backlog 修正为 done 并迁入 archive；正文此前“保留 backlog”均为执行时流程限制记录，由本节更新。
- 实际执行分支：main；执行 commit：`87d69ac75d781bc0337f2f746291868b799f8329`；diff anchor：`e1dee2549e35486fbb36172579bf0d6564f2dedc`。
- 已在执行 commit 快照重算并核实 code/test 最终 PASS，历史 reviewed_scope：`42658742333b6b92`；spec 与 Review 原件保持不变。
- 本任务直接在 main 完成，未创建登记 worktree/attempt，不补造 execution_id、handoff 或 dispatch ledger。此为用户授权的一次性文档状态维护，不宣称正常 worktree lifecycle 已执行。
