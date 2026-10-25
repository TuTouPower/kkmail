# Task review t054（reviewer_focus: 测试）

- task：`t054_google_oauth_callback`
- spec：`docs/tasks/t054_google_oauth_callback/spec.md`
- diff_anchor：`4ef9bf7ada1aaa9b67ea67dfccc1dfcd9b98d10a`
- target：`git -C '<local-path>' diff 4ef9bf7ada1aaa9b67ea67dfccc1dfcd9b98d10a`
- round：1
- reviewed_at：2026-10-24T15:14:00+08:00

reviewed_scope: 4d2e04d57e73ba5e

## Findings

### t054_test_f001 - E2E 重新授权仅断言按钮可见（存在即通过），且缺少重新授权保存提交与 `/#oauth-return` / `/api/accounts/oauth/active` 草稿恢复测试

- 严重度：important
- 锚点：AC-001、AC-009（重新授权提交保存、成功回调返回添加/编辑表单并恢复所属分组与非敏感草稿）及危险模式「存在即通过」
- 位置：`tests/e2e/provider_account_forms.spec.ts:64-69`、`tests/e2e/stubApi.ts:281-320`、`src/frontend/src/components/provider_account_form.test.tsx:146-148,219-297`、`tests/mail_core/test_google_oauth_callback.py`
- 问题：
    1. `tests/e2e/provider_account_forms.spec.ts:64-69`（用例名含 `and reauthorization`）在打开编辑既有 Gmail 账户对话框后，仅执行 `await expect(editDialog.getByRole('button', { name: '重新授权', exact: true })).toBeVisible()` 即点「取消」退出，未触发点击「重新授权」与「保存修改」（命中「存在即通过」危险模式）；同时 `tests/e2e/stubApi.ts:285-320` 对 `/api/accounts/oauth/flows/stub-oauth-flow-1` 硬编码返回 `intent: 'create'`，不支持 `reauthorize` 流程。
    2. `src/frontend/src/components/provider_account_form.test.tsx:219-297` 在重新授权完成后仅验证了点击「取消」不发送 PATCH，未验证点击「保存修改」触发 `PATCH /api/accounts/{id}` 携带 `oauth_flow_id`，导致 `src/frontend/src/components/settings_account_form.tsx:234-238` 的编辑态 OAuth 保存分支在前端组件测试与 E2E 中均未覆盖。
    3. AC-009 要求「返回添加/编辑表单并保留所属分组与非敏感草稿」，对应后端 `GET /api/accounts/oauth/active`（`src/mail_core/api/oauth_routes.py:133`）与前端 `#oauth-return` 恢复逻辑（`src/frontend/src/App.tsx:78-82`、`src/frontend/src/components/SettingsModal.tsx:85-107`、`src/frontend/src/components/settings_account_form.tsx:85-108`），但后端测试从未调用 `/api/accounts/oauth/active`，前端单测与 E2E 均将该接口硬编码为 `{ flow: null }`，整条恢复链路为 0 覆盖。
- 建议：
    1. 在 `tests/mail_core/test_google_oauth_callback.py` 增加对 `GET /api/accounts/oauth/active`（pending/authorized/跨会话隔离/取消与消费后返回 `null`）的断言，以及过期流程调用 callback 和 `POST /api/accounts` 失败关闭的断言。
    2. 在 `src/frontend/src/components/provider_account_form.test.tsx` 与 `tests/e2e/provider_account_forms.spec.ts`（配合 `stubApi.ts`）中补齐：编辑既有 Gmail API 账户点击「重新授权」后再点击「保存修改」提交 `PATCH /api/accounts/{id}`（含 `oauth_flow_id`），以及通过 `#oauth-return` / `/api/accounts/oauth/active` 自动打开添加/编辑表单并恢复 `group_id`、`client_id`、`client_type`、`verified_email` 的验证。

### t054_test_f002 - 后端测试用 `set_oauth_http_hooks` 绕过生产 HTTP 传输层，且未覆盖 AC-011 的 `redirect_uri_mismatch`、`invalid_client`、网络错误脱敏与前端失败重发

- 严重度：important
- 锚点：AC-008、AC-011（错误分类脱敏展示与重新发起；重新授权缺 Refresh Token 时校验相同客户端）及评审维度「mock 边界 / 生产逻辑可达」
- 位置：`tests/mail_core/test_google_oauth_callback.py:162-165,180-188,256-259`、`src/mail_core/accounts/oauth_flow.py:341-356,466-493,552-562`、`src/frontend/src/components/provider_account_form.test.tsx:126-297`
- 问题：
    1. `tests/mail_core/test_google_oauth_callback.py` 全程通过 `set_oauth_http_hooks` 替换 `_call_token_endpoint` 与 `_call_profile_endpoint`，使生产路径 `default_urllib_token_post` 与 `urllib_json_request`（`src/mail_core/accounts/oauth_flow.py:341-356`）从未被执行。
    2. AC-011 明确列出的 `redirect_uri_mismatch`、`invalid_client`、网络错误等 `ProviderHttpError` 异常分支（`src/mail_core/accounts/oauth_flow.py:468-485`）及其对秘密参数（`client_secret`、`code`、`code_verifier`）的脱敏，还有重新授权时若更换了 `client_id` 且未返回 `refresh_token` 则拒绝保留旧令牌的分支（`src/mail_core/accounts/oauth_flow.py:553-562`），在 `test_google_oauth_callback.py` 中均无测试。
    3. 前端 `src/frontend/src/components/provider_account_form.test.tsx` 只测试了 `pending` -> `authorized` 状态转换，未测试轮询返回 `failed` / `expired` 时展示脱敏错误提示、可取消并重新发起授权（AC-011）。
- 建议：
    1. 在 `tests/mail_core/test_google_oauth_callback.py` 中增加不设置 `set_oauth_http_hooks`、触达 `_call_token_endpoint` / `_call_profile_endpoint` 底层 `default_urllib_token_post` / `urllib_json_request` 的测试，覆盖 `redirect_uri_mismatch`、`invalid_client`、网络异常、秘密脱敏，以及重新授权更换 `client_id` 时缺 `refresh_token` 被拒。
    2. 在 `src/frontend/src/components/provider_account_form.test.tsx` 增加流程状态为 `failed` / `expired` 时渲染 `[role="alert"]` 错误文案并支持取消后重新发起授权的断言。

### t054_test_f003 - 缺少 spec 测试策略与 AC-003/AC-007/AC-009 要求的桌面端独立实例 OAuth 回调、外链打开与焦点恢复测试

- 严重度：important
- 锚点：AC-003、AC-007、AC-009、AC-011（桌面端系统浏览器打开、动态本地端口 loopback 回调与窗口焦点恢复）
- 位置：`src/desktop/startup.js:101-102`、`src/desktop/startup.test.js:60-92`、`src/desktop/main.js:187-190`
- 问题：
    1. `spec.md` 测试策略明确要求：「桌面用独立实例确认系统浏览器无应用 Cookie 仍可回调、动态端口和焦点恢复，不以 BrowserWindow 参数单测代替桌面流程证据」，但本次 diff 在 `src/desktop/` 下未新增或修改任何测试（连 `src/desktop/startup.js:101-102` 新增的 `MAIL_CORE_PUBLIC_ORIGIN` / `MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN` 也未在 `src/desktop/startup.test.js` 断言）。
    2. 缺少 Electron 独立实例测试导致桌面端真实交互未被检验：在 Electron `BrowserWindow` 中，`mainWindow.webContents.setWindowOpenHandler`（`src/desktop/main.js:187-190`）调用 `shell.openExternal(target)` 并返回 `{ action: 'deny' }`，这会使渲染进程 `window.open(...)` 返回 `null`，进而触发 `src/frontend/src/components/settings_account_form.tsx:196-197` 误报「浏览器拦截了授权窗口」；同时系统浏览器无 Electron Cookie 完成动态端口 loopback 回调后窗口恢复焦点并同步授权状态的桌面链路也未经实测验证。
- 建议：
    1. 在 `src/desktop/startup.test.js` 补充对 `MAIL_CORE_PUBLIC_ORIGIN` 与 `MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN` 的 `collectSidecarExtras` 断言。
    2. 参考 `src/desktop/clipboard.test.js` 在 `src/desktop/` 补充 Electron 独立实例 OAuth 集成测试，验证动态端口 loopback 回调、系统外链拦截打开（且桌面端不误报弹窗被拦截）、无 Cookie 外部请求回调后窗口 `focus` 恢复授权成功状态。

### t054_test_f004 - 可补充复制回调地址按钮、编辑态打开帮助弹窗、OAuth 路由未认证/缺 CSRF 拦截及重新授权后 `sync_status` 恢复断言

- 严重度：minor
- 锚点：AC-002、AC-005、AC-012、AC-013（边界覆盖扩展）
- 位置：`src/frontend/src/components/provider_account_form.test.tsx:193-205`、`tests/mail_core/test_google_oauth_callback.py:212-370`
- 问题：
    1. `src/frontend/src/components/provider_account_form.test.tsx` 断言了 `#account-redirect-uri` 的值，但未点击「复制回调地址」按钮验证 `navigator.clipboard.writeText` 与复制状态提示（AC-002），也未在编辑既有 Google 账户对话框内点击打开凭据帮助弹窗（AC-013）。
    2. `tests/mail_core/test_google_oauth_callback.py` 验证了跨会话访问返回 403，但未显式断言未登录请求 `/api/accounts/oauth/*`（除 callback 外）返回 401、写请求缺少 `X-CSRF-Token` 返回 403（AC-005），也未在重新授权 `PATCH` 成功后断言原 `sync_status="auth_failed"` 的账户状态恢复为 `"idle"`（AC-012）。
- 建议：在 `provider_account_form.test.tsx` 与 `test_google_oauth_callback.py` 中补充上述断言。

## 结论

- 改测方向复核：无（`src/frontend/src/components/provider_account_form.test.tsx:76` 为新增帮助关键词断言，`tests/e2e/stubApi.ts` 为新增 OAuth 与账户写接口 stub，无弱化或迁就实现的改测）
- 本轮新发现：4 条（3 important，1 minor）
- 未进表的提示：无
- 总体判断：后端 PG 并发/行锁/跨会话与 PKCE 核心测试扎实，但存在 E2E 重新授权「存在即通过」且缺编辑保存与 `/#oauth-return` 恢复测试、后端 `set_oauth_http_hooks` 绕过生产 HTTP 层且缺 AC-011 关键错误分支测试、以及缺少桌面 Electron 独立实例 OAuth 验证三项 important 缺口，本轮判定 FAIL。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：`re_verified` — 独立运行 `KKMAIL_TEST_MODE=unit .venv/bin/pytest tests/mail_core/test_google_oauth_callback.py`、`npm --prefix src/frontend test`、`npm --prefix src/frontend run test:e2e -- provider_account_forms.spec.ts` 并核查源码断言；新增 Google OAuth 与 IMAP 路径已验证，但编辑重新授权在 E2E 仅测按钮可见、前端未测点击保存修改（见 `t054_test_f001`）。
- AC-002：`re_verified` — 独立运行后端与前端测试并核查 `test_google_oauth_callback.py:79-92,304-360` 与 `provider_account_form.test.tsx:53-109,193-200`，缺项提示、复用加密配置与非 Google IMAP 不受阻均已验证（复制按钮点击建议见 `t054_test_f004`）。
- AC-003：`re_verified` — 独立运行 `test_google_oauth_callback.py:34-77` 验证 Web `MAIL_CORE_PUBLIC_ORIGIN`、拒绝未受信 Host/Forwarded/query `desktop=1` 与 `KKMAIL_SIDECAR=1` 动态端口，但缺少桌面 Electron 独立实例验证（见 `t054_test_f003`）。
- AC-004：`re_verified` — 独立运行 `test_google_oauth_callback.py:93-171` 与 `provider_account_form.test.tsx:76`，确认 PKCE `S256`、`gmail.modify`、`access_type=offline`、缺 scope 或缺 Refresh Token 拒绝保存及 7 天说明。
- AC-005：`re_verified` — 核查 `.scratch/t054_backend.log`（`.scratch/test_runs/b5f621ccab79419dbde2a6966f0df0e2/junit.xml` 25 passed）与 `test_google_oauth_callback.py:272-277,362-370,506-522`，跨会话、logout epoch 递增、取消与过期状态已验证；过期后调用 callback/save 阻断及未登录/缺 CSRF 断言需补齐（见 `t054_test_f001`、`t054_test_f004`）。
- AC-006：`re_verified` — 独立运行 unit 并核查 PG 套件日志与 `test_google_oauth_callback.py:124-151,383-425`，错误 provider、篡改/缺 state、缺 code、重放、并发回调（`Barrier(2)`）与授权码复用均失败关闭。
- AC-007：`re_verified` — 核查 `test_google_oauth_callback.py:217,262-276` 无 Cookie `system_browser` 换码暂存且不直接建号、跨会话 403；桌面独立实例集成验证缺失（见 `t054_test_f003`）。
- AC-008：`re_verified` — 核查 `test_google_oauth_callback.py:285-295,312-322,431-440,489-504`，真实邮箱覆盖手填邮箱、重复邮箱拒绝、重新授权异邮拒绝、IMAP 转 Gmail API 拒绝已验证；但底层生产 HTTP 传输被 hook 绕过（见 `t054_test_f002`）。
- AC-009：`re_verified` — 核查前端与后端测试代码，发现 `/#oauth-return` 与 `GET /api/accounts/oauth/active` 草稿恢复及前端重新授权提交保存均未测试（见 `t054_test_f001`）。
- AC-010：`re_verified` — 独立运行 `test_google_oauth_callback.py:173-209` 与 `provider_account_form.test.tsx:111-124`，验证 `no-store`、`no-referrer`、CSP、`history.replaceState`、状态 API 白名单、浏览器存储无秘密残留及日志脱敏。
- AC-011：`re_verified` — 核查 `test_google_oauth_callback.py` 与 `provider_account_form.test.tsx`，发现缺少 `redirect_uri_mismatch`、`invalid_client`、网络错误脱敏、重新授权换 `client_id` 缺 `refresh_token` 拒绝及前端失败状态重发测试（见 `t054_test_f002`）。
- AC-012：`re_verified` — 核查 `test_google_oauth_callback.py:331-360,442-488` 及 PG 运行结果，验证后台刷新轮换与重新授权并发保留新 Refresh Token 及多账户多流程隔离（`sync_status` 恢复断言建议见 `t054_test_f004`）。
- AC-013：`re_verified` — 独立运行 `provider_account_form.test.tsx:13-21,75-84` 与 `provider_account_forms.spec.ts:13-18`，验证 Google 帮助弹窗内容与官方链接（编辑态打开帮助建议见 `t054_test_f004`）。

coverage = 13 / 13 (100.0%)

verdict: FAIL

## Round 2 (2026-10-24T18:32:47+08:00)

reviewed_scope: 066ca8c4fdbd6b3a

### Findings

本轮零新 finding。

### 前轮 finding 复核

|finding_id|复核结论|代码与运行证据|
|---|---|---|
|t054_test_f001|已消除|`tests/e2e/provider_account_forms.spec.ts:60-76` 刷新至 `/#oauth-return` 后核对实际恢复字段，再点击重新授权与保存，断言真实前端 PATCH 请求包含 `oauth_flow_id`；`provider_account_form.test.tsx:332-387` 核对分组、Client ID、邮箱和 hash 清理；PG 测试实际查询 `/oauth/active` 并验证流程隔离。|
|t054_test_f002|已消除|`test_google_oauth_callback.py:600-689` 未设置业务 HTTP hook，直接执行生产 urllib 传输，验证 HTTPError/URLError 分类和秘密脱敏；`:499-519` 验证更换客户端且缺 RT 被拒绝；组件参数化用例验证 failed/expired、取消、重发及最终 PATCH。|
|t054_test_f003|已消除|`src/desktop/oauth_integration.test.js:47-88` 加载实际编译 SPA，使用生产窗口选项/preload/外链处理器，真实 Electron `window.open` 被 deny 时不误报；Node 无 Cookie HTTP 请求完成动态 loopback 回调，focus 后真实组件显示授权结果并保存。Python PG 用例验证账户与加密存储结果，并通过本地假供应商 HTTP 服务执行生产 token/profile 传输。`startup.test.js:64-85` 补齐新增 sidecar 配置断言。|
|t054_test_f004|已消除|组件新增复制成功/不可用反馈、编辑帮助交互；后端新增未认证 401、缺 CSRF 403；重新授权后断言 `sync_status=running` 并查询真实 WorkerJob，且验证新 RT、旧 Secret/到期缓存清理。|

### 验证与危险模式扫描

- 独立执行 `npx vitest run src/components/provider_account_form.test.tsx`：18 passed。
- 独立执行 `KKMAIL_TEST_ELECTRON=1 scripts/run-mail-core-tests.sh run -k google_oauth_callback --no-cov`：9 passed，证据 `.scratch/t054_test_reviewer_r2.log`；包含真实 PG、跨流程同码并发及独立 Electron 集成。
- 核查已有门禁日志：前端全量与 OpenAPI/CSS 检查通过；UI E2E 16 passed；全栈串行重跑 8 passed；桌面测试与 packaged smoke 通过。完整后端大套件在本轮审阅时仍运行，最终收尾由实施侧核对。
- 改测方向复核：无迁就实现的既有测试预期变更。相对 diff_anchor，既有帮助断言只增加内容，旧 E2E 行为保持；其余为新增 OAuth 用例与测试桩。新增 PG 用例的 `idle` 预期修正为 `running` 有生产调用 `update_account_app → enqueue_account_sync` 支持，并增加 WorkerJob 存储断言，未削弱行为覆盖。
- 危险模式逐项核查：无恒真断言、删/反转断言、注释断言、独占测试、禁止类型抑制、放大超时掩盖失败或条件绕过关键断言。`toMatchObject` 用于检验新增请求载荷中的必需字段，未替代既有精确断言；`toBeVisible` 仅作交互前置/结果的一部分，后续有字段、请求、DB 与凭据断言。Electron 输入通过原生属性 setter 加 input/change 事件触达实际 React 表单，点击触发实际生产组件；未用赋值冒充拖拽、快捷键或焦点行为。
- 跳过条件核查：PG 用例只在显式 unit 模式缺 DB 时跳过；Electron 集成由独立环境开关启用，blueprint 定义专用命令，本轮已实际执行且通过，不是未执行测试冒充 PASS。
- mock 边界核查：组件/E2E 在 HTTP 边界设桩；后端部分契约测试使用 provider HTTP hook，但新增 urllib 边界测试及真实 Electron/本地供应商 HTTP 集成已触达生产 code exchange、getProfile、账户保存和加密凭据。没有复制业务实现作为成功证据。
- 七视角扫描：安全覆盖会话/CSRF、PKCE、重放及秘密脱敏；正确性覆盖身份、保存、重新授权及失败重试；契约覆盖生成接口与请求载荷；性能/资源覆盖并发回调和实例收尾；架构覆盖实际组件/API/存储/桌面路径；健壮性覆盖远端错误与回滚；测试/文档/规格对应新增门禁及已批准的真实供应商不测范围。

### 结论

- 本轮新发现：0 条；首轮 4 条 finding 已消除。
- 未进表的提示：可继续增强真实多 API 进程相互领取流程、实际 uvicorn 日志输出和已授权流程直接查询过期状态的专项回归；现有测试覆盖对应 AC 的核心行为，属于补充场景，不构成新 blocker。`test_google_oauth_callback.py:593-597` 当前先调用 callback 使流程过期，再查询状态，不能单独证明状态查询自身执行过期迁移；本轮未将其当作该分支的独立证据。
- 总体判断：新增和重新授权保存、草稿恢复、生产 HTTP 错误、动态桌面回调与跨流程授权码竞争均有有效行为证据；本报告范围内无未解决 critical/important。
- 系统性 follow-up：无。
- 实测限制：未进行真实 Google 账号/同意屏幕/2FA 授权；符合 spec 有意不测范围。系统浏览器外链启动边界由实际生产处理器加捕获函数验证，未宣称已打开真实 Google 账户页面。

### AC 复验方式

- AC-001：`re_verified` — 独立组件测试实际发起登录、重新授权与保存，E2E 用例核对新增和编辑保存请求；Google IMAP 用例保留。
- AC-002：`re_verified` — 核对缺项、已有加密客户端复用、实际回调地址与复制成功/失败断言，独立执行相关前后端用例。
- AC-003：`re_verified` — 独立后端 metadata 用例核对受信 origin、伪造 Host/query 拒绝；独立 Electron 用例验证动态 loopback 与生产外链 deny 行为。
- AC-004：`re_verified` — 核对并独立执行授权 URL、PKCE challenge/verifier、scope、offline、缺权限/RT 拒绝与帮助 7 天说明。
- AC-005：`re_verified` — 独立 PG 套件执行跨会话状态/取消/保存拒绝、logout epoch、取消/过期，以及未认证与 CSRF 拒绝。
- AC-006：`re_verified` — 独立执行 provider/state/code/replay 失败关闭、同 state 并发以及跨流程同码竞争；核对持久 CredentialSecret 与 DB 锁路径。
- AC-007：`re_verified` — 独立 Electron 用例使用无 Cookie Node 请求回调，随后由原应用确认保存；PG 用例确认回调本身尚未建号且跨会话不能领取。
- AC-008：`re_verified` — 独立 PG/urllib/假供应商 HTTP 用例执行身份核对、真实邮箱覆盖提示、重复邮箱/异邮拒绝、IMAP 转协议拒绝。
- AC-009：`re_verified` — 独立组件用例恢复分组/客户端/邮箱并确认 PATCH；核对浏览器刷新恢复 E2E、DB 原子保存与重复保存拒绝、Electron 最终保存。
- AC-010：`re_verified` — 独立执行 callback 响应头与 HTML 无秘密、状态响应无令牌、URL 清理脚本与脱敏错误用例；核对响应白名单和前端秘密草稿不持久化断言。
- AC-011：`re_verified` — 独立执行拒绝、缺 scope/RT、HTTPError/网络异常、客户端不匹配与前端 failed/expired 重发；核对原凭据保留与流程隔离断言。
- AC-012：`re_verified` — 独立 PG 套件执行后台轮换与重新授权期间 RT 保留、新凭据保存/缓存清理、错误目标拒绝及真实同步任务入队。
- AC-013：`re_verified` — 独立组件测试打开新增/编辑帮助并核对 Gmail IMAP、Web/Desktop、Gmail API、scope、7 天期限及自有配置说明；核查官方链接正文。

coverage = 13 / 13 (100.0%)

verdict: PASS

## Round 3 (2026-10-24T18:39:15+08:00)

reviewed_scope: 899e4999950197e3

### Findings

### t054_test_f005 - 新增锁序回归缺少并发原语导入，真实 PG 门禁失败

- 严重度：important
- 锚点：AC-012（账户编辑与后台并发安全）；新增针对 code f006 的回归无法执行，不具备验证修复的证据。
- 位置：`tests/mail_core/test_google_oauth_callback.py:827-828,860`，`test_reauthorization_and_normal_group_move_share_lock_order_pg`。
- 问题：函数使用 `Event`、`ThreadPoolExecutor`，但本函数和模块顶层均未导入这两个名字；其他函数内部的局部导入不对本函数可见。独立运行 `scripts/run-mail-core-tests.sh run -k reauthorization_and_normal_group_move_share_lock_order_pg --no-cov`，在 `account_locked = Event()` 处返回 `NameError`；补 Event 后仍会在执行器引用处失败。证据 `.scratch/t054_test_reviewer_r3.log` 为 1 failed；实施侧 `.scratch/t054_r3_backend.log` 同样失败。
- 建议：在该用例作用域显式导入 `threading.Event` 和 `concurrent.futures.ThreadPoolExecutor`，再重跑新增并发回归及相关后端门禁；不要把当前 NameError 当实现死锁复现。

### t054_test_f006 - 锁序回归只排除错误文本中的 deadlock，其他事务失败会假绿

- 严重度：important
- 锚点：AC-012（并发保存不丢新凭据、账户修改可完成）；危险模式「弱化断言／掩盖失败」。
- 位置：`tests/mail_core/test_google_oauth_callback.py:844-864`。
- 问题：`authorize` 与 `move` 捕获所有异常并转换成字符串，最终唯一结果断言是 `not any('deadlock' in item.lower() for item in results)`。因此 `AssertionError`（受控事件等待超时）、`ValueError`、授权保存失败等返回值均满足断言，即使两个事务都没有成功也会 PASS。并发用例没有断言结果均为 `ok`，也未核对保存后的分组/新凭据。此问题独立于 f005：导入补齐后仍可能将非 deadlock 失败伪装成并发安全证据。
- 建议：保留异常原样传播，或精确断言两个事务均返回 `ok`；随后核对账户最终分组和新授权凭据，确保两个生产操作都完成。事件包装仅固定交错，不应绕过错误结果。

### 前轮 finding 复核

- Round 1 test f001-f004：本轮完整 diff 中对应新增/编辑保存、草稿恢复、urllib 错误、Electron 真实实例、复制、帮助与鉴权断言仍保留，未反向弱化；仍视为已消除。
- Round 2 测试报告没有新 finding；本轮新增锁序、指针竞争与非对象响应回归。指针回归与异常响应用例有外部可观察结果断言；锁序回归存在上述两项问题。
- Code Round 2 的 f006-f009 不由测试 reviewer裁定实现是否修复；本轮检验其验证证据：指针竞争和非对象响应由新增生产路径回归覆盖，Compose Origin 由实际渲染配置核验；锁序回归当前失败，不能报告全部通过。

### 验证与结论

- 独立命令：锁序 PG 定向 1 failed / 535 deselected；Compose `config --no-interpolate --format json` 的 API `MAIL_CORE_PUBLIC_ORIGIN` 映射为 `${MAIL_CORE_PUBLIC_ORIGIN:-}`，配置传递已接入。未改代码或测试。
- 已核查日志：本轮全栈 8 passed；本轮定向后端门禁存在 f005 NameError。此前完整后端 532 passed / 1 显式 Electron skipped、前端 293/UI 16/全栈 8/desktop 与 packaged PASS，均不能代替新增回归本轮执行结果。
- 改测方向复核：既有测试断言保留，本轮主要新增回归，未发现旧测试迁就实现改预期；新锁序用例错误吞掉失败是新引入问题，见 f006。
- 危险模式扫描：新增指针测试包装真实读取以固定 TOCTOU，未替换写入/清理副作用；非对象响应仅在供应商 HTTP 边界替换返回值。锁序用例包装原生产函数仍调用原实现，但异常字符串加不完整结果断言会掩盖失败，已按 important 报告。其余无新增 skip/only、恒真断言、删除测试、类型抑制或超时放大。
- 七视角：安全/正确性覆盖原会话和授权码回归；契约核对 Compose Origin 与部署指南；性能/资源核对新增并发用例生命周期；架构确认调用真实生产账户路径；健壮性覆盖非对象响应；测试/文档/规格发现锁序用例本身的运行与断言缺陷。
- 本轮新发现：2 条 important。
- 未进表提示：上一轮可选覆盖扩展仍适用，无新扩展建议。
- 系统性 follow-up：无；两项问题直接位于当前 task 新增回归。
- 总体判断：新锁序回归不能执行，且错误判定可假绿，本轮 FAIL。

### AC 复验方式

- AC-001：`re_verified` — 核对当前 diff 中入口、组件提交与 E2E 新增/编辑保存断言保持，前端本轮未变。
- AC-002：`re_verified` — 核对配置缺项、复制、空秘密保留断言及新增 env/Compose/部署配置。
- AC-003：`re_verified` — 独立渲染 Compose 配置并核对网页可信 origin、桌面动态 loopback 的现有测试。
- AC-004：`re_verified` — 核对保留的授权 URL、PKCE、scope、offline、缺 RT 拒绝断言。
- AC-005：`re_verified` — 核对保留的会话/epoch/CSRF/取消过期拒绝用例。
- AC-006：`re_verified` — 核对同 state/跨流程同码并发及持久 DB 领取用例未改弱。
- AC-007：`re_verified` — 核对真实 Electron 无 Cookie 回调、原应用确认保存及 DB 验证路径保留。
- AC-008：`re_verified` — 核对 token/profile 生产传输、身份/重复/异邮/IMAP 拒绝测试保留。
- AC-009：`re_verified` — 核对草稿恢复和原子保存断言，并核对新增活跃指针受控竞争回归。
- AC-010：`re_verified` — 核对响应秘密白名单、callback 安全头、URL 清理与日志脱敏断言保留。
- AC-011：`re_verified` — 核对 failed/expired 重试和新增非对象 token 响应失败状态测试。
- AC-012：`re_verified` — 独立执行新增真实 PG 锁序回归，确认 NameError，并查证其异常捕获会漏判失败，见 f005/f006。
- AC-013：`re_verified` — 核对新增/编辑帮助和官方文档说明测试保留。

coverage = 13 / 13 (100.0%)

verdict: FAIL

## Round 4 (2026-10-24T18:42:37+08:00)

reviewed_scope: 82374890bf0a9881

### Findings

本轮零新 finding。

### 前轮 finding 复核

- `t054_test_f005`：已消除。`test_google_oauth_callback.py:6-7` 已在模块顶层显式导入 `ThreadPoolExecutor` 与 `Event`；独立执行两个锁序、指针竞争及非对象响应回归，4 passed，未再出现 NameError。
- `t054_test_f006`：已消除。`:864` 精确断言两事务均为 `ok`，`:865-868` 核对最终分组和重新授权 RT；异常虽然保留为诊断字符串，任何非 `ok` 值都会失败。新增 create/reauthorize 回归同样在 `:983-990` 断言两事务成功，并核对两个不同账户、原账户分组及两份新 RT，未沿用仅排除错误关键字的弱断言。
- Round 1 `test_f001-f004`：当前完整 diff 中新增/编辑保存、回调恢复、生产 urllib、错误、Electron、复制、帮助与鉴权断言仍保留，未回退。
- Code `f010` 对应验证：新增 `test_oauth_create_and_group_reauthorization_share_lock_order_pg` 调用实际账户 create/update 与 OAuth 消费生产路径，事件包装仍调用原函数。`.scratch/t054_r3_lock_red.log` 明确记录旧实现真实 PG `DeadlockDetected` 导致精确结果断言失败；当前独立回归通过，且有 DB 保存效果断言。不是复制实现或只检查未抛异常。

### 验证与危险模式扫描

- 独立执行 `scripts/run-mail-core-tests.sh run -k 'google_oauth_callback and (lock_order or concurrent_start or non_object)' --no-cov`：4 passed，证据 `.scratch/t054_test_reviewer_r4.log`。
- 独立重算最终交付指纹：`82374890bf0a9881`，与本轮 prompt 相符。`git diff --check` 无错误；无 reviewer 看不到的未跟踪交付文件。
- 核查最终相关后端日志 `.scratch/t054_r4_backend.log`：66 passed（包括明确启用的 Electron 与账户分组回归）；本轮全栈 `.scratch/t054_r4_full_stack.log`：8 passed。此前完整后端 532 passed / 1 显式 Electron skipped；前端本轮未变，保留已核查的 293 passed、UI E2E 16 passed、桌面与 packaged PASS 证据。未宣称最终全量后端又执行一次。
- 改测方向复核：无旧测试迁就实现改预期；新测试修正缺导入并强化双方成功/存储效果断言，符合首轮红灯针对实现修复。`.scratch/t054_r3_lock_red.log` 的死锁红灯与修复后绿灯能够对应同一生产行为。
- 危险模式扫描：无新增测试删除、反转断言、恒真断言、skip/only、类型抑制或超时阈值放大。两项并发测试的异常字符串现在由精确成功断言兜住，不再漏判非死锁错误；事件包装只固定线程交错，不替代真实 DB 或生产锁。既有 Electron 显式开关本轮实际开启并通过，未借跳过规避验收。
- 七视角复核：安全确认会话/CSRF/PKCE/秘密测试未删；正确性和资源通过并发两事务完成及持久结果验证；契约确认 API/生成契约未在本轮变动；架构确认测试调用实际 application/credentials；健壮性确认非对象响应失败状态；测试/文档/规格确认部署 Origin 说明与新增门禁一致。没有扩大到未改领域。

### 结论

- 本轮新发现：0 条；本报告历史 `test_f001-f006` 均已消除。
- 未进表提示：Round 2 已列可选专项回归仍属增强建议，不新增 blocker；真实第三方 Google 账号授权仍按 spec 有意不测。
- 系统性 follow-up：无。
- 总体判断：新增并发回归现可执行且断言真实保存效果；本报告范围无未解决 critical/important，本轮 PASS。

### AC 复验方式

- AC-001：`re_verified` — 核对当前完整 diff 的 Google 新增/编辑提交与 IMAP 保留路径，现有组件/E2E行为断言未改。
- AC-002：`re_verified` — 核对客户端字段、空秘密保留、复制/缺项断言与最终 Compose/env/部署说明。
- AC-003：`re_verified` — 核对可信 origin 与动态 loopback 测试，Compose API 环境传递保持 Round 3 独立渲染结果。
- AC-004：`re_verified` — 核对保留的 code/PKCE/scope/offline/缺 RT 拒绝用例与实际生产路径。
- AC-005：`re_verified` — 核对原会话、epoch、CSRF、TTL 和取消拒绝断言，新增锁改动未移除此校验。
- AC-006：`re_verified` — 核对 state/code 同步与跨流程同码并发断言，DB 原子领取仍保留。
- AC-007：`re_verified` — 核对 Electron 实际 SPA、无 Cookie 回调与原应用确认保存的生产路径及本轮 66 项日志。
- AC-008：`re_verified` — 核对 token/profile 生产传输、真实邮箱/重复/异邮/协议拒绝断言，未变。
- AC-009：`re_verified` — 独立执行活跃指针竞争与新增/重新授权并发保存回归，核对恢复及原子保存的既有断言。
- AC-010：`re_verified` — 核对响应白名单、callback 安全头、URL 清理、加密与脱敏测试保留。
- AC-011：`re_verified` — 独立执行非对象 token 响应回归，核对既有错误分类、取消、过期、重发行为断言。
- AC-012：`re_verified` — 独立执行两项真实 PG 锁序回归与指针竞争；精确核对双方成功、账户归属及新 RT 持久结果。
- AC-013：`re_verified` — 核对新增/编辑帮助与官方链接说明断言保留，本轮前端未变。

coverage = 13 / 13 (100.0%)

verdict: PASS
