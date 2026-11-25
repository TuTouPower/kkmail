---
pid: "p095"
slug: "gmail_imap_retry_proxy_and_background_pollution"
status: "closed"
resolution: "transferred"
reason: "已核实根因与铁律重构范围，拆分为 t089/t090/t091 三连 task 实施"
fix_ref: "t089,t090,t091"
---
# p095 Gmail 全账户反复重试与网络异常状态污染

- 现象：用户侧栏全部 Gmail 账号（5 个，`provider=imap`、`imap.gmail.com:993`）集体显示灰字「网络异常，正在重试」（`connectivity_state='degraded'`），期间部分账号进一步升级为红字「网络连接不可用，系统正在重试」（`unreachable`），而同机的 Microsoft Graph 与 163/QQ IMAP 账号正常；但同时出现大量 163/QQ/Outlook 的巡检、delta 与写回任务被 `ProviderCapacityUnavailable` 连带延迟，直到 `imap.gmail.com` DNS 轮换到可达 IPv4 后 5 个 Gmail 账号才一起恢复 `connected`。Worker 日志与 `worker_jobs.last_error` 只留下 `OSError code=[REDACTED]`，`accounts.config.last_connectivity_error` 只留下裸 `OSError`。
- 影响：
    1. Gmail 连接频繁阻塞并退化/熔断，且单次连接失败持有全局 8 槽位之一长达 `60s * IPv4 数`（实测 120s），引发全局 `ProviderCapacityUnavailable` 饥饿风暴，拖累 163/QQ/Outlook 正常账号同步与写回。
    2. 后台静默同步（全目录 patrol、IDLE 唤醒/补偿、periodic 续跑）缺少或丢失 `background=True` 血缘标记，失败后违反「后台静默同步故障不外溢」契约，把所有 Gmail 账号同时标成 `degraded` / `unreachable`。
    3. 错误码被错误脱敏与二次摘要剥离，生产日志与账号诊断无法直接区分 `ENETUNREACH`（101）、`EHOSTUNREACH`（113）等真实网络错误。
    4. 已确认合并进同一修复范围的同类位点：
        - 连接与预算：`ImapProvider._connect`（`src/mail_core/providers/imap.py:846-910`）及其唯一建连入口 `_connect_with_permit`（`:787-803`）、`open_idle_session`（`:1834`），影响全部 IMAP 同步/写回/归档/巡检/IDLE 与连接校验；需同步评估代理下的 `validate_imap_host` / `validate_imap_peer_address`（`src/mail_core/providers/host_security.py:69-111`）边界。对比：`src/mail_core/security/remote_image_proxy.py:352-385`（`_connect_with_fallback`）已实现 IPv4 优先、总超时预算与防 IPv6 `ENETUNREACH` 掩盖 `TimeoutError`（但其为 SSRF 防护直连目标 IP，是否走 HTTP 代理属独立安全边界，复用底层直连 Dialer 原语并保持禁止代理）；`src/mail_core/providers/oauth.py:264-565` 走 `urllib.request` 自动支持 `HTTPS_PROXY`。
        - 错误码留存：`src/mail_core/security/redact.py:25`（通用 `code=` 密钥正则误杀 `safe_provider_summary` 生成的 `OSError code=<errno>`）、`src/mail_core/security/redact.py:116-123`（`safe_provider_summary(str)` 正则只保留 `status=` 丢弃 `code=`），影响 `logging_config.py`（`RedactingFilter`）、`sync/jobs.py:472`（`fail_job` → `safe_error`）、`accounts/health.py:180`（`record_connectivity_failure`）、`sync/delta.py:539`、`sync/reconcile.py:221`、`sync/remote_push.py:529`。
        - 后台血缘保留：`src/mail_core/sync/patrol.py:257-264`（入队 `SYNC_FOLDER_DELTA` 缺 `background=True`）、`src/mail_core/sync/idle_watcher.py:648-658`（`_enqueue_delta` 缺 `background=True`）、`src/mail_core/sync/delta.py:325,387,505,522,655`（`sync_context_payload(None, ...)` 丢弃 `worker/main.py:280` 传入的 `background=True`）、`src/mail_core/sync/engine.py:174,220,242,349,419-725`（`sync_folder_metadata` 未透传 `background`，`_scan_context_payload` / `sync_context_payload` 在 `request_id=None` 时丢失 `background=True`）。另 `src/mail_core/sync/remote_push.py:201-208` 入队 `SYNC_ACCOUNT_FOLDERS` 传空 `payload={}`，在重构 `WorkerJob` 强类型血缘时统一显式声明归属。
- 根因：（**环境/网络触发 + 架构缺陷放大**）
    1. **缺失统一出站传输层与代理策略（环境主触发 + 架构割裂）**：运行容器 `kkmail-mail-core-worker` 注入了宿主机代理 `HTTP_PROXY` / `HTTPS_PROXY=http://host.docker.internal:7890`（`urllib` 驱动的 Graph OAuth/API 借此畅通，实测经该代理 `CONNECT imap.gmail.com:993` 与 `108.177.97.108:993` 均在 `0.61s–1.15s` 成功），但 `ImapProvider._connect`（`imap.py:850-854`）裸调标准库 `imaplib.IMAP4_SSL`，完全忽略代理环境变量且无显式代理原语。当旋转 DNS 返回境内直连被阻断的 Google IPv4（实测 `108.177.97.108/109` 均超时）时，全部 Gmail 账号同时断连；同时 `host_security.py` 将 SSRF 校验绑定在建连后 `sock.getpeername()`（且直连存在 DNS TOCTOU 窗口），无法区分受信任代理通道与直接出网。
    2. **连接预算与双栈超时/错误掩盖（架构缺陷）**：`docker-compose.mail-core.yml` 默认 bridge 网络无 IPv6 路由但 DNS 返回 A+AAAA。`imaplib` 底层 `socket.create_connection(..., all_errors=False)` 串行尝试所有地址：先在每个阻塞 IPv4 耗时完整 `io_timeout=60s`（且 `_connect_with_permit` 在建连前即占死全局 8 槽位之一，单个失败锁槽 120s），最后试 IPv6 时 `0ms` 抛 `OSError(101)` 并覆盖前面的 `TimeoutError`；缺乏统一的两段式超时（`connect_timeout` vs `io_timeout`）、主错误优先保留与端点级快速熔断隔离（Bulkhead）。
    3. **后台血缘靠易碎隐式 JSON 约定而非 Schema 一等公民（架构缺陷）**：`WorkerJob` 缺乏一等公民执行来源列，`resolve_sync_context` 依赖自由 `payload` 猜测且缺省判为前台，而 `sync_context_payload(None, ...)` 会丢弃 `background` 标记；`patrol`、`idle_watcher` 及无 `request_id` 续跑任务全部泄漏为前台故障，污染 `connectivity_state`。
    4. **跨层错误传播依赖非结构化字符串与正则互砍（架构缺陷）**：`safe_provider_summary(exc)` 产出 `"OSError code=101"` 后，`redact.py:25` 的通用 `code=` 密钥正则把 `101` 替换为 `[REDACTED]`，`health.py:180` 二次调用 `safe_provider_summary(str)` 又按 `:117` 只留 `status=` 剥成裸 `"OSError"`，且建连阶段信息全部丢失。
- 铁律重构方案（零兼容负担、拒绝局部补丁）：
    1. **统一出站传输层与通道隔离（→ t089）**：建设 `src/mail_core/net/` 统一出站 Dialer（显式支持全局与账号级 HTTP CONNECT / HTTPS / SOCKS5 / SOCKS5h 代理与 `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY`/`NO_PROXY`、直连 Pin-IP 消除 DNS TOCTOU、受信任代理与目标宿主分离校验、IPv4 优先与有界总建连预算、`connect_timeout` 与 `io_timeout` 分离、防止本地无路由 `ENETUNREACH` 掩盖远端 `TimeoutError`、以及同端点负反馈短冷却熔断 Bulkhead）；将 `ImapProvider` 与 `remote_image_proxy.py` 统一收口到该原语。
    2. **`WorkerJob` 强类型执行血缘一等公民化（→ t090）**：为 `WorkerJob` 新增非空执行来源/后台标记列与 Alembic 迁移，废弃脆弱的 `payload` 猜谜与 `sync_context_payload`；所有 `enqueue_job` 调用必须显式传入执行域，后继/重试/重排任务由调度框架原生继承，彻底保证巡检、IDLE 与周期续跑静默不污染账号健康态。
    3. **强类型结构化故障模型与白名单投影（→ t091）**：以不可变 `StructuredFailure`（含 `phase` / `error_type` / `errno` / `http_status` / `retry_after_s` / `domain`）贯通传输、Provider、同步、Worker 与账号健康诊断；由白名单字段确定性投影日志、`WorkerJob.last_error` 与 `last_connectivity_error`，将 `redact()` 收窄至不可信自由文本边界。
- 测试缺口：
    1. `ImapProvider` 单测均 monkeypatch `_connect` 或 `IMAP4_SSL`，未覆真实多地址回退、总建连超时封顶、`TimeoutError` 不被 `ENETUNREACH` 掩盖、代理隧道建连与 SSRF 边界、以及端点熔断不拖垮全局连接槽。
    2. `test_logging_trace_and_redact.py` 未覆 `OSError(errno)` 经安全摘要/日志/任务错误/健康状态全链路后保留 `phase` 与 `errno`，同时保证真实凭据/OAuth `code` 仍严格脱敏。
    3. `test_sync_backend_handler_isolation.py` 与 `test_sync_background_lineage.py` 把 `sync_context_payload(None, ...)` 不带 `background` 写成了正向预期，缺强制显式血缘、`patrol` / `idle_watcher` / 周期续跑失败全链路隔离及 Alembic 迁移往返验证。
- 线索：
    - `.scratch/repro_gmail_retry_cascade.py`（项目 venv 执行 `PYTHONPATH=src .venv/bin/python .scratch/repro_gmail_retry_cascade.py`，已稳定复现：1）`ImapProvider._connect_with_permit()` 忽略 `HTTPS_PROXY`、对双栈 4 地址串行耗时 `2 * timeout` 且全程持有 permit、最终抛出 `OSError(ENETUNREACH)` 掩盖 `TimeoutError`；2）`safe_provider_summary(exc)` 经 `redact()` / `safe_error()` 变为 `OSError code=[REDACTED]`、经二次 `safe_provider_summary()` 变为 `OSError`；3）`patrol`、`idle_watcher` 及 `sync_context_payload(None, ...)` 续跑均被 `resolve_sync_context` 判为 `is_background=False` → `failure_kind=transport`）。
    - 生产现场（2026-11-25 12:25–12:29 CST，容器 `kkmail-mail-core-worker` 与 `kkmail-mail-core-pg`）：12:26:20 `imap.gmail.com` 解析为 `108.177.97.108/109` + IPv6，容器直连报 `OSError(101)`，而经 `host.docker.internal:7890` `CONNECT` 在 `0.611s–1.145s` 成功返回 `* OK Gimap ready`；12:27:00 DNS 轮换到 `142.251.8.108/109` 后容器直连恢复（`0.37s`），5 个 Gmail 账号于 `04:27:57–04:29:50 UTC` 全部恢复 `connected`。
- 处理：t089,t090,t091；resolution=transferred；reason=已核实根因与铁律重构范围，拆分为 t089/t090/t091 三连 task 实施
