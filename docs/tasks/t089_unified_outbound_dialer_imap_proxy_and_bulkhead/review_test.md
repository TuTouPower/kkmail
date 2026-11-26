# Task review t089（reviewer_focus: 测试）

- task：`t089_unified_outbound_dialer_imap_proxy_and_bulkhead`
- spec：`docs/tasks/t089_unified_outbound_dialer_imap_proxy_and_bulkhead/task.md`
- diff_anchor：`4fd1656be379191a3ba9531f8cbd2e94a8803816`
- target：`git diff 4fd1656be379191a3ba9531f8cbd2e94a8803816`
- round：1
- reviewed_at：2026-11-25T13:54:21+08:00

## Findings

### t089_test_f001 - `remote_image_proxy` 禁代理与直连 Pin-IP 重构路径未真正穿透到建连层

- 严重度：important
- 锚点：AC-002（远程图片代理直连路径：DNS 校验后实际直连安全 IP 且保持禁代理）及「测试策略」（`remote_image_proxy` 复用直连原语且禁代理不回归）
- 位置：`tests/mail_core/test_net_outbound.py:793-801`（`test_remote_image_proxy_enforces_direct_only_even_with_proxy_env`）、`tests/mail_core/test_remote_image_proxy.py:255-305, 342-443`
- 问题：
    1. `test_remote_image_proxy_enforces_direct_only_even_with_proxy_env` 虽然设置了 `HTTPS_PROXY` 和 `MAIL_CORE_OUTBOUND_PROXY`，但将 `mail_core.security.remote_image_proxy.socket.getaddrinfo` 替身返回 `127.0.0.1` 后调用 `fetch_safe_remote_image("https://evil.example.test/pixel.png")` 并断言 `SSRFSecurityError`。该执行路径在 `src/mail_core/security/remote_image_proxy.py:378` 的前置 DNS 校验处即抛出异常退出，根本未到达本次重构后第 382-413 行的 `_connect_with_fallback`（`connect_ips_with_fallback`）、`wrap_tls_socket`、`conn_sock.settimeout` 与 `http.client.HTTPConnection` 请求流程。
    2. 正如 `test_plain_socks5_resolves_locally_validates_ssrf_and_sends_ipv4` 所证明，`socks5://` 代理模式同样会在本地 DNS 校验阶段拦截 `127.0.0.1`；因此仅测试「`getaddrinfo` 返回 `127.0.0.1` 时报 `SSRFSecurityError`」无法区分 `fetch_safe_remote_image` 是否真正在放行 IP 场景下绕过代理直连（如果实现将公网图片拉取错误改走 `HTTPS_PROXY` / `MAIL_CORE_OUTBOUND_PROXY`，或第 382-413 行 `wrap_tls_socket`/超时逻辑出现回归，该测试仍会通过）。
    3. 核查 `tests/mail_core/test_remote_image_proxy.py` 与全量测试覆盖率产物（`.scratch/test_runs/dcfe647ee74c4ce5b5c045d3c1127f6e/coverage.json`）：既有测试调用 `fetch_safe_remote_image` 时全部传入 `mock_opener`（于第 344 行早退）或直接 monkeypatch 函数本身，导致 `src/mail_core/security/remote_image_proxy.py:379-519` 在全套 2252 个用例中执行覆盖率为 0%。
- 建议：在 `tests/mail_core/test_net_outbound.py` 补测 `fetch_safe_remote_image` 的真实直连成功路径：同时开启本地回环 HTTP CONNECT / SOCKS5 代理监听器与目标 HTTP/HTTPS 图片服务端（借助 `MAIL_CORE_PROXY_ALLOW_CIDRS` 或测试端口/socket 边界转发并保持 `HTTPS_PROXY`、`MAIL_CORE_OUTBOUND_PROXY` 环境变量生效），验证：(a) 成功拉取并校验图片字节；(b) 代理未收到任何请求；(c) 建连层实际使用首次解析校验后的 Pin-IP，且 HTTPS 场景经 `wrap_tls_socket` 保留目标主机 SNI 与分段超时。

### t089_test_f002 - `EndpointBulkhead` 测试通过 `client_factory` 与直接调用内部方法绕开了 `ImapProvider` → `DialedIMAP4_SSL` 真实熔断链路

- 严重度：important
- 锚点：AC-004（端点进入冷却后快速失败释放槽位、不饿死健康账号及半开恢复）与「测试可信」（不通过绕过被测生产接线制造假绿）
- 位置：`tests/mail_core/test_net_outbound.py:925-1025`（`test_bulkhead_prevents_blocked_gmail_from_starving_healthy_accounts` 与 `_DialDummy`）
- 问题：
    1. 该用例是全仓唯一覆盖 AC-004 的测试，但在触发失败阶段（第 935-950 行）给 `ImapProvider` 注入了 `client_factory=lambda *a, **kw: _DialDummy(..., bh, ...)`。在 `src/mail_core/providers/imap.py:902-933` 中，传入 `client_factory` 会短路 `DialedIMAP4_SSL` / `DialedIMAP4` 的创建分支；测试里仅靠 `_DialDummy.__init__` 手动以 `tls=False` 调用 `dial_stream(..., bulkhead=bh)`，并未经过生产代码的 `ImapProvider._connect()` → `DialedIMAP4_SSL._create_socket()` → `dial_stream()` 接线。即使 `ImapProvider._connect()` 漏传 `bulkhead=bh` 或 `DialedIMAP4_SSL` 丢弃该参数，该测试仍会通过。
    2. 全套 2252 个测试中，所有经过 `DialedIMAP4_SSL` 的代理/集成用例均显式传入了 `bulkhead=None`（如 `tests/mail_core/test_net_outbound.py:605, 650`）或未产生建连失败；健康账号 `imap.163.com`（第 989-998 行）也使用 `client_factory=_HealthyImap` 绕过 `DialedIMAP4_SSL`。
    3. 冷却期满后的半开恢复阶段（第 1006-1011 行）未通过 `ImapProvider` 或 `dial_stream` 执行真实半开探针，而是直接在测试中调用 `bh.before_dial` / `bh.raise_if_open` / `bh.record_success`；既未端到端验证探针成功后通过真实建连自动清除熔断，也未验证半开探针再次超时重开冷却窗口及并发持槽者触发 `before_dial` 二次拒绝时立即释放 `ConnectionPermit` 的行为（`.scratch/test_runs/dcfe647ee74c4ce5b5c045d3c1127f6e/coverage.json` 显示 `src/mail_core/net/bulkhead.py:115-116, 125, 160` 在真实拨号链中均未命中）。
- 建议：移除 `_DialDummy` 对 `client_factory` 的绕过，直接用真实 `ImapProvider`（不传 `client_factory`）配合 socket 边界控制（如不可达本地黑洞套接字或 `mail_core.net.dialer._default_connector` / `getaddrinfo` 边界替身）触发 `DialedIMAP4_SSL` 连续建连超时，验证熔断开启、并发前景请求在申请槽位前快速失败、真实连接的健康账号不触发 `ProviderCapacityUnavailable`，并通过 `ImapProvider` / `dial_stream` 端到端验证冷却到期后半开探针成功关闸与失败重开冷却。

### t089_test_f003 - `https://` 代理隧道及若干账号/配置边界分支缺少覆盖

- 严重度：minor
- 锚点：AC-001 /「测试策略」（代理协议与账号配置校验覆盖可更完整）
- 位置：`tests/mail_core/test_net_outbound.py:526-685`（对应 `src/mail_core/net/dialer.py:311-318`、`src/mail_core/accounts/service.py:179-186`、`src/mail_core/providers/factory.py:259-260`）
- 问题：当前测试覆盖了 `http://`、`socks5://`、`socks5h://` 代理隧道，但 `https://` 代理方案（先与代理建立外层 TLS 再执行 `CONNECT`，`src/mail_core/net/dialer.py:311-318`）仅有 URL 解析检查而无拨号隧道测试；此外，`build_provider` 为 `graph` 账号传递 `outbound_proxy`/`proxy_mode`、`update_account` 传空串/None 清除账号代理配置、`MAIL_CORE_CONNECT_TIMEOUT_S` 在 `dial_stream` 运行期读取（`dialer.py:28-31`）以及 `ImapProvider` 运行时受 `NO_PROXY`/`proxy_mode="direct"` 覆盖代理环境变量的场景尚未建立回归测试。
- 建议：在 `tests/mail_core/test_net_outbound.py` 补充 `https://` 代理隧道拨号、小写 `https_proxy`、`ImapProvider(proxy_mode="direct")` 与 `build_provider(graph)` / `update_account` 清除代理配置的测试用例。

### t089_test_f004 - 两段式超时缺少真实阻塞套接字与剩余预算耗尽分支测试

- 严重度：minor
- 锚点：AC-003（有界建连预算与两段式超时切换）
- 位置：`tests/mail_core/test_net_outbound.py:888-918`（`test_two_phase_timeout_applies_connect_budget_then_io_timeout`）
- 问题：`test_two_phase_timeout_applies_connect_budget_then_io_timeout` 仅以 `_FakeSock`、`_FakeCtx` 与恒定 `clock=lambda: 100.0` 检查 `settimeout` 调用序列 `[2.5, 4.0, 60.0]`，未在真实 `ImapProvider` / `DialedIMAP4_SSL` 与静默回环套接字（accept 后不发送 ServerHello）下实测 `connect_timeout`（如 `0.2s`）确实截断握手而不阻塞至 `io_timeout=60s`，也未覆盖 `wrap_tls_socket` 与代理握手在 `remaining <= 0` 时主动超时退出的分支（`src/mail_core/net/dialer.py:168-172`、`src/mail_core/net/tunnel.py:43`）。
- 建议：新增本地静默 TCP 监听夹具用例，验证 `ImapProvider(..., connect_timeout=0.2, timeout=60.0)` 在真实套接字握手挂起时于 `connect_timeout` 窗口内快速失败而非卡住 60s。

### t089_test_f005 - `tests/conftest.py` 未隔离新增出站超时/熔断环境变量与全局配置单例

- 严重度：minor
- 锚点：测试隔离健壮性（`tests/conftest.py` 跨用例状态污染风险）
- 位置：`tests/conftest.py:16-36`（`_isolate_outbound_network_state`）
- 问题：`_isolate_outbound_network_state` 清除了 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`NO_PROXY`、`MAIL_CORE_OUTBOUND_PROXY`、`MAIL_CORE_NO_PROXY` 并清空 `default_bulkhead().reset()` 中的条目，但未清除 `MAIL_CORE_CONNECT_TIMEOUT_S`、`MAIL_CORE_CONNECT_ATTEMPT_TIMEOUT_S`、`MAIL_CORE_CIRCUIT_FAILURE_THRESHOLD`、`MAIL_CORE_CIRCUIT_COOLDOWN_S`、`MAIL_CORE_PROXY_ALLOW_CIDRS`，也未在部分用例通过 `get_config()` / `set_config()` 改写全局 `configure_default_bulkhead` 阈值后复位默认 `(2, 30.0)` 与配置缓存。
- 建议：在 `tests/conftest.py` 中补充上述环境变量清理及 `reset_config()` / 默认熔断阈值复位逻辑。

## 结论

- 改测方向复核：无「迁就实现」的改测。逐处核查结果如下：
    - `tests/mail_core/test_a350_toctou_disclosure.py`（整文件删除）：原测试检查的是 `host_security.py` / `factory.py` 中“接受 DNS TOCTOU 窗口并在 `login` 前用 `getpeername()` 补救”的残余风险文档；`t089` 契约消除了该 TOCTOU 窗口，并由 `test_direct_pin_ip_prevents_dns_rebinding_toctou_and_blocks_mixed_ips` 在行为层替代，删除合法。
    - `tests/mail_core/test_adoptions_patch.py:32-36`（删除 `test_ssrf_rejects_dns_answers_mixing_public_and_private_ips`）：原测试依赖 `validate_imap_host` 在构建期做 `getaddrinfo`；`t089` 规范明确取消构建期 DNS 检查以免误伤 `socks5h` 代理并消除 TOCTOU，混合私网 IP 拦截已迁移至 `dial_stream` 并由 `test_direct_pin_ip_prevents_dns_rebinding_toctou_and_blocks_mixed_ips` 覆盖，删除合法且附有说明。
    - `tests/mail_core/test_imap_id_handshake.py:120-124`（删除 `test_imap_connect_rejects_private_peer_before_login`）：原测试断言建连后 `sock.getpeername()` 拦截私网对端；`t089` 规范移除了事后 `getpeername()` 检查以允许连接回环/私网受信任代理，并由拨号前 Pin-IP 测试替代，删除合法；其余 5 个用例仅将 mock 目标从 `imaplib.IMAP4_SSL` 同步更新为 `mail_core.providers.imap.DialedIMAP4_SSL`，未改动任何预期断言。
    - `tests/mail_core/test_provider_connection_budget_integration.py:67, 105, 173-186`（`test_imap_peer_verification_failure_releases_permit` 替换为 `test_imap_pin_ip_ssrf_failure_releases_permit`）：保留相同的“私网地址抛 `ValueError('private or loopback')` 且立即释放 `ConnectionPermit`”契约预期，并将已移除的 `fake_imap.peer_ip` (`getpeername`) 替换成经过真实 `DialedIMAP4_SSL` 与 `mail_core.net.dialer.socket.getaddrinfo` 的 Pin-IP 预建连拦截，方向合法且增强了集成真实性。
    - `tests/mail_core/test_archive_scheduler.py:193`、`tests/mail_core/test_imap_connect_socket_cleanup.py:37`、`tests/mail_core/test_medium_providers_sync_blobs.py:81, 96, 128, 156`：仅同步将 `ImapProvider._connect()` 依赖的边界类从 `imaplib.IMAP4_SSL` 更新为 `mail_core.providers.imap.DialedIMAP4_SSL`（及兼容新增关键字参数 `**_kwargs`），原有断言语义均保持不变。
- 本轮新发现：5 条（important 2 条：`t089_test_f001`、`t089_test_f002`；minor 3 条：`t089_test_f003`、`t089_test_f004`、`t089_test_f005`）
- 未进表的提示：
    1. 危险模式扫描说明：`tests/mail_core/test_net_outbound.py:515, 906` 存在两处 `# type: ignore`（第 515 行 `# type: ignore[union-attr]`、第 906 行 `# type: ignore[arg-type]`）。经逐一核查，第 515 行在运行时若返回 `None` 仍会立即触发 `AttributeError` 失败，第 906 行在 `test_cmd` 无 Python 静态类型门禁的情况下亦未屏蔽任何运行时断言失败，未命中“降低行为覆盖/掩盖失败”的 blocking 阈值，建议在后续修复时一并清理（第 515 行先断言 `is not None`）。
    2. 测试文件复杂度与规模提示：`tests/mail_core/test_net_outbound.py` 达 1025 行（最大圈复杂度为测试夹具 `_handle_conn` 14、`_handle_client` 12），其余受影响测试文件均在 650 行以内；建议补充用例时按代理协议、SSRF/Pin-IP、双栈超时与熔断拆分或精简夹具以维持可读性。
    3. 本轮独立复跑验证结果（均在当前 worktree 下以只读验证方式实际执行通过）：
        - 定向 unit 模式运行 `test_net_outbound.py` 及全部改动/关联测试文件：144 passed, 7 skipped（7 个 skip 均为 unit 模式下按设计跳过的 DB/PG 用例）；
        - `scripts/run-mail-core-tests.sh run --no-cov -k "test_net_outbound or test_imap_protocol_suite or test_imap_provider_live or test_remote_image_proxy or test_provider_connection_budget_integration or test_adoptions_patch or test_imap_id_handshake or test_imap_connect_socket_cleanup or test_medium_providers_sync_blobs or test_archive_scheduler or test_host_security or test_t061_imap_idle_probe or test_oauth_transport"`（真实 PostgreSQL 15433 + 真实 Dovecot IMAP 1143）：151 passed, 0 failed, 0 skipped；
        - `docs/blueprint/testing.md` `test_cmd` 全部 4 项门禁：`pytest .repo_template/tests -q -m contract`（389 passed, 1 skipped）、`(cd src/frontend && npm test && npx tsc -b && npm run build)`（56 文件全部通过且 openapi/css 检查通过）、`(cd src/desktop && npm test)`（通过；Electron OAuth 集成按未设外部凭据跳过）、`python3 scripts/check_doc_sensitive.py docs --check`（35 文件 0 违规）。
- 总体判断：存在 2 条未解决 `important` 测试可信与覆盖缺陷（`t089_test_f001` 与 `t089_test_f002`）导致 AC-002 与 AC-004 复验作废（`TICK-VOID`），本轮判定 FAIL。
- 系统性 follow-up：无（`t090` / `t091` 为结构化血缘与故障模型后续任务，与本次两条测试覆盖缺口无重叠）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/mail_core/test_net_outbound.py:581-656, 804-840` 使用真实回环 HTTP CONNECT / SOCKS5h 代理与 TLS IMAP/HTTPS 服务端（启用主机名校验）实测 `ImapProvider.list_folders()`、`ImapProvider.open_idle_session()` 与 OAuth `urllib` 透传正确目标 SNI 及 `NO_PROXY` 优先级，并已独立重跑通过。
- AC-002：TICK-VOID，re_verified。`tests/mail_core/test_net_outbound.py:727-791` 与 `tests/mail_core/test_provider_connection_budget_integration.py:173-186` 覆盖了直连/普通 SOCKS5 拨号器的 Pin-IP 防 TOCTOU 与回环代理端点放行，但 `test_remote_image_proxy_enforces_direct_only_even_with_proxy_env`（`tests/mail_core/test_net_outbound.py:793-801`）仅在 DNS 阶段拦截 `127.0.0.1`，未实际触达 `fetch_safe_remote_image` 重构后的直连/TLS/禁代理建连路径（`src/mail_core/security/remote_image_proxy.py:379-519` 全套覆盖率 0%），见 `t089_test_f001`。
- AC-003：TICK-VALID，re_verified。`tests/mail_core/test_net_outbound.py:847-918` 实测双栈混合 IPv6 `ENETUNREACH` 与 IPv4 `TimeoutError` 时按 IPv4 优先、受共享建连预算 8.0s 封顶并保留主异常 `TimeoutError`，且验证两段式超时由建连尝试预算切换至 `io_timeout=60.0`，已独立重跑通过。
- AC-004：TICK-VOID，re_verified。`tests/mail_core/test_net_outbound.py:925-1025` 通过 `client_factory=_DialDummy` 与 `_HealthyImap` 绕过了 `ImapProvider` → `DialedIMAP4_SSL` → `dial_stream` 的真实生产接线，且半开恢复仅直接调用 `EndpointBulkhead` 内部方法而非经真实拨号路径触发，无法证明 `ImapProvider` 真实建连失败会正确触发熔断与半开恢复，见 `t089_test_f002`。
- AC-005：TICK-VALID，re_verified。在独立测试会话下重跑 `scripts/run-mail-core-tests.sh run --no-cov -k "..."` 涵盖 `test_net_outbound`、真实 Dovecot `test_imap_protocol_suite`、`test_imap_provider_live`、`test_remote_image_proxy`、`test_provider_connection_budget_integration` 等 151 个用例全部通过（0 failed / 0 skipped），且 `docs/blueprint/testing.md` `test_cmd` 4 项命令全部执行通过。
- AC-006：TICK-VALID，re_verified。核对 `git diff 4fd1656be379191a3ba9531f8cbd2e94a8803816 -- docs/` 已同步更新 `docs/specs/account_connection.md`、`docs/specs/mail_sync_and_storage.md`（均在 front matter `tasks` 登记 `t089`）及 `docs/blueprint/architecture.md`、`docs/blueprint/conventions.md`、`docs/blueprint/testing.md`，且 `check_doc_sensitive.py` 检查 0 违规。

coverage = 6 / 6

reviewed_scope: 038c6b531e238f5e

verdict: FAIL

## Round 2 (2026-11-25T14:50:15+08:00)

- reviewed_anchor：`4fd1656be379191a3ba9531f8cbd2e94a8803816`
- target：`git diff 4fd1656be379191a3ba9531f8cbd2e94a8803816`
- round：2
- reviewed_at：2026-11-25T14:50:15+08:00

### Findings

#### t089_test_f006 - `docs/blueprint/testing.md` 定向门禁命令未同步纳入拆分后的 `test_net_resilience.py`

- 严重度：minor
- 锚点：AC-006 / 门禁文档与拆分后测试套件一致性
- 位置：`docs/blueprint/testing.md:82`
- 问题：Round 2 将原 `test_net_outbound.py` 拆分为共享夹具 `tests/mail_core/outbound_fixtures.py`（450 行）、代理与策略测试 `tests/mail_core/test_net_outbound.py`（384 行）和韧性/熔断测试 `tests/mail_core/test_net_resilience.py`（427 行），其中 `docs/blueprint/testing.md:82` 描述的“CONNECT/SOCKS5 代理 TLS+SNI、双栈超时保留、全局槽位隔离”核心 IMAP 用例均位于 `test_net_resilience.py`，但该行命令仍只写了 `tests/mail_core/test_net_outbound.py`，单独按文档执行会漏跑 `test_net_resilience.py`。
- 建议：将 `docs/blueprint/testing.md:82` 的命令更新为 `KKMAIL_TEST_MODE=unit PYTHONPATH=src .venv/bin/pytest --no-cov tests/mail_core/test_net_outbound.py tests/mail_core/test_net_resilience.py`。

### 结论

- 前轮 finding 复核：
    - `t089_test_f001`（`important`）：**已消除**。`tests/mail_core/test_net_outbound.py:272-322`（`test_remote_image_proxy_direct_http_https_and_ssrf_with_proxy_env`）已改为同时启动本地 `LoopbackHttpsServer`（HTTPS/HTTP 图片服务端）与 `LoopbackHttpConnectProxy` / `LoopbackSocks5Proxy`（同时设置 `HTTPS_PROXY` 与 `MAIL_CORE_OUTBOUND_PROXY`），先验证未放行 `127.0.0.1` 时于 DNS 阶段拦截并报 `SSRFSecurityError`，再在 `MAIL_CORE_PROXY_ALLOW_CIDRS="127.0.0.1/32"` 放行下仅在 OS 端口边界将 443/80 映射到回环端口，完整跑通 `fetch_safe_remote_image` → `connect_ips_with_fallback` → `wrap_tls_socket`（校验 `https_img_srv.sni_seen == ["img.example.test"]`）→ `http.client.HTTPConnection` 全链路且验证两个代理收到 0 个请求。`.scratch/test_runs/6bd642be31a34fbb8eb391e08bb894fb/coverage.json` 实测 `src/mail_core/security/remote_image_proxy.py:379-427, 495-519` 已全部覆盖。
    - `t089_test_f002`（`important`）：**已消除**。`tests/mail_core/test_net_resilience.py:260-381`（`test_real_imap_bulkhead_permit_isolation_and_half_open_recovery`）移除了 `_DialDummy` 与 `_HealthyImap` 对 `client_factory` 的绕过，直接用真实 `ImapProvider` 走 `DialedIMAP4_SSL` → `dial_stream` → `EndpointBulkhead` 对接 `SilentAcceptServer` 与 `LoopbackTlsImapServer`，端到端覆盖：(1) 连续两次真实 TLS 握手超时触发熔断并释放槽位；(2) 6 个后台槽位被占满时 10 路并发 `imap.gmail.com` 请求在申请槽位前直接 `EndpointCircuitOpenError` 快速失败，而健康 `imap.163.com` 经真实 `DialedIMAP4_SSL` 成功同步；(3) 冷却到期后半开探针再次超时自动重开冷却窗口；(4) 恢复后半开探针经真实 `ImapProvider` 成功并关闸清槽。`tests/mail_core/test_net_resilience.py:383-427` 亦补齐 `EndpointCircuitOpenError.retry_after_seconds`、`is_capacity_error` 与 Worker `reschedule_job` 延期且不计 `failure_attempts` 的契约测试。
    - `t089_test_f003`（`minor`）：**已消除**。`tests/mail_core/test_net_outbound.py:85-99, 162-200, 350-355` 与 `tests/mail_core/test_net_resilience.py:80-120, 224-238` 已补全 `https://` TLS-in-TLS 代理隧道（覆盖 OAuth urllib 与 `ImapProvider` 外层+内层双向 TLS 与目标 SNI 验证）、小写 `https_proxy` 回落、`build_provider(graph)` 代理字段注入、真实 PostgreSQL 下 `update_account` 传空白清除 `proxy_mode`/`outbound_proxy`、`ImapProvider(proxy_mode="direct")` 忽略环境变量代理及 `MAIL_CORE_CONNECT_TIMEOUT_S` 运行时读取。
    - `t089_test_f004`（`minor`）：**已消除**。`tests/mail_core/test_net_resilience.py:222-257` 新增真实 `SilentAcceptServer` 在 `MAIL_CORE_CONNECT_TIMEOUT_S="0.2"`（`timeout=60.0`）下于 2 秒内快速超时截断的实测、`io_timeout=None` 复位 `sock.gettimeout()` 为 `None` 的验证以及 `wrap_tls_socket` 剩余预算耗尽抛 `TimeoutError` 的覆盖。
    - `t089_test_f005`（`minor`）：**已消除**。`tests/conftest.py:16-47` 已补全 `MAIL_CORE_CONNECT_TIMEOUT_S`、`MAIL_CORE_CONNECT_ATTEMPT_TIMEOUT_S`、`MAIL_CORE_CIRCUIT_FAILURE_THRESHOLD`、`MAIL_CORE_CIRCUIT_COOLDOWN_S` 与 `MAIL_CORE_PROXY_ALLOW_CIDRS` 环境变量清理，并在每个用例前后同步执行 `default_bulkhead().reset()`、`configure_default_bulkhead(failure_threshold=2, cooldown_s=30.0)` 与 `reset_config()`；同时原 `test_net_outbound.py:515, 906` 的 `# type: ignore` 已彻底清理。
- 改测方向复核：无「迁就实现」的改测。Round 2 未新增削弱既有测试断言的改动；原删除/适配的既有测试（`test_a350_toctou_disclosure.py`、`test_adoptions_patch.py`、`test_imap_id_handshake.py`、`test_provider_connection_budget_integration.py`、`test_archive_scheduler.py`、`test_imap_connect_socket_cleanup.py`、`test_medium_providers_sync_blobs.py`）与 Round 1 核查一致，均属消除构建期 DNS TOCTOU / 事后 `getpeername()` 或同步边界类名 `DialedIMAP4_SSL` 的合法变更。`tests/mail_core/test_net_outbound.py` 与 `tests/mail_core/test_net_resilience.py` 均无 `# type: ignore`、无恒真断言、无跳过门禁。
- 本轮新发现：1 条（`minor`：`t089_test_f006`，0 条 `critical` / `important`）
- 未进表的提示：
    1. 拆分后文件规模与复杂度良好：`tests/mail_core/outbound_fixtures.py`（450 行，最大圈复杂度 `_handle_client` 13）、`tests/mail_core/test_net_outbound.py`（384 行，最大圈复杂度 8）、`tests/mail_core/test_net_resilience.py`（427 行，最大圈复杂度 `test_real_imap_bulkhead_permit_isolation_and_half_open_recovery` 15）。
    2. 本轮独立复跑验证结果（均在当前 worktree 下实际执行通过）：
        - 定向 unit 模式（`test_net_outbound.py`、`test_net_resilience.py` 及全部改动/关联测试）：101 passed, 8 skipped（8 个 skip 均为 unit 模式下按设计跳过的 DB/PG 用例）；
        - `scripts/run-mail-core-tests.sh run --no-cov -k "test_net_outbound or test_net_resilience or test_imap_protocol_suite or test_imap_provider_live or test_remote_image_proxy or test_provider_connection_budget_integration or test_adoptions_patch or test_imap_id_handshake or test_imap_connect_socket_cleanup or test_medium_providers_sync_blobs or test_archive_scheduler or test_host_security or test_t061_imap_idle_probe or test_oauth_transport"`（真实 PostgreSQL 15433 + 真实 Dovecot IMAP 1143）：152 passed, 0 failed, 0 skipped；
        - `docs/blueprint/testing.md` `test_cmd` 全部 4 项门禁：`pytest .repo_template/tests -q -m contract`（389 passed, 1 skipped）、`(cd src/frontend && npm test && npx tsc -b && npm run build)`（56 文件 597 tests 全部通过且 `openapi:check`/`css:check` 通过）、`(cd src/desktop && npm test)`（12 suites 全部通过；Electron OAuth 集成按未设外部凭据跳过）、`python3 scripts/check_doc_sensitive.py docs --check`（35 文件 0 违规）。
        - 同步核查全量 run 产物（`.scratch/test_runs/6bd642be31a34fbb8eb391e08bb894fb/test_summary.json`）：2253 passed, 0 failed, 2 skipped（环境限定 `/dev/shm` 与 Electron 集成 mode），`remote_image_proxy.py`、`net/dialer.py`、`net/http_client.py` 与 `net/bulkhead.py` 新增及重构路径均已命中。
- 总体判断：Round 1 全部 5 条 finding（含 2 条 `important` 阻断项）均已真实消除，本轮仅发现 1 条 `minor` 文档命令同步提示（`t089_test_f006`），全部 6 条 AC 均获真实测试支撑，判定 PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/mail_core/test_net_resilience.py:46-167` 与 `tests/mail_core/test_net_outbound.py:53-200, 324-384` 使用真实回环 HTTP CONNECT、HTTPS TLS-in-TLS CONNECT 与 SOCKS5h 代理服务端，实测 `ImapProvider` 短连接/IDLE、OAuth `urllib` 与 `NO_PROXY`/`proxy_mode="direct"` 覆盖并校验目标 SNI，已独立重跑通过。
- AC-002：TICK-VALID，re_verified。`tests/mail_core/test_net_outbound.py:213-322` 与 `tests/mail_core/test_provider_connection_budget_integration.py:173-186` 覆盖直连与普通 SOCKS5 拨号器的单次 DNS Pin-IP 防 TOCTOU、混合私网拦截、回环代理端点放行，以及 `fetch_safe_remote_image` 拦截非放行私网 DNS 且在放行回环图片服务端时绕过在监听代理直连并保留 TLS SNI，已独立重跑通过。
- AC-003：TICK-VALID，re_verified。`tests/mail_core/test_net_resilience.py:189-258` 覆盖 IPv4 优先双栈回退、8.0s 总预算封顶且保留 `TimeoutError` 不被 IPv6 `ENETUNREACH` 掩盖、`SilentAcceptServer` 在 `MAIL_CORE_CONNECT_TIMEOUT_S="0.2"` 下于 2s 内截断替代 60s 阻塞及 `io_timeout=None` 切换，已独立重跑通过。
- AC-004：TICK-VALID，re_verified。`tests/mail_core/test_net_resilience.py:260-427` 通过真实 `ImapProvider` → `DialedIMAP4_SSL` → `dial_stream` 验证连续握手超时开启 `EndpointBulkhead` 冷却、10 路并发前景请求在持槽前 `EndpointCircuitOpenError` 快速失败而不饿死健康 `imap.163.com` 账号，以及半开探针失败重开与成功恢复关闸和 Worker `retry_after_seconds` 延期语义，已独立重跑通过。
- AC-005：TICK-VALID，re_verified。独立运行 `scripts/run-mail-core-tests.sh run --no-cov -k "..."` 涵盖 `test_net_outbound`、`test_net_resilience`、真实 Dovecot `test_imap_protocol_suite`、`test_imap_provider_live`、`test_remote_image_proxy`、`test_provider_connection_budget_integration` 等 152 个用例全部通过，且 `docs/blueprint/testing.md` `test_cmd` 4 项门禁全部执行通过。
- AC-006：TICK-VALID，re_verified。核对 `docs/specs/account_connection.md`、`docs/specs/mail_sync_and_storage.md`（均已登记 `t089`）及 `docs/blueprint/architecture.md`、`docs/blueprint/conventions.md`、`docs/blueprint/testing.md` 均已同步更新，`check_doc_sensitive.py` 检查 0 违规（另见 `t089_test_f006` `minor` 建议补充 `testing.md:82` 命令列表）。

coverage = 6 / 6

reviewed_scope: fac7d89714976f59

verdict: PASS
