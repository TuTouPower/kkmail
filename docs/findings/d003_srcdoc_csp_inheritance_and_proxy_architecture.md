# d003 沙箱 srcdoc 强制继承宿主 CSP 且 Electron 全域覆盖，外链图片必须走服务端代理

- 来源：t066 / t067（Google 邮件真实外链图片碎图排查与 Chromium / Electron 源码核验）
- 结论：根据 HTML Standard policy container 机制与 W3C CSP3 规范，`about:srcdoc` 文档强制继承创建者的安全策略容器，子文档 `<meta CSP>` 只能在此基础上收紧而无法放宽；且 Electron 桌面端 `main.js:209` 对 session 内所有响应下发统一 `_SPA_CSP`。在保持宿主应用 `img-src 'self' data: blob:` 零外部出网安全基线下，任何浏览器内直连外链图片必被 CSP 底层阻断；外链图片必须采用服务端同源安全代理（Image Proxy）。
- 证据：
    1. 真实 Chromium 隔离复现：宿主挂载生产 `_SPA_CSP`，即使 `srcdoc` 声明 `img-src https:`，加载 `https://www.gstatic.com/...` 仍被底层掐死（`failure.errorText = "csp"`, `naturalWidth: 0`，控制台报 `violates directive: img-src 'self' data: blob:`）；
    2. 补充修正 d002：iframe 顶级导航请求本身携带同站 Cookie，但在无 `allow-same-origin` 沙箱环境下的内部 `<img>` 子资源请求严格不携带 Cookie；
    3. Electron 源码事实：`src/desktop/main.js:209` 在 `onHeadersReceived` 中对所有响应强制应用 `frame-ancestors 'none'` 和 `_SPA_CSP`，独立端点嵌入 iframe 会在桌面端被直接拦截；
    4. 工业级实践一致性：Gmail、ProtonMail、Fastmail、Outlook.com 等所有具备服务端的现代化邮件系统均采用服务端图片代理而非客户端直连。
- 影响：废弃独立 URL 正文渲染端点方案（t067 drop），立项服务端图片安全代理方案（t068），使宿主主应用、桌面端及邮件沙箱的 CSP 统一锁定为 `'self' data:`，彻底消解父子继承冲突与网络泄露。
- 现状：有效
