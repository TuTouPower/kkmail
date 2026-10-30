# d002 沙箱 iframe 请求不携带同站 Cookie，内联图片不能直接复用附件 URL

- 来源：t066 / p067（cid: 内联图片映射方案验证）
- 结论：给邮件正文 iframe 设置 `sandbox="allow-popups allow-popups-to-escape-sandbox"`（不含 `allow-same-origin`）后，其文档为不透明源；从该 iframe 发出的 `<img>` 子资源请求不会携带同站 `SameSite=Lax` 会话 Cookie。因此不能把 `cid:` 直接重写为需要 Cookie 认证的 `/api/mail/attachments/{id}`。
- 证据：
    1. 最小复现 `.scratch/test_sandbox_cookie_iframe.mjs`：页面设置 `sid=abc; Path=/; SameSite=Lax`，沙箱 iframe 的 `<img src="/img">` 请求头中 `cookie` 为 `(none)`，但图片本身仍可加载（`naturalWidth=1`）；
    2. Chromium headless（Playwright）实测；`allow-same-origin` 会恢复 Cookie，但违反 `mailBody.ts` 的沙箱安全基线，不能采用；
    3. 另测 `Content-Disposition: attachment` 不影响 Chromium 将响应渲染为 `<img>`，但无 Cookie 时认证接口会先返回 401。
- 影响：t066 的 `cid:` 内联图片必须由父页面带认证获取附件字节后以 `data:` URL 注入（或使用等价的无 Cookie 短期签名 URL），不得为附件 URL 方案给 iframe 增加 `allow-same-origin`。CSP 仍可保持不放开远程 http(s)。
- 现状：有效
