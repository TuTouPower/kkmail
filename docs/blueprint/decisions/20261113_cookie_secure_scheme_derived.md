# 016 会话 Cookie Secure 改为按连接协议推导，取代 A98 (t079)（2026-11-13）

- **背景**：审阅项 A98（review_20261027_021416 的 adoption_decision.md）认定「会话 Cookie Secure 默认关闭」是问题：当时 compose 中 `MAIL_CORE_COOKIE_SECURE` 默认 0，而同一部署又允许 `MAIL_CORE_HOST_BIND` 把 API 暴露到局域网明文 HTTP，默认关意味着会话 Cookie 可能明文传输。A98 的修复说明要求默认改 1 并注释本机 HTTP 调试时显式置 0；712faf77（2026-10-27）据此把 compose 默认值改为 1。
- **决策**：本决策正式取代 A98。`MAIL_CORE_COOKIE_SECURE` 配置项彻底删除（compose 不注入、后端不读取、桌面端不透传、文档不记载）；`cookie_secure()` 只按请求实际 scheme 判定 Secure（HTTPS 为真，其余为假），保留 A21/A37 的代理信任边界（只信经验证写入 ASGI scope 的 scheme，不信未验证的转发头）。同一变更补齐登录回验闭环：前端 login 成功后必须回验 /api/auth/me，回验失败以具名错误 `session_not_established` 显式报错，不再静默回登录表单。
- **原因**：Secure 是对「这条连接是否加密」这一事实的陈述，不是一个可以独立于部署形态存在的配置声明。A98 默认改 1 后，配置声称的传输事实与真实入口（局域网 .local 域名 + HTTP）脱钩：浏览器按规则丢弃 HTTP 下发的 Secure Cookie，登录 200 后会话校验 401，且前端静默吞掉，使该入口静默不可用 17 天而无人察觉（p078）。翻回默认 0 同样不成立——那只是把同一个可脱钩开关反着设置，下一轮审阅仍会再翻。改为由连接协议推导后，任何入口形态（回环 HTTP、局域网 HTTP、TLS 反代后的 HTTPS）都自动得到与事实一致的 Secure 属性，不需要也不允许人工配置干预。用户 2026-11-13 已明确：局域网 HTTP 明文为已接受的部署形态（手机常开 VPN 与 Tailscale 冲突，不采用 HTTPS 方案）；本决策与之同向——HTTP 入口的会话明文风险由部署形态本身承担并在 guides 中明示，不由一个 Cookie 开关假装消除。
- **安全边界**：HTTPS 入口下 Secure 自动启用，A98 担心的「HTTPS 部署却忘开 Secure」不再可能发生；未验证的 `X-Forwarded-Proto` 等转发头不能单独抬升 Secure 判定（A21 边界保留并有单测）；SameSite=None 仍以「按 scheme 推导的 Secure 为真」为前提，联动不回归。
- **回退**：t079 实现 commit 整体 revert 即恢复 A98 行为（配置项与默认值 1 一并回来）；无数据迁移，回退无残留。
