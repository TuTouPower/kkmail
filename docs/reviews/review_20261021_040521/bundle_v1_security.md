> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

# Intensive Review — 视角 1 安全

## Summary

- Target: 当前全库；HEAD `daca631aec54c30ce02cdb5e6499ae196dc3a72d`。
- 范围：清单 168 文件 / 23508 行中安全边界，重点审阅 `mail_core/api`、`security`、`accounts/credentials.py`、providers、blobs、backup、runtime、Electron、compose、前端邮件 HTML 与关联测试。另扫描全部 1300 个可达 Git commit patch，检查凭据与私人邮箱；历史报告不作为 finding 来源。
- Findings: Critical / High / Medium / Low / Info = **1 / 2 / 4 / 1 / 1**。
- Verdict: **BLOCK**。
- 验证：仅静态读取、Git history/blame、无副作用 Python AST / stdlib 探针；未运行 DB、服务、联网攻击或完整测试。系统 Python 缺 FastAPI/httpx，未声称 HTTP 端到端复现。

## Critical / High

- [Critical][99] mail_core/api/app.py:161 L155-L164 — 未认证 SPA fallback 可逃逸前端根目录读取进程可读文件。证据：`candidate = _DIST / full_path; if candidate.is_file(): return FileResponse(candidate)`，catch-all 路由未挂 `require_auth`，也未使用 StaticFiles 的根目录约束。请求 `/%2e%2e/%2e%2e/<repo_file>` 或编码斜杠可使解码后的 `full_path` 包含 `..`；使用足够层级可读取已知绝对路径目标。已提取原函数做 AST 探针，设 `_DIST` 为现有 `frontend` 并传入 `unquote('%2e%2e/requirements-mail-core.txt')`，返回仓库根文件，确认路径逃逸。生产启用 frontend/dist 时，攻击者无需 Session/API Key 即可读取源码、配置、挂载于进程可读路径的密钥、`/proc/self/environ` 等；取得 session/blob key 后可伪造会话、解密数据。规范：`docs/security.md` 实例级认证与密钥保护、CWE-22。修复：删除通用任意文件 fallback，仅由 `StaticFiles` 提供明确静态目录，SPA 未知路径固定返回 index；若保留文件分支，先 `candidate.resolve()` 并校验 `candidate.is_relative_to(_DIST.resolve())`，拒绝越界、绝对路径与目录链接逃逸。测试须覆盖未认证、百分号编码、重复斜杠、符号链接。溯源：[HEAD 代码](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/api/app.py#L155-L164)，blame 起源 `a4a5239a`。

- [High][100] mail_core/providers/imap.py:126 L123-L129 — IMAP TLS 未验证服务器证书与主机名。证据：`imaplib.IMAP4_SSL(self.host, self.port, timeout=timeout)` 没有 `ssl_context`，随后立即 `client.login(self.username, self.password)`。只读 stdlib 探针确认 `IMAP4_SSL.__init__` 在缺省上下文时调用 `ssl._create_stdlib_context()`，结果 `verify_mode=0`、`check_hostname=False`。网络中间人可提供自签或错误主机名证书并接收 LOGIN 密码及邮件内容；默认 `use_ssl=True` 并未建立可信服务器身份。规范：CWE-295；`docs/security.md` 网络与凭据保护。修复：`ssl_context=ssl.create_default_context()`，确保 CERT_REQUIRED 与 hostname verification；私人 CA 通过明确可信 CA 配置导入，不增加禁用校验开关。增加自签/主机名错误证书被拒绝、受信证书成功测试。溯源：[HEAD 代码](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/providers/imap.py#L123-L129)，blame 起源 `6afa9cf0`。

- [High][95] outlook_mail_reader.py:20 L20-L26 @ 34c8131069298bf14989f853decba8e3ee8c4dd2 — 公开 Git 历史仍含疑似真实邮箱、密码和 OAuth refresh token。历史文件包含 EMAIL、PASSWORD、CLIENT_ID、REFRESH_TOKEN 字面量；只输出形状验证结果：邮箱长度 31、密码长度 14、client_id 长度 36、refresh token 长度 424 且具有 Microsoft OAuth token 形状，各值均非常见占位。当前代码删除并未消除 Git 可达历史曝光，`git show <sha>:outlook_mail_reader.py` 仍能读到。隐私泄露存在置信度 100；凭据真实性/目前是否仍有效未经远程使用验证，综合置信度 95。规范：intensive-review §3 公开仓历史隐私扫描、CWE-798/CWE-200。修复：先撤销对应 refresh token、修改账户密码并检查登录记录；再按仓库维护流程清理敏感 Git 历史及 release/cache/fork 可控副本。不得仅删当前文件。报告未复述真实邮箱或凭据；[历史证据定位](https://github.com/TuTouPower/kkmail/blob/34c8131069298bf14989f853decba8e3ee8c4dd2/outlook_mail_reader.py#L20-L26)。

## Medium / Low / Info

- [Medium][99] mail_core/security/auth.py:159 L152-L169、L199-L217；mail_core/api/auth_routes.py:75 L75-L78 — 改密与退出不能撤销已签发会话。Cookie 仅签入 `v` 与 `csrf`，`read_session` 仅验证签名/30 天期限；改密只更新 bcrypt hash，退出只删除当前浏览器 Cookie。此前复制 Cookie 的客户端在改密或退出后仍能 GET `/api/auth/me` 取得 CSRF，继续完整访问实例，直至自然过期/轮换签名密钥。规范：CWE-613、会话撤销安全不变量；当前单用户能力模型不影响此结论。修复：将持久化 session epoch / password-change generation 签入会话并每次验证，改密原子增加 epoch；退出需撤销当前 session ID，或明确实施全实例登出。新增“保存旧 Cookie、退出/改密、另一客户端重放被拒绝”测试。证据：[会话读取与改密](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/security/auth.py#L152-L217)。

- [Medium][100] mail_core/security/redact.py:46 L43-L48；mail_core/sync/delta.py:314、reconcile.py:66、remote_push.py:122 — Provider 响应体仍可进入日志与持久化错误。真实 urllib transport 在 `oauth.py:174`、`:298` 用 HTTP body 作为异常 message；`safe_error` 保留 `str(exc)` 首行 120 字节，所以 body 中不带已知 key 名称的个人信息或凭据仍被保留。上述三个 `log.exception` 更直接打印整个异常/链，完全绕过 `safe_error`，即便 body 含 `refresh_token` 等明确字段也原样进入日志。`tests/mail_core/test_redact_and_poll.py` 仅测试 message='bad request'、body 单独传入情况，与真实 transport 不符。规范：`docs/security.md` 日志承诺“不保存 provider 响应体”、AGENTS 脱敏要求、CWE-532。修复：ProviderHttpError 对外只保留类型/status/允许枚举 error code，message 不保存 raw body；所有 provider failure 日志使用结构化安全字段，禁止未脱敏 exception chain。增加实际 transport-shaped message 含敏感 body 测试。证据：[safe_error](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/security/redact.py#L43-L48)、[裸 traceback](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/sync/remote_push.py#L118-L124)。

- [Medium][90] mail_core/backup/package.py:244 L241-L258 — 默认备份在缺 backup key 时静默降级为明文。`do_encrypt` 在 encrypt=None 时取决于环境有没有 key；运维按文档调用 `run_backup()`、遗失备份密钥配置时仍产生 postgres.dump 并可返回 ok。DB dump 含邮件正文/索引/个人数据，blob 加密不足以保护数据库内容；操作者可能按“密封备份包”文档将整个目录复制到离线/异地。当前 compose/bootstrap 配置正常时不会触发。规范：`docs/security.md` 备份“密封备份包”及独立密钥要求，CWE-311。修复：生产 `run_backup` 默认强制加密，先加载必需 key 再写文件；明文只允许明确离线测试参数并返回清晰不同类型/状态。证据：[隐式明文分支](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/backup/package.py#L241-L258)。

- [Medium][95] mail_core/backup/package.py:249 L248-L267、L289-L291 — 密封失败会把明文 dump 留在目标备份目录。先 `_build_plain_dir(out/'plain')` 写 DB dump，完成后才 load_backup_key/加密，删除 plain 仅在整个正常路径末尾；无 finally，且成功路径 `rmtree(ignore_errors=True)` 可静默留下明文。触发包括错误长度/版本备份 key、加密/写盘失败、清理权限问题或进程中止；同步/复制目标目录可将明文一并上传。规范：备份密封和敏感临时文件清理，CWE-459/CWE-312。修复：写入权限 0700 的独立工作目录，在任何异常路径 finally 清理，密封写完并校验后原子发布最终目录；清理失败明确报错，不得报告 encrypted success。证据：[先写明文后加载密钥](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/backup/package.py#L248-L267)、[忽略清理错误](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/backup/package.py#L289-L291)。

- [Low][95] mail_core/backup/crypto.py:49 L49-L56 — 独立 backup key 的强制契约仅靠文档，未校验与任一 blob key 不同。相同 32 字节密钥会被直接接受，削弱离线备份与在线 blob 密钥泄露相互隔离；仅在操作者误配时触发。规范：`docs/security.md` / backup/crypto.py 模块明确 MUST NOT be blob keyring。修复：备份前比较 backup key 与全部 blob key 字节，重复则拒绝创建包；增加重复 key 测试。证据：[加载 key 无隔离校验](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/backup/crypto.py#L49-L56)。

- [Info][65] mail_core/providers/oauth.py:191 L188-L193、L170、L283 — API 绝对分页链接与 urllib redirect 无同源限制，存在防御纵深缺口。BearerTransport 对任意 `http...` path 附加 token；Graph next/deltaLink 原样来自 provider response/持久化 cursor，urllib 自动 follow redirect 时也可能转发 Authorization。当前未找到邮件发送者可直接操纵 provider 链接或调用该 transport 的公开 API，因此不认定已可利用 SSRF/token 外泄。若 provider 返回跨域链接、可信端点重定向或 checkpoint 被污染，token 会发送到任意 origin，且可能降为 HTTP。修复建议：绝对链接仅允许对应 provider HTTPS origin，redirect 每一跳重新校验并拒绝跨域认证头转发。证据：[附加 Bearer 与任意绝对 URL](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/providers/oauth.py#L188-L193)。

## Spec Compliance / 保留设计

- 单用户已认证 UUID 能力模型已按 `docs/security.md` 执行，未将跨账户 UUID 访问报为 IDOR。
- 前端邮件正文使用 DOMPurify + 无 script/same-origin 权限 sandbox iframe，默认屏蔽远程图片；未发现需要新增入口或恢复扩展的理由。
- API 写操作 Session CSRF 与 Bearer 分界明确；附件 UUID/path 约束、Content-Disposition 控制符处理、AES-GCM/AAD、blob digest 校验、loopback bind 值得保留。
- 未报告已移除 Flask 接口、永久 out-of-scope 浏览器扩展或历史弱默认配置为当前运行时漏洞。

## Appendix — Traceability / 限制

- Skill：`/Users/developer/kar/code/my_file/coding_agent/skills_mine/intensive-review/SKILL.md` §3 视角1、§4、§6。
- 全库审查按主任务约定保留当前仍存在问题，不因其早于 HEAD 起源过滤。关键行已检查 git blame，历史泄露直接定位完整 commit。
- Git patch 扫描覆盖 private-key block、GitHub/Google API token、JWT、refresh/password/client-secret 常量、常见私人邮箱域；未把测试示例、公开联系信息直接认定私人信息泄露。除报告所列历史账户材料外，无其他高置信真实密钥泄露结论。此为启发式扫描，不能证明所有秘密均已排除。
- 无真实凭据/邮箱写入本报告，未验证历史凭据有效性，未调用真实第三方账户。
