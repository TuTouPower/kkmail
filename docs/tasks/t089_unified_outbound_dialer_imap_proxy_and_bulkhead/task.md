# Task spec

## 背景

2026-11-25 生产诊断与 `.scratch/repro_gmail_retry_cascade.py` 复现表明，现行出站网络实现存在三层架构割裂（见 `p095`）：

1. 协议适配各自裸连：`ImapProvider._connect` 直接调用标准库 `imaplib.IMAP4_SSL`，完全忽略容器 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`（实测通过宿主代理 `CONNECT imap.gmail.com:993` 0.6s–1.1s 建连成功，而直连轮换到受阻 Google IPv4 超时）；同时 `host_security.py` 把 SSRF 校验绑定在建连后 `sock.getpeername()` 与构建期 `getaddrinfo()`，既存在 DNS TOCTOU 窗口，又无法区分「受信任代理隧道」与「直连目标公网 IP」。
2. 连接预算与超时未分离：`ImapProvider._connect_with_permit` 在建连前即占住全局 8 槽位之一，并把用于读写Commands的 `io_timeout=60s` 直接传给 `socket.create_connection`，导致双栈黑洞 IP 串行阻塞 120s 锁死槽位，引发 163/QQ/Outlook 等健康账号批量 `ProviderCapacityUnavailable`。
3. 双栈回退错误掩盖：`imaplib` 底层 `socket.create_connection(..., all_errors=False)` 在无 IPv6 路由的容器内先耗时等待 IPv4 超时，再瞬时触发 IPv6 `OSError(ENETUNREACH)` 并丢弃前面的 `TimeoutError`；`remote_image_proxy.py` 已自行实现 `_connect_with_fallback`，与 IMAP 各自重复造轮子。

按开发铁律，废除协议层裸连与事后 `getpeername()` 补丁，建设统一的出站网络建连原语、代理隧道、Pin-IP SSRF 防护、两段式超时与端点熔断隔离。

## 契约区

### 范围

- 建立统一出站传输原语（`src/mail_core/net/`）：统一解析出站代理策略（集中配置、可选账号级覆盖、`HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`/`NO_PROXY`），支持直连 Pin-IP、HTTP/HTTPS `CONNECT` 隧道与 SOCKS5/SOCKS5h 代理隧道。
- 重构 SSRF 防护边界（消除 `host_security.py` 构建期 DNS TOCTOU 与事后 `getpeername()` 校验）：直连模式先解析并校验全部目标 IP 非私网/回环/保留段后按 IP 直连并保留 TLS SNI；代理模式校验目标主机合法性并仅连接受信任代理端点，禁止通过私有 IP 绕过策略访问内网资源。
- 统一双栈回退与两段式超时：分离 `connect_timeout`（受控总建连预算 + 单地址上限，默认不复用 60s 读超时）与 `io_timeout`（建连与 TLS 握手完成后切换为读写超时）；IPv4 优先尝试，保留有效远端失败（如 `TimeoutError`）不被无本地路由的 `ENETUNREACH` 覆盖。
- 将 `ImapProvider`（短连接、批操作与长连接 `open_idle_session`）与 `remote_image_proxy.py` 收口到同一底层建连原语（`remote_image_proxy` 强制直连禁代理，保持原 SSRF 零外泄契约）；`oauth.py` 复用同一显式代理策略解析。
- 为不可达传输端点引入有界负缓存/熔断与快速失败隔离（Bulkhead），避免同一受阻 host 多账号并发重试长期占死全局连接槽位（`ConnectionPermit`）。
- 更新 `docs/blueprint/architecture.md`、`docs/blueprint/conventions.md`、`docs/blueprint/testing.md` 与 `docs/specs/mail_sync_and_storage.md` / `account_connection.md`。

### 非范围

- 不改变 `WorkerJob` 数据表结构与后台任务血缘字段（由 `t090` 负责）。
- 不改造 `StructuredFailure` 诊断模型与 `redact()` 日志/DB 格式化边界（由 `t091` 负责）。
- 不新增发信、联系人或系统通知功能；不修改线上生产 `.env` 或部署容器。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [ ] AC-001：配置了出站代理（`HTTPS_PROXY` / `HTTP_PROXY` / `ALL_PROXY` 或显式代理配置，且目标不在 `NO_PROXY`）时，IMAP 同步与 IDLE 建连通过代理隧道完成 TLS 握手并透传正确目标 SNI，不再忽略代理强制直连。
- [ ] AC-002：直连模式下（含配置允许或禁止私网开关、以及远程图片代理直连路径），DNS 解析为私网/回环/保留 IP 时在 TCP 建连前即被拦截；实际连向的远端套接字地址即被校验的安全 IP（消除解析后重绑定 TOCTOU），且代理模式下连接位于私网/回环的受信任代理端点不再误触发 SSRF 拒绝。
- [ ] AC-003：面对同时返回阻塞超时 IPv4 与本地无路由（`ENETUNREACH`）IPv6 的目标主机，建连总耗时严格受有界建连预算控制（显著低于原 `N * io_timeout` 串行阻塞），连接完成后才应用长读超时，且抛出的主异常保留远端 `TimeoutError` 而非被 IPv6 `ENETUNREACH` 掩盖。
- [ ] AC-004：当同一远端端点连续建连超时/不可达进入端点短冷却窗口后，后续并发请求快速失败并立即释放连接预算槽位，不因多个账号同时阻塞握手而耗尽全局连接池致使其他健康账号出现 `ProviderCapacityUnavailable`。
- [ ] AC-005：通过 `ImapProvider` 与远程图片代理回归测试及真实本地 IMAP 套件：`scripts/run-mail-core-tests.sh run` 相关协议/安全/代理/连接预算用例及 `docs/blueprint/testing.md` 的 `test_cmd` 通过。
- [ ] AC-006：同步更新 `docs/specs/account_connection.md`、`docs/specs/mail_sync_and_storage.md`（登记 `t089`）及对应 blueprint 文档。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试：AC-001 使用真实本地回环代理（HTTP CONNECT / SOCKS5 监听套接字 + TLS 服务端夹具）验证；AC-002 使用可控 DNS 解析与本地受限地址夹具验证 Pin-IP 与代理边界；AC-003/004 使用双栈黑洞/超时套接字夹具与并发连接槽压测验证；AC-005/006 由测试门禁与文档检查验证。

## 上下文区

- 关联 spec：docs/specs/account_connection.md
- 关联说明：同时涉及 `docs/specs/mail_sync_and_storage.md` 的出站传输与连接预算部分，finalization 时在两份 active spec 登记本 task。
- 来源：p095（2026-11-25 生产故障排查与 `.scratch/repro_gmail_retry_cascade.py` 最小复现；从开发铁律拆分为三连重构首棒）

### 有意不测

- 真实公网跨境链路与宿主机商业代理进程：依赖外部网络抖动不可控，由本地回环 CONNECT/SOCKS5 代理夹具与受限 IP 双栈夹具等价覆盖。

### 测试策略

- 单元测试：覆盖代理 URL 解析、`NO_PROXY` 匹配、HTTP CONNECT 握手与 407/502 失败映射、SOCKS5/SOCKS5h 握手、Pin-IP 消除 TOCTOU、双栈 IPv4 优先与错误优先级保留、两段超时切换、端点熔断冷却与自动恢复。
- 集成测试：覆盖 `ImapProvider` 经真实回环 TLS + 代理同步及 IDLE 建连、多账号受阻不饿死健康账号槽位、`remote_image_proxy` 复用直连原语且禁代理不回归、`scripts/run-mail-core-tests.sh run` 真实 PG + IMAP 协议门禁。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无（已于 2026-11-25 在生产容器实测通过 `CONNECT` 代理连接 `imap.gmail.com:993` 成功返回 `* OK Gimap ready`，且双栈 `socket.create_connection` 行为已在 `.scratch/repro_gmail_retry_cascade.py` 复现核实）

### 风险与回退

- 风险：统一替换 `imaplib.IMAP4_SSL` 建连路径若未正确维护 `sock`/`file` 属性或 TLS `server_hostname` 校验，可能影响 `ImapIdleSession` 关闭或证书校验；端点短冷却阈值过高可能延缓网络恢复后的首次重连。
- 回退：通过分支级提交独立隔离，若出现协议栈不兼容可整体回退本 commit；端点冷却窗口设计为可配置短周期且仅影响建连，不写库。

### 依赖与约束

- 无前置 task 依赖；`review_level: full`。
- 安全约束：代理模式下不得把任意目标直连内网，远程图片代理仍强制直连禁止走出站代理；不得在日志或异常消息中泄漏代理鉴权凭据或账号口令。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：更新统一出站传输层、IMAP 代理通道与建连/读写分离预算描述。
- `docs/blueprint/conventions.md`：更新代理配置、Pin-IP SSRF 边界与两段式超时约定。
- `docs/blueprint/testing.md`：补充出站代理、双栈超时与端点熔断门禁说明。
