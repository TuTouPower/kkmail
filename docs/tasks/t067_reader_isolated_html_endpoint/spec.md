# Task spec

## 背景

在 `t066` 落地了远程图片服务端持久化与 CID Signed URL 机制后，用户在放行发件人（如 `noreply-accounts@google.com`）后打开包含真实外链图片（Google CDN `https://www.gstatic.com/...`）的邮件，图片依然呈碎图状态。经真实 Chromium 隔离复现，捕获到浏览器底层的致命报错：
`Loading the image 'https://www.gstatic.com/...' violates the following Content Security Policy directive: "img-src 'self' data: blob:". The action has been blocked.`

**根因分析**：
当前邮件正文使用 `<iframe srcdoc="...">` 嵌入页面。W3C CSP 规范与现代浏览器（Chromium / WebKit）规定，`srcdoc` iframe 会自动继承父页面的 CSP，且子文档内部通过 `<meta CSP>` 只能比父页面更严格，绝对无法突破或放宽父页面的限制。主应用宿主 SPA 的安全基线 `_SPA_CSP` 定义了 `img-src 'self' data: blob:`（守住主应用零外部出网、防数据外泄基线）；这导致无论在邮件内部怎么放行 `https:`，父页面的规则在浏览器底层直接一票否决，外链图片被强制阻断。

**测试盲区暴露**：
现有前端组件测试运行在不执行 CSP 的 jsdom 环境中，仅检查了 srcdoc 字符串是否拼接成功（测试假绿）；快速 E2E 冒烟测试使用的是未挂载后端安全中间件的轻量服务，没有跑在带着真实 `_SPA_CSP` 响应头的环境下。

**解决策略**：
彻底切断父子 CSP 继承死锁。主应用 SPA 外壳严格保持 `img-src 'self' data: blob:` 安全基线不变；邮件正文从内联 `srcdoc` 改造为独立的隔离渲染路由端点（拥有独立的 HTTP 浏览上下文与专属响应头）。由后端在该端点上独立、动态下发正文专属 CSP（未放行返回严格拦截，已放行放开 `https: http:`），主客隔离、各司其职，彻底根除 CSP 继承冲突。并在真实浏览器测试中补齐外链图片加载与解码（`naturalWidth > 0`）验证。

## 契约区

### 范围

- 主应用 SPA 安全基线保全：`src/mail_core/api/app.py` 中的 `_SPA_CSP` 保持最严格的 `img-src 'self' data: blob:` 规则，严禁向主应用放开 `https:` / `http:` 外部图片源。
- 邮件正文独立隔离渲染路由端点：
    - 服务端提供独立的邮件正文 HTML 渲染端点（如 `GET /api/mail/messages/{id}/rendered-body`），返回完整的 HTML 文档；
    - 该端点响应独立的专属 HTTP Headers：
        - `Content-Type: text/html; charset=utf-8`；
        - `Content-Security-Policy`:
            - 未放行远程图片时：`default-src 'none'; img-src 'self' data: cid:; style-src 'unsafe-inline'; font-src https: data:; base-uri 'none';`
            - 已放行远程图片时：`default-src 'none'; img-src https: http: data: 'self' cid:; style-src 'unsafe-inline'; font-src https: data:; base-uri 'none';`
        - `X-Content-Type-Options: nosniff`；
        - `Referrer-Policy: no-referrer`；
    - 端点鉴权与沙箱兼容：支持凭登录会话或短时渲染签名访问，严禁削弱 iframe `sandbox` 安全基线（不引入 `allow-scripts` 或 `allow-same-origin`）。
- 前端阅读器沙箱加载重构：
    - `MessageReader` 中的邮件正文 iframe 改为指向独立浏览上下文的 URL，彻底解耦并阻断对父页面 CSP 的继承限制；
    - 支持向该独立端点传递渲染样式参数（如当前主题、是否应用智能深色反转），或由阅读器注入样式；
    - 放行远程图片时，刷新该独立端点 URL（如带上时间戳或版本参数），使全新 CSP 策略的独立文档立即重新加载。
- 补齐真实全栈外链图片端到端测试：
    - 建立在真实挂载 `_SPA_CSP` 中间件与真实 FastAPI 容器环境下的 Playwright E2E 测试；
    - 验证未放行时外部请求为 0 且被拦截；放行后真实发起外部图片请求且图片成功解码（`naturalWidth > 0`），控制台无 CSP 拦截报错。

### 非范围

- 为所有外部图片搭建服务端转储或反向代理（如 Google Image Proxy 类似服务）。
- 撤销或放宽 iframe sandbox（严禁 `allow-same-origin` 和 `allow-scripts`）。
- 修改数据库已有的放行表模型或签发算法（继续复用 t066 的已存数据与逻辑）。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：主应用外壳 SPA 的 HTTP 响应头严格保持 `img-src 'self' data: blob:`，严禁在主页面下发 `https:` 或 `http:` 远程图片源，守住应用外壳零外部出网安全基线。
- [ ] AC-002：邮件正文在具有独立 HTTP 响应上下文的隔离沙箱 iframe 中渲染，完全切断对主页面 SPA CSP 的继承限制。
- [ ] AC-003：未放行远程图片时，正文独立端点下发的 CSP 严格拦截外部 `http(s):` 图片，并不发起外部网络请求；含内联图片的邮件正常加载内联图。
- [ ] AC-004：单封邮件放行或发件人白名单生效后，正文独立文档以放开后的正文 CSP 重新加载，外部远程图片（如 Google gstatic.com 等）在浏览器中真实发起网络请求且解码成功（`naturalWidth > 0`），控制台零 CSP 阻断报错。
- [ ] AC-005：切换深色模式或单信原色覆盖时，独立渲染正文能够正确呈现对应的智能深色反转或原色纸张视图。
- [ ] AC-006：在挂载真实 `_SPA_CSP` 的全栈 Playwright 自动化测试中，验证外链图片在放行前拦截、放行后成功解码（`naturalWidth > 0`），且父页面与未放行子页面零外部泄漏。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试。AC-001 通过服务端响应头测试断言验证；AC-002 至 AC-005 通过独立渲染端点 API 测试与前端集成测试验证；AC-006 通过挂载真实后端中间件的 Playwright 真实浏览器请求拦截与图片解码断言验证。

## 上下文区

- 来源：`t066` 真实环境部署后复现的真实外链图片碎图问题（2026-10-31 核实：Chromium 控制台报 `violates directive: img-src 'self' data: blob:`；根因在于 `srcdoc` 强制继承主应用 `_SPA_CSP`）。
- 技术发现：W3C CSP 规范第 6.7 节规定 `srcdoc` 继承宿主 CSP 且不可放宽，必须使用独立 URL 端点解耦浏览上下文。

### 有意不测

- 第三方 CDN 服务器宕机或因本地 GFW 阻断导致的网络超时（使用本地受控图片服务器与稳定外链作为测试目标）。

### 测试策略

- 后端 API 测试：独立渲染端点响应头、CSP 指令格式、未放行与已放行动态切换测试。
- 前端组件测试：阅读器与独立正文 iframe 的通信、URL 刷新、深色模式传参测试。
- Playwright E2E（真实环境）：全链路带着真实 `_SPA_CSP` 测试外链图片放行与 `naturalWidth > 0` 真实解码。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：独立端点若需要鉴权，在无 `allow-same-origin` 的沙箱 iframe 下无法携带 Cookie；以短时渲染签名（类似预览 Token）或安全桥梁解决。
- 回退：切回原有内联 srcdoc 渲染逻辑即可。

### 依赖与约束

- 严格遵守沙箱安全基线（禁止 `allow-same-origin`）。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：记录邮件正文独立隔离渲染端点与主站 CSP 解耦架构。
- `docs/blueprint/conventions.md`：记录正文专属 CSP 动态下发与主应用零出网基线约定。
