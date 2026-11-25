# Task review t091（reviewer_focus: 测试）

- task：`t091_typed_structured_failure_and_allowlist_diagnostics`
- spec：`docs/tasks/t091_typed_structured_failure_and_allowlist_diagnostics/task.md`
- diff_anchor：`917504e4e88bc804c133cac90481f1266fb82f7d`
- target：`git diff 917504e4e88bc804c133cac90481f1266fb82f7d`
- round：1
- reviewed_at：2026-11-26T01:52:16+08:00
    reviewed_scope: b9c7e0300cb8e4a5

## Findings

### t091_test_f001 - 缺失 sync_account_folders 与 HTTP/TLS 异常经 Worker 落库链路测试，掩盖 WorkerJob.last_error 退化缺陷

- 严重度：important
- 锚点：违反 AC-001（「出站/IMAP/HTTP 层抛出的结构化传输或协议异常（如代理握手失败、TCP 超时 `errno=110`、不可达 `errno=101`、TLS 握手失败、HTTP 5xx/429/401）通过同步引擎与 Worker 后，Worker 日志、`WorkerJob.last_error` 与 `accounts` 健康诊断 `last_connectivity_error` 均完整保留可读故障阶段、异常类型与结构化状态码/errno」）及测试策略（「真实 PG 下运行同步失败路径（`delta` / `reconcile` / `sync_account_folders` / `remote_push`）」）
- 位置：`tests/mail_core/test_t091_structured_failure_and_diagnostics.py:217-250`、`tests/mail_core/test_t091_structured_failure_and_diagnostics.py:343-496`（对照 `src/mail_core/worker/handlers.py:447-478`、`src/mail_core/sync/jobs.py:582-605`、`src/mail_core/security/redact.py:79-106`）
- 问题：
    1. PG 集成测试 `test_t091_pg_worker_log_job_health_and_api_preserve_structured_diagnostics` 仅覆盖了 `SYNC_FOLDER_DELTA`（`OSError(ENETUNREACH)`）、`RECONCILE_FOLDER`（`ProxyTunnelError` 502）与 `push_remote_operations`（`OSError(ENETUNREACH)`）。其中 `delta` 与 `reconcile` 均在内部捕获异常并以 `error=failure.format()` 字符串返回给 `handlers.py:_evaluate_result`（`handlers.py:221-230`）；而测试策略明确要求覆盖的 `sync_account_folders`（及 `sync_folder_metadata`）直接抛出异常走 `handlers.py:447-478` 的 `except Exception as exc:` 分支，在测试中完全缺席。
    2. HTTP 5xx/429/401（`ProviderHttpError` / `RateLimitedError` / `OAuthError` / HTTP 包装的 `URLError`）、TLS 握手失败（`ssl.SSLCertVerificationError`）与 TCP 超时（`ETIMEDOUT`）未经过同步引擎 + Worker（`handle_job`）全链路测试，单测（`:217-250`、`:544-586`）也只断言了 `StructuredFailure.from_exception(...)`，未验证 `safe_error()` / `fail_job()` / `handle_job()`。
    3. **该覆盖缺口掩盖了可复现的 AC-001 行为缺陷**：当 `sync_account_folders`（或 `sync_folder_metadata`）向 `handlers.py:471-477` 抛出 `ProviderHttpError` / `RateLimitedError` 并经 `reschedule_job(..., error=exc)` → `fail_job` → `_project_job_error(exc)` → `safe_error(exc)` 写入 `WorkerJob.last_error` 时，`safe_error` 仍走 `_format_provider_http_error(exc)`（`redact.py:79-102`）。实测传入 `urllib_json_request` 风格的 `ProviderHttpError("transport error: [Errno 101] Network is unreachable", status=None)`（带 `URLError(OSError(ENETUNREACH, ...))` cause 与 `phase=tcp_connect`）或 `RateLimitedError("rate limited", status=429, retry_after_seconds=17.0, body='{"error":"429"}')` 时，`fail_job` 分别写出 `"ProviderHttpError phase=tcp_connect: transport error: [Errno 101] Network is unreachable"` 与 `"RateLimitedError phase=http status=429: rate limited"`——丢弃了 `errno=` 与 `retry_after=` 结构化字段并保留原始消息文本，与 Worker 日志和 `last_connectivity_error`（使用 `StructuredFailure.format()`）发生分叉。
- 建议：在 `tests/mail_core/test_t091_structured_failure_and_diagnostics.py` 补齐 `SYNC_ACCOUNT_FOLDERS`（及 `SYNC_FOLDER_METADATA`）通过 `handle_job` 捕获 `ProviderHttpError`（含 `URLError(dial_err)`、HTTP 503/429/401）、`SSLCertVerificationError` 与 `TimeoutError(ETIMEDOUT)` 的 PG 集成测试及 `safe_error`/`fail_job` 单测，断言 Worker 日志、`WorkerJob.last_error` 与 `last_connectivity_error` 均保留白名单字段且不泄漏原始消息；同时配合实现侧将 `handlers.py:476` / `_project_job_error` 统一经 `StructuredFailure` 投影。

### t091_test_f002 - 日志脱敏测试传入 StructuredFailure 对象而非生产字符串参数，未覆盖 symbolic_code 在传参链路仍触发 code=[REDACTED]

- 严重度：important
- 锚点：违反 AC-001（「完整保留可读故障阶段、异常类型与结构化状态码/errno，不出现 `code=[REDACTED]`」）及测试策略（「覆盖 `redact` / `RedactingFilter` 对真实凭据/OAuth `code` 的拦截以及对结构化诊断 `errno` 的零误杀」）
- 位置：`tests/mail_core/test_t091_structured_failure_and_diagnostics.py:296`、`tests/mail_core/test_t091_structured_failure_and_diagnostics.py:343-496`（对照 `src/mail_core/sync/delta.py:563`、`src/mail_core/sync/reconcile.py:222`、`src/mail_core/sync/remote_push.py:562,667`、`src/mail_core/worker/handlers.py:228`、`src/mail_core/security/redact.py:118-123`）
- 问题：`test_t091_redaction_boundary_preserves_errno_and_masks_all_secrets:296` 调用 `logger.exception("worker failure projected=%s raw=%s", failure, ...)` 时传入的是 **`StructuredFailure` 实例**，而生产代码 `delta.py:563`、`reconcile.py:222`、`remote_push.py:562` 均把 `err_summary = failure.format()`（`str`）当作日志参数传入，`handlers.py:228` 与 `remote_push.py:667` 也把 `failure.format()`（`str`）传给 `reschedule_job` / `mark_remote_operation`。与此同时，新增测试仅构造了 `errno=` 异常，未覆盖 `StructuredFailure` 的 `symbolic_code` 字段（输出 `code=<val>`，见 `src/mail_core/mail/domain/failures.py:441-442`）。实测对带 `code="57P03"` 的异常（同 `tests/mail_core/test_safe_error_converge_a325.py:33-38` 的 `DbError`）先调用 `sf.format()` 再经过 `log.error("failed: %s", sf.format())` 或 `safe_error(sf.format())` 时，仍命中 `redact()` 的通用 `code=` 正则并输出 `"DbError status=503 code=[REDACTED]"`。
- 建议：在 `test_t091_redaction_boundary_preserves_errno_and_masks_all_secrets` 与 PG 集成测试中按生产真实传参方式补充 `str` 路径（`log.error(..., failure.format())` / `fail_job` / `mark_remote_operation`）及带 `symbolic_code` 的结构化故障回归用例，确保非凭据 `code=` 投影与自由文本 `?code=` / `"code":` 脱敏彻底分离。

### t091_test_f003 - 测试文件存在未导入类型符号 Any 及对 ImapProvider 私有方法 \_open_client 的 monkeypatch

- 严重度：minor
- 锚点：行为缺陷（测试代码静态类型解析失败风险及私有方法耦合）
- 位置：`tests/mail_core/test_t091_structured_failure_and_diagnostics.py:195,209`、`tests/mail_core/test_t091_structured_failure_and_diagnostics.py:442,472`
- 问题：
    1. `:442`（`_run_pg_reconcile_proxy_case`）与 `:472`（`_run_pg_remote_push_case`）签名使用了 `Any`，但文件顶部未导入 `from typing import Any`；当前仅依赖 `from __future__ import annotations` 延迟求值避免运行期报错，静态检查或 `typing.get_type_hints()` 会报 `NameError`。
    2. `:195` 与 `:209` 在 `test_t091_imap_and_http_provider_failures_preserve_phase_and_unwrapping` 中 monkeypatch 了私有方法 `prov._open_client`，而 `ImapProvider` 已暴露公开注入参数 `client_factory`（`_connect()` 生产异常收敛逻辑本身仍有触达，故非 blocking）。
- 建议：文件顶部补充 `from typing import Any`；将 `:195,209` 改为通过 `ImapProvider(..., client_factory=...)` 注入测试桩客户端。

## 结论

- 改测方向复核：无（相对 `diff_anchor` 未修改或删除任何既有测试文件，仅新增 `tests/mail_core/test_t091_structured_failure_and_diagnostics.py` 共 586 行 `< 600` 行，无 `.skip`/`.only`/`# type: ignore`/恒真断言/弱化断言；相关既有测试在单元测试 92 passed、24 PG-only skipped 与定向 PG 66 passed 中全部回归通过）。
- 本轮新发现：3 条（`important` 2 条、`minor` 1 条）。
- 未进表的提示：
    - `tests/mail_core/test_t091_structured_failure_and_diagnostics.py` 为 586 行，已接近 600 行单文件阈值，后续补齐 `sync_account_folders` / HTTP / TLS 用例建议按场景适度拆分或辅助函数化。
    - 上下文区已声明「有意不测」真实公网外部邮件服务商报错报文（由夹具替代），不作为缺口出 finding。
- 总体判断：存在 2 条未解决 `important` 测试覆盖与脱敏隔离缺陷（且 AC-001 判定 `TICK-VOID`），本轮测试评审判定 `FAIL`。
- 系统性 follow-up：无（当前缺口归属 `t091` 范围，经 `task.py list` 核对不存在重复 backlog 任务）。

### AC 复验方式

- AC-001：TICK-VOID，re_verified。经独立查证 `tests/mail_core/test_t091_structured_failure_and_diagnostics.py` 并运行 `fail_job`/`safe_error`/`RedactingFilter` 复现验证，缺失 `sync_account_folders` 与 HTTP 5xx/429/401/TLS 异常经 `handle_job` 落库全链路测试，且未测出 `ProviderHttpError`/`RateLimitedError` 写入 `WorkerJob.last_error` 丢弃 `errno`/`retry_after` 以及 `symbolic_code` 字符串传参仍触发 `code=[REDACTED]` 的缺陷。
- AC-002：TICK-VALID，re_verified。独立运行单元测试（92 passed, 24 skipped）与定向 PG 测试（`scripts/run-mail-core-tests.sh run --no-cov -k "test_t091 or ..."`, 66 passed），并核对 `test_t091_redaction_boundary_preserves_errno_and_masks_all_secrets`、`tests/mail_core/test_logging_trace_and_redact.py` 与 `tests/mail_core/test_redact_and_poll.py` 断言，确认 URL query `?code=`/`?token=`、JSON `"code":`/`"token":`、`Authorization`/`Cookie`/JWT/DSN 与异常栈凭据仍稳定替换为 `[REDACTED]` 且未泄漏至日志、`WorkerJob.last_error` 与账号诊断字段。
- AC-003：TICK-VALID，re_verified。独立运行并核对 `test_t091_single_source_classification_and_transient_helpers`、`tests/mail_core/test_account_health_state_machine.py` 与 `tests/mail_core/test_sync_backend_handler_isolation.py` 源码及执行结果，确认 `classify_failure` 与 `StructuredFailure` 保持单一事实来源，且 `ENOSPC`/`EMFILE`/`EACCES` 与自由文本错误均严格归为 `UNKNOWN` 而非 `TRANSPORT`。
- AC-004：TICK-VALID，trust_prior。本轮独立重跑并通过了 `test_cmd`（`.repo_template/tests` 389 passed, 1 skipped；`src/frontend` `npm test` 56 文件 597 passed + `npx tsc -b` + `vite build` + `openapi:check` + `css:check`；`src/desktop` `npm test` 12 项通过；`check_doc_sensitive.py docs --check` 35 文件 0 违规）、`blackbox_verify`（25 passed）、`export_openapi.py --check`（46 paths ok）与 66 条定向 PG 用例；后端全量 PG 套件（2271 用例）本轮未完整重跑，全量通过结论依赖实施侧留存摘要 `.scratch/test_runs/ac6f23e656d843b3a3590bd1894389e5/test_summary.json`（2269 passed，2 基线环境 skip）。
- AC-005：TICK-VALID，re_verified。独立核对 `docs/specs/mail_sync_and_storage.md`（front matter `tasks` 已登记 `t091` 并补入条目）、`docs/blueprint/conventions.md`、`docs/blueprint/testing.md` 与 `docs/pending/p095_gmail_imap_retry_proxy_and_background_pollution.md`（`status: "closed"`, `resolution: "transferred"`, `fix_ref: "t089,t090,t091"`）均已同步更新闭环。

coverage = 4 / 5

verdict: FAIL

## Round 2 (2026-11-26T02:49:14+08:00)

- diff_anchor：`917504e4e88bc804c133cac90481f1266fb82f7d`
- target：`git diff 917504e4e88bc804c133cac90481f1266fb82f7d`
- round：2
- reviewed_at：2026-11-26T02:49:14+08:00

reviewed_scope: b575fc4300398750

## Findings

本轮无新 finding（0 条）。

## 结论

- 前轮 finding 复核：
    - `t091_test_f001`：**已消除**。新增 `tests/mail_core/test_t091_pg_worker_diagnostics_integration.py` 补齐了 `fail_job` 对 `RateLimitedError`（保留 `retry_after=17.0` 与 `run_after`）和 HTTP 包装 `URLError(dial_err)`（保留 `errno=ENETUNREACH`）的单测断言（`:127-151`），以及 `SYNC_ACCOUNT_FOLDERS`、`SYNC_FOLDER_METADATA`、`SYNC_FOLDER_DELTA` 经真实 `handle_job` 落库 PostgreSQL 的全链路集成测试（`:245-414`），覆盖 HTTP 503/429/401、`OAuthError` 429、`PermanentAuthError`、真实 `ImapProvider -> DialedIMAP4_SSL -> dial_stream` 的 DNS `gaierror` / TCP `ETIMEDOUT` / TLS `SSLCertVerificationError` 到 `WorkerJob.last_error`、`Account.config["last_connectivity_error"]`、`list_accounts_app()` DTO 与日志输出；配合 `src/mail_core/worker/handlers.py:187,228,461,468,476` 与 `src/mail_core/sync/jobs.py:582-606` 统一传递并投影 `StructuredFailure`，消除原 `WorkerJob.last_error` 丢字段与漏文本分叉。
    - `t091_test_f002`：**已消除**。`src/mail_core/sync/delta.py:563`、`src/mail_core/sync/reconcile.py:222`、`src/mail_core/sync/remote_push.py:571`、`src/mail_core/worker/handlers.py:461` 及 `src/mail_core/security/redact.py:205-261` 已统一传递/保护 `StructuredFailure` 实例而不放松 `redact()` 自由文本脱敏；`tests/mail_core/test_t091_pg_worker_diagnostics_integration.py:75-151` 覆盖 `DbError(status=503, code="57P03")` 经 formatter-only、`RedactingFilter` 与 `format_safe_exception_chain` 完整保留 `code=57P03` 同时严格将 `?code=`、`Bearer`、`SECRET_DB` 等凭据脱敏为 `[REDACTED]`，且验证 `HTTPError` 状态码不重复输出为 `code=401`；`:416-524` 进一步在真实 PG 下验证 `push_remote_operations` 对 `IMAP4.abort`、部分批量 `TimeoutError` 与非结构化业务错误字符串的正确保留。
    - `t091_test_f003`：**已消除**。`tests/mail_core/test_t091_structured_failure_and_diagnostics.py:20` 已补充 `from typing import Any`（两份 `test_t091_*.py` 文件通过 `typing.get_type_hints()` 全量解析校验），且 `:193-220` 与 `tests/mail_core/test_t091_pg_worker_diagnostics_integration.py:441-489` 均改为通过 `ImapProvider(..., client_factory=...)` 公开参数注入并经公开方法 `list_folders()` / `push_remote_operations()` 触达生产逻辑，已清除对 `_open_client` 私有方法的 monkeypatch。
- 改测方向复核：无「迁就实现」的改测。`tests/mail_core/test_worker_loop.py:538-540` 整体删除了旧 `MagicMock` 用例 `test_handle_job_sanitizes_error_in_connectivity_failure` 并附迁移说明：该用例原断言 `handlers.py` 向 `record_connectivity_failure` 传入 `"ConnectionError"` 字符串并 mock 了 `record_connectivity_failure` 与 `reschedule_job`，因 `handlers.py:187` 契约改为传递强类型 `StructuredFailure` 而语义失效；其 `ConnectionError("connection failed: postgresql://user:my_secret_password@host/db?token=ya29.secret")` 脱敏与落库场景已在 `tests/mail_core/test_t091_pg_worker_diagnostics_integration.py:374-414` 通过真实 PG 与 `handle_job`（无 `record_connectivity_failure` / `reschedule_job` mock）等价并更严格地补回。其余既有测试无预期改写。
- 本轮新发现：0 条。
- 未进表的提示：
    - `tests/mail_core/test_t091_structured_failure_and_diagnostics.py` 共 596 行（`max_cc=6`），`tests/mail_core/test_t091_pg_worker_diagnostics_integration.py` 共 524 行（`max_cc=6`），均满足 `< 600` 行、`CC < 15`、零 `# type: ignore`、无无条件 `.skip` 与弱化断言。
    - 上下文区「有意不测」真实公网外部邮件服务商报错报文（由边界夹具替代），不计覆盖缺口。
- 总体判断：Round 1 全部 3 条 finding（含 2 条 `important` 阻断项）均已从实现与测试覆盖上真实消除且无新阻塞项，本轮测试评审判定 `PASS`。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。独立运行单元测试（93 passed, 15 PG-only skipped）与定向 PG 测试（`scripts/run-mail-core-tests.sh run --no-cov -k "test_t091 or test_worker_loop or test_t064 or test_remote_push"`, 56 passed），并查证 `tests/mail_core/test_t091_structured_failure_and_diagnostics.py` 与 `tests/mail_core/test_t091_pg_worker_diagnostics_integration.py`，确认 DNS/TCP(`ENETUNREACH`/`ETIMEDOUT`)/Proxy(`502`/`socks_reply=5`)/TLS(`SSLCertVerificationError`)/IMAP(`IMAP4.error`/`IMAP4.abort`/`PermanentAuthError`)/HTTP(`503`/`429`+`retry_after`/`401`/`URLError`) 及 `symbolic_code` 经 `sync_account_folders`/`sync_folder_metadata`/`delta`/`reconcile`/`remote_push` 与 Worker `handle_job` 后在日志、`WorkerJob.last_error`、`Account.config["last_connectivity_error"]` 与 `list_accounts_app()` DTO 完整保留且无 `code=[REDACTED]` 或裸 `"OSError"` 退化。
- AC-002：TICK-VALID，re_verified。独立运行并核对 `test_t091_redaction_boundary_preserves_errno_and_masks_all_secrets`、`test_t091_symbolic_code_logging_and_fail_job_decoupled_from_redact`、`test_t091_pg_sync_folder_metadata_conn_and_auth_boundary` 与 `tests/mail_core/test_logging_trace_and_redact.py` 等既有脱敏回归套件，确认 `?code=`/`?token=`、JSON `"code":`/`"token":`、`Authorization`/`Cookie`/JWT/DSN 与异常链凭据均替换为 `[REDACTED]` 且未泄漏至日志、`WorkerJob.last_error` 或账号诊断字段。
- AC-003：TICK-VALID，re_verified。独立运行并核对 `test_t091_single_source_classification_and_transient_helpers`、`test_t091_dns_http_disconnect_and_safe_reason_security_boundary`、`tests/mail_core/test_account_health_state_machine.py` 与 `tests/mail_core/test_sync_backend_handler_isolation.py`，确认 `classify_failure` 与 `StructuredFailure` 保持单一事实来源，`FailurePhase.OPERATION` 已移除、`from_dict` 拒绝伪造 `safe_reason` 尾注注入，且 `ENOSPC`/`EMFILE`/`EACCES` 与自由文本错误均严格不归入 `TRANSPORT`。
- AC-004：TICK-VALID，trust_prior。本轮独立重跑并通过了 `test_cmd`（`.repo_template/tests` 389 passed, 1 skipped；`src/frontend` `npm test` 56 文件 + `npx tsc -b` + `vite build` + `openapi:check` + `css:check`；`src/desktop` `npm test` 12 项通过；`check_doc_sensitive.py docs --check` 35 文件 0 违规）、`blackbox_verify`（25 passed）、`export_openapi.py --check`（46 paths ok）与 56 条定向 PG 用例；后端全量 PG 套件（2276 用例）未在本轮重跑，全量通过结论依赖实施侧留存摘要 `.scratch/test_runs/1b9784e4a85e46db921f92ac11513629/test_summary.json`（2274 passed，2 基线环境 skip）。
- AC-005：TICK-VALID，re_verified。独立核对 `docs/specs/mail_sync_and_storage.md`（已登记 `t091`）、`docs/blueprint/conventions.md`、`docs/blueprint/testing.md` 与 `docs/pending/p095_gmail_imap_retry_proxy_and_background_pollution.md`（`status: "closed"`, `resolution: "transferred"`, `fix_ref: "t089,t090,t091"`）均已同步更新闭环。

coverage = 4 / 5

verdict: PASS
