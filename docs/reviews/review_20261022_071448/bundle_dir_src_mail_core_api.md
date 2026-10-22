# Bundle Review — dir:src/mail_core/api

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 8 allowlisted tracked files

## Findings

- [High][96] src/mail_core/api/app.py:68-L74 — 默认信任任意代理头，可伪造来源 IP 绕过登录限流 — 证据：代理头中间件默认启用，未配置可信 IP 时 trusted_hosts='\*'；登录失败计数用 request.client.host，直连客户端可轮换 X-Forwarded-For。 — 依据：src/mail_core/api/auth_routes.py:63-68；docs/guides/security.md:71 要求显式配置可信代理。 — 修复：默认不信任转发头；只有明确配置可信代理 IP/CIDR 才启用，并从已验证的 ASGI scheme 判断 Secure cookie。
- [High][99] src/mail_core/api/accounts.py:114-L152 — AccountDTO 使用 slots 却通过 __dict__ 序列化，账户 API 返回 500/400 — 证据：AccountDTO 声明 @dataclass(frozen=True, slots=True)，没有 __dict__；list 账户访问时异常成为 500，create/update 的宽泛 catch 会转成 400。 — 依据：src/mail_core/mail/application/accounts.py:25-38。 — 修复：显式构造 AccountOut 字段，或使用 dataclasses.asdict/dataclasses.fields 兼容 slots。

## Files examined

- src/mail_core/api/__init__.py
- src/mail_core/api/accounts.py
- src/mail_core/api/app.py
- src/mail_core/api/auth_routes.py
- src/mail_core/api/deps.py
- src/mail_core/api/http_headers.py
- src/mail_core/api/mail.py
- src/mail_core/api/sse.py
