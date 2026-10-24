---
tid: "t054"
slug: "google_oauth_callback"
title: "支持 Google OAuth 跳转回调与账户重新授权"
status: "done"
branch: "main"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "4ef9bf7ada1aaa9b67ea67dfccc1dfcd9b98d10a"
depends_on: "t053"
conflicts_with: ""
note: "来源：用户补充；Google 保留 IMAP 应用密码并新增 OAuth 授权码跳转回调，覆盖网页与 Electron；依赖 t053; 2026-10-25T02:00:57+08:00 用户明确授权补归档；直接 main 执行提交 e1dee2549e35486fbb36172579bf0d6564f2dedc；历史双路 Review 指纹 82374890bf0a9881 已核实；无 attempt，不伪造 ledger/handoff"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- `2026-10-24`：用户明确增加 Google 登录跳转与回调，独立交付网页/桌面新增及重新授权。依赖 t053，full review；官方协议已核实，尚未实施。
- 创建期仅写本批 task 与派生索引；不 start、不改生产代码，创建 commit 待用户确认。
- 2026-10-24：沿用用户此前明确授权，在 main 继续 t054 → t055。工具链仅支持 worktree，保留真实 front matter，不伪造 attempt。
- 首轮代码 5 条、测试 4 条 finding 逐项修复；补生产 HTTP、恢复草稿、重新授权 PATCH、过期、取消与 Electron 真实 SPA 集成测试。
- 新增跨流程同码并发复现：原实现两次回调均 200；使用凭据引用 advisory lock 原子领取授权码，阻止缺行锁竞争。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-24T15:20:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t054_code_f001|important|已修|修正 window.open 返回值判断，Electron 覆盖 deny 行为|`src/frontend/src/components/settings_account_form.tsx`|
|t054_code_f002|important|已修|pending/authorized 均检查有效期并清理结果|`src/mail_core/accounts/oauth_flow.py`|
|t054_code_f003|important|已修|公共客户端不继承旧 Secret，保存移除旧 Secret|`src/mail_core/accounts/oauth_flow.py`|
|t054_code_f004|important|已修|显式检查剪贴板 API，失败提示手动复制|`src/frontend/src/components/settings_account_form.tsx`|
|t054_code_f005|minor|已修|移除旧 expires_at，仅清理当前流程活跃指针|`src/mail_core/accounts/oauth_flow.py`|
|t054_test_f001|important|已修|补重新授权 PATCH、活跃草稿恢复和隔离测试|`src/frontend/src/components/provider_account_form.test.tsx`|
|t054_test_f002|important|已修|补生产 urllib、错误脱敏、客户端不匹配与重试|`tests/mail_core/test_google_oauth_callback.py`|
|t054_test_f003|important|已修|补独立 Electron 真实 SPA/API/PG/HTTP 与配置测试|`src/desktop/oauth_integration.test.js`|
|t054_test_f004|minor|已修|补复制、编辑帮助、鉴权/CSRF、同步恢复测试|`tests/mail_core/test_google_oauth_callback.py`|

### Round 2 (2026-10-24T18:40:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t054_code_f006|important|已修|OAuth 移组先锁 sidebar 再锁账户，与普通移组同序；真实 PG 并发回归|`src/mail_core/mail/application/accounts.py`|
|t054_code_f007|important|已修|active 指针读、比较、清空及 start 写入均使用相同引用锁|`src/mail_core/accounts/oauth_flow.py`|
|t054_code_f008|minor|已修|非对象 token 响应返回固定脱敏失败，不调用其 get 方法|`src/mail_core/accounts/oauth_flow.py`|
|t054_code_f009|important|已修|Compose API 传递可信 Origin，配置模板及部署指南说明登记步骤|`docker-compose.mail-core.yml`|

### Round 3 (2026-10-24T18:45:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t054_code_f010|important|已修|所有 OAuth 保存先锁 sidebar，再锁账户/流程/指针；新增与重新授权并发回归|`src/mail_core/mail/application/accounts.py`|
|t054_test_f005|important|已修|补齐 Event 和 ThreadPoolExecutor 导入并实际执行 PG 回归|`tests/mail_core/test_google_oauth_callback.py`|
|t054_test_f006|important|已修|并发两事务均须成功，检查账户分组和新凭据，任何异常均失败|`tests/mail_core/test_google_oauth_callback.py`|

### Round 4 (2026-10-24T18:50:00+08:00)

Round 4 零 finding，code/test 均 PASS。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：AC-001 至 AC-013 全部满足。真实 Google 账号授权未执行，使用真实应用/API/PG 与隔离供应商 HTTP 验证。
- 测试：最终定向后端（OAuth、凭据、账户及分组，含独立 Electron）66 passed；此前完整后端 532 passed / 1 显式 Electron 模式 skipped；前端 41 文件 293 passed；TypeScript/build/lint/OpenAPI/CSS token 核验通过；桌面测试及 packaged PG 冒烟通过；模板契约 149 passed / 1 skipped。
- 黑盒：UI E2E 16 passed；最终真实全栈 E2E 8 passed。首轮与 UI E2E 共用产物目录导致 trace ENOENT，串行重跑闭环。Electron 使用生产 SPA、外链处理器、真实 API/隔离 PG、供应商 HTTP 夹具，覆盖动态端口、无 Cookie 回调、焦点恢复及最终保存。
- review：Round 4 code/test 均 PASS，0 未解决 finding；最终指纹 `82374890bf0a9881`。独立重算一致。
- 流程：沿用用户“直接 main，模仿 task-run”授权；不创建虚假 worktree/attempt，front matter 仍 backlog，未调用要求登记 worktree 的 finish/cleanup。t053 执行 commit `4ef9bf7` 作为本 task diff anchor。preflight --allow-backlog --require-verified PASS，仅脏工作区警告。
- 依赖评估：复用现有 stdlib OAuth HTTP、CredentialStore 与 SQLAlchemy 事务边界，避免额外 OAuth SDK 引入第二套秘密缓存/会话状态；PKCE、一次性消费、身份核验与并发均直接测试生产逻辑。

|AC|实际证据|
|---|---|
|AC-001|`settings_account_form.tsx`、组件与浏览器新增/重新授权保存测试|
|AC-002|metadata/start 配置校验、命名字段/复制组件测试、Compose 配置解析|
|AC-003|受信 Origin/动态端口后端测试、真实 Electron 与部署指南|
|AC-004|授权请求 PKCE/scope/offline 参数及缺权限/Refresh Token 拒绝测试|
|AC-005|会话隔离、epoch、CSRF、过期/取消与最终保存拒绝测试|
|AC-006|同 state 并发、跨流程同 code 竞争及重放真实 PG 回归|
|AC-007|独立 Electron 外部无 Cookie HTTP 回调，账户最终确认保存|
|AC-008|真实 token/profile HTTP 传输、重复邮箱/异邮箱/IMAP 切换拒绝测试|
|AC-009|active 草稿与分组恢复、浏览器返回恢复、最终 POST/PATCH 与取消|
|AC-010|白名单状态、日志/浏览器存储脱敏与 callback CSP/no-store/no-referrer|
|AC-011|urllib 错误、异常 JSON、拒绝/过期、弹窗拦截、取消后重发|
|AC-012|后台轮换保留、公共 Secret 清理、有效期清理、三类并发 PG 回归|
|AC-013|新增/编辑帮助弹窗及官方步骤说明组件/浏览器测试|

### 结果摘要

- Google OAuth 授权码、PKCE、身份核验、短期加密状态、跨进程原子消费与最终确认保存；保留 IMAP 与已有命名凭据。
- 标准 Compose 可信 Origin 配置、Web/桌面回调区别、部署说明与生成接口契约。
- 未创建外部 OAuth 应用，未执行真实第三方账号授权、部署或 push。

## 直接 main 执行归档补记（2026-10-25T02:00:57+08:00）

- 用户本轮明确要求已完成任务归档。本次将状态由 backlog 修正为 done 并迁入 archive；正文此前“保留 backlog”均为执行时流程限制记录，由本节更新。
- 实际执行分支：main；执行 commit：`e1dee2549e35486fbb36172579bf0d6564f2dedc`；diff anchor：`4ef9bf7ada1aaa9b67ea67dfccc1dfcd9b98d10a`。
- 已在执行 commit 快照重算并核实 code/test 最终 PASS，历史 reviewed_scope：`82374890bf0a9881`；spec 与 Review 原件保持不变。
- 本任务直接在 main 完成，未创建登记 worktree/attempt，不补造 execution_id、handoff 或 dispatch ledger。此为用户授权的一次性文档状态维护，不宣称正常 worktree lifecycle 已执行。
