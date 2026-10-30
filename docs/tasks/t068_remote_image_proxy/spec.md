# Task spec

## 背景

在 `t066` 落地了远程图片放行入库与 CID Signed URL 机制后，用户在放行发件人后打开包含真实外链图片（Google CDN `https://www.gstatic.com/...`）的邮件，图片依然呈碎图状态。经实测确证（`docs/findings/d003`），根因在于 `about:srcdoc` 强制继承宿主 policy container，且 Electron 全 session 强制注入 `_SPA_CSP`，子文档内的 meta CSP 无法超越父级限制。如果尝试让浏览器直连外部图片，不仅破坏主站零出网基线、泄漏用户真实 IP 和浏览器指纹，还会撞上 Electron `frame-ancestors 'none'` 拦截及混合内容（HTTP/HTTPS）阻断。

现代工业级 Webmail（Gmail、ProtonMail、Fastmail、Outlook.com 等）的标准架构无一例外采用**服务端安全图片代理（Image Proxy）**：浏览器永远只向本站请求同源图片，服务端代替浏览器安全抓取外链并做格式验证与隐私脱敏。

本 task 建立服务端安全图片代理架构，彻底消除 CSP 继承冲突，将全系统 CSP 永久锁定为 `'self' data:` 零外部出网，提供真正的隐私防追踪，并补齐真实端到端测试。

## 契约区

### 范围

- 服务端图片安全代理端点：
    - 挂载独立免 Cookie 预览路由：`GET /api/mail/messages/{id}/remote-images?token=...`；
    - **确定性无状态 Token**：使用 `itsdangerous`（复用主密钥与专用 salt `kkmail/remote-image-proxy/v1`），载荷绑定 `version=1`、`purpose="remote-image"`、`message_id`、`url` 及时间戳；
    - **实时放行状态核验**：端点处理代理请求时，实时检查目标 `message_id` 在数据库中是否依然处于放行状态（单封放行或发件人白名单）；若白名单已被撤销，立即返回 403 拒绝，实现零缓存延迟的实时撤销；
    - **严密 SSRF 防护门禁**：
        - Scheme 与端口白名单：仅限 `http` 与 `https`，仅限标准端口 80 与 443；拒绝包含 userinfo（如 `user:pass@host`）的 URL；
        - DNS 解析与全局地址核验：解析所有 A / AAAA 记录，严格排除私有网络、本地回环、链路本地、多播及保留地址（`127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `::1`, `fc00::/7`, `fe80::/10`，以及拆解后的 IPv4-mapped IPv6 地址）；
        - DNS Rebinding 防护：TCP 连接直连至已完成安全校验的目标 IP，TLS 握手时通过 SNI 传递原主机名并验证目标证书；
        - 重定向防护：禁止自动无限制重定向，手动严格跟随重定向（最多 3 跳），每一跳必须重新通过完整 SSRF 校验；
        - 出网请求净化：请求严禁携带任何 Cookie、Authorization、Referer；固定客户端 User-Agent；设置 `Accept: image/*`；
        - 资源配额与超时：连接超时 5s、总读取超时 15s；单图最大体积 10 MiB（流式读取超限立即断开）；并发拉取保护；
        - 格式与安全位图白名单：仅限 `image/png`, `image/jpeg`, `image/gif`, `image/webp`，严格排除 `image/svg+xml`（防御 XSS）及一切非位图；按文件头真实魔数核验，输出受控 MIME，不透传上游不可信 Header；
        - 响应头强制设置：`Content-Disposition: inline`、`X-Content-Type-Options: nosniff`、`Cache-Control: private, max-age=...`、针对独立访问设置纵深防御 `Content-Security-Policy: default-src 'none'`；
        - 日志脱敏：`token` 与目标 `url` 自动脱敏屏蔽。
- 正文外链 URL 代理重写与前端集成：
    - 服务端邮件详情接口：当邮件处于已放行状态时，服务端扫描正文 HTML 中出现的外链 URL，签发对应的代理 URL 映射列表 `remote_images: [{ url, proxy_url }]`（有界上限，最多 200 个，单个 URL 长度 ≤2048）；
    - 前端 `prepareMailHtml`：若处于已放行状态，将正文中完全匹配的 `img[src]` 与行内 `style="background-image:url(...)"` 重写为对应的本站代理 URL；未放行时，直接移除或不替换，保持拦截横幅；
    - 全局 CSP 统一：
        - 宿主应用 `_SPA_CSP` 保持最严苛的 `img-src 'self' data: blob:`；
        - 桌面端 `hardening.js` 保持 `img-src 'self' data: blob:`；
        - 邮件正文沙箱 iframe 的 CSP 统一且固定为：`default-src 'none'; img-src 'self' data: cid:; style-src 'unsafe-inline'; font-src data:;`，三处 CSP 永久无需放开全局 `http(s):`，零外部出网！
- 真实端到端测试与质量门禁：
    - 后端单测：覆盖 SSRF 地址校验矩阵（包含 IPv4、IPv6、私网段、回环、IPv4-mapped、重定向跳板）、超时、超限中断、魔数核验、Token 签名与篡改、撤销后实时阻断；
    - 全栈 E2E：在真实挂载 `_SPA_CSP` 的环境下，验证未放行时外链图片不发请求并展示提示条；放行后外链图片经本站代理加载且在真实浏览器中解码成功（`naturalWidth > 0`），控制台零 CSP 报错；验证整个页面全程零第三方跨域网络请求。

### 非范围

- 服务端图片永久磁盘持久化缓存（避免磁盘无限增长，本 task 仅做运行时内存/流式转发，缓存机制留作未来独立 task）。
- 支持 SVG 格式图片的代理转换（为防范 XSS 纵深防御，SVG 保持不代理）。
- 支持自定义协议（如 `data:` 或内部 `cid:` 走普通内联处理，不走此远程代理）。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：主应用外壳 SPA 的 HTTP 响应头严格保持 `img-src 'self' data: blob:`，正文沙箱 iframe 严格保持 `img-src 'self' data: cid:`，全站全程无任何浏览器请求直连第三方外部域名，守住零外部出网安全基线。
- [ ] AC-002：默认拦截远程图片时，正文中不发起任何远程图片网络请求（包括代理请求），并正常展示拦截提示条；点击「仅此邮件允许加载」或「总是允许来自此发件人的图片」后，正文外链图片通过本站安全代理端点流式加载，并在真实浏览器中解码成功（`naturalWidth > 0`），控制台零 CSP 拦截错误。
- [ ] AC-003：代理端点对请求目标执行严格 SSRF 防护：拒绝私有 IP、本地回环（127.0.0.1 等）、链路本地、多播及特殊格式 IP 请求；拒绝跳转至私有地址的重定向请求；拒绝非 80/443 端口请求。
- [ ] AC-004：代理端点流式读取超过 10 MiB 或耗时超过 15s 的外部图片时，主动中止连接并释放资源，不导致服务端内存无界膨胀或连接挂死。
- [ ] AC-005：代理端点对外部响应执行真实文件头魔数核验，仅放行受控安全位图（PNG/JPEG/GIF/WebP）；声明与真实不符、SVG 或可执行格式拒绝返回图片。
- [ ] AC-006：代理端点在处理请求时实时校验邮件放行状态；在设置页移除发件人白名单后，已签发的代理 URL 再次请求立即返回 403 拒绝，相关邮件重新打开即刻恢复拦截提示条。
- [ ] AC-007：行内样式中 `background-image: url(...)` 引用的远程背景图，在放行后同样被安全重写为本站代理 URL 并成功渲染显示。
- [ ] AC-008：代理 URL Token 签名不可伪造或篡改，Token 中包含目标 URL；伪造、篡改或过期 Token 拒绝请求；访问日志与错误报告中 `token` 与目标 `url` 均自动脱敏。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试。AC-001 通过 CSP 响应头断言验证；AC-002 通过包含真实 `_SPA_CSP` 的 Playwright E2E 测试图片请求来源（仅限本站）与 `naturalWidth > 0` 验证；AC-003 至 AC-006 通过后端集成测试与异常输入矩阵验证；AC-007、AC-008 通过前端 HTML 重写单测、Token 验签与日志脱敏单测验证。

## 上下文区

- 来源：`d003`（2026-10-31 确证：`srcdoc` 继承宿主 CSP 且不可放宽，Electron 全 session 覆盖，必须采用服务端代理彻底消解死锁）；`t066`（完成放行状态数据库持久化与白名单模型）。
- 架构决策：采纳 Claude Code (`opus 5.5`, effort=`high`) 深度审阅结论，废弃独立正文端点方案（t067 drop），采用与 Gmail / ProtonMail / Fastmail 一致的服务端图片安全代理（Image Proxy）架构，守住全站 `'self' data:` 零外部出网安全基线。

### 有意不测

- 外部第三方图片服务遭遇 DNS 劫持或 GFW 彻底阻断的极端场景（测试使用本地受控的独立 HTTP 图片服务模拟外部网络）。

### 测试策略

- 后端 SSRF 单元测试：各种私网 IP 变形、IPv6-mapped、回环地址、重定向跳转、非标端口拦截断言。
- 后端代理功能测试：有效 Token 转发、魔数核验、撤销后实时 403 阻断、超时与大图截断测试。
- 前端正文重写测试：外链图片 URL 匹配替换、未放行时移除 src、行内背景图替换测试。
- Playwright 全栈 E2E（真实环境）：全链路跑在真实 `_SPA_CSP` 响应头下，断言放行后外部图片经代理成功解码（`naturalWidth > 0`），控制台无任何 CSP 违规报错。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：若部署环境通过特定的上游代理（如 Clash TUN fake-ip 模式）访问外部网络，DNS 返回的 fake-ip（如 `198.18.0.0/15`）可能被严格 SSRF 规则误判为保留地址；增加配置项 `MAIL_CORE_PROXY_ALLOW_CIDRS` 允许环境自定义白名单。
- 回退：配置关闭图片代理开关或撤销发件人白名单即可。

### 依赖与约束

- 严格遵守沙箱安全基线，不开放全局 `http(s):`，严禁 `allow-same-origin`。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：记录服务端安全图片代理架构、SSRF 纵深防护与零外部出网设计。
- `docs/blueprint/conventions.md`：记录外链图片代理流转、MIME 魔数核验与代理 Token 规范。
