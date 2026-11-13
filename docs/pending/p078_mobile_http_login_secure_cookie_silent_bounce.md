---
pid: "p078"
slug: "mobile_http_login_secure_cookie_silent_bounce"
status: "todo"
---
# p078 手机浏览器经 .local 域名 http 登录后静默回登录框：会话 Cookie 带 Secure 被丢弃

- 现象：2026-11-13 22:12 用户实报：iPhone 浏览器打开 http://karsondemacbook-pro.local:37281/ ，页面能正常打开，输入正确登录密码后显示「登录中」，约 2 秒后无任何报错、无任何反应，又回到密码输入框，进不去邮箱界面。同一密码在 Mac 本机经 localhost 访问可正常登录（主 agent 已实测本机 API 登录返回 200）。
- 影响：所有经非 localhost 的 http 明文地址（局域网 .local 域名、局域网 IP 等）访问 mail-core Web 端的浏览器登录全部不可用；桌面 http://localhost 因浏览器把 localhost 视为可信源、破例接受 http 下的 Secure Cookie 而不受影响，问题被长期掩盖。
- 根因：（2026-11-13 22:1x 在 Mac 本机实测确认）
    1. docker-compose.mail-core.yml:134 将 MAIL_CORE_COOKIE_SECURE 的默认值设为 1（强制开启），且当前部署的 .env 未设置该变量，故容器内实际生效值为 1。src/mail_core/security/auth.py 的 cookie_secure() 在 env 已设值时直接采用 env、不再看请求 scheme。登录响应 Set-Cookie 实测属性为：kkmail_mc_session；HttpOnly；Max-Age=2592000；Path=/；SameSite=lax；Secure（值已打码不记录）。
    2. http://karsondemacbook-pro.local 不是安全上下文，浏览器（含 iOS Safari）不会保存/回送 http 响应下发的 Secure Cookie。复现证据：用遵循浏览器 Cookie 规则的客户端（Python cookiejar）经 .local 域名登录，POST /api/auth/login 返回 200，但紧接着 GET /api/auth/me 返回 401（Cookie 未被回送）；改为手动回送同一 Cookie 后 GET /api/auth/me 返回 200，证明服务端会话本身有效、仅在浏览器侧被传输规则丢弃。容器 kkmail-mail-core-api 同一时段（2026-11-13 14:08-14:14 UTC）访问日志亦呈多次「POST /api/auth/login 200 紧跟 GET /api/auth/me 401」的形态。
    3. 前端放大了静默性：src/frontend/src/api/client.ts 的 checkSession() 对 /api/auth/me 的 401 直接 return false、不抛错、不提示，登录 POST 成功后会话校验失败，界面无任何报错直接回登录框，与用户所见完全一致。
    4. 已排除的怀疑：密码错误（本机与 .local 域名登录 POST 均 200）；API 基地址写死 localhost（src/frontend/src/lib/apiBase.ts 默认同源空字符串）；服务端 Host/Origin 校验拦截（.local 域名的登录请求实际到达服务端并返回 200 与 Set-Cookie）。
    5. 同类位点：logout 的 delete_cookie 与全部依赖该会话 Cookie 的接口共用同一机制，非独立位点；处理本条时仍须全仓扫 MAIL_CORE_COOKIE_SECURE 与 set_cookie 引用复核无遗漏。
- 测试缺口：现有测试都在 localhost/测试客户端下运行，不模拟浏览器对「http 非可信源 + Secure Cookie」的丢弃行为，故漏过。应补：其一，cookie_secure 与 compose 默认值在 http 非 localhost 场景下的契约测试；其二，登录 200 但会话校验 401 时前端给出明确报错（而非静默回登录框）的用例。
- 线索：docker-compose.mail-core.yml:132-134（默认 1 的注释与变量行）、src/mail_core/security/auth.py:175-189（cookie_secure）、src/mail_core/api/auth_routes.py:72-84（set_cookie/delete_cookie）、src/frontend/src/api/client.ts（login/checkSession）、src/frontend/src/lib/apiBase.ts（同源基地址）。复现于 Mac 本机 curl 与 Python cookiejar，无 .scratch/ 文件留存。
    建议修复方向（未实施）：部署层在局域网 http 场景显式设 MAIL_CORE_COOKIE_SECURE=0（compose 注释即为此设）仅为治标，会话将明文过局域网，仅适合可信局域网；根治是为局域网访问提供 HTTPS 并保留 Secure；同时前端在「登录成功但会话校验 401」时给出明确报错。
- 处理：未开
