# Task spec

## 背景

2026-11-25 生产排查与 `.scratch/repro_gmail_retry_cascade.py` 复现表明，现行跨层故障传递存在结构化失真：

1. `delta.py` / `reconcile.py` 先调用 `safe_provider_summary(exc)` 把异常压缩成文本 `"OSError code=101"`，随结果返回给 `handlers.py`；
2. `handlers.py` 把该文本传给 `reschedule_job` → `fail_job` → `safe_error(str)` → `redact(str)`，同时日志也经 `RedactingFilter` → `redact()`，而 `redact.py:25` 的通用 `code=` 密钥正则误杀 `code=101`，导致日志与 `worker_jobs.last_error` 变成毫无诊断价值的 `OSError code=[REDACTED]`；
3. `accounts/health.py:180` 对已是摘要的字符串二次调用 `safe_provider_summary(str)`，`redact.py:116-123` 正则只识别 `status=` 丢弃 `code=`，使 `accounts.config.last_connectivity_error` 退化为裸 `"OSError"`；
4. 建连阶段信息（`dns` / `proxy_connect` / `tcp_connect` / `tls` / `auth`）全部在压缩与二次正则过程中丢失。

按开发铁律，废除「先压文本→正则脱敏误杀→二次正则截断」的脆弱链路，建立强类型 `StructuredFailure` 模型作为唯一跨层故障载体，并收紧 `redact()` 边界只处理不可信自由文本。

## 契约区

### 范围

- 建立强类型 `StructuredFailure`（如 `phase`、`error_type`、`errno`、`http_status`、`retry_after_s`、`domain` 等受控白名单字段）及统一异常提取/分类入口，无缝承接 `t089` 出站网络层带阶段信息的结构化错误与现有 Provider/HTTP/IMAP 异常。
- 贯通故障传递与持久化全链路：`providers/`、`sync/`（`delta`、`reconcile`、`engine`、`remote_push`）、`worker/handlers.py`、`sync/jobs.py`（`WorkerJob.last_error`）、`accounts/health.py`（`last_connectivity_error`）与 `logging_config.py` 直接由白名单 `StructuredFailure` 确定性投影诊断信息（含 `phase`、`error_type`、`errno` / `http_status`），绝不再被通用密钥正则误改或二次摘要剥离。
- 严格收紧 `security/redact.py` 职责边界：`redact()` 专职对不可信自由文本（原始日志文本、栈追踪、第三方消息串、URL query、JSON 凭据载荷）执行敏感信息脱敏，确保不破坏 OAuth `code` / `token` / `password` / JWT / Cookie / DSN 的严密拦截；结构化白名单投影与日志占位不再落入误杀陷阱。
- 保持对外 DTO（`AccountOut` / `AccountSummary.last_connectivity_error` 及前端类型）可空字符串展示契约清晰可读（如含阶段与 `errno`/`status` 信息），同步验证前后端测试与 OpenAPI 检查（若有字段变化同步生成校验）。
- 同步更新 `docs/blueprint/conventions.md`、`docs/blueprint/testing.md` 与 `docs/specs/mail_sync_and_storage.md`。

### 非范围

- 不改变底层网络代理与双栈超时策略（已由 `t089` 完成）。
- 不改变 `WorkerJob` 表结构与后台血缘隔离规则（已由 `t090` 完成）。
- 不在前端重做侧栏或设置页交互布局。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [x] AC-001：出站/IMAP/HTTP 层抛出的结构化传输或协议异常（如代理握手失败、TCP 超时 `errno=110`、不可达 `errno=101`、TLS 握手失败、HTTP 5xx/429/401）通过同步引擎与 Worker 后，Worker 日志、`WorkerJob.last_error` 与 `accounts` 健康诊断 `last_connectivity_error` 均完整保留可读故障阶段、异常类型与结构化状态码/errno，不出现 `code=[REDACTED]` 或退化为裸 `"OSError"`。
- [x] AC-002：安全脱敏边界不退化：URL query `?code=...` / `?token=...`、JSON `"code": "..."` / `"token": "..."`、HTTP `Authorization` / `Cookie` / JWT / DSN 与原始异常栈中的任何凭据秘密仍被完整替换为 `[REDACTED]`，绝不进入日志、`WorkerJob.last_error` 或账号诊断字段。
- [x] AC-003：`sync/context.py` 的结构化故障域分类（`AUTH` / `TRANSPORT` / `CONTROL` / `UNKNOWN`）与 `StructuredFailure` 保持单一事实来源，非网络 `OSError`（如 `ENOSPC` / `EMFILE` / `EACCES`）与自由文本错误仍严格不归入 `TRANSPORT`。
- [x] AC-004：后端全量 PostgreSQL 测试套件（`scripts/run-mail-core-tests.sh run`）与 `docs/blueprint/testing.md` 的 `test_cmd`、`blackbox_verify` 及 `export_openapi.py --check` / `openapi:check` 全部通过。
- [x] AC-005：同步更新 `docs/specs/mail_sync_and_storage.md`（登记 `t091`）及对应 blueprint 文档；转办来源 `p095` 完整闭环。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试：AC-001/002/003 由脱敏边界单测、日志过滤测试及端到端 Worker/健康态 PG 集成测试验证；AC-004/005 由全量门禁与脚本检查验证。

## 上下文区

- 关联 spec：docs/specs/mail_sync_and_storage.md
- 来源：p095（2026-11-25 `.scratch/repro_gmail_retry_cascade.py` 复现确认 `OSError code=[REDACTED]` 与二次摘要剥离成裸 `OSError`）

### 有意不测

- 真实公网外部邮件服务商报错报文：由构造带真实 `errno`、HTTP 响应体与敏感查询串/头部的异常夹具覆盖。

### 测试策略

- 单元测试：覆盖 `StructuredFailure` 从网络阶段/OS/HTTP 异常到投影格式的往返；覆盖 `redact` / `RedactingFilter` 对真实凭据/OAuth `code` 的拦截以及对结构化诊断 `errno` 的零误杀；覆盖非网络 `OSError` 与自由文本误判反向断言。
- 集成测试：真实 PG 下运行同步失败路径（`delta` / `reconcile` / `sync_account_folders` / `remote_push`），断言 `WorkerJob.last_error`、`Account.config` 与 API `last_connectivity_error` 保留阶段与 `errno` 且无秘密泄漏；全量 PG 门禁与前端/E2E 门禁全绿。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：收窄 `redact()` 边界或改变摘要文本格式时，必须确保不会放松对任意未结构化 `code=...` 凭据（如 URL/JSON/log 中的 OAuth 授权码）的脱敏，也不破坏已有健康诊断或测试断言契约。
- 回退：通过分支提交隔离，必要时可独立回退；保留所有针对 OAuth 授权码脱敏的回归测试用例。

### 依赖与约束

- 依赖 `t090`（及 `t089`、`t090` 链式上下文）；`review_level: full`。
- 约束：严禁通过忽略 `code` 密钥脱敏来换取 `errno` 可见性——必须通过「白名单结构化模型与自由文本脱敏分离」从架构根治。

### Finalization 时更新的 blueprint

- `docs/blueprint/conventions.md`：更新结构化故障模型与安全脱敏白名单分离契约。
- `docs/blueprint/testing.md`：补充故障诊断保留与凭据脱敏回归门禁说明。
