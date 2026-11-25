# Task review t089（reviewer_focus: 代码）

- task：`t089_unified_outbound_dialer_imap_proxy_and_bulkhead`
- spec：`docs/tasks/t089_unified_outbound_dialer_imap_proxy_and_bulkhead/task.md`
- diff_anchor：`4fd1656be379191a3ba9531f8cbd2e94a8803816`
- target：`git diff 4fd1656be379191a3ba9531f8cbd2e94a8803816`
- round：1
- reviewed_at：2026-11-25T13:57:22+08:00

## Findings

### t089_code_f001 - `https://` 代理隧道下启用 TLS（IMAP 993 / Graph HTTPS）时二次 `wrap_socket` 剥离外层 TLS 导致握手必败

- 严重度：critical
- 锚点：AC-001（及 spec 范围要求支持 HTTP/HTTPS `CONNECT` 代理隧道；`https://` 代理无法完成 TLS 目标握手）
- 位置：`src/mail_core/net/dialer.py:311-346`（以及 `src/mail_core/net/dialer.py:157-186` `wrap_tls_socket`）
- 问题：当出站代理采用 `https://proxy:port`（`proxy.scheme == "https"`）且目标连接启用 TLS（`tls=True`，包括 `ImapProvider` 端口 993 与 `urlopen_outbound` 请求 `https://` Graph/OAuth 端点）时，`dial_stream` 先在第 312 行调用 `wrap_tls_socket(sock, server_hostname=proxy.host, ...)` 生成外层 `ssl.SSLSocket`，并在第 320 行通过外层加密隧道完成 `HTTP CONNECT`；随后第 340 行又把该外层 `ssl.SSLSocket` 直接传给 `wrap_tls_socket(sock, server_hostname=target_host, ...)`。CPython `ssl.SSLSocket._create()` 会读取 `sock.fileno()`、调用 `sock.detach()` 并直接把内层 OpenSSL 会话绑定到底层原始 TCP 文件描述符，从而丢弃外层代理 TLS 会话并将内层明文 TLS `ClientHello` 直接写入外层已加密的代理连接流。经本地真实回环 HTTPS `CONNECT` 代理与 TLS 服务端实测复现，`dial_stream(..., tls=True, proxy=parse_proxy_url("https://127.0.0.1:..."))` 直接报错 `ssl.SSLError: [SSL: UNEXPECTED_MESSAGE] unexpected message`。
- 建议：当 `proxy.scheme == "https"` 且 `tls=True` 时，不要对 `ssl.SSLSocket` 直接调用 `SSLContext.wrap_socket()`；改为基于 `ssl.MemoryBIO` + `SSLContext.wrap_bio()`（或 `socket.socketpair()` 双向泵桥接外层 `SSLSocket` 后再包裹真实内层 `SSLSocket`，以保持 `imaplib`/`http.client` 所需的 `.makefile('rb')`、`.settimeout()` 与 `.shutdown()` 语义）实现真正的 TLS-in-TLS 隧道，并补充真实回环 `https://` 代理 + TLS 目标集成测试。

### t089_code_f002 - 重构 `host_security.py` 时误删多个微软邮箱域名与 IMAP 主机，破坏「拒绝 Microsoft IMAP」既有契约

- 严重度：important
- 锚点：行为缺陷（违反关联规范 `docs/specs/account_connection.md:19` 与 `docs/blueprint/conventions.md:227`「创建、编辑、导入与 provider 构建均拒绝可识别的 Microsoft IMAP」）
- 位置：`src/mail_core/providers/host_security.py:19-39`
- 问题：本次 diff 重写 `host_security.py` 时将 `MICROSOFT_DOMAINS` 与 `MICROSOFT_IMAP_HOSTS` 从 `frozenset` 改为可变 `set`，并在重排中误删了原有已受控域名 `"live.fr"`、`"live.de"`、`"outlook.de"`（这些域名在前端 `src/frontend/src/lib/account_providers.ts:22` 仍识别为 `microsoft`），以及原有已受控 IMAP 主机 `"imap.outlook.com"`、`"imap.hotmail.com"`、`"outlook.office.com"`。导致通过 `POST /api/accounts`、`PATCH /api/accounts/{id}` 或 `build_provider()` 提交 `user@outlook.de`、`user@live.de`、`user@live.fr` 或主机 `imap.outlook.com`、`imap.hotmail.com`、`outlook.office.com` 创建/更新/构建 IMAP 账户时，`reject_microsoft_imap()` 不再拦截。
- 建议：在 `src/mail_core/providers/host_security.py` 恢复 `"live.fr"`、`"live.de"`、`"outlook.de"` 至 `MICROSOFT_DOMAINS`，恢复 `"imap.outlook.com"`、`"imap.hotmail.com"`、`"outlook.office.com"` 至 `MICROSOFT_IMAP_HOSTS`（保留新增项），并将两者恢复为不可变 `frozenset`。

### t089_code_f003 - `update_account` 在清理空 `proxy_mode` 前先执行 `validate_connection`，导致清空 `proxy_mode=""` 必定失败

- 严重度：important
- 锚点：行为缺陷（账户编辑传入 `config={"proxy_mode": ""}` 试图恢复默认自动代理模式时返回 HTTP 400，且使空串清理代码不可达）
- 位置：`src/mail_core/accounts/service.py:140-141, 152, 179-186`；`src/mail_core/accounts/connection.py:34-38`
- 问题：`update_account` 在第 179-183 行显式实现了解除账号代理覆写的空值清理分支（`for key in ("outbound_proxy", "proxy_mode"): if key in config_patch and (config_patch[key] is None or not str(config_patch[key]).strip()): merged.pop(key, None)`）。但在第 141 行（以及同时提交凭据时的第 152 行）函数先使用未弹出空串的 `effective_config` 调用 `validate_connection()` -> `validate_outbound_proxy_config()` -> `validate_proxy_mode("")`，直接抛出 `ValueError("config.proxy_mode: unsupported proxy_mode ''; expected 'auto' or 'direct'")` 并在 API 层转为 400。结果只有 `outbound_proxy=""` 和 `imap_user=""` 能成功清空，`proxy_mode=""` 的清除分支在到达第 179 行前即必定失败。
- 建议：在调用 `validate_connection` 构造 `effective_config` 时（或抽取统一的 `normalize_account_config` helper），先按与第 170-183 行一致的语义清理空白 `imap_user`、`username`、`outbound_proxy`、`proxy_mode` 键再做校验。

### t089_code_f004 - `EndpointCircuitOpenError` 缺少 `retry_after_seconds` 且在 delta/reconcile 被字符串化，导致冷却窗口内空耗任务重试额度并提前永久失败

- 严重度：important
- 锚点：行为缺陷（端点熔断开启后，Worker 重试既不等待冷却时间又在冷却期内多次记失败并提前耗尽 `max_attempts`）
- 位置：`src/mail_core/net/bulkhead.py:17-29`；`src/mail_core/sync/delta.py:538-554`；`src/mail_core/sync/reconcile.py:217-234`；`src/mail_core/worker/handlers.py:223-230`；`src/mail_core/sync/jobs.py:480-484`
- 问题：`EndpointCircuitOpenError` 仅定义了 `retry_after_s`，而 `fail_job()`（`src/mail_core/sync/jobs.py:480`）仅识别 `retry_after_seconds` 来约束最小重试退避；同时 `sync_folder_delta`（`delta.py:538-554`）与 `reconcile_folder`（`reconcile.py:217-234`）捕获所有 `Exception`（含 `EndpointCircuitOpenError`）并转为 `{"status": "provider_error", "error": safe_provider_summary(exc)}` 字符串字典，导致 `handlers.py:224` 传入字符串 `error` 调用 `reschedule_job(..., count_failure=True)`。当某端点因超时进入冷却窗口后，任务的指数退避 `1s, 2s, 4s, 8s, 16s`（累计 31s）会在默认 30s 冷却期内连续 5 次撞上 `EndpointCircuitOpenError`，白白消耗 5/8 的 `failure_attempts` 并多次触发 `record_connectivity_failure`；若将 `MAIL_CORE_CIRCUIT_COOLDOWN_S` 调大至 ≥120s，则 7 次重试（累计 127s）会在首轮冷却期结束前耗尽 `DEFAULT_MAX_ATTEMPTS=8`，使任务在未经第二次真实探测前即被永久标为 `FAILED`。
- 建议：在 `EndpointCircuitOpenError` 上补充 `retry_after_seconds` 属性（返回 `self.retry_after_s`），并在 `delta.py` / `reconcile.py` 的 `provider_error` 结果及 `handlers.py:223` 中透传 `retry_after`（或像 `CAPACITY_ERRORS` 一样对冷却期熔断采用不计入永久失败的延迟重排），确保任务下次至少在冷却到期后唤醒。

### t089_code_f005 - `oauth.py` 漏捕获 `NetworkSecurityError` 且对 `EndpointCircuitOpenError` 执行无效重试与歧义误判

- 严重度：minor
- 锚点：行为缺陷（经 `urlopen_outbound` 触发 SSRF 或熔断异常时，OAuth/Graph 传输层的异常语义与重试行为失配）
- 位置：`src/mail_core/net/http_client.py:187-192`；`src/mail_core/providers/oauth.py:341-363, 552-604`
- 问题：(1) `NetworkSecurityError` 继承自 `ValueError` 而非 `OSError`，`http_client.py:189` 的 `except OSError` 不会将其包装为 `URLError`，`default_urllib_token_post`（`oauth.py:341-362`）与 `urllib_json_request`（`oauth.py:552-564`）也未捕获 `NetworkSecurityError`，导致 SSRF 拦截直接以裸 `ValueError` 跳过 `OAuthTokenClient.get_access_token` 的 `except ProviderHttpError` 映射向外逸出。(2) 当 `EndpointCircuitOpenError` 经 `http_client.py:192` 包装进 `URLError` 后，`urllib_json_request`（`oauth.py:590-604`）会将其当作普通 `transport_exc` 对 `GET`/`HEAD` 睡眠 1+2+3=6 秒重试 3 次（违背快速失败目的），对 `POST`/`PATCH` 误判为 `AmbiguousOutcomeError`（实际在建连前已熔断，请求从未发出）。
- 建议：在 `oauth.py` 的 `default_urllib_token_post` 与 `urllib_json_request` 中显式识别 `NetworkSecurityError`（直接不可重试地转为 `ProviderHttpError`）以及 `URLError.reason` 中的 `EndpointCircuitOpenError`（跳过重试与 `AmbiguousOutcomeError` 误判，直接快速失败并保留 `retry_after` 信息）。

### t089_code_f006 - `urlopen_outbound` 无代理直连分支忽略 `connect_timeout` 与系统代理，且 `dial_stream(..., io_timeout=None)` 未重置超时

- 严重度：minor
- 锚点：行为缺陷（`urlopen_outbound` 与 `dial_stream` 的超时/直连契约在特定路径存在静默偏差）
- 位置：`src/mail_core/net/http_client.py:113-131, 170-200`；`src/mail_core/net/dialer.py:221-222, 348-349`
- 问题：(1) 当未设置代理环境变量或目标命中 `NO_PROXY` 时，`_should_use_custom_dial_opener` 返回 `False`，`urlopen_outbound` 回退调用裸 `urllib.request.urlopen(req, timeout=timeout)`，导致方法签名声明的 `connect_timeout`（默认 10s）、`per_attempt_timeout` 与双栈错误保留均被静默忽略；且即使账号/调用方显式指定 `proxy_mode="direct"`，在 macOS 桌面 sidecar 进程中 stdlib `urlopen` 仍会读取 macOS 系统代理（`_scproxy`）。(2) `dial_direct_ips`（`dialer.py:221`）与 `dial_stream`（`dialer.py:348`）仅在 `io_timeout is not None` 时调用 `sock.settimeout(...)`，当调用方传入 `io_timeout=None`（如 `DialedIMAP4_SSL(..., timeout=None)`）期望阻塞套接字时，经过 `wrap_tls_socket` 的套接字仍残留建连阶段剩余超时而非重置为 `None`。
- 建议：对 `io_timeout=None` 在握手后显式执行 `sock.settimeout(None)`；对于 `urlopen_outbound` 显式传入 `proxy_mode="direct"` 且无环境变量代理时至少使用 `ProxyHandler({})` 阻止系统代理介入，并在后续评估为公开目标全面收口 `connect_timeout`。

### t089_code_f007 - 多处新建与修改函数圈复杂度 `CC >= 15`

- 严重度：minor
- 锚点：代码质量（圈复杂度量化标准：`CC >= 15` 且本 task 新建或新增分支/嵌套）
- 位置：`src/mail_core/net/dialer.py:226`；`src/mail_core/net/policy.py:65`；`src/mail_core/net/proxy.py:64, 144`；`src/mail_core/net/tunnel.py:65, 172`；`src/mail_core/providers/oauth.py:279, 434`；`src/mail_core/config/models.py:85`；`src/mail_core/providers/factory.py:139`；`src/mail_core/accounts/service.py:113`；`src/mail_core/config/loader.py:48`；`src/mail_core/providers/imap.py:897`
- 问题：经 AST 静态计量（基数 1 + 条件/循环/异常/三元/布尔分支），本 task 新建及新增分支的以下函数圈复杂度达 `>= 15`：
    - 新建函数：`dial_stream`（`src/mail_core/net/dialer.py:226`，CC=29）、`is_restricted_ip`（`src/mail_core/net/policy.py:65`，CC=21）、`matches_no_proxy`（`src/mail_core/net/proxy.py:144`，CC=20）、`handshake_socks5`（`src/mail_core/net/tunnel.py:172`，CC=19）、`handshake_http_connect`（`src/mail_core/net/tunnel.py:65`，CC=17）、`parse_proxy_url`（`src/mail_core/net/proxy.py:64`，CC=17）。
    - 本 task 新增分支的既有函数：`urllib_json_request`（`src/mail_core/providers/oauth.py:434`，CC=45）、`MailCoreConfig.validate`（`src/mail_core/config/models.py:85`，CC=43）、`build_provider`（`src/mail_core/providers/factory.py:139`，CC=42）、`update_account`（`src/mail_core/accounts/service.py:113`，CC=39）、`default_urllib_token_post`（`src/mail_core/providers/oauth.py:279`，CC=20）、`load_config`（`src/mail_core/config/loader.py:48`，CC=17）、`ImapProvider._connect`（`src/mail_core/providers/imap.py:897`，CC=15）。
- 建议：将 `dial_stream` 拆分为直连/代理子步骤与熔断结果记录 helper；将 `handshake_socks5` 的方法协商与认证子协商拆出；将 `MailCoreConfig.validate` 的出站网络校验与 `update_account` 的配置归一化拆为独立小函数，降低单函数分支深度。

## 结论

- 本轮新发现：7 条（1 条 critical、3 条 important、3 条 minor）
- 未进表的提示：
    - **文件过大（仅列路径与行数，不进 finding 表）**：`src/mail_core/providers/imap.py` 1936 行（≥ 800 阈值，本 task 净增 70 行，建议将长连接/客户端工厂与认证错误映射拆出）；`src/mail_core/providers/oauth.py` 604 行（≥ 400 阈值，本 task 净增 39 行）；`src/mail_core/accounts/service.py` 464 行（≥ 400 阈值，本 task 净增 8 行）。注：`src/mail_core/security/remote_image_proxy.py` 为 519 行但本 task 净减 51 行，不计膨胀；测试文件 `tests/mail_core/test_net_outbound.py` 为 1025 行（≥ 600）、`tests/mail_core/test_provider_connection_budget_integration.py` 为 604 行（净增 9 行），由测试审阅维度跟进。
    - **圈复杂度 10–14 提示**：`src/mail_core/net/dialer.py:103` `connect_ips_with_fallback`（CC=13）、`src/mail_core/net/http_client.py:134` `urlopen_outbound`（CC=10）、`src/mail_core/net/proxy.py:203` `resolve_outbound_proxy`（CC=10）。
    - **零引用导出 / 死代码提示**：`src/mail_core/net/dialer.py:189` `dial_direct_ips`（及 `src/mail_core/net/__init__.py:17,70` 导出）在全仓 `src/` 与 `tests/` 中零调用；`src/mail_core/net/proxy.py:42` `ProxyConfig.urllib_proxy_url()` 在全仓零调用且会重新拼接含明文口令的代理 URL，建议移除以减少秘密暴露面。
    - **集中配置单一来源漂移**：`MailCoreConfig`（`src/mail_core/config/models.py:26-31`）虽新增了 `outbound_proxy`、`no_proxy`、`outbound_connect_timeout_s`、`outbound_per_attempt_timeout_s`，但 `src/mail_core/config/__init__.py:13` 仅同步了熔断参数给 `default_bulkhead()`，`resolve_outbound_proxy` 与 `dialer.py` 在 `env=None` 时仍直接读取 `os.environ` 而忽略 `set_config()`/`reset_config(env)` 注入的配置对象。
    - **7 视角正交体检确认**：已逐一排查安全（凭据脱敏、Pin-IP SSRF、头/控制字符注入、`remote_image_proxy` 禁代理、DTO 零回显）、正确性（`https://` TLS-in-TLS、`proxy_mode=""` 清理顺序、`host_security` 微软黑名单回退、双栈异常优先级）、契约/Breaking（API/Config/异常兼容）、性能与资源（连接超时与槽位释放、`EndpointBulkhead` 上界裁剪）、架构与可维护性（文件膨胀、CC、零引用导出）、健壮性与可观测（Worker 重试与冷却时间对齐、`oauth.py` 异常捕获）、文档与规格一致性（spec/blueprint 同步与 Non-Scope 边界）。
- 总体判断：存在 1 条 critical 与 3 条 important 阻断性问题（`https://` 代理 TLS-in-TLS 必败、`host_security.py` 误删微软域名/主机、`update_account` 无法空串清除 `proxy_mode`、以及熔断异常在 Worker 中空耗重试额度），本轮判定 FAIL。
- 系统性 follow-up：`t091`（backlog，强类型结构化故障模型与白名单诊断投影重构）将接手故障结构化分类与诊断建模；上述 4 条阻断性缺陷均属 `t089` 本身交付范围，需在本 task 修复后重审。

### AC 复验方式

- AC-001：TICK-VOID，re_verified。HTTP CONNECT 与 SOCKS5/SOCKS5h 代理在 `ImapProvider` 与 `open_idle_session` 下可完成代理隧道 TLS+SNI 握手，但明确支持的 `https://` 代理方案在启用 TLS 目标时因 `dialer.py` 对外层 `SSLSocket` 二次 `wrap_socket` 剥离外层 TLS 会话，实测抛出 `ssl.SSLError: [SSL: UNEXPECTED_MESSAGE]` 无法建连（`t089_code_f001`）。
- AC-002：TICK-VALID，re_verified。已查证 `src/mail_core/net/dialer.py`、`src/mail_core/net/policy.py`、`src/mail_core/providers/host_security.py` 与 `src/mail_core/security/remote_image_proxy.py` 并复跑回归测试：直连单次 DNS 解析并校验全部 IP 后 Pin-IP 建连且保留 SNI、`remote_image_proxy` 维持禁代理直连与 SSRF 校验、受信任回环/私网代理端点不被误拦，且已移除建连后 `getpeername()` 补丁。
- AC-003：TICK-VALID，re_verified。已查证 `connect_ips_with_fallback` 与 `wrap_tls_socket` 并复跑双栈预算测试：IPv4 优先尝试、共享 `connect_timeout`/`per_attempt_timeout` 总预算、握手完成后才应用 `io_timeout`，且 `_error_priority` 保留远端 `TimeoutError` 不被本地 `ENETUNREACH` 覆盖。
- AC-004：TICK-VALID，re_verified。已查证 `EndpointBulkhead` 与 `ImapProvider._connect_with_permit` 并复跑并发连接预算测试：冷却窗口内先于 `acquire_permit` 调用 `raise_if_open` 快速失败，并发探测竞争失败时在 `except` 路径立即释放 `ConnectionPermit`，不致健康账号遭遇 `ProviderCapacityUnavailable`。
- AC-005：TICK-VALID，re_verified。已在本工作区独立复跑 `docs/blueprint/testing.md` 全部 `test_cmd`（`pytest .repo_template/tests -q -m contract` 389 passed / 1 skipped；前端 `npm test` 56 文件 597 passed + `openapi:check` + `css:check` + `tsc -b` + `vite build` 通过；桌面端 `npm test` 通过；`scripts/check_doc_sensitive.py docs --check` 35 文件 0 违规）及 `scripts/run-mail-core-tests.sh run -k "test_net_outbound or test_imap_protocol or test_remote_image_proxy or test_provider_connection_budget" --no-cov -q`（真实 PG + Dovecot IMAP 65 passed）与 `scripts/run-mail-core-tests.sh unit -q`（exit 0）。
- AC-006：TICK-VALID，re_verified。已核对 `git diff` 中 `docs/specs/account_connection.md`、`docs/specs/mail_sync_and_storage.md`（均已登记 `t089` 并补充契约条款）、`docs/blueprint/architecture.md`、`docs/blueprint/conventions.md`（新增第十三节）及 `docs/blueprint/testing.md`。

coverage = 6 / 6

reviewed_scope: 038c6b531e238f5e
verdict: FAIL

## Round 2 (2026-11-25T14:52:41+08:00)

- diff_anchor：`4fd1656be379191a3ba9531f8cbd2e94a8803816`
- target：`git diff 4fd1656be379191a3ba9531f8cbd2e94a8803816`
- round：2
- reviewed_at：2026-11-25T14:52:41+08:00

## Findings

### t089_code_f008 - 账户创建与 OAuth 重授权路径未复用 `normalize_account_config`

- 严重度：minor
- 锚点：契约一致性（`create_account` 与带 `oauth_flow_id` 的 `update_account_app` 对空白 `proxy_mode` / `outbound_proxy` 的处理与普通 `update_account` 不一致）
- 位置：`src/mail_core/accounts/service.py:41-61`；`src/mail_core/api/accounts.py:267`；`src/mail_core/accounts/oauth_flow.py:610-619, 671-681`；`src/mail_core/mail/application/accounts.py:294-302`
- 问题：`update_account`（`src/mail_core/accounts/service.py:143`）现已在校验前调用 `normalize_account_config()` 剔除空白的 `imap_user`、`username`、`outbound_proxy`、`proxy_mode`。但 `create_account`（`service.py:41, 59`）、`api_create_account`（`api/accounts.py:267`）及 `consume_oauth_flow_for_create` / `consume_oauth_flow_for_reauthorize`（`oauth_flow.py:610-619, 671-681`）仍直接把原始 `config` / `merged_config` 传给 `validate_connection()` 并落库，且 `update_account_app` 在带 `oauth_flow_id` 时会把 `config` 置为 `None`（`mail/application/accounts.py:302`）从而跳过 `update_account` 的归一化。结果在创建账户或通过 OAuth 重新授权的同时传入 `{"proxy_mode": ""}` 会触发 HTTP 400（`unsupported proxy_mode ''`），而传入 `{"outbound_proxy": ""}` 会把空字符串存入库或在重授权时保留旧代理字段。
- 建议：在 `create_account`、`api_create_account` 以及 `oauth_flow.py` 的创建/重授权合并配置前统一调用 `normalize_account_config()`。

### t089_code_f009 - `src/mail_core/net/proxy.py` 注解引用 `Any` 但未从 `typing` 导入

- 严重度：minor
- 锚点：类型契约（运行时 `typing.get_type_hints()` 解析失败且静态类型检查报未定义符号）
- 位置：`src/mail_core/net/proxy.py:8, 50`
- 问题：文件顶部仅导入了 `from typing import Literal, Mapping`，第 50 行函数签名 `def _resolve_proxy_port(parts: Any, scheme: str) -> int:` 引用了未导入的 `Any`。因开启了 `from __future__ import annotations` 模块可正常导入，但实测执行 `typing.get_type_hints(proxy._resolve_proxy_port)` 抛出 `NameError: name 'Any' is not defined`。
- 建议：将参数注解改为 `urllib.parse.SplitResult` 或在第 8 行补充导入 `Any`。

## 结论

- 前轮 finding 复核：
    - `t089_code_f001`（critical）：**已消除**。`src/mail_core/net/dialer.py:255-256` 在 `https://` 代理隧道下启用目标 TLS 时调用 `src/mail_core/net/tunnel.py:284-318` 的 `bridge_tls_socket()`（基于 `socket.socketpair()` + 单泵线程及 `outer_ssl_sock.pending()` 排空），保留外层代理 TLS 会话与内层目标 TLS SNI、`settimeout`、`makefile` 与退出清理（实测 `ImapProvider.list_folders()` / `open_idle_session()` / `urllib_json_request()` 及独立回环复测闭合后泵线程归零）。
    - `t089_code_f002`（important）：**已消除**。`src/mail_core/providers/host_security.py:19-45` 已恢复 `MICROSOFT_DOMAINS`（含 `"outlook.de"`、`"live.fr"`、`"live.de"`）与 `MICROSOFT_IMAP_HOSTS`（含 `"imap.outlook.com"`、`"imap.hotmail.com"`、`"outlook.office.com"`）及不可变 `frozenset`。
    - `t089_code_f003`（important）：**已消除**。`src/mail_core/accounts/connection.py:23-34` 抽取出 `normalize_account_config()`，且 `src/mail_core/accounts/service.py:143, 181` 在调用 `validate_connection()` 前先归一化合并配置并在校验后落库，`proxy_mode=""` 与 `outbound_proxy=""` 均可正常清除（`test_update_account_clears_blank_proxy_mode_and_outbound_proxy_pg` 通过真实 PG 验证）。
    - `t089_code_f004`（important）：**已消除**。`src/mail_core/net/bulkhead.py:31-34` 为 `EndpointCircuitOpenError` 新增 `retry_after_seconds` 属性（返回 `retry_after_s`），`src/mail_core/providers/connection_slots.py:133-140` 将 `EndpointCircuitOpenError` 纳入 `CAPACITY_ERRORS`；核实 `sync/delta.py`、`sync/reconcile.py`、`sync/engine.py`、`sync/remote_push.py`、`worker/handlers.py` 与 `providers/imap.py` 均先于通用 `Exception` 命中 `CAPACITY_ERRORS` / `is_capacity_error`，实现不计 `failure_attempts`、不污染账号健康且按冷却时间 `retry_after` 延迟重排。
    - `t089_code_f005`（minor）：**已消除**。`src/mail_core/net/http_client.py:189-190` 直接透传 `EndpointCircuitOpenError`；`src/mail_core/providers/oauth.py:359-376, 531-533, 591-592` 显式将 `NetworkSecurityError` 映射为 `ProviderHttpError`，并在 `default_urllib_token_post` 与 `urllib_json_request`（含 `_unwrap_circuit_open`）直接快速失败重抛 `EndpointCircuitOpenError`，不再睡眠重试或误判为 `AmbiguousOutcomeError`。
    - `t089_code_f006`（minor）：**已消除**。`src/mail_core/net/dialer.py:356-357` 对 `io_timeout=None` 显式调用 `sock.settimeout(None)` 且已移除零引用的 `dial_direct_ips`；`src/mail_core/net/http_client.py:196-199` 对显式 `proxy_mode="direct"` 使用 `ProxyHandler({})` 阻断系统 `_scproxy` 代理介入。
    - `t089_code_f007`（minor）：**已消除**。经 AST 重新计量，`src/mail_core/net/` 下全部函数均已低于 15（最高为 `parse_proxy_url` CC=14、`connect_ips_with_fallback` / `_socks5_negotiate_auth` CC=13、`is_restricted_ip` / `urlopen_outbound` CC=12、`dial_stream` CC=11）；修改的既有函数中 `urllib_json_request`（44→10）、`build_provider`（38→11）、`load_config`（15→11）、`ImapProvider._connect`（16→6）均降至 15 以下，`update_account`（35→30）净降 5 个分支，而 `default_urllib_token_post`（19→19）、`MailCoreConfig.validate`（34→34）、`validate_connection`（62→62）、`OAuthTokenClient.get_access_token`（21→21）及 `fetch_safe_remote_image`（40→40）均通过抽取 helper 保持净增分支为 0。
- 本轮新发现：2 条（0 条 critical、0 条 important、2 条 minor：`t089_code_f008`、`t089_code_f009`）
- 未进表的提示：
    - **文件过大（仅列路径与行数，不进 finding 表）**：`src/mail_core/providers/imap.py` 1921 行（≥ 800 阈值，本 task 净增 55 行）；`src/mail_core/providers/oauth.py` 616 行（≥ 400 阈值，本 task 净增 51 行）；`src/mail_core/accounts/service.py` 458 行（≥ 400 阈值，本 task 净增 2 行）；`src/mail_core/net/dialer.py` 429 行（新建，≥ 400 阈值）；`src/mail_core/providers/connection_slots.py` 429 行（≥ 400 阈值，本 task 净增 3 行）。注：`src/mail_core/security/remote_image_proxy.py` 519 行但净减 51 行，不计膨胀；测试文件 `tests/mail_core/test_medium_providers_sync_blobs.py` 647 行净增 0 行，`tests/mail_core/test_provider_connection_budget_integration.py` 604 行（≥ 600，净增 9 行，由测试审阅维度关注）。
    - **圈复杂度 10–14 与既有高复杂度未增分支提示**：新/降阶函数 CC 10–14 为 `parse_proxy_url`（14）、`_validate_sidebar_layout`（14）、`connect_ips_with_fallback`（13）、`_socks5_negotiate_auth`（13）、`merge_credentials`（13）、`is_restricted_ip`（12）、`urlopen_outbound`（12）、`_retry_delay_for_http_outcome`（12）、`_extract_imap_password`（12）、`dial_stream`（11）、`load_config`（11）、`_build_imap_provider` / `build_provider`（11）、`resolve_outbound_proxy` / `_unwrap_ip_and_check_cidrs` / `BearerTransport.__call__` / `_build_json_request` / `_parse_json_response` / `urllib_json_request` / `create_account` / `_validated_imap_port`（各 10）；既有 ≥15 但本 task 净增分支 ≤ 0 的函数包括 `validate_connection`（62）、`fetch_safe_remote_image`（40）、`MailCoreConfig.validate`（34）、`update_account`（30）、`OAuthTokenClient.get_access_token`（21）、`default_urllib_token_post`（19）及 `imap.py` 既有协议解析方法。
    - **架构与边缘提示**：(1) 前轮指出的零引用导出 `dial_direct_ips` 与 `ProxyConfig.urllib_proxy_url()` 已清除；(2) `src/mail_core/config/__init__.py` 仅将熔断配置同步至 `default_bulkhead()`，`resolve_outbound_proxy` 与 `dialer.py` 在 `env=None` 时仍直接读取 `os.environ` 而非 `get_config()`；(3) `src/mail_core/net/http_client.py:124-127` 在 `proxy is None` 且无系统/环境代理匹配时仍走 stdlib `urlopen`（未对裸直连公开 HTTPS 目标施加 `connect_timeout`）；(4) `src/mail_core/blobs/archive.py:1047, 1079` 返回 `capacity_unavailable` 时未携带 `retry_after`（回落默认 5s `capacity_retry_seconds`，不计失败次数）。
    - **7 视角正交体检**：已复核安全、正确性、契约·Breaking、性能·资源、架构·可维护性、健壮性·可观测与文档·规格一致性全部 7 个视角；前轮全部阻断问题已解决，本轮未发现新的 critical / important 问题。
- 总体判断：Round 1 全部 7 条 finding（含 1 条 critical、3 条 important）均已真实修复并经代码与测试双重验证，Round 2 仅余 2 条非阻断 minor（`t089_code_f008`、`t089_code_f009`），判定 PASS。
- 系统性 follow-up：`t090`（`WorkerJob` 强类型执行血缘与后台隔离）与 `t091`（强类型结构化故障模型 `StructuredFailure` 与白名单诊断投影重构）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。已核对 `src/mail_core/net/dialer.py`、`src/mail_core/net/tunnel.py`（含 `https://` TLS-in-TLS `bridge_tls_socket`）、`src/mail_core/net/proxy.py`、`src/mail_core/net/imap_client.py`、`src/mail_core/providers/imap.py` 与 `oauth.py`，并复跑 `test_net_outbound.py` + `test_net_resilience.py`（unit 模式 13 passed, 1 skipped，PG 用例在 `scripts/run-mail-core-tests.sh run` 中已通过，涵盖 HTTP CONNECT、`https://` TLS-in-TLS、SOCKS5/SOCKS5h、IDLE 与 `proxy_mode="direct"`）及独立回环泵线程清理校验。
- AC-002：TICK-VALID，re_verified。已核对 `src/mail_core/net/policy.py`、`src/mail_core/net/dialer.py`、`src/mail_core/providers/host_security.py`（已恢复 `frozenset` 与全部 Microsoft 域名/主机）及 `src/mail_core/security/remote_image_proxy.py`；直连单次解析校验全部 IP 后 Pin-IP 建连并保留 SNI，代理放行受信任内网/回环代理同时拦截私网目标字面地址，远程图片代理强制直连禁代理且移除了事后 `getpeername()` 补丁。
- AC-003：TICK-VALID，re_verified。已核对 `connect_ips_with_fallback`、`wrap_tls_socket` 与 `_open_configured_socket`：IPv4 优先尝试、共享 `connect_timeout`/`per_attempt_timeout` 预算、握手结束后应用 `io_timeout`（含 `io_timeout=None` 重置阻塞模式）及 `_error_priority` 保留远端 `TimeoutError` 不被 IPv6 `ENETUNREACH` 覆盖。
- AC-004：TICK-VALID，re_verified。已核对 `EndpointBulkhead`、`ImapProvider._connect_with_permit`、`connection_slots.py`（`CAPACITY_ERRORS` 含 `EndpointCircuitOpenError`）及 `sync/` / `worker/handlers.py`：冷却期内在 `acquire_permit` 前快速失败并在竞争探针失败时即时释放槽位，且触发 `capacity_unavailable` 按 `retry_after_seconds` 延后重排而不空耗 `failure_attempts`，真实 PG+IMAP 并发测试通过。
- AC-005：TICK-VALID，re_verified。已在本工作区独立复跑 `docs/blueprint/testing.md` `test_cmd` 全部 4 项（`.repo_template/tests -q -m contract` 389 passed / 1 skipped；前端 `npm test` 56 文件 597 passed + `openapi:check` + `css:check` + `tsc -b` + `vite build` 通过；桌面端 `npm test` 12 suites 通过、1 条 OAuth env 用例按设计 skip；`scripts/check_doc_sensitive.py docs --check` 35 文件 0 违规）及 `./scripts/run-mail-core-tests.sh run -k "test_net_outbound or test_net_resilience or test_imap_protocol or test_remote_image_proxy or test_provider_connection_budget or test_imap_connect or test_imap_id or test_adoptions_patch or test_archive_scheduler or test_medium_providers_sync_blobs" --no-cov -q`（真实 PG + Dovecot IMAP `stage=tests status=passed`，116.724s）。
- AC-006：TICK-VALID，re_verified。已核对 `git diff 4fd1656be379191a3ba9531f8cbd2e94a8803816` 中的 `docs/specs/account_connection.md`、`docs/specs/mail_sync_and_storage.md`（均已登记 `t089` 与对应契约）、`docs/blueprint/architecture.md`、`docs/blueprint/conventions.md` 与 `docs/blueprint/testing.md`。

coverage = 6 / 6

reviewed_scope: fac7d89714976f59
verdict: PASS
