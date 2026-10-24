---
tid: "t053"
slug: "provider_account_forms"
title: "按邮箱供应商定制添加与编辑账户表单"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "来源：用户确认；供应商定制新增/编辑表单、获取凭据帮助图标与弹窗、下线 Microsoft IMAP；当前运行 DB 25 Graph/9 IMAP，未发现 Microsoft IMAP；Google/Microsoft 跳转回调分别由 t054/t055 交付"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- `2026-10-24`：用户要求设置页添加与编辑账户按供应商定制；官方依据和供应商矩阵写入 spec，统一为一个可验收账户配置交付。
- 查重依据：仅 main 分支，无登记 worktree；t051、t052 是文件夹任务，无等价账户表单 backlog。
- 用户补充后：t053 交付表单/帮助弹窗/Microsoft IMAP 下线；t054/t055 分别实现 Google/Microsoft 跳转与回调，全部 full review。
- 只读核对当前运行 DB：25 Graph、9 IMAP，未发现 Microsoft IMAP。用户确认无须迁移，不增加迁移范围。
- 创建期仅落盘本 task 与派生索引，不改生产实现，不 start；创建 commit 待用户确认。
- 执行期（直接 main）：用户明确要求在 `main` 分支按顺序执行 t053 → t054 → t055。实现 `src/mail_core/accounts/connection.py`、`credential_edit` 行锁与只读缓存、`AccountDialog` 供应商矩阵、`CredentialHelp` 帮助弹窗，并在 API/service/factory/legacy import 全路径拒绝 Microsoft IMAP。
- Round 1/2/3 Review 闭环：修复 `provider_profile` 与 `imap_user`/`username` 类型校验、只读 `env:` 凭据刷新内存缓存与轮换 RT 保留、legacy import Microsoft IMAP 拒绝预检、Google `gmail.modify` 权限说明、手填独立登录名保留，以及补齐权限帮助、Zoho 与跨供应商草稿隔离测试。Round 3 双路 review PASS（`reviewed_scope=4072f20530f238a5`）。
- 直接 main 流程限制：`task.py start`/`finish` 要求独立 task worktree；按既有 direct-main 约定保留 front matter `status: backlog`，不伪造 worktree/attempt。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-24T14:10:51+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t053_code_f001|important|已修|限制 `provider_profile` 必须为字符串并在连接校验入口拦截非法类型。|`src/mail_core/accounts/connection.py:36`|
|t053_code_f002|important|已修|只读 `env:` 凭据刷新允许只读落盘并在进程内缓存最新 Access Token 与轮换后的 Refresh Token。|`src/mail_core/accounts/credentials.py:280`、`src/mail_core/providers/oauth.py:107`|
|t053_code_f003|important|已修|移除旧库迁移脚本 Microsoft IMAP 默认主机并在写入前统一预检拒绝 Microsoft IMAP。|`scripts/migrate_from_legacy_db.py:318`|
|t053_code_f004|important|已修|Google OAuth 帮助补充 `gmail.modify` 范围说明且不额外要求发信或全量范围。|`src/frontend/src/lib/account_providers.ts:5`|
|t053_code_f005|important|已修|`changeVendor` 不再清空已手填的 IMAP 登录名。|`src/frontend/src/components/settings_account_form.tsx:39`|
|t053_test_f001|important|已修|新增参数化组件测试打开真实 Google/Microsoft 帮助弹窗验证权限与持续访问说明。|`src/frontend/src/components/provider_account_form.test.tsx:75`|
|t053_test_f002|important|已修|新增七供应商参数化测试并验证 Zoho 个人/付费企业主机、数据中心、计划限制与 2FA/SAML 说明。|`src/frontend/src/components/provider_account_form.test.tsx:53`|
|t053_test_f003|important|已修|新增跨供应商/协议切换与关闭重开测试，验证秘密草稿清空、提交载荷隔离及浏览器存储无残留。|`src/frontend/src/components/provider_account_form.test.tsx:86`|

### Round 2 (2026-10-24T14:14:22+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t053_code_f006|important|已修|连接校验入口强制检查 `imap_user`/`username` 为字符串，支持空串清除独立登录名，并补齐 PG 事务回滚与列表可读回归。|`src/mail_core/accounts/connection.py:42`、`tests/mail_core/test_provider_accounts_pg.py:83`|

### Round 3 (2026-10-24T14:32:34+08:00)

Round 3 零 finding；code/test reviewer 均 PASS，`reviewed_scope=4072f20530f238a5`。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：AC-001 至 AC-018 全部满足。task front matter 因直接 main 流程限制保留 backlog。
- 测试：模板契约 149 passed / 1 skipped；后端定向单测 32 passed、真实隔离 PG 套件 41 passed；前端 41 文件 289 passed，`tsc -b`、`vite build`、`oxlint`、`openapi:check`、CSS token 检查全部通过。
- 黑盒：浏览器 UI E2E（`provider_account_forms.spec.ts`、`settings_workspace.spec.ts`）3 passed；真实全栈 E2E（`full_stack.spec.ts`）8 passed。
- review：代码与测试 reviewer Round 3 PASS，0 未解决 finding；最终 `reviewed_scope=4072f20530f238a5`。
- AC 证据：

|AC|实际证据|
|---|---|
|AC-001|`src/frontend/src/lib/account_providers.ts`、`src/frontend/src/components/settings_account_form.tsx`、`src/frontend/src/components/provider_account_form.test.tsx`|
|AC-002|`src/frontend/src/lib/account_providers.ts`、`src/frontend/src/components/provider_account_form.test.tsx`、`tests/mail_core/test_provider_account_forms.py`|
|AC-003|`src/frontend/src/lib/account_providers.ts`、`src/mail_core/mail/application/accounts.py`、`tests/mail_core/test_provider_accounts_pg.py`|
|AC-004|`src/frontend/src/components/settings_account_form.tsx`、`src/mail_core/accounts/connection.py`、`tests/mail_core/test_provider_account_forms.py`|
|AC-005|`src/frontend/src/lib/account_providers.ts`、`src/frontend/src/components/settings_account_form.tsx`、`src/frontend/src/components/provider_account_form.test.tsx`|
|AC-006|`src/frontend/src/lib/account_providers.ts`、`src/frontend/src/components/credential_help.tsx`、`src/frontend/src/components/provider_account_form.test.tsx`|
|AC-007|`src/frontend/src/lib/account_providers.ts`、`src/frontend/src/components/settings_account_form.tsx`、`src/frontend/src/components/provider_account_form.test.tsx`|
|AC-008|`src/frontend/src/components/settings_account_form.tsx`、`src/mail_core/providers/factory.py`、`tests/e2e/full_stack.spec.ts`|
|AC-009|`src/frontend/src/components/settings_account_form.tsx`、`src/frontend/src/components/SettingsModal.test.tsx`、`tests/mail_core/test_provider_accounts_pg.py`|
|AC-010|`src/mail_core/api/accounts.py`、`src/mail_core/mail/application/accounts.py`、`tests/mail_core/test_provider_accounts_pg.py`|
|AC-011|`src/mail_core/accounts/connection.py`、`src/mail_core/accounts/service.py`、`tests/mail_core/test_provider_accounts_pg.py`|
|AC-012|`src/mail_core/accounts/credentials.py`、`src/mail_core/providers/oauth.py`、`tests/mail_core/test_provider_accounts_pg.py`、`tests/mail_core/test_provider_account_forms.py`|
|AC-013|`src/frontend/src/components/settings_account_form.tsx`、`src/frontend/src/components/provider_account_form.test.tsx`|
|AC-014|`src/mail_core/accounts/connection.py`、`src/mail_core/api/accounts.py`、`tests/mail_core/test_provider_account_forms.py`、`tests/mail_core/test_provider_accounts_pg.py`|
|AC-015|`src/frontend/src/components/settings_account_form.tsx`、`tests/e2e/provider_account_forms.spec.ts`|
|AC-016|`src/frontend/src/components/credential_help.tsx`、`tests/e2e/provider_account_forms.spec.ts`|
|AC-017|`src/frontend/src/lib/account_providers.ts`、`src/frontend/src/components/credential_help.tsx`、`src/frontend/src/components/provider_account_form.test.tsx`|
|AC-018|`src/mail_core/accounts/connection.py`、`src/mail_core/providers/factory.py`、`scripts/migrate_from_legacy_db.py`、`tests/mail_core/test_provider_account_forms.py`|

### 结果摘要

- 完成供应商定制添加与编辑账户表单、获取凭据帮助弹窗、OAuth 命名凭据局部更新与行锁串行化，以及 Microsoft IMAP 全路径下线。
- 更新 `docs/specs/account_connection.md`、`docs/specs_index.md`、`docs/blueprint/{architecture,conventions,testing}.md` 与 OpenAPI/TypeScript 生成契约。
