---
pid: "p099"
slug: "https_proxy_default_port_80"
status: "closed"
resolution: "resolved"
reason: "新增 _DialedHTTPSConnection 并按 TLS 对齐 default_port=443，修复无显式端口 HTTPS 经代理错拨 80；补齐代理默认端口与 Host 头回归测试；PG 专项 162 passed、前端/桌面端/E2E 25 passed 与 389 contract 全通过"
fix_ref: "main"
---
# p099 HTTPS 代理默认端口被 HTTPConnection 覆盖为 80 导致 Graph 请求失败

- 现象：部署 `990bcf4c` 后，经 `HTTPS_PROXY` 发起的所有无显式端口 `https://` 请求（如 `https://graph.microsoft.com/v1.0/...`、`https://login.microsoftonline.com/...`）在 `kkmail-mail-core-worker` 中全部以 `[SSL: WRONG_VERSION_NUMBER]` 失败，并触发 `EndpointCircuitOpenError phase=proxy_connect` / `capacity_unavailable`，导致全部 25 个 `graph` 账号无法完成同步与巡检。
- 影响：`src/mail_core/net/http_client.py` 中所有经 `urlopen_outbound`（OAuth Token 刷新与 Graph JSON API 调用）的无显式端口 HTTPS 请求；已全仓扫描 `HTTPConnection`/`HTTPSHandler` 子类及直接构造点，另一处 `src/mail_core/security/remote_image_proxy.py` 已显式计算 `port = 443 if scheme == "https" else 80` 并正确传参和设置 `Host` 头，无同类问题。
- 根因：`mail_core.net.http_client._DialedHTTPConnection` 直接继承 `http.client.HTTPConnection`（`default_port = 80`），`_DialedHTTPSHandler.https_open` 构造连接时未传递 `port` 且类未按 HTTPS 覆写 `default_port = 443`。`HTTPConnection.__init__` 在无显式 `:port` 时用 `self.default_port` 将 `self.port` 设为 `80`，导致 `connect()` 中 `int(self.port or ...)` 取到 `80` 并向代理发起 `CONNECT <host>:80`，随后对其执行 TLS 握手触发 `WRONG_VERSION_NUMBER` 且 `Host` 头基准端口也错用 `80`。
- 测试缺口：现有 `tests/mail_core/test_net_outbound.py` 的 `urllib_json_request` / `default_urllib_token_post` 代理集成测试统一构造了显式回环端口 URL（`https://graph.test:{https_srv.port}/v1.0/me`），`HTTPConnection.__init__` 直接解析到非空端口，未触发默认端口解析路径；需补无显式端口 `https://` 与 `http://`（含 IPv6 字面量与 `Host` 头校验）的真实代理端到端测试及 `_DialedHTTPConnection` / `_DialedHTTPSConnection` 默认端口契约单测。
- 线索：`.scratch/repro_p099.py`（`_DialedHTTPConnection("graph.microsoft.com", use_tls=True)` 复现 `port=80, default_port=80`）。
- 处理：main；resolution=resolved；reason=新增 \_DialedHTTPSConnection 并按 TLS 对齐 default_port=443，修复无显式端口 HTTPS 经代理错拨 80；补齐代理默认端口与 Host 头回归测试；PG 专项 162 passed、前端/桌面端/E2E 25 passed 与 389 contract 全通过
