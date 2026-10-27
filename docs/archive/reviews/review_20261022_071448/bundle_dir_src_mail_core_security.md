# Bundle Review — dir:src/mail_core/security

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 5 allowlisted tracked files

## Findings

- [High][99] src/mail_core/security/auth.py:255-L361 — 改密后会话 epoch 更新失败仍返回成功，跨进程旧会话继续有效 — 证据：密码先提交，随后写 sidecar/清初始密码，再调用失效逻辑；该逻辑吞掉数据库更新异常并只写 warning，路由仍返回成功。 — 依据：docs/specs/auth_and_session.md:26-27 要求改密与立即撤销一致。 — 修复：密码 hash 与 epoch 在同一 DB transaction 提交；epoch 失败则改密失败，避免夹在提交后的 sidecar 副作用。
- [Medium][100] src/mail_core/security/auth.py:217-L300 — 5 秒 epoch 缓存与立即撤销契约冲突 — 证据：多 API 进程分别缓存 session_epoch，logout/change-password 后其他进程在缓存期内仍接受旧 cookie。 — 依据：docs/specs/auth_and_session.md:27 规定跨进程即时吊销。 — 修复：认证时读取权威 epoch，或使用可靠的跨进程失效通知。
- [Medium][90] src/mail_core/security/auth.py:118-L194 — 数据库凭据查询失败会被当成首启无记录并回退旧环境密码 — 证据：数据库异常返回 None，调用方随后使用环境变量/hash 文件 bootstrap 密码；数据库恢复后进程仍缓存旧 hash。 — 依据：docs/blueprint/decisions.md Plan A 规定初始化后数据库为权威。 — 修复：区分空记录与查询失败；配置数据库但查询失败时 fail closed，不回退 bootstrap 值。

## Files examined

- src/mail_core/security/__init__.py
- src/mail_core/security/auth.py
- src/mail_core/security/defaults.py
- src/mail_core/security/ratelimit.py
- src/mail_core/security/redact.py
