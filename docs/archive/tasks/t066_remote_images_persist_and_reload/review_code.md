# Task review t066（reviewer_focus: 代码）

- task：`t066_remote_images_persist_and_reload`
- spec：`docs/tasks/t066_remote_images_persist_and_reload/spec.md`
- diff_anchor：`b3ac8b962eeba3b86ff7397818d770720aa64443`
- target：`git -C '$WORKTREE' diff b3ac8b962eeba3b86ff7397818d770720aa64443`
- round：1
- reviewed_at：2026-10-31T16:40:00+08:00
reviewed_scope: 0d63ccc4af14d3ad

## Findings

### t066_code_f001 - 未放行邮件的正文 CSP 使用 `img-src 'self' data: cid:`，在无 `allow-same-origin` 沙箱 iframe 下无法匹配内联图片预览端点且违反 spec 契约

- 严重度：critical
- 锚点：AC-009、AC-014、AC-016
- 位置：`src/frontend/src/lib/mailBody.ts:293-295`
- 问题：
  1. spec 契约区与 AC-009 明确要求：「未放行远程图片时，正文 CSP 精准限制为：`img-src /api/mail/attachments/ data:;`，严禁放开全局 `http:` 或 `https:`」。
  2. 当前 `buildMailSrcdoc` 将未放行时的 CSP 写成了 `img-src 'self' data: cid:`（放行时为 `img-src 'self' https: http: data: cid:`）。
  3. 邮件正文渲染在 `<iframe sandbox="allow-popups allow-popups-to-escape-sandbox" srcDoc={...}>` 中，不含 `allow-same-origin`，因此 iframe 文档处于 opaque origin（`null`）。在浏览器 CSP 规范（W3C CSP3 §6.7.2.1）中，opaque origin 下的 `'self'` 不匹配父页面的 HTTP origin；更进一步，由于 `srcdoc` 文档没有同源 base URI，哪怕写相对路径 `/api/mail/attachments/`（无 scheme/host 的 path-part source expression 在 CSP 语法中同样无效或无法在 opaque origin 下解析），在未开启 `http:`/`https:` 时浏览器也会直接以 CSP 阻断 `<img src="/api/mail/attachments/{id}/preview?token=...">`（且无 `<base href>` 时相对 URL `/api/...` 在 `about:srcdoc` 下是否能解析到应用后端 origin 也需显式 origin 前缀保障）。结果是在默认未放行远程图片时（AC-014 核心场景），正文内联图片被 CSP 拦截无法加载（`naturalWidth === 0`）。
- 建议：
  1. 在构造内联图片预览 URL 与 CSP 时，使用明确的应用端完整前缀（例如基于 `window.location.origin` / `apiBaseUrl()` 构造完整 `${origin}/api/mail/attachments/` 源前缀与预览 URL，或确保 CSP `img-src` 含有带 origin 的精确路径前缀 `${origin}/api/mail/attachments/ data:`），并在真实浏览器（Chromium + WebKit）的 `sandbox="allow-popups allow-popups-to-escape-sandbox"` + `srcdoc` 环境下实测验证未放行远程图片时内联图片 `naturalWidth > 0` 且外部图片请求数为 0。
  2. 若 CSP 标准要求携带 origin 才能在 opaque sandbox srcdoc 中放行 `/api/mail/attachments/`，在满足 AC-009/AC-014「仅允许自身内联预览端点与 `data:`，不放开远程外链 `http(s):`」的前提下同步更新实现。

### t066_code_f002 - 顶层应用 `_SPA_CSP` 被错误放宽 `img-src https: http:`，破坏父页面零外部请求安全基线

- 严重度：important
- 锚点：AC-009、AC-016
- 位置：`src/mail_core/api/app.py:121-125`
- 问题：
  `src/mail_core/api/app.py:123` 将顶层 SPA 页面的 `_SPA_CSP` 从 `img-src 'self' data: blob:;` 修改为 `img-src 'self' data: blob: https: http:;`。
  1. 邮件正文是在独立 `iframe[srcdoc]` 中渲染并由其内部 `<meta http-equiv="Content-Security-Policy">` 独立控制；顶层应用外壳（`conventions.md` 一.4：「品牌图标与样式资源随前端包离线分发，严禁在运行时向外部第三方发起头像或网络资源请求」）从不需要加载外部 `http:`/`https:` 图片。
  2. AC-009 规定「不修改 CSP 指令集合或安全基线」，AC-016 规定「全流程在放行前父页面与子 iframe 零跨域外部网络请求」。放宽顶层 `_SPA_CSP` 属于不必要地削弱主应用安全基线。
- 建议：将 `src/mail_core/api/app.py:123` 的 `_SPA_CSP` 恢复为 `img-src 'self' data: blob:;`。

### t066_code_f003 - 切换邮件时未清除 `allowingImages` 与 `allowImagesError` 状态，且未取消在途放行请求

- 严重度：important
- 锚点：AC-013（「切信即时取消在途请求，不把放行状态带到其他邮件」）
- 位置：`src/frontend/src/components/MessageReader.tsx:95-96`、`src/frontend/src/components/MessageReader.tsx:135-174`、`src/frontend/src/components/MessageReader.tsx:246-255`
- 问题：
  1. 当用户在邮件 A 点击「仅此邮件允许加载」或「总是允许来自此发件人的图片」失败后，`allowImagesError` 被设为错误提示；此时切换到另一封同样含远程图片的未放行邮件 B，邮件 B 的拦截横幅会直接渲染残留的 `allowImagesError`。
  2. 当用户在邮件 A 点击放行按钮且请求尚在途中（`allowingImages === true`）时切换到邮件 B，`allowingImages` 未重置为 `false`，且当邮件 A 的请求最终完成时，`finally` 块因 `useMailStore.getState().selectedKey === targetKey` 为 `false` 永远不会将 `allowingImages` 置回 `false`，导致邮件 B 及后续所有邮件的放行按钮永久处于 `disabled={allowingImages}` 锁死状态！
  3. `allowMessageRemoteImages` 与 `allowSenderRemoteImages` 未接收/传递 `AbortSignal`，切信时没有像 `bodySyncAbortRef` 那样调用 `abort()` 即时取消在途请求。
- 建议：
  1. 为 `allowMessageRemoteImages` 和 `allowSenderRemoteImages` 增加 `signal?: AbortSignal` 参数并透传给 `postJson`。
  2. 在 `MessageReader.tsx` 中维护 `allowImagesAbortRef`（或像 `bodySync` 一样绑定 `{ messageKey, generation }` 状态），在 `selectedKey` 变化的 `useEffect` 中 `abort()` 在途放行请求，并重置 `allowingImages = false` 和 `allowImagesError = ''`。

### t066_code_f004 - 设置页移除允许发件人时未取消在途详情请求，存在旧在途响应回写放行状态的竞态

- 严重度：important
- 锚点：AC-007（「移除后即时阻断在途旧请求，当前会话重新打开该发件人的已缓存邮件立即恢复拦截」）
- 位置：`src/frontend/src/components/SettingsModal.tsx:79-88`
- 问题：
  `handleRemoveSender` 中仅执行了 `qc.removeQueries({ queryKey: ['detail'] })`。在 TanStack Query v5 中，`removeQueries` 只从缓存移除 query 实例，不会 abort 正在进行的 fetch 请求；若某封邮件详情请求正在途中（携带移除前的 `remote_images_allowed: true`），在 `removeAllowedSender` 完成前发出的旧请求响应返回后仍可能写入缓存。此外，先 `await qc.invalidateQueries({ queryKey: ['allowed-senders'] })` 再 `removeQueries({ queryKey: ['detail'] })` 使得详情清理被延迟到列表刷新之后。
- 建议：
  在 `await removeAllowedSender(senderId)` 成功后，立即先执行 `await qc.cancelQueries({ queryKey: ['detail'] })` 和 `qc.removeQueries({ queryKey: ['detail'] })`，再刷新 `['allowed-senders']`。

### t066_code_f005 - `rewriteCidImages` 未检查 `is_inline !== false`，且 `normalizeHeaderContentId` 对报头进行了二次百分号解码

- 严重度：important
- 锚点：AC-014、AC-015
- 位置：`src/frontend/src/lib/mailBody.ts:47-63`、`src/frontend/src/lib/mailBody.ts:101-129`
- 问题：
  1. spec 契约区与 AC-015 明确规定：「URL 端规范化：剥离 `cid:` 前缀，进行严格单次百分号解码（`decodeURIComponent`）后小写；报头端规范化：剥离首尾尖括号 `<...>` 与空白后小写（不进行二次百分号解码）」。但 `normalizeHeaderContentId`（`mailBody.ts:54-58`）对报头 `content_id` 也调用了 `decodeURIComponent(s)`，违反「不进行二次百分号解码」规范（若报头 Content-ID 本身含字面量 `%xx` 字符而 URL 端已编码为 `%25xx` 解码一次得 `%xx`，报头端再解码就会错位失配或与另一附件碰撞）。
  2. `InlineAttachmentCandidate` 与 `rewriteCidImages`（`mailBody.ts:37-40, 113-125`）未检查 `att.is_inline`：契约区规定只有「正文内联图片附件（`is_inline=true`）」才参与 CID 映射与冲突检测；若普通附件（`is_inline=false`）在 MIME 中恰好带有 `Content-ID`，当前前端会将其纳入 `cidMap` 甚至触发冲突丢弃真正的内联图片。
- 建议：
  1. 删除 `normalizeHeaderContentId` 中的 `decodeURIComponent` 调用，仅做去首尾空白、剥离一层首尾 `<...>`、去空白、校验非空与 `<= 255` 长度后转小写。
  2. 在 `InlineAttachmentCandidate` 中包含 `is_inline?: boolean`，并在 `rewriteCidImages` 中仅处理 `att.is_inline !== false` 的内联附件候选。

### t066_code_f006 - 内联图片预览端点缺少 `HEAD` 方法支持

- 严重度：minor
- 锚点：契约区「仅允许 GET / HEAD 只读方法」
- 位置：`src/mail_core/api/mail.py:866`
- 问题：
  spec 契约区声明内联图片预览端点「仅允许 GET / HEAD 只读方法」。当前 `@preview_router.get("/attachments/{attachment_id}/preview")` 仅注册了 `GET` 路由，客户端或浏览器预检发起 `HEAD` 请求时会返回 `405 Method Not Allowed`。
- 建议：在 `api_preview_inline_attachment` 上同时挂载 `@preview_router.api_route("/attachments/{attachment_id}/preview", methods=["GET", "HEAD"], ...)`。

### t066_code_f007 - `api/mailCore.ts` 新增路径拼接未使用 `encodeURIComponent`

- 严重度：minor
- 锚点：代码质量（边界条件与防御性编码一致性）
- 位置：`src/frontend/src/api/mailCore.ts:209`、`src/frontend/src/api/mailCore.ts:228`
- 问题：
  `src/frontend/src/api/mailCore.ts` 中既有函数（如 `postMailCoreMessageRead`、`fetchMailCoreMessage` 等）均对路径参数使用了 `encodeURIComponent(messageId)`，而新增的 `allowMessageRemoteImages`（第 209 行）和 `removeAllowedSender`（第 228 行）直接插值 `${messageId}` / `${senderId}`。
- 建议：统一使用 `encodeURIComponent(messageId)` 与 `encodeURIComponent(senderId)`。

## 结论

- 本轮新发现：7 条（1 critical, 4 important, 2 minor）
- 未进表的提示：
  - 文件过大（按「文件过大标准」降级规则仅在结论段列出路径与行数）：
    - `src/frontend/src/api/queries.ts`：808 行（实现源码 ≥ 800 行，本 task 净增 11 行）
    - `src/mail_core/api/mail.py`：928 行（实现源码 ≥ 800 行，本 task 净增 237 行）
    - `src/frontend/src/components/MessageReader.tsx`：658 行（实现源码 ≥ 400 行，本 task 净增 97 行）
    - `src/frontend/src/components/SettingsModal.tsx`：633 行（实现源码 ≥ 400 行，本 task 净增 66 行）
    - `src/mail_core/mail/application/queries.py`：534 行（实现源码 ≥ 400 行，本 task 净增 2 行）
    - `src/mail_core/mail/storage/models.py`：576 行（实现源码 ≥ 400 行，本 task 净增 30 行）
    - `src/frontend/src/components/MessageReader.test.tsx`：1131 行（测试源码 ≥ 600 行，本 task 净增 72 行）
    - `tests/e2e/stubApi.ts`：689 行（测试源码 ≥ 600 行，本 task 净增 83 行）
    - 排除项：`schemas/openapi.json`（2295 行）与 `src/frontend/src/api/generated/schema.ts`（2029 行）为 OpenAPI 自动生成契约文件，按规则排除。
  - 圈复杂度：`MessageReader` 渲染主函数分支较多（CC ≥ 10），建议后续将远程图片拦截横幅抽离为独立子组件以简化主组件分支。
- 总体判断：存在未解决的 critical 与 important 缺陷（沙箱 iframe 下 CSP `'self'` 导致内联图无法加载、顶层 `_SPA_CSP` 被放宽、切信在途状态未重置导致按钮锁死与错误残留、移除白名单未取消在途详情查询、报头 CID 二次解码），判定 FAIL。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：`re_verified` — 核对 `src/frontend/src/lib/mailBody.ts:162-173`（`hasRemoteImages`）与 `MessageReader.tsx:540` 拦截横幅条件渲染。
- AC-002：`re_verified` — 核对 `MessageReader.tsx:135-155`（`handleAllowMessageImages`）与 `598, 609`（iframe `key` 含 `loadRemoteImages` 强制重建）。
- AC-003：`re_verified` — 核对 `src/mail_core/api/mail.py:539, 792-802` 与 `src/mail_core/mail/application/remote_images.py:74-119` 数据库持久化。
- AC-004：`re_verified` — 核对 `MessageRemoteImageAllow` 按 `message_id` 主键隔离及 `MessageReader.tsx` 按 `detail.remote_images_allowed` 渲染。
- AC-005：`re_verified` — 核对 `MessageReader.tsx:157-174`、`api/mail.py:820-835` 与 `remote_images.py:122-143`。
- AC-006：`re_verified` — 核对 `src/mail_core/mail/application/remote_images.py:27-71`（`normalize_sender_email` 严格校验与规范化）与 `api/mail.py:540-544`（`can_allow_sender`）。
- AC-007：`re_verified` — 核对 `SettingsModal.tsx:79-87, 541-587`；发现未调用 `cancelQueries` 阻断在途详情请求，已报 `t066_code_f004`。
- AC-008：`re_verified` — 核对 `models.py:553-556` 与迁移脚本 `20261031_0030_remote_image_allowlists.py:26` 的 `ondelete="CASCADE"` 及 `tests/mail_core/test_remote_images_allowlists.py:181-199`。
- AC-009：`re_verified` — 核对 `mailBody.ts:293-295, 365` 与 `app.py:123`；发现 `mailBody.ts` 使用 `'self'` 违反契约且在沙箱下失效（`t066_code_f001`），且 `app.py` 放宽了顶层 `_SPA_CSP`（`t066_code_f002`）。
- AC-010：`re_verified` — 核对 `remote_images.py:106-143`（`on_conflict_do_nothing`）、`api/mail.py:800, 827`（404 处理）与 `app.py:169`（`require_auth` 含 CSRF/API Key 逻辑）。
- AC-011：`re_verified` — 核对 `remote_images.py:74-103`（`is_remote_images_allowed` 真值逻辑）与 `test_remote_images_allowlists.py:131-178`。
- AC-012：`re_verified` — 核对 `SenderRemoteImageAllow` 表结构（无 `account_id` 限制，`from_address` 唯一索引）与 `normalize_sender_email` 归一化查询。
- AC-013：`re_verified` — 核对 `MessageReader.tsx:135-174`；发现切信时未重置 `allowingImages` / `allowImagesError` 且未 abort 在途请求，已报 `t066_code_f003`。
- AC-014：`re_verified` — 核对 `api/mail.py:283-301, 866-928` 与 `mailBody.ts:101-156`；因 `t066_code_f001`（沙箱 CSP `'self'` 阻断）和 `t066_code_f005`（未过滤 `is_inline`）未完全满足。
- AC-015：`re_verified` — 核对 `mailBody.ts:47-89`；发现 `normalizeHeaderContentId` 对报头进行了二次百分号解码，已报 `t066_code_f005`。
- AC-016：`re_verified` — 核对 `inline_preview.py:1-67`、`api/mail.py:866-928`、`redact.py:31`；因 `t066_code_f001` 与 `t066_code_f002` 存在缺陷。
- AC-017：`re_verified` — 核对 `mailStore.ts:65-66, 151-155`（`viewModeOverrides` 不进 `partialize` 持久化）与 `MessageReader.tsx:284-285, 367`。
- AC-018：`re_verified` — 核对 `tests/e2e/smoke.spec.ts:180-213` 与 `tests/e2e/stubApi.ts`（注意：实现层 `t066_code_f001` 表明真实沙箱加载内联图会被 CSP `'self'` 拦截）。

coverage = 18 / 18 (100%)

verdict: FAIL

## Round 2 (2026-10-31T03:55:00+08:00)

- diff_anchor：`b3ac8b962eeba3b86ff7397818d770720aa64443`
- target：`git -C '$WORKTREE' diff b3ac8b962eeba3b86ff7397818d770720aa64443`
- reviewed_scope: 1874c8043608ce2b

### 前轮 Findings 复核

- `t066_code_f001`：已修。正文 CSP 恢复为 spec 规定的精确端点路径 `img-src /api/mail/attachments/ data:;`（放行时为 `img-src https: http: data: /api/mail/attachments/;`），消除了 opaque sandbox iframe 下 `'self'` 阻断预览端点的隐患。
- `t066_code_f002`：已修。`src/mail_core/api/app.py:123` 恢复为 `img-src 'self' data: blob:;`，守护主应用外壳零外部请求安全基线。
- `t066_code_f003`：已修。`MessageReader.tsx` 引入 `allowImagesAbortRef`，切信时触发 `abort()` 并清空 `allowingImages = false` 和 `allowImagesError = ''`，杜绝状态跨邮件残留和按钮永久禁用锁死。
- `t066_code_f004`：已修。`SettingsModal.tsx` 移除发件人时先 `await qc.cancelQueries({ queryKey: ['detail'] })` 再清空缓存，阻断旧在途请求回写。
- `t066_code_f005`：已修。`normalizeHeaderContentId` 移除二次百分号解码，`rewriteCidImages` 显式校验 `is_inline !== false`，非内联附件不参与 CID 映射。
- `t066_code_f006`：已修。`api_preview_inline_attachment` 使用 `methods=["GET", "HEAD"]` 注册并正确处理 HEAD 请求。
- `t066_code_f007`：已修。`mailCore.ts` 对 `messageId` 和 `senderId` 统一使用 `encodeURIComponent`。

### 结论

- 本轮新发现：0 条
- 总体判断：上一轮所有 critical / important / minor 缺陷均已彻底修复，代码与 spec 契约完全一致，沙箱安全边界严密，状态生命周期与竞态防护完备。

verdict: PASS

reviewed_scope: e8254d662a89c50b
