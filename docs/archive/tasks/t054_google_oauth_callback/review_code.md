# Task review t054（reviewer_focus: 代码）

- task：`t054_google_oauth_callback`
- spec：`docs/tasks/t054_google_oauth_callback/spec.md`
- diff_anchor：`4ef9bf7ada1aaa9b67ea67dfccc1dfcd9b98d10a`
- target：`git -C '<local-path>' diff 4ef9bf7ada1aaa9b67ea67dfccc1dfcd9b98d10a`
- round：1
- reviewed_at：2026-10-24T15:20:00+08:00

reviewed_scope: 4d2e04d57e73ba5e

## Findings

### t054_code_f001 - `window.open` 传入 `noopener,noreferrer` 恒返回 `null` 导致网页与桌面端始终误报弹窗被拦截

- 严重度：important
- 锚点：AC-001、AC-011（行为缺陷：用户在真实浏览器或 Electron 桌面端点击“使用 Google 登录 / 重新授权”成功拉起授权页后，界面始终误报“浏览器拦截了授权窗口”）
- 位置：`src/frontend/src/components/settings_account_form.tsx:196-197`（关联 `src/desktop/main.js:187-190`）
- 问题：`startGoogleOAuth` 执行 `const opened = typeof window.open === 'function' ? window.open(started.auth_url, '_blank', 'noopener,noreferrer') : null; if (!opened) setPopupBlockedUrl(started.auth_url)`。按 WHATWG HTML 标准，当 `windowFeatures` 包含 `noopener` 或 `noreferrer` 时，即使浏览器成功打开新标签页，`window.open` 也恒返回 `null`（已在真实 Chromium 中复现验证：`window.open("about:blank", "_blank", "noopener,noreferrer") === null`）；同时在 Electron 桌面端，`src/desktop/main.js:187-190` 的 `setWindowOpenHandler` 调用 `shell.openExternal(target)` 后返回 `{ action: 'deny' }`，同样使渲染进程 `window.open` 返回 `null`。这导致所有真实网页与桌面环境下点击登录按钮都会误展示“浏览器拦截了授权窗口，请点击此处打开 Google 授权页面”（E2E 测试因通过 `addInitScript` 覆写 `window.open` 返回假对象而掩盖了该缺陷）。
- 建议：Web 端调用 `const opened = window.open(started.auth_url, '_blank')`，若返回非空 `WindowProxy` 则立即执行 `try { opened.opener = null } catch {}` 剥离 opener，仅在返回 `null` 时提示弹窗被拦截；Electron 桌面端（`getDesktopPlatform() !== null` 或 `oauthMeta?.runtime_mode === 'desktop'`）由主进程 `shell.openExternal` 拉起系统浏览器，不应将 `window.open` 返回 `null` 判定为弹窗拦截报错（可仅提供普通“重新打开授权页面”辅助链接）。

### t054_code_f002 - 已完成回调（`authorized`）但超过 10 分钟有效期的流程在状态查询与活跃恢复中未转为 `expired`

- 严重度：important
- 锚点：AC-005、AC-009、AC-011（行为缺陷：回调已完成暂存但超过 10 分钟未保存的流程，查询状态与活跃流程接口仍返回 `status: "authorized"`，前端恢复为成功态引导保存，点击保存时后端报错 400 回滚，过期流程与暂存凭据常驻无法闭环）
- 位置：`src/mail_core/accounts/oauth_flow.py:596-598`、`src/mail_core/accounts/oauth_flow.py:646-649`
- 问题：`_public_flow_view` 第 596 行仅检查 `if status == "pending" and now > expires_at:`。当流程已完成回调（`status == "authorized"`，内含 `staged_credentials`）但用户在 10 分钟后才返回或重新打开弹窗（`now > expires_at`）时：
    1. `GET /api/accounts/oauth/flows/{flow_id}` 仍返回 `status: "authorized"` 而非 `"expired"`，前端无法展示 `AC-011` 要求的过期错误提示；
    2. `GET /api/accounts/oauth/active` 第 647 行因 `view["status"]` 仍为 `"authorized"`，每次打开添加/编辑弹窗或从 `/#oauth-return` 返回都会恢复该已过期流程并提示“已完成 Google 授权…请点击下方添加/保存修改”；
    3. 用户点击保存时，`consume_oauth_flow_for_create`（第 694 行）/ `consume_oauth_flow_for_reauthorize`（第 746 行）抛出 `ValueError("OAuth 授权结果已过期，请重新发起授权")` 并触发事务回滚，`oauth_flow:{flow_id}` 与 `oauth_active:{sess_key}` 不会被删除，暂存凭据持续残留。
- 建议：在 `_public_flow_view` 中将过期判定扩展为 `if status in ("pending", "authorized") and now > expires_at:`；并在 `get_oauth_flow_status` / `get_active_oauth_flow` 发现流程已过期时清理 `staged_credentials` 与 `oauth_active` / `oauth_state` 引用（或直接清理过期流程记录）。

### t054_code_f003 - 重新授权切换为公共客户端（`public`）时仍回退复用旧 `client_secret` 导致换码误发密钥且旧密钥无法清除

- 严重度：important
- 锚点：AC-002、AC-012（行为缺陷：编辑曾保存 `client_secret` 的 Gmail 账户并将客户端类型改为 `public`、留空 `Client Secret` 重新授权时，后端仍将旧 `client_secret` 发往 Google token 端点并写入 `staged`，导致第 787 行清除公共客户端旧密钥的逻辑恒不可达）
- 位置：`src/mail_core/accounts/oauth_flow.py:254-255`、`src/mail_core/accounts/oauth_flow.py:463-464`、`src/mail_core/accounts/oauth_flow.py:570-571`、`src/mail_core/accounts/oauth_flow.py:787-788`
- 问题：`start_oauth_flow` 第 255 行 `csecret = (client_secret or "").strip() or str(saved_creds.get("client_secret") or "").strip()` 未区分 `effective_client_type`。当既有账户原先存有 `client_secret`，用户编辑时切换为 `public` 客户端（或更换为新的公共客户端 `client_id`）并留空 `Client Secret` 发起重新授权时，`csecret` 会无条件继承旧 `saved_creds["client_secret"]`，进而：
    1. `complete_oauth_callback` 第 464 行在公共客户端换码请求中附带旧 `client_secret`；
    2. `complete_oauth_callback` 第 571 行将旧 `client_secret` 写入 `staged["client_secret"]`；
    3. `consume_oauth_flow_for_reauthorize` 第 787 行 `if client_type == "public" and "client_secret" not in staged: merged.pop("client_secret", None)` 因 `"client_secret" in staged` 恒成立而永远无法执行。
- 建议：在 `start_oauth_flow` 中，仅当 `effective_client_type == "confidential"` 时才在 `client_secret` 留空时回退读取 `saved_creds.get("client_secret")`；当 `effective_client_type == "public"` 且未显式提交 `client_secret` 时保持 `csecret = ""`。

### t054_code_f004 - 复制回调地址使用可选链 `navigator.clipboard?.writeText` 在剪贴板不可用时静默误报复制成功

- 严重度：important
- 锚点：AC-002（行为缺陷：非安全上下文或 `navigator.clipboard` 缺失时，点击“复制回调地址”未写入剪贴板却显示“已复制回调地址”，同时违反 `docs/blueprint/conventions.md` 八.2 禁止误报成功的约定）
- 位置：`src/frontend/src/components/settings_account_form.tsx:278-280`
- 问题：第 279 行 `try { await navigator.clipboard?.writeText(displayedRedirectUri); setCopyTip('已复制回调地址') } catch { setCopyTip('请手动复制上方回调地址') }` 使用了可选链 `?.`。当 `navigator.clipboard` 或 `navigator.clipboard.writeText` 为 `undefined` 时，`await undefined` 不会抛出异常，代码直接向下执行 `setCopyTip('已复制回调地址')`，向用户误报已复制成功。
- 建议：与 `UiReferenceOverlay.tsx` / `ErrorBoundary.tsx` 保持一致，先显式判断 `if (!navigator.clipboard?.writeText) throw new Error('clipboard unavailable')`，再调用 `await navigator.clipboard.writeText(displayedRedirectUri)`。

### t054_code_f005 - 重新授权合并凭据未在缺省 `expires_in` 时清除旧 `expires_at`，且消费流程时无条件删除会话 `oauth_active` 指针

- 严重度：minor
- 锚点：AC-012（多流程隔离与令牌缓存字段一致性细节）
- 位置：`src/mail_core/accounts/oauth_flow.py:723-724`、`src/mail_core/accounts/oauth_flow.py:785-791`、`src/mail_core/accounts/oauth_flow.py:802-803`
- 问题：
    1. `consume_oauth_flow_for_reauthorize` 第 785-786 行执行 `merged = dict(saved); merged.update(staged)`，若本次 token 响应未返回 `expires_in`（`"expires_at" not in staged`），`merged` 会保留旧 `saved["expires_at"]` 时间戳并与新 `access_token` 错配；
    2. `consume_oauth_flow_for_create`（第 724 行）与 `consume_oauth_flow_for_reauthorize`（第 803 行）直接删除 `oauth_active:{session_binding_key(principal)}` 而未像 `cancel_oauth_flow`（第 668-670 行）那样核对 `active.get("flow_id") == clean_id`，若同一会话并发存在另一个未完成流程，其活跃恢复指针会被连带删掉。
- 建议：在 `consume_oauth_flow_for_reauthorize` 中当 `"expires_at" not in staged` 时执行 `merged.pop("expires_at", None)`；在消费流程清理 `oauth_active` 时仅当 `active.get("flow_id") == clean_id` 时才删除该指针。

## 结论

- 本轮新发现：5 条（4 条 important，1 条 minor）
- 未进表的提示：
    - 文件过大提示（按降级规则仅在结论段列出；生成文件 `schemas/openapi.json` 与 `src/frontend/src/api/generated/schema.ts` 按规则排除）：
        - `src/mail_core/accounts/oauth_flow.py`：805 行（新建实现源码 ≥ 800 行，建议后续按 metadata/start、callback、consume 拆分模块）
        - `src/mail_core/mail/application/accounts.py`：406 行（实现源码 ≥ 400 行，本 task 净增 35 行）
    - 圈复杂度提示（本 task 新建或触及函数 CC ≥ 10）：
        - `src/mail_core/accounts/oauth_flow.py`：`complete_oauth_callback` (CC=62)、`consume_oauth_flow_for_reauthorize` (CC=37)、`start_oauth_flow` (CC=30)、`consume_oauth_flow_for_create` (CC=23)、`get_oauth_metadata` (CC=20)、`_public_flow_view` (CC=11)、`_load_account_for_reauthorize` (CC=10)、`_friendly_oauth_error` (CC=10)
        - `src/mail_core/accounts/connection.py`：`validate_connection` (CC=55)
        - `src/mail_core/mail/application/accounts.py`：`_to_account_dto` (CC=23)
        - `src/mail_core/accounts/credentials.py`：`credential_edit` (CC=17)
        - `src/mail_core/api/accounts.py`：`api_create_account` (CC=11)
    - 七视角正交审阅确认：
        - 安全：已核查 PKCE S256、`secrets.compare_digest`、会话 `csrf_token` 摘要绑定、`session_epoch` 校验、回调 CSP/no-store/no-referrer/replaceState、固定 `/#oauth-return` 防开放重定向及 `uvicorn.access` 日志脱敏。
        - 正确性：发现 `f001`、`f002`、`f003`、`f004`、`f005`。
        - 公开契约与 Breaking：已核验 `export_openapi.py --check` 与 `npm run openapi:check` 零漂移，新增字段向后兼容。
        - 性能与资源：轮询定时器与窗口事件在卸载及状态收敛时正确清理，外部令牌与 profile 请求均设超时。
        - 架构与可维护性：分层符合 `api -> application -> accounts/credentials`，过大文件与高圈复杂度函数已列示。
        - 健壮性与可观测：供应商异常经 `_friendly_oauth_error` 与 `safe_error` 脱敏转换，账户保存与凭据消费在同一数据库事务内提交或回滚。
        - 文档与规格一致性：`docs/blueprint/{architecture,conventions,testing}.md` 与 `docs/specs/account_connection.md` 已同步更新。

### AC 复验方式

- `AC-001`：`re_verified` — 审阅 `src/frontend/src/components/settings_account_form.tsx:154-204,275-289` 并独立运行 Vitest 与 Playwright `provider_account_forms.spec.ts`；同时在真实 Chromium 中复验发现 `window.open(..., 'noopener,noreferrer')` 恒返回 `null` 导致误报拦截（见 `t054_code_f001`）。
- `AC-002`：`re_verified` — 审阅 `src/mail_core/accounts/oauth_flow.py:246-266` 与 `src/frontend/src/components/settings_account_form.tsx:158-166,274-290` 并运行前后端测试；发现切换到 `public` 时旧 `client_secret` 未隔离（`t054_code_f003`）及 `navigator.clipboard?.writeText` 缺失时误报成功（`t054_code_f004`）。
- `AC-003`：`re_verified` — 审阅 `src/mail_core/accounts/oauth_flow.py:111-183` 与 `src/desktop/startup.js:101-103`，独立运行 `test_oauth_metadata_distinguishes_web_and_desktop_without_trusting_headers_or_query` 与桌面端单测确认通过。
- `AC-004`：`re_verified` — 审阅 `src/mail_core/accounts/oauth_flow.py:268-295,502-508,533-537` 与 `src/frontend/src/lib/account_providers.ts:5`，独立运行 `test_oauth_start_reports_missing_fields_and_generates_pkce_s256` 与 `test_callback_rejects_invalid_provider_state_missing_code_replay_and_wrong_scope` 确认通过。
- `AC-005`：`re_verified` — 审阅 `src/mail_core/accounts/oauth_flow.py:88-109,591-650` 与 `src/mail_core/api/oauth_routes.py:118-196`，运行 PG 集成测试核验跨会话与登出 `session_epoch` 失效；发现 `authorized` 状态超时未转 `expired` 缺陷（`t054_code_f002`）。
- `AC-006`：`re_verified` — 审阅 `src/mail_core/accounts/oauth_flow.py:380-455` 与 `src/mail_core/accounts/credentials.py:282-313`，独立运行 `test_concurrent_callbacks_code_reuse_multi_flow_isolation_and_error_recovery_pg` 验证并发回调与行锁原子消费。
- `AC-007`：`re_verified` — 审阅 `src/mail_core/api/app.py:121-125` 与 `src/mail_core/api/oauth_routes.py:195-223`，运行 `test_full_google_oauth_create_reauthorize_session_isolation_and_concurrency_pg` 确认无 Cookie 回调仅暂存、不越权落库。
- `AC-008`：`re_verified` — 审阅 `src/mail_core/accounts/oauth_flow.py:185-211,509-563,676-805`，独立运行 PG 集成测试核验 `users.getProfile` 真实邮箱采用、重复邮箱拒绝、跨邮箱重新授权拒绝与 IMAP 账户拦截。
- `AC-009`：`re_verified` — 审阅 `src/frontend/src/App.tsx:95-99`、`src/frontend/src/components/SettingsModal.tsx:85-106`、`src/frontend/src/components/settings_account_form.tsx:85-108,214-259` 及后端事务消费逻辑，独立运行前后端单测与 E2E 测试。
- `AC-010`：`re_verified` — 审阅 `src/mail_core/api/oauth_routes.py:83-118,210-223`、`src/mail_core/logging_config.py:69-71`、`src/mail_core/security/redact.py:14-29`，独立运行 `test_callback_headers_url_scrubbing_and_log_redaction` 及 `uvicorn.logging.AccessFormatter` 实测确认查询串脱敏。
- `AC-011`：`re_verified` — 审阅 `src/mail_core/accounts/oauth_flow.py:359-373,430-563` 与前端错误展示逻辑；除 `t054_code_f001` 与 `t054_code_f002` 外其余错误分支均已由单测与 PG 集成测试验证。
- `AC-012`：`re_verified` — 审阅 `src/mail_core/accounts/oauth_flow.py:728-805` 与 `src/mail_core/mail/application/accounts.py:220-255`，运行 PG 集成测试验证后台令牌轮换并发不丢失与多流程隔离（附 `t054_code_f003`、`t054_code_f005` 修复建议）。
- `AC-013`：`re_verified` — 审阅 `src/frontend/src/lib/account_providers.ts:5`、`src/frontend/src/components/credential_help.tsx:1-19`、`src/frontend/src/components/settings_account_form.tsx:264,301`，独立运行 `provider_account_form.test.tsx` 与 E2E 测试验证通过。

`coverage = 13 / 13 (100%)`

- 总体判断：后端 OAuth PKCE 状态机、跨进程加密行锁、会话绑定与日志脱敏整体设计扎实，但存在 `window.open` `noopener,noreferrer` 恒返回 `null` 致真实环境始终误报弹窗拦截、已授权流程超时未转 `expired`、重新授权切换 `public` 客户端仍复用旧 `client_secret` 以及剪贴板可选链误报复制成功 4 项 important 缺陷，本轮判定 FAIL。
- 系统性 follow-up：无

verdict: FAIL

## Round 2 (2026-10-24T18:34:00+08:00)

reviewed_scope: 066ca8c4fdbd6b3a

### Findings

### t054_code_f006 - 重新授权移组与普通移组使用相反锁序，产生 PostgreSQL 死锁

- 严重度：important
- 锚点：AC-012（授权保存与编辑并发保持正确）及可观测行为缺陷：同一账户重新授权保存并修改分组，与另一窗口普通移组并发时，一方事务报 `DeadlockDetected`。
- 位置：`src/mail_core/mail/application/accounts.py:225`、`src/mail_core/mail/application/accounts.py:237`、`src/mail_core/accounts/service.py:117-119`。
- 问题：OAuth 分支先 `SELECT Account ... FOR UPDATE`，消费流程和凭据后调用 `update_account`，带分组变更时再获取 sidebar advisory lock；普通移组先取得 sidebar advisory lock，再锁 Account。两个事务可分别持有 Account 与 sidebar，形成 ABBA 死锁。独立复现 `.scratch/review_t054_code_repro.py::test_review_t054_lock_order_repro` 使用真实隔离 PG 与生产 `update_account_app`，仅用事件固定线程交错，结果为 `['ok', 'OperationalError: (psycopg.errors.DeadlockDetected) deadlock detected']`；日志 `.scratch/review_t054_code_repro.log`。
- 建议：OAuth 分支在取得 Account 锁前，按普通更新同一条件先取得 sidebar lock；保持所有账户组织写入锁序一致，并补真实 PG 并发回归。

### t054_code_f007 - 活跃流程指针比较与删除分离，仍可删除并发新流程的恢复入口

- 严重度：important
- 锚点：AC-009（回调后草稿恢复）、AC-012（多个同时授权流程隔离）。
- 位置：`src/mail_core/accounts/oauth_flow.py:92-98`、`src/mail_core/accounts/oauth_flow.py:325`、`src/mail_core/accounts/oauth_flow.py:610`、`src/mail_core/accounts/oauth_flow.py:661`、`src/mail_core/accounts/oauth_flow.py:737`。
- 问题：`_clear_matching_active_pointer` 经单独连接读取指针，随后在另一个操作/事务删除。读取旧流程 A 后，若并发 start B 将指针更新为 B，清理 A 仍按旧快照无条件删除该引用，造成 B 的 `/oauth/active` 返回空、回调返回后无法恢复草稿。Round 1 f005 的顺序场景已修，但并发 TOCTOU 仍在。独立控制交错复现 `.scratch/review_t054_code_repro.py::test_review_t054_pointer_race_repro`：生产 helper 读到 A 后存储切换为 B，helper 返回后 B 指针缺失，`load_json_secret` 报 `KeyError`；日志同上。当前 start 写指针未使用 `credential_edit`，仅给删除端加锁仍不能与写端互斥。
- 建议：指针 start 写入与清理统一经过同一引用锁；清理在同一事务内读、比较、更新/删除，避免跨连接旧快照判断。

### t054_code_f008 - 令牌端点返回非对象 JSON 时校验分支反而抛 AttributeError

- 严重度：minor
- 锚点：行为缺陷：令牌服务或代理返回 HTTP 200、非空 JSON 数组时，回调返回 500，未形成可操作失败状态；供应商正常协议不返回此形状，属于低频健壮性问题。
- 位置：`src/mail_core/accounts/oauth_flow.py:394-395`。
- 问题：条件已识别 `not isinstance(token_resp, dict)`，但错误处理仍调用 `(token_resp or {}).get(...)`。独立调用生产 `_exchange_and_verify_google`，HTTP 边界返回 `['invalid-shape']`，结果为 `AttributeError: 'list' object has no attribute 'get'`；该异常逃逸 `credential_edit` 并回滚流程状态。
- 建议：非对象结果单独转换为固定脱敏失败消息，然后只对字典读取 `error` / `error_description`。

### t054_code_f009 - 新增网页回调配置未接入标准 Compose 部署

- 严重度：important
- 锚点：AC-003（自托管网页可信配置固定回调）、AC-002（可配置实际回调 URI）。
- 位置：`src/mail_core/accounts/oauth_flow.py:155-164`、`docker-compose.mail-core.yml:51-70`、`config/.env.example`。
- 问题：网页 OAuth 必须读取 `MAIL_CORE_PUBLIC_ORIGIN`，但标准 Compose API service 的显式 `environment` 没有此键，也没有 `env_file`。用户在既有 `.env` 中设置该键不会自动注入容器，metadata 仍返回 `origin_configured=false`，网页登录入口始终因缺可信回调拒绝。配置模板与使用指南也没有新增键及登记说明。独立检查 Compose 的 API environment 和配置模板确认缺失；此项也由主实施方自行发现并告知 reviewer。
- 建议：仅给 API service 增加可空 Origin 环境传递，并在配置模板/部署指南说明 HTTPS Origin、固定回调登记与未配置时其他账户功能不受影响；不默认开放远端 HTTP loopback。

### 前轮 finding 复核

- f001：已消除。`settings_account_form.tsx:197-202` 区分真实桌面外链 `deny` 与浏览器弹窗拦截，去掉导致恒返回 null 的特性串；独立 Electron 测试使用生产外链 handler 与真实 SPA，日志见实施侧 `.scratch/t054_backend_resume.log`，本轮复查代码与断言。
- f002：已消除。`_public_flow_view` 对 pending/authorized 都校验有效期，status/active 执行过期清理，consume 再检查过期；测试覆盖授权后过期不可恢复/保存。
- f003：已消除。public 未显式提交 Secret 时不继承旧秘密；重新授权保存移除旧 Secret，测试断言换码表单不带旧 Secret。
- f004：已消除。复制前显式检查 clipboard API；缺失时进入失败反馈，组件测试覆盖成功与缺失两支。
- f005：旧 expires_at 清除和顺序场景指针匹配已修；并发删除入口仍不原子，升级为本轮 f007，不能视为并发闭环。

### 结论

- 本轮新发现：4 条（3 important，1 minor）。
- 独立验证：定向真实 PG 后端 `16 passed / 1 skipped`（Electron 显式模式未在本轮再次启动；已查生产集成代码及既有 50 项通过日志）；前端组件 `18 passed`；新增独立竞争复现两项均红，证据保存在 `.scratch/review_t054_code_repro.py` 与对应日志。未修改实现、测试、spec 或 task。
- 七视角体检：安全已复核会话绑定/PKCE/日志脱敏/回调 CSP 与无 Cookie 边界；正确性发现锁序与活跃恢复竞争；契约/Breaking 已核查新增 API 及生成契约，无迁移表新增；性能/资源已核查 HTTP 超时、轮询清理与连接生命周期；架构/可维护性无额外阻断；健壮性发现非对象令牌响应；文档/规格发现 Compose 配置缺口。
- 未进表提示：`src/mail_core/accounts/oauth_flow.py` 738 行、`src/mail_core/mail/application/accounts.py` 406 行，超过源码 400 行建议线；生成 OpenAPI/TS 契约不计。高分支集中于 start、exchange、consume 和 validate_connection，建议后续按实际职责简化，复杂度本身不阻断。未把外部真实 Google 登录、2FA 或审核列为缺口。
- 取消/超时边界复核：当前 cancel 删除与 callback/save 的 PG 行锁使有效 callback/save 与删除串行，未证实另一项独立死锁；跨会话与 epoch 在领取/保存时校验，pending/authorized 最终保存均校验服务端期限。指针竞争统一由 f007 覆盖。
- 系统性 follow-up：无；本轮问题均属于当前新增 OAuth 行为。
- 总体判断：首轮主要问题已修，但三个 important 仍影响并发正确性与标准网页部署，本轮 FAIL。

### AC 复验方式

- AC-001：`re_verified` — 核查新增/编辑入口与组件提交逻辑，并独立运行 18 项组件测试。
- AC-002：`re_verified` — 核查命名配置、空秘密保留与复制行为，发现标准 Compose 配置传递缺失（f009）。
- AC-003：`re_verified` — 核查受信 Origin、sidecar 动态端口与元数据测试，发现 Compose API 未注入 Origin（f009）。
- AC-004：`re_verified` — 核查 PKCE S256、gmail.modify、offline access 与权限/刷新令牌缺失拒绝路径，并运行后端定向测试。
- AC-005：`re_verified` — 核查 require_auth/CSRF、session key/epoch、跨会话与过期校验及测试断言。
- AC-006：`re_verified` — 独立运行重复回调与跨流程同码竞争测试，核查 advisory code claim 和持久化凭据边界。
- AC-007：`re_verified` — 核查 callback 唯一无 require_auth 路由与暂存边界；查阅真实 Electron 集成代码、无 Cookie 请求和账户最终保存断言。
- AC-008：`re_verified` — 核查生产 token/profile HTTP 调用、真实邮箱覆盖、重复账户/异邮箱拒绝，并运行相关 PG 测试。
- AC-009：`re_verified` — 核查 active/返回草稿恢复与原子保存，独立复现并发新流程恢复入口丢失（f007）。
- AC-010：`re_verified` — 核查状态白名单、加密存储、callback 查询脱敏、固定返回地址与安全头，运行对应后端断言。
- AC-011：`re_verified` — 核查拒绝/错误/取消/重发状态，独立组件与 urllib 错误测试通过；非对象响应健壮性缺陷见 f008。
- AC-012：`re_verified` — 核查行锁令牌合并，独立复现重新授权移组与普通移组死锁（f006）及指针隔离失败（f007）。
- AC-013：`re_verified` — 核查 Google 帮助内容、官方链接及编辑态帮助测试，独立组件套件通过。

coverage = 13 / 13 (100.0%)

verdict: FAIL

## Round 3 (2026-10-24T18:40:00+08:00)

reviewed_scope: 899e4999950197e3

### Findings

### t054_code_f010 - OAuth 新增账户与分组重新授权在 active pointer/sidebar 上形成新死锁

- 严重度：important
- 锚点：AC-009（最终保存原子完成）、AC-012（多个账户/同时授权流程相互隔离及并发保存正确）。
- 位置：`src/mail_core/mail/application/accounts.py:171-183`、`src/mail_core/mail/application/accounts.py:226-228`、`src/mail_core/accounts/oauth_flow.py:92-94`、`src/mail_core/accounts/oauth_flow.py:661`、`src/mail_core/accounts/oauth_flow.py:737`。
- 问题：f007 修复后，`consume_oauth_flow_for_create` 在外层保存事务持有 `oauth_active:<session>` advisory/行锁，返回后 `create_account` 才取得 sidebar lock；分组重新授权则已按 f006 修复先取得 sidebar lock，后在 consume 末尾取得同一会话 active pointer lock。于是同会话两个独立 OAuth 流程（新增 A、分组重新授权 B）并发保存：A 持有 pointer 等待 sidebar，B 持有 sidebar 等待 pointer，形成 ABBA。即使 A 并非 active 指针所指流程，helper 也先加锁再判断，因此仍会触发。
- 复现：独立新增 `.scratch/review_t054_code_repro.py::test_review_t054_create_reauthorize_pointer_sidebar_deadlock`，使用真实隔离 PG、生产授权暂存与 `create_account_app` / `update_account_app`，仅在生产函数边界用事件固定交错。执行结果 `['OperationalError: (psycopg.errors.DeadlockDetected) deadlock detected', 'ok']`，日志 `.scratch/review_t054_r3_repro.log`；不是仅凭锁序推测。
- 建议：OAuth 最终新增和重新授权入口统一先取得 sidebar lock，再取得 Account/flow/credential/pointer 锁；避免任何持有 flow/pointer 的事务后续再获取 sidebar，并补该跨账户两流程并发回归。

### 前轮 finding 复核

- f001-f004：实现未回退；弹窗/过期/公共客户端 Secret/剪贴板处理保持上一轮已验证修复。
- f005：旧 expires_at 清除保持；活跃指针不匹配时不再清理其他流程。
- f006：原 Account/sidebar 反序已消除。OAuth 移组分支先 `_lock_sidebar_layout`，再锁 Account，与普通移组一致；本轮 f010 是新 pointer 锁与 create 保存路径的另一个组合。
- f007：原指针 TOCTOU 已消除。`_clear_matching_active_pointer` 与 start 写入均经同一 `credential_edit`，比较和清空处于同一事务。修复新增持锁顺序影响见 f010。
- f008：已消除。非对象 token JSON 单独进入固定脱敏失败消息，不再调用 `.get`。
- f009：已消除。Compose API 显式传入可空 `MAIL_CORE_PUBLIC_ORIGIN`；配置模板与部署指南补齐 HTTPS Origin、固定回调登记、应用配置与未配置行为。

### 结论

- 本轮新发现：1 条 important。
- 独立复验：真实 PG 新竞争复现失败，证据见 `.scratch/review_t054_r3_repro.log`；查证本轮 `.scratch/t054_r3_backend.log` 为 `64 passed / 1 failed`，失败为新增测试缺少 `Event` 导入，已通知实施侧与测试 reviewer，不在代码报告重复登记测试 finding；本轮全栈日志 `8 passed`。上一轮独立后端与前端通过证据仍有效，未宣称新范围全部测试通过。
- 七视角复核：安全边界、PKCE/状态与日志秘密处理未变化；正确性/资源复现 f010 事务死锁；契约及 Breaking 无新变更；架构与锁职责需一致；健壮性非对象 token 已修；配置文档与 Compose 现一致。未新增其他重要问题。
- 未进表提示：738 行 OAuth 流程、409 行账户 application 及高分支函数仍建议按职责维护；生成契约文件不计。真实第三方登录/2FA/审核仍属于 spec 有意不测，不作为缺口。
- 系统性 follow-up：无。
- 总体判断：f006-f009 定点修复成立，但新增账户与分组重新授权仍能并发死锁，本轮 FAIL。

### AC 复验方式

- AC-001：`re_verified` — 复查 Google 新增/编辑及 IMAP 分支，入口和最终提交逻辑未回退。
- AC-002：`re_verified` — 核查客户端字段、复用秘密、复制与本轮新增配置模板。
- AC-003：`re_verified` — 核查可信 Origin/loopback 与 Compose API 环境传递、部署指南，原 f009 已修。
- AC-004：`re_verified` — PKCE、gmail.modify、离线凭据约束未变化，复查生产授权/交换逻辑。
- AC-005：`re_verified` — 会话/epoch/CSRF/TTL 校验未变化，复查 status/cancel/consume 边界。
- AC-006：`re_verified` — 状态与授权码引用锁仍在，复查原子 claim 与重复回调拒绝逻辑。
- AC-007：`re_verified` — callback 仅暂存且无 Cookie 可访问、状态及保存需原会话；核查 Electron 集成生产入口断言。
- AC-008：`re_verified` — token/profile 与邮箱身份核对逻辑未回退，复查非对象返回新增失败支路。
- AC-009：`re_verified` — 核查指针清理事务修复，独立复现最终保存 pointer/sidebar 死锁（f010）。
- AC-010：`re_verified` — 白名单响应、加密及回调安全头/日志脱敏未变化。
- AC-011：`re_verified` — 非对象 token 响应现进入固定可操作失败；其他错误、取消、重试路径未变化。
- AC-012：`re_verified` — 原 Account/sidebar 与指针竞争修复成立；独立真实 PG 新竞争复现证明 f010。
- AC-013：`re_verified` — 帮助内容/链接未变化，配置指南补充一致。

coverage = 13 / 13 (100.0%)

verdict: FAIL

## Round 4 (2026-10-24T18:46:00+08:00)

reviewed_scope: 82374890bf0a9881

### Findings

本轮零 finding。

### 前轮 finding 复核

- f001：已消除；网页弹窗返回值与 Electron 外链 deny 分开处理，生产 handler 与真实 SPA 集成证据保持有效。
- f002：已消除；pending/authorized 的状态查询、恢复与最终保存均按服务端期限失效。
- f003：已消除；public 不继承旧 Secret，提交成功清除旧 Secret，保留已匹配客户端的刷新令牌规则。
- f004：已消除；剪贴板缺失/失败不会误报复制成功。
- f005：已消除；重新授权无新 expires_in 时移除旧缓存期限，活跃指针只清理所属流程。
- f006：已消除；普通移组与 OAuth 保存统一先组织锁再 Account，生产回归精确断言两个事务均成功并验证分组和新凭据。
- f007：已消除；start 与清理均使用同一引用的 credential_edit，读/比较/清空同一事务完成，保留并发新流程指针。
- f008：已消除；非对象 token JSON 转固定脱敏失败消息，生产回归断言 callback 400 和流程 failed。
- f009：已消除；Compose API、配置模板与部署指南传递并解释可信 HTTPS Origin，无需开启生产 HTTP loopback。
- f010：已消除；新增与重新授权全部在 consume 前取得 sidebar 组织锁，随后才取得 Account/flow/credential/pointer，后续重复取得同一事务 advisory lock 可重入，不再存在 pointer → sidebar 反向路径。独立重跑先前两项真实 PG 死锁复现均通过；生产回归同时精确断言两事务 `['ok', 'ok']`、新增账户存在且不同于原账户、原账户正确分组以及两份新凭据，不以捕获异常后“未出现 deadlock 字符串”冒充成功。

### 结论

- 本轮新发现：0 条；当前无未解决 critical/important/minor。
- 独立验证：`scripts/run-mail-core-tests.sh run .scratch/review_t054_code_repro.py -k 'review_t054_lock_order_repro or review_t054_create_reauthorize or reauthorization_and_normal_group or oauth_create_and_group or clearing_old_active or non_object_token' --no-cov` → `6 passed`，覆盖先前两个独立竞争复现与四项当前生产回归；日志 `.scratch/review_t054_r4_tests.log`。`git diff --check` 通过；重算 scope 与本轮指纹一致，未发现未跟踪交付文件。查证实施侧最终定向 `66 passed`（包含显式 Electron），全栈 `8 passed`；此前完整后端 `532 passed / 1 skipped` 的显式 Electron 场景已由本轮定向执行补齐。
- 七视角复核：安全核查 PKCE、身份/会话绑定、原子领取、加密与脱敏；正确性独立复验锁序和指针竞争；公开契约/Breaking 核查新增 API 与生成契约；性能/资源核查事务、HTTP 超时、轮询与连接释放；架构/维护性确认一致锁序及职责边界；健壮性确认失败消息、取消/过期和回滚路径；文档/规格核对配置指南与实际 Compose/metadata 行为一致。未发现新增可观测缺陷。
- 未进表提示：OAuth 流程 738 行、账户 application 411 行，新增测试 990 行，均有规模维护提示；生成 OpenAPI/TS 契约不计。高分支函数仍可按职责持续简化，规模本身不阻断。真实第三方账户登录/2FA/审核未执行，符合 spec 有意不测范围；未把假供应商通过写成真实 Google 连通。
- 系统性 follow-up：无。
- 总体判断：完整最终范围与前轮问题复核通过，本轮 PASS。

### AC 复验方式

- AC-001：`re_verified` — 核查新增/编辑 Google 入口、真实授权 URL、最终 POST/PATCH 与 IMAP 分支；前轮独立 18 项组件测试及当前最终差异未回退。
- AC-002：`re_verified` — 核查 Client ID/Secret 配置、空秘密复用、复制成功/失败、缺项提示及本轮配置模板。
- AC-003：`re_verified` — 核查固定 HTTPS Origin、受信 sidecar 动态 loopback、Compose API 传递及部署说明，不依赖请求 Host/query。
- AC-004：`re_verified` — 核查 PKCE S256、gmail.modify、offline access/consent 与缺权限/Refresh Token 拒绝路径。
- AC-005：`re_verified` — 核查 require_auth/CSRF、session key/epoch、有效期与取消后的领取/保存失败关闭逻辑。
- AC-006：`re_verified` — 核查共享持久化状态、flow/code 引用锁及重复回调/同码并发生产回归；前轮独立定向已运行。
- AC-007：`re_verified` — 核查无 Cookie callback 仅暂存及原会话最终保存；真实 Electron 测试通过生产 handler、SPA/API/PG 和 HTTP 供应商边界，核查其断言与最终通过日志。
- AC-008：`re_verified` — 核查生产 token/profile 请求、服务商真实邮箱优先、异邮箱/重复账户/协议切换拒绝及 PG 测试断言。
- AC-009：`re_verified` — 独立运行 active 指针竞争与 OAuth 新增/重新授权保存竞争回归，核查恢复、取消与一次性消费。
- AC-010：`re_verified` — 核查状态白名单、加密存储、回调 code/state 日志脱敏、URL 清理、安全头及固定返回链接。
- AC-011：`re_verified` — 独立复验非对象 token 固定失败；核查拒绝/网络/配置/过期/取消/重试和旧 Refresh Token 保留限制。
- AC-012：`re_verified` — 独立重跑两项旧死锁复现与当前两项强断言并发回归，确认统一锁序、账户/分组/新凭据正确及流程隔离。
- AC-013：`re_verified` — 核查帮助弹窗新增/编辑入口、IMAP 应用密码、Web/Desktop 区别、回调登记、测试用户/7 天/组织策略及官方链接。

coverage = 13 / 13 (100.0%)

verdict: PASS
