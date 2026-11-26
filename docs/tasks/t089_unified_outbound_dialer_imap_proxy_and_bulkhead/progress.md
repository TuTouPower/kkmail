---
tid: "t089"
slug: "unified_outbound_dialer_imap_proxy_and_bulkhead"
title: "统一出站网络原语、IMAP代理与双栈槽位隔离"
status: "done"
branch: "t089_unified_outbound_dialer_imap_proxy_and_bulkhead"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "4fd1656be379191a3ba9531f8cbd2e94a8803816"
spec_source_sha: "4fd1656be379191a3ba9531f8cbd2e94a8803816"
depends_on: ""
conflicts_with: ""
note: "来源 p095；铁律重构统一出站 Dialer/代理/Pin-IP SSRF/两段超时/端点熔断"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 2026-11-25（Round 1）：新增统一出站传输层 `src/mail_core/net/`（`policy.py`、`proxy.py`、`tunnel.py`、`bulkhead.py`、`dialer.py`、`imap_client.py`、`http_client.py`），重构 `host_security.py`、`imap.py`、`factory.py`、`oauth.py`、`remote_image_proxy.py` 与 `config/`；首轮全量单测+PG+IMAP（2252 passed）与 E2E（25 passed）通过，但独立代码/测试 review 因 TLS-in-TLS、`MICROSOFT_*` 删域、`config_patch` 空白清除、熔断槽位整合与测试隔离/真实性问题判 FAIL。
- 2026-11-25（Round 2 修复与全量复验）：
    - 在 `src/mail_core/net/tunnel.py` 新增 `bridge_tls_socket()`（`socket.socketpair()` + 单泵线程及 `pending()` 排空），支持 `https://` 代理隧道下的 TLS-in-TLS `DialedIMAP4_SSL` 与 `urlopen_outbound`（解决 `t089_code_f001`）。
    - 恢复 `src/mail_core/providers/host_security.py` 不可变 `frozenset` 与完整 `MICROSOFT_DOMAINS` / `MICROSOFT_IMAP_HOSTS`（解决 `t089_code_f002`）。
    - 在 `src/mail_core/accounts/connection.py` 提取 `normalize_account_config()`，于 `service.py` `update_account()` 校验与落库前剔除空白配置键（解决 `t089_code_f003`）。
    - 为 `EndpointCircuitOpenError` 增加 `retry_after_seconds` 属性并纳入 `CAPACITY_ERRORS`（`connection_slots.py`），确保触发端点冷却时走延迟重排且不计入 `failure_attempts`（解决 `t089_code_f004`）。
    - 修复 `http_client.py` / `oauth.py` 透传 `EndpointCircuitOpenError` 与 `ProxyHandler({})`（显式 `proxy_mode="direct"`），`dialer.py` 支持 `io_timeout=None` 并删除零引用符号，全量重构 `src/mail_core/net/` 与调用链使 `net/` 全部函数 `CC < 15`（解决 `t089_code_f005`、`t089_code_f006`、`t089_code_f007`）。
    - 扩充 `tests/conftest.py` 环境变量与默认熔断器自动隔离，将出站测试拆分为 `outbound_fixtures.py`、`test_net_outbound.py`、`test_net_resilience.py`，改用真实回环 TLS IMAP / SilentAccept / HttpsServer + PostgreSQL 复测，清理全部 `# type: ignore`（解决 `t089_test_f001` ~ `t089_test_f005`）。
    - 重跑全部门禁通过后由独立 code / test reviewer 完成 Round 2 复审（均 `verdict: PASS`）；Round 2 新增 3 条非阻断 minor 转入 `p096`。

## Review 处置

### Round 1 (2026-11-25T13:59:18+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t089_code_f001|critical|已修|为 HTTPS CONNECT 隧道目标 TLS 新增 `bridge_tls_socket()` socketpair 泵桥接，隔离外层代理 TLS 与内层 SNI/超时|`src/mail_core/net/tunnel.py:284-318`|
|t089_code_f002|important|已修|恢复不可变 `frozenset` 与被误删 Microsoft 域名与 IMAP 主机条目|`src/mail_core/providers/host_security.py:19-45`|
|t089_code_f003|important|已修|抽取 `normalize_account_config()` 并在 `update_account()` 校验前清除空白代理键，经真实 PG 验证|`src/mail_core/accounts/service.py:143,181`|
|t089_code_f004|important|已修|为 `EndpointCircuitOpenError` 增加 `retry_after_seconds` 并纳入 `CAPACITY_ERRORS` 走延迟重排且不计 `failure_attempts`|`src/mail_core/providers/connection_slots.py:133-140`|
|t089_code_f005|minor|已修|`http_client.py` 直接重抛 `EndpointCircuitOpenError`，`oauth.py` 停止对其重试且明确映射 `NetworkSecurityError`|`src/mail_core/providers/oauth.py:359-376`|
|t089_code_f006|minor|已修|`dialer.py` 在 `io_timeout=None` 显式调用 `sock.settimeout(None)`，移除死代码，`direct` 阻断系统代理|`src/mail_core/net/dialer.py:356-357`|
|t089_code_f007|minor|已修|拆分 helper 使 `src/mail_core/net/` 全函数 `CC < 15`，调用方分支显著下降或无净增|`src/mail_core/net/dialer.py:297-389`|
|t089_test_f001|important|已修|改用本地回环 HTTPS 服务端 + 未放行私网拦截与放行后 `fetch_safe_remote_image` 真实直连验证（代理 0 请求）|`tests/mail_core/test_net_outbound.py:272-322`|
|t089_test_f002|important|已修|移除替身工厂，改用真实 `ImapProvider` 对接 `SilentAcceptServer` 与 `LoopbackTlsImapServer` 验证熔断、隔离与 `retry_after`|`tests/mail_core/test_net_resilience.py:260-427`|
|t089_test_f003|minor|已修|补齐 `https://` TLS-in-TLS、小写 `https_proxy`、`build_provider(graph)`、真实 PG 空白配置清除及 `direct` 覆盖|`tests/mail_core/test_net_resilience.py:80-238`|
|t089_test_f004|minor|已修|新增真实 `SilentAcceptServer` 在 `MAIL_CORE_CONNECT_TIMEOUT_S` 下的快速截断与 `io_timeout=None` 实测|`tests/mail_core/test_net_resilience.py:222-257`|
|t089_test_f005|minor|已修|`conftest.py` 自动复位环境变量、全局熔断与配置，并拆分测试文件与清理 `# type: ignore`|`tests/conftest.py:16-47`|

### Round 2 (2026-11-25T14:52:41+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t089_code_f008|minor|遗留|`create_account` 与带 `oauth_flow_id` 合并路径未同步调用 `normalize_account_config()`，保留 `PATCH` 先行收口，其余路径转入 p096|p096|
|t089_code_f009|minor|遗留|`src/mail_core/net/proxy.py` 参数注解 `Any` 缺失导入但受 `from __future__ import annotations` 保护不影响运行，转入 p096|p096|
|t089_test_f006|minor|遗留|`docs/blueprint/testing.md:82` 定向命令需补充拆分后的 `test_net_resilience.py`，不影响全量运行，转入 p096|p096|

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：`./scripts/run-mail-core-tests.sh run` 2253 passed, 2 skipped（覆盖率 86%，含真实 PostgreSQL 15433 与 Dovecot IMAP 1143）；`pytest .repo_template/tests -q -m contract` 389 passed, 1 skipped；前端 `vitest`（56 文件 597 tests + `openapi:check` + `css:check`）、`tsc -b` 与 `vite build` 通过；桌面端 `npm test` 12 suites 通过；`check_doc_sensitive.py docs --check` 35 文件 0 违规。
- 黑盒：`npm --prefix src/frontend run test:e2e` Playwright 全链路 25 passed。
- review：Round 1 FAIL（code 7 条、test 5 条）；Round 2 复审 code（`review_code.md`）与 test（`review_test.md`）均 `verdict: PASS`（`reviewed_scope: fac7d89714976f59`，AC-001 ~ AC-006 全部 `TICK-VALID` / `coverage = 6 / 6`）；Round 2 新增 3 条非阻断 minor（`t089_code_f008`、`t089_code_f009`、`t089_test_f006`）已转入 `p096`。
- AC 判定：见 `task.md` 行内打勾

### 结果摘要

- 建立统一出站网络层 `src/mail_core/net/`（`policy.py`、`proxy.py`、`tunnel.py`、`bulkhead.py`、`dialer.py`、`imap_client.py`、`http_client.py`），统一解析 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`/`NO_PROXY` 与账号级配置，支持直连 Pin-IP、HTTP/HTTPS `CONNECT` 隧道（含 TLS-in-TLS bridge）与 SOCKS5/SOCKS5h 代理通道。
- 消除 `host_security.py` 构建期 DNS TOCTOU 与事后 `getpeername()` 检查；实现直连全 IP 私网校验 + Pin-IP SNI 建连，明确区分受信任内网代理与禁止直连内网目标，同时保留 `remote_image_proxy` 强制直连禁代理契约。
- 落地双栈 IPv4 优先回退、有效远端异常优先级保留、两段式超时（`connect_timeout` vs `io_timeout`）以及基于 `EndpointBulkhead` 与 `CAPACITY_ERRORS` 的端点短冷却与连接槽隔离，并补齐 `test_net_outbound.py` / `test_net_resilience.py` 回归套件；遗留次要收口见 `p096`。

### 长期文档闭环

- 已在 active spec [`docs/specs/account_connection.md`](../../specs/account_connection.md) 与 [`docs/specs/mail_sync_and_storage.md`](../../specs/mail_sync_and_storage.md) 的 front matter `tasks` 清单中登记 `t089`，并同步更新 [`docs/blueprint/architecture.md`](../../blueprint/architecture.md)、[`docs/blueprint/conventions.md`](../../blueprint/conventions.md) 与 [`docs/blueprint/testing.md`](../../blueprint/testing.md)。
