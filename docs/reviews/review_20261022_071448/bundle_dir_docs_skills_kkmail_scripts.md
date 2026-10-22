# Bundle Review — dir:docs/skills/kkmail/scripts

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 1 allowlisted tracked files

## Findings

- [Medium][93] docs/skills/kkmail/scripts/kkmail_cli.py:22-L46 — CLI 将长期有效 session cookie/CSRF token 明文写入缓存且未限制权限 — 证据：默认缓存位于 home 下 .cache；保存用 write_text，未设置 0600 文件或 0700 父目录。标准 umask 下同机可遍历该目录的用户可能读取可重放 cookie，默认有效期 30 天。 — 依据：src/mail_core/security/auth.py:76-77；跨用户读取还依赖 home 目录权限。 — 修复：私有 cache dir 与文件权限设为 0700/0600，并使用原子写；限制缓存有效期或提供禁用缓存选项。
- [Medium][90] docs/skills/kkmail/scripts/kkmail_cli.py:19-L204 — CLI 允许把登录密码或 API key 发往任意明文 HTTP URL — 证据：--url 可覆盖默认 loopback 地址；没有限制非 loopback URL 必须 HTTPS，login body 与后续 API key 会经 urllib 明文发送。 — 依据：CLI 请求构造见 kkmail_cli.py:65-69,100-120,203-204。 — 修复：非 loopback 地址强制 HTTPS；仅允许 HTTP loopback。

## Files examined

- docs/skills/kkmail/scripts/kkmail_cli.py
