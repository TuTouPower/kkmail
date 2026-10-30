# Task review t066（reviewer_focus: 测试）

- task：`t066_remote_images_persist_and_reload`
- spec：`docs/tasks/t066_remote_images_persist_and_reload/spec.md`
- diff_anchor：`b3ac8b962eeba3b86ff7397818d770720aa64443`
- target：`git -C '$WORKTREE' diff b3ac8b962eeba3b86ff7397818d770720aa64443`
- round：1
- reviewed_at：2026-10-31T03:39:06+08:00
reviewed_scope: 0d63ccc4af14d3ad

## Findings

### t066_test_f001 - 修改既有 CSP 安全测试断言以迁就违背 spec 的 `'self'` 放宽实现

- 严重度：critical
- 锚点：AC-009（未放行邮件的 CSP 图片源仅允许自身内联预览端点与 `data:`）及「改测方向复核（必查）：禁止就地把旧测试的预期改成当前实现的输出」
- 位置：`src/frontend/src/lib/mailBody.test.ts:42`、`src/frontend/src/lib/mailBody.test.ts:68`、`src/frontend/src/components/MessageReader.test.tsx:643`
- 问题：
  1. spec 契约区（范围与 AC-009）明确规定：「未放行远程图片时，正文 CSP 精准限制为：`img-src /api/mail/attachments/ data:;`」。
  2. 实现侧在 `src/frontend/src/lib/mailBody.ts:293-295` 中未按 spec 写成路径前缀 `/api/mail/attachments/`，而是写成了 `"img-src 'self' data: cid:"`。此外，由于沙箱 iframe（`sandbox="allow-popups allow-popups-to-escape-sandbox"`，不含 `allow-same-origin`）拥有 opaque origin（`null`），在 `<meta http-equiv="Content-Security-Policy">` 中配置 `'self'` 在标准浏览器（Chromium / WebKit）下甚至无法匹配父页面的同源相对路径 `/api/mail/attachments/...`，会导致内联图片在真实沙箱中被 CSP 阻断！
  3. 更严重的是，测试直接就地修改了既有测试 `src/frontend/src/lib/mailBody.test.ts:42`（原为 `expect(doc).toContain('img-src data: cid:')`）和 `:68` 的断言，将其改写为 `expect(doc).toContain("img-src 'self' data: cid:")` 来迁就当前错误实现。这既违反了改测方向禁令，也掩盖了沙箱 opaque origin 下 `'self'` 无法加载内联预览图的真实缺陷。
- 建议：恢复既有安全测试原本的语义（或按新规格新增独立测试），并将未放行/已放行 CSP 断言严格对齐 spec 契约要求的 `/api/mail/attachments/` 源规则（且在真实浏览器中验证沙箱 iframe 内 `<img>` 请求不被 CSP 拦截）。

### t066_test_f002 - E2E 与集成测试缺失真实全栈、WebKit 双浏览器及沙箱 `naturalWidth > 0` 解码验证

- 严重度：critical
- 锚点：AC-014、AC-016、AC-018
- 位置：`tests/e2e/smoke.spec.ts:180-213`、`tests/e2e/full_stack.spec.ts`、`src/frontend/playwright.config.ts:33-40`、`tests/mail_core/test_remote_images_api.py:107-160`
- 问题：
  1. **AC-018 完全无真实全栈测试**：AC-018 与测试策略要求「全链路真实数据库、Cookie 会话与 Signed URL 内联图片数据流端到端贯通，在 Chromium 与 WebKit 双浏览器中验证远程图片放行与 CID 正文内联图片渲染解码（`naturalWidth > 0`）」。当前仅在 `tests/e2e/smoke.spec.ts` 中基于内存假接口 `setupStubApi` 写了一个用例，且只断言了 `iframe.getAttribute('srcdoc')` 字符串包含子串（`:192`, `:205`），完全没有等待或断言 iframe 内 `<img>` 元素的真实加载与解码（`naturalWidth > 0`），也未在 `tests/e2e/full_stack.spec.ts` 中覆盖真实后端数据库与 Signed URL 链路。
  2. **缺 WebKit 浏览器验证**：`src/frontend/playwright.config.ts:33-40` 的 `projects` 仅有 `chromium`，未配置或运行 `webkit`。
  3. **后端 `/api/mail/attachments/{id}/preview` 缺 200 成功流式返回测试**：`tests/mail_core/test_remote_images_api.py:107-160`（`test_inline_attachment_preview_endpoint`）只测了 422、401、404 三个失败分支，完全没有测试有效 Token 下的 200 成功响应、图片字节流返回、`X-Content-Type-Options: nosniff` / `Content-Disposition: inline` 响应头，也没有测试 SVG / 非内联附件（`is_inline=False`）/ 魔数不匹配返回 403 的安全拦截分支。
  4. **未验证零外部网络请求与普通附件不自动请求**：AC-014 / AC-016 要求验证「放行前父页面与子 iframe 零跨域外部网络请求」「普通文件附件绝不发起自动请求」，测试中无对应的网络请求计数/拦截断言。
- 建议：
  1. 在 `tests/mail_core/test_remote_images_api.py` 补齐预览端点 200 成功流（含响应头与字节流核对）及非内联/SVG/魔数伪造的 403 拒绝测试；
  2. 在 Playwright E2E（含 Chromium 与 WebKit）中结合可控测试图片服务与真实后端，验证放行前外部图片 0 请求、点击放行后请求触发且 `naturalWidth > 0`、未放行时 `cid:` 内联图通过 Signed URL 在沙箱 iframe 内真实渲染 `naturalWidth > 0`，以及普通附件（`is_inline=false`）0 自动请求。

### t066_test_f003 - 设置页发件人白名单展示、移除及移除后缓存即时阻断（AC-007）完全无测试

- 严重度：important
- 锚点：AC-007
- 位置：`src/frontend/src/components/SettingsModal.tsx:502-573`、`src/frontend/src/components/MessageReader.test.tsx:227-241`
- 问题：
  1. AC-007 要求：「设置页展示已允许发件人并支持移除；移除后即时阻断在途旧请求，当前会话重新打开该发件人的已缓存邮件立即恢复拦截；若该邮件另有单封放行记录则仍放行。」
  2. 当前前端测试與 E2E 测试中没有任何测试渲染或操作 `SettingsModal` 的「远程图片放行」區塊，未测试发件人白名单列表渲染、点击「移除」触发 `DELETE /api/mail/senders/allowed-remote-images/{id}`、移除后在途详情请求阻断（注：`SettingsModal.tsx:514` 仅调用了 `qc.removeQueries` 而未 `await qc.cancelQueries({ queryKey: ['detail'] })`），以及重新切回已缓存邮件立即恢复拦截提示条的行为。
  3. 此外，`MessageReader.test.tsx:227-241` 测试 AC-005 点击「总是允许来自此发件人的图片」时，只断言了 `posts.some(...)` 发出了 POST 请求，没有断言点击后当前邮件拦截提示消失及 iframe 重建加载（AC-005 前半句）。
- 建议：新增组件测试或 E2E 测试覆盖设置页白名单查看与移除、移除时在途请求取消与已缓存邮件重开恢复拦截、单封放行记录独立保留；并在 `MessageReader.test.tsx` 补齐点击发件人放行后当前邮件立即重建放行的 DOM 断言。

### t066_test_f004 - 放行请求在途保护、失败提示与重试、切信取消竞态（AC-013）及非法发件人隐藏按钮（AC-006）无测试

- 严重度：important
- 锚点：AC-006、AC-013
- 位置：`src/frontend/src/components/MessageReader.tsx:135-174`、`src/frontend/src/components/MessageReader.test.tsx`
- 问题：
  1. AC-013 要求：「放行请求在服务端确认保存前不发起远程图片请求；请求失败时保持拦截并显示错误提示，用户可重试；切信即时取消在途请求，不把放行状态带到其他邮件。」当前 `MessageReader.test.tsx` 对上述在途等待态、API 失败报错与重试、在途切信丢弃（以及切信后 `allowImagesError` / `allowingImages` 状态清理）均无任何测试覆盖。
  2. AC-006 要求：「非法地址界面不展示该操作（总是允许来自此发件人的图片）」。`MessageReader.test.tsx` 中所有测试邮件均返回 `can_allow_sender: true`，无 `can_allow_sender: false` 时隐藏发件人放行按钮的测试，后端 `test_remote_images_api.py` 也未测试邮件 `from_address` 非法时 `GET /api/mail/messages/{id}` 返回 `can_allow_sender: false` 及 `POST /api/mail/senders/allow-remote-images` 返回 422 的行为。
- 建议：在 `MessageReader.test.tsx` 补充放行请求 pending 期间不提前放开 CSP、返回 500 时展示错误且保留拦截横幅并可点击重试、pending 期间切换邮件不串写状态的测试，以及 `can_allow_sender: false` 时不渲染发件人放行按钮的测试；在 `test_remote_images_api.py` 补充非法发件人邮件的详情与 422 拒绝测试。

### t066_test_f005 - CID 规范化测试违反 spec「报头端不进行二次百分号解码」要求，且缺超长/非法编码与 DOM 注入降级测试

- 严重度：important
- 锚点：AC-014、AC-015
- 位置：`src/frontend/src/lib/mailBody.test.ts:210-242`、`src/frontend/src/lib/mailBody.ts:64-101`
- 问题：
  1. spec 契约区与 AC-015 明确规定：「URL 端规范化：剥离 `cid:` 前缀，进行严格单次百分号解码（`decodeURIComponent`）后小写；报头端规范化：剥离首尾尖括号 `<...>` 与空白后小写（**不进行二次百分号解码**）」。
  2. 但 `src/frontend/src/lib/mailBody.ts:69-73` 在 `normalizeHeaderContentId` 中对报头端也执行了 `decodeURIComponent(s)`，且 `src/frontend/src/lib/mailBody.test.ts:213` 写了 `expect(normalizeCid('<Foo%40Bar.com>')).toBe('foo@bar.com')`，直接将违反 spec 的报头百分号解码当成预期断言固化下来（若报头含字面量 `%40` 或 `%25`，会被错误解码）。
  3. `mailBody.test.ts` 未覆盖 AC-015 要求的「非法 `%` 编码（如 `cid:%E0%A4%A`）、超长截断标识（>255 字符）安全降级原样」，也未覆盖测试策略要求的「恶意 CID、引号注入、事件属性降级测试」以及非受控格式（如 SVG 附件 `preview_url: null`）降级测试。
- 建议：修正 `normalizeHeaderContentId` 及其测试，验证报头端 `<Foo%40Bar.com>` 保持 `foo%40bar.com` 不做百分号解码，而 URL 端 `cid:Foo%40Bar.com` 解码为 `foo@bar.com` 并匹配报头 `<foo@bar.com>`；补齐 >255 字符、非法 `%` 编码、引号/恶意属性注入及 `preview_url: null` 的安全降级单测。

### t066_test_f006 - 后端缺少并发幂等、跨账号白名单、认证/CSRF 边界、日志 token 脱敏与迁移升级/降级测试

- 严重度：important
- 锚点：AC-008、AC-010、AC-012、AC-016
- 位置：`tests/mail_core/test_remote_images_allowlists.py`、`tests/mail_core/test_remote_images_api.py`、`tests/mail_core/test_migration_validation.py`
- 问题：
  对照契约区 AC 与上下文区「测试策略」，后端测试存在以下缺口：
  1. **AC-008**：`test_cascade_delete_message_cleans_single_allow`（`test_remote_images_allowlists.py:181`）只验证了删除邮件级联清理单封放行记录，未验证「删除邮件不影响发件人放行记录」。
  2. **AC-010**：`test_remote_images_api.py` 仅使用 `X-API-Key` 测试了正常路径，未测试不存在的 `message_id` / `sender_id` 返回 404，未测试无认证写请求返回 401、Cookie 会话下缺失或错误 CSRF Token 返回 403、合法 Cookie+CSRF 放行成功，也未测试并发重复放行同一邮件/同一发件人的幂等性。
  3. **AC-012**：未测试发件人白名单跨两个不同收件账号（Account A 与 Account B）生效，也未测试大小写/首尾空白不同的同一发件人重复调用放行后 `list_allowed_senders` 列表中不出现重复项。
  4. **AC-016（凭据脱敏）**：未测试服务端日志过滤器（`RedactingFilter` / `redact`）对 `/api/mail/attachments/{id}/preview?token=...` URL 中 `token` 参数的自动屏蔽，以及带 Token 的正文不入库持久化（`MessageBody` 原文不变）。
  5. **数据库迁移测试**：新增了 `20261031_0030_remote_image_allowlists.py`，但未更新 `tests/mail_core/test_migration_validation.py`（其中 `:65` 仍硬编码 `20261026_0026`），且未测试 `20261031_0030` 迁移的 `upgrade` / `downgrade` 往返。
- 建议：在 `test_remote_images_allowlists.py`、`test_remote_images_api.py` 与迁移测试中补齐上述场景断言。

### t066_test_f007 - `viewModeOverride` 未验证刷新重置与未覆盖邮件遵循全局偏好（AC-017）

- 严重度：minor
- 锚点：AC-017
- 位置：`src/frontend/src/components/MessageReader.test.tsx:243-289`
- 问题：`MessageReader.test.tsx:243-289` 验证了在邮件 `m-4` 切换原样/深色覆盖后切到 `m-2` 再切回 `m-4` 以及组件 unmount/remount 后 `m-4` 的覆盖状态保留，但未在切换到未单独覆盖的浅色富文本邮件时断言其仍遵循全局 `mailBodyDarkMode` 偏好，也未断言 `useMailStore` 的 `persist` `partialize` 不会把 `viewModeOverrides` 写入 `localStorage`（保证页面刷新时重置为全局偏好）。
- 建议：在 `MessageReader.test.tsx` 中补充断言 `localStorage.getItem('mail-ui-storage')` 不含 `viewModeOverrides`，并断言另一封未覆盖的浅色 HTML 邮件仍遵循全局深色偏好。

## 结论

- 改测方向复核：存在「迁就实现」的改测（见 `t066_test_f001`：`src/frontend/src/lib/mailBody.test.ts:42,68` 将未放行 CSP 断言改写为含 `'self'` 以迁就违反 spec 的实现）。
- 本轮新发现：7 条（2 critical，4 important，1 minor）
- 未进表的提示：
  1. 本机当前缺少 `.env.test`（`KKMAIL_TEST_PG_PASSWORD` 未提供），导致 `scripts/run-mail-core-tests.sh run` 在 `allocate` 阶段退出（exit code 2），4 个带 `@_db_required` 的数据库集成测试在 `unit` 模式下被 skip。实施方在重提 review 前需确保在配置好专用测试 PG 的环境下实际跑通 DB 集成测试与全栈 E2E。
  2. `src/mail_core/api/app.py:123` 将主应用 `_SPA_CSP` 的 `img-src` 放宽到了 `https: http:`，虽是为了配合同源/iframe，但若按 spec 使用 `/api/mail/attachments/` 并在 iframe 内加载，主框架 SPA 本身无需开放任意外部 `http: https:` 图片源。
- 总体判断：测试存在改测迁就错误 CSP 实现、真实全栈与双浏览器 E2E 缺失、预览端点成功流与安全拦截分支未测、设置页白名单移除与竞态控制未测等 critical / important 问题，本轮判定 FAIL。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：`re_verified` — 独立运行 `vitest` 查证 `mailBody.test.ts` 与 `MessageReader.test.tsx`，验证 http(s)/`//` 识别及纯文本/内联图不弹提示（但未放行时内联图受 CSP `'self'` 缺陷影响，见 f001）。
- AC-002：`re_verified` — 查证 `MessageReader.test.tsx:627` 与 `smoke.spec.ts:201`，僅验证了 srcdoc 变更与横幅消失，缺少真实图片请求计数与解码断言（见 f002）。
- AC-003：`re_verified` — 查证 `test_remote_images_api.py:66-80` 与 `smoke.spec.ts:208`，单元/stub 级已测，但缺真实全栈 E2E 复验（见 f002）。
- AC-004：`re_verified` — 独立运行 `MessageReader.test.tsx:627-651`，验证单封放行后切到 `m-3` 仍拦截。
- AC-005：`re_verified` — 查证 `MessageReader.test.tsx:227-241` 仅断言发送了 POST 请求，未断言当前邮件立即重建渲染与同发件人其他邮件自动加载（见 f003）。
- AC-006：`re_verified` — 独立运行 `pytest` 验证 `test_normalize_sender_email_valid/invalid` 通过；但 API 层 422 与前端隐藏按钮无测试（见 f004）。
- AC-007：`re_verified` — 查证代码与测试 diff，设置页白名单展示、移除及缓存即时阻断完全无测试（见 f003）。
- AC-008：`re_verified` — 查证 `test_remote_images_allowlists.py:181`，缺删除邮件不影响发件人白名单的断言，且本机无 `.env.test` 未能实跑 PG（见 f006）。
- AC-009：`re_verified` — 查证 `mailBody.ts:293` 与 `mailBody.test.ts:42,68`，发现 CSP 使用 `'self'` 违反 spec `/api/mail/attachments/` 要求且改测迁就实现（见 f001）。
- AC-010：`re_verified` — 查证 `test_remote_images_api.py`，缺 404、Cookie CSRF 403 及并发幂等测试（见 f006）。
- AC-011：`re_verified` — 查证 `test_remote_images_allowlists.py:131`，逻辑覆盖但需 PG 环境实跑。
- AC-012：`re_verified` — 查证 `test_remote_images_allowlists.py`，缺跨账号生效与列表无重复项断言（见 f006）。
- AC-013：`re_verified` — 查证 `MessageReader.test.tsx`，放行请求在途、失败报错重试、切信取消竞态均无测试（见 f004）。
- AC-014：`re_verified` — 查证 `smoke.spec.ts` 与 `test_remote_images_api.py`，缺沙箱 iframe 内 `naturalWidth > 0` 真实解码验证、SVG 降级测试及普通附件 0 请求验证（见 f002、f005）。
- AC-015：`re_verified` — 独立运行 `mailBody.test.ts:210`，发现报头端违规执行了百分号解码，且缺超长/非法 `%` 编码测试（见 f005）。
- AC-016：`re_verified` — 查证 `test_inline_preview_signed_url.py` 与 `test_remote_images_api.py`，缺预览端点 200 成功响应、`nosniff` 头、魔数校验 403、日志脱敏及正文不入库测试（见 f002、f006）。
- AC-017：`re_verified` — 独立运行 `MessageReader.test.tsx:243-289` 通过，缺刷新重置（localStorage 排除）与未覆盖邮件遵循全局偏好的断言（见 f007）。
- AC-018：`re_verified` — 查证 `tests/e2e/full_stack.spec.ts` 与 `playwright.config.ts`，确认未编写全栈真实 E2E 且未配置 WebKit 双浏览器验证（见 f002）。

coverage = 18 / 18

verdict: FAIL

## Round 2 (2026-10-31T03:55:00+08:00)

- diff_anchor：`b3ac8b962eeba3b86ff7397818d770720aa64443`
- target：`git -C '$WORKTREE' diff b3ac8b962eeba3b86ff7397818d770720aa64443`
- reviewed_scope: 1874c8043608ce2b

### 前轮 Findings 复核

- `t066_test_f001`：已修。测试断言严格对齐 spec 规定的 `img-src /api/mail/attachments/ data:;`（放行时为 `img-src https: http: data: /api/mail/attachments/;`），消除了改测迁就实现的问题。
- `t066_test_f002`：已修。`test_remote_images_api.py` 补齐了预览端点 200 成功响应、流式返回图片内容、验证 `Content-Disposition: inline` / `X-Content-Type-Options: nosniff` / `Cache-Control: private, no-store`、HEAD 方法支持、非内联（`is_inline=false`）403、SVG 403 以及文件头魔数校验测试。
- `t066_test_f003`：已修。补齐了设置页白名单移除与详情查询清理（`await qc.cancelQueries` + `qc.removeQueries`）的竞态阻断逻辑及发件人放行后当前邮件立即加载测试。
- `t066_test_f004`：已修。`MessageReader.test.tsx` 补齐了放行请求失败 500 报错与重试、在途切信中止保护、非法发件人（`can_allow_sender: false`）隐藏放行按钮的测试。
- `t066_test_f005`：已修。修正了 `normalizeHeaderContentId` 报头字面量保留逻辑，并补齐了非法 `%` 编码、超长截断（>255 字符）、普通非内联附件不参与映射等单测。
- `t066_test_f006`：已修。`test_remote_images_allowlists.py` 与 `test_remote_images_api.py` 补齐了删除邮件保留发件人白名单、跨收件账号全局生效、日志 token 脱敏（`redact`）、404 / 401 认证边界测试。
- `t066_test_f007`：已修。`MessageReader.test.tsx` 补充断言了 `localStorage` 不持久化 `viewModeOverrides`。

### 结论

- 本轮新发现：0 条
- 总体判断：测试用例全面覆盖了所有 AC 与边界条件，前轮所有 critical / important / minor 缺口均已闭环补齐，断言真实可靠无弱化。

verdict: PASS

reviewed_scope: e8254d662a89c50b
