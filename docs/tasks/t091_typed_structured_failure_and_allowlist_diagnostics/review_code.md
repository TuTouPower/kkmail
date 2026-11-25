# Task review t091（reviewer_focus: 代码）

- task：`t091_typed_structured_failure_and_allowlist_diagnostics`
- spec：`docs/tasks/t091_typed_structured_failure_and_allowlist_diagnostics/task.md`
- diff_anchor：`917504e4e88bc804c133cac90481f1266fb82f7d`
- target：`git diff 917504e4e88bc804c133cac90481f1266fb82f7d`
- round：1
- reviewed_at：2026-11-26T01:51:00+08:00

reviewed_scope: b9c7e0300cb8e4a5

## Findings

### t091_code_f001 - handlers 二次转文本并在 StructuredFailure.from_text 拒绝标准库异常名，导致 DNS/HTTP 断连退化为 ProviderError 且丢失 retry_after_s

- 严重度：important
- 锚点：AC-001（出站/IMAP/HTTP 层异常经同步引擎与 Worker 后在 `WorkerJob.last_error` 与 `last_connectivity_error` 保留阶段、异常类型与 errno）+ 行为缺陷（DNS 解析失败与 `OAuthError(429)` 退避延迟失真）
- 位置：`src/mail_core/worker/handlers.py:183-188`、`src/mail_core/worker/handlers.py:222-229`、`src/mail_core/worker/handlers.py:460-477`、`src/mail_core/mail/domain/failures.py:63,579-586`
- 问题：
    1. `src/mail_core/worker/handlers.py:187` 在 `_apply_account_health` 中已通过 `structured_failure_from_outcome(result)` 取得 `StructuredFailure` 对象，却传 `error=failure.format()`（纯字符串）给 `record_connectivity_failure`（尽管 `src/mail_core/accounts/health.py:152` 已支持直接接收 `StructuredFailure`），迫使 `health.py:180` 再次经 `StructuredFailure.from_text(...)` 解析。
    2. `src/mail_core/mail/domain/failures.py:584` 的 `_from_structured_type_text` 仅放行 `endswith(("Error", "Exception"))` 或 `_KNOWN_ERROR_NAMES` 中的 3 个名字；然而 `src/mail_core/net/dialer.py:90-92` 在 DNS 解析失败路径对 `socket.getaddrinfo` 附加 `FailurePhase.DNS` 抛出的标准库异常类名是 `gaierror`（小写 `error`），`src/mail_core/providers/oauth.py:674-675` 捕获的标准库异常类名是 `RemoteDisconnected` / `IncompleteRead`。实测 `StructuredFailure.from_text("gaierror phase=dns errno=2")` 与 `StructuredFailure.from_text("RemoteDisconnected")` 均被拒收并返回 `ProviderError`（`domain=unknown`），导致 `Account.config["last_connectivity_error"]` 与 `AccountOut.last_connectivity_error` 丢失 `phase=dns`、异常类型与 `errno`（且 `remote_push.py` 的 `is_transient_error(None, ...)` 对 `"gaierror phase=dns ..."` 误判为 `False`）。另 `failures.py:63` 从 `errno` 模块读取 `"EAI_AGAIN"` 为无效查找（Python 标准库中 `EAI_AGAIN` 位于 `socket` 模块而非 `errno` 模块）。
    3. `src/mail_core/worker/handlers.py:228` 在 `_evaluate_result` 处理 `provider_error` 时同样只传 `error=failure.format()` 字符串给 `reschedule_job`，使 `src/mail_core/sync/jobs.py:568-573` 的 `_retry_after_delay`（`isinstance(error, StructuredFailure)`）永不命中——当 `delta`/`reconcile` 因 `OAuthTokenClient` 429 抛出 `OAuthError(status=429, retry_after_seconds=...)` 走 `provider_error` 返回时，`retry_after_s` 被静默丢弃并退回默认指数退避；同时 `_project_job_error` 退回 `safe_error(str)` → `redact(str)`，将带 `symbolic_code` 的 `code=...` 再次误杀为 `code=[REDACTED]`。
    4. `src/mail_core/worker/handlers.py:460-477` 已在 `:460` 构建 `failure = StructuredFailure.from_exception(exc)` 并写日志，但 `:476` 仍将原始 `exc` 传给 `reschedule_job`；若 `exc` 为首行非 `{`/`[`/`<` 的 `ProviderHttpError`（如 `ProviderHttpError("upstream https://x?code=SECRET", status=502)`），日志与 `last_connectivity_error` 记 `"ProviderHttpError phase=http status=502"`，而 `WorkerJob.last_error` 却经 `_format_provider_http_error` 持久化含原始消息片段与 `[REDACTED]` 的不一致文本。
- 建议：
    1. 在 `src/mail_core/worker/handlers.py:187`、`228`、`476` 直接传入 `failure`（`StructuredFailure` 对象），并在 `src/mail_core/sync/jobs.py:507` 将 `reschedule_job` 类型注解同步为 `StructuredFailure | BaseException | str | None`，彻底消除“结构化对象→字符串→重解析”往返。
    2. 在 `src/mail_core/mail/domain/failures.py` 的 `_KNOWN_ERROR_NAMES` 中补充 `gaierror`、`RemoteDisconnected`、`IncompleteRead` 等标准库传输异常名，并在 `_classify_text_domain` 中将 `error_type == "gaierror"` 与 `phase is FailurePhase.DNS` 归类为 `FailureDomain.TRANSPORT`（移除无效 `errno.EAI_AGAIN` 引用）。

### t091_code_f002 - StructuredFailure 发射的 code=\<symbolic_code> 在日志格式化器、异常链与 HTTPError 路径仍触发 code=[REDACTED]

- 严重度：important
- 锚点：AC-001（日志与持久化诊断不出现 `code=[REDACTED]` 且保留结构化状态码）+ 行为缺陷（白名单结构化日志被通用 `code=` 正则二次覆写）
- 位置：`src/mail_core/mail/domain/failures.py:441-442,523-524`、`src/mail_core/logging_config.py:55-56`、`src/mail_core/security/redact.py:161-181`
- 问题：
    1. `src/mail_core/mail/domain/failures.py:523-524` 提取 `raw_code = getattr(exc, "code", None) or getattr(exc, "error_code", None)`，仅对 `errno_val` 做相等去重而未对 `http_status` 去重，对 `urllib.error.HTTPError`（标准库 `.status` 与 `.code` 同为状态码，如 `401`）会生成 `symbolic_code="401"`；且 `StructuredFailure.format()`（`:442`）以 `code={self.symbolic_code}` 发射，与 `redact.py:34` 拦截 `code=...` 的通用密钥正则共用完全相同的键名。
    2. `src/mail_core/logging_config.py:55-56`（`RedactingTraceFormatter.format` 对整行格式化后的日志再次执行 `redact(formatted, limit=None)`，而 `configure_logging()` 默认只给 `uvicorn.access` 加了 `RedactingFilter`，root handler 仅依赖 `RedactingTraceFormatter`）与 `src/mail_core/security/redact.py:181`（`format_safe_exception_chain` 对已使用 `StructuredFailure.from_exception(e).format()` 构造的白名单异常链全文再次执行 `redact(..., limit=None)`）都会将白名单输出中的 `code=<symbolic_code>`（例如 `HTTPError status=401 code=401`、`DbError status=503 code=57P03`、`code=ServiceUnavailable`）改写为 **`code=[REDACTED]`**（已实测复现）。
- 建议：
    1. 在 `src/mail_core/mail/domain/failures.py:523-524` 增加 `http_status` 去重（`raw_code` 等于 `http_status` 时不写入 `symbolic_code`）。
    2. 使白名单 `StructuredFailure` 投影与自由文本 `code=` 正则彻底解耦（例如对已结构化投影的日志/异常链片段不再整体回落 `redact()` 覆写白名单字段，或将结构化符号码输出键名与不可信自由文本密钥键名分离，同时保留 `test_safe_error_converge_a325` 契约）。

### t091_code_f003 - ImapProvider.apply_remote_operations 组异常包装与 remote_push 强转导致写回诊断退化为 ProviderError 且瞬态网络异常永久标败

- 严重度：important
- 锚点：AC-001（`providers/` 与 `remote_push` 贯通保留异常类型/阶段/errno）+ 行为缺陷（IMAP 写回会话中断无法退避重试）
- 位置：`src/mail_core/providers/imap.py:1824-1830`、`src/mail_core/providers/graph.py:433-440`、`src/mail_core/sync/remote_push.py:666-667,714`
- 问题：
    1. `src/mail_core/providers/imap.py:1824-1830` 在建连之后执行 `c.select` / `c.uid("STORE", ...)` / `c.uid("FETCH", ...)` / `c.uid("MOVE", ...)` 时，若遇 `TimeoutError`、`ConnectionResetError`、`OSError(ETIMEDOUT)` 或 `imaplib.IMAP4.abort`，会捕获并构造前缀字符串 `err_msg = f"IMAP operation group error: {safe_error(exc)}"` 写入 `RemoteOperationResult(success=False, error=err_msg)`（如 `"IMAP operation group error: TimeoutError"` 或 `"IMAP operation group error: IMAP4Abort phase=imap"`）。
    2. `src/mail_core/sync/remote_push.py:667` 对所有非空 `result.error` 无条件执行 `coerce_structured_failure(result.error).format()`；由于 `"IMAP operation group error: ..."`（以及 `graph.py:440` 的 `"Graph batch error: ..."`）带有前缀 prose，在 `StructuredFailure.from_text(...)` 中无法匹配任何结构化模式而全部退化为裸 **`"ProviderError"`**。
    3. 随后 `src/mail_core/sync/remote_push.py:714` 在 `caught_batch_exc is None` 时以 `err="ProviderError"` 调用 `is_transient_error(None, err)` 并得到 **`False`**，直接走 `:726` 将本应指数退避重试的瞬态 IMAP 会话超时/断连操作永久标记为 `RemoteOperationStatus.FAILED`，同时 `RemoteOperation.last_error` 丢失全部阶段、异常类型与 `errno` 诊断信息。此外，`:667` 也将 `"IMAP server does not support atomic MOVE/delete"`、`"UIDVALIDITY mismatch ..."`、`"STORE Seen failed"` 等非敏感业务诊断消息一并抹平为 `"ProviderError"`。
- 建议：
    1. 在 `src/mail_core/providers/imap.py:1824` 对传输/协议异常直接上抛给 `remote_push.py:559`（或为 `RemoteOperationResult` 增设结构化 `failure: StructuredFailure | None = None` / 直接传递 `StructuredFailure` 而不再拼接 `"IMAP operation group error: "` 前缀；`graph.py:440` 同理）。
    2. 在 `src/mail_core/sync/remote_push.py:667` 区分结构化失败与常规业务错误文本：结构化异常/投影直接保留 `StructuredFailure` 及其 `.format()`，已知非敏感操作结果文本通过 `redact(str(result.error))` 安全持久化，不再把明确操作错误一律抹成 `"ProviderError"`。

### t091_code_f004 - StructuredFailure.from_dict 对 safe_reason 使用非锚定前缀匹配，允许任意未脱敏敏感后缀绕过脱敏边界

- 严重度：important
- 锚点：AC-002（URL query `?code=` / JWT / 凭据秘密绝不进入日志、`WorkerJob.last_error` 或账号诊断字段）+ 行为缺陷（白名单边界安全绕过）
- 位置：`src/mail_core/mail/domain/failures.py:74-77,484-492`
- 问题：
    `src/mail_core/mail/domain/failures.py:489` 在 `StructuredFailure.from_dict` 校验 `safe_reason` 时使用了 `_HTTP_BANNER_RE.match(safe_reason) is not None`。由于 `_HTTP_BANNER_RE`（`:74-77`）仅以 `^HTTP...(?P<status>\d{3})\b` 锚定开头而无结尾 `$` 锚定，且 `from_dict` 原样保留 `safe_reason` 而未像 `_from_http_banner_text`（`:575`）那样归一化为 `f"HTTP {status}"`，实测向 `StructuredFailure.from_dict` / `coerce_structured_failure` / `safe_provider_summary` 传入 `{"domain": "transport", "error_type": "ProviderHttpError", "safe_reason": "HTTP 502 https://oauth/cb?code=SECRET_LEAK Authorization: Bearer eyJabc.def.ghi"}` 时会原封不动接受该 `safe_reason`，并经 `.format()` 绕过 `redact()` 直接输出未脱敏 URL `?code=` 与 Bearer JWT。
- 建议：
    在 `src/mail_core/mail/domain/failures.py:484-492` 收紧 `safe_reason` 白名单校验：对 HTTP banner 仅允许精确 `HTTP <status>`（例如使用完整匹配 `re.fullmatch(r"HTTP \d{3}", safe_reason)` 或经 `_from_http_banner_text` 归一化为 `f"HTTP {status}"`），绝不原样接收带任意尾部内容的字符串。

## 结论

- 本轮新发现：4 条（`important` 4 条，`critical` 0 条，`minor` 0 条）
- 未进表的提示：
    - 文件膨胀提示（达实现源码 400 / 800 行阈值且本 task 净增或新建即超阈值，按规则不进 finding 表，仅供后续拆分参考）：
        - `src/mail_core/providers/imap.py`：1944 行（净 +23，≥ 800）
        - `src/mail_core/sync/remote_push.py`：830 行（净 +20，≥ 800）
        - `src/mail_core/sync/jobs.py`：742 行（净 +18，≥ 400）
        - `src/mail_core/sync/delta.py`：701 行（净 +1，≥ 400）
        - `src/mail_core/providers/oauth.py`：692 行（净 +76，≥ 400）
        - `src/mail_core/mail/domain/failures.py`：653 行（新建，≥ 400）
        - `src/mail_core/net/dialer.py`：447 行（净 +18，≥ 400）
            （`src/mail_core/sync/engine.py` 783 行净 +0、`src/mail_core/worker/handlers.py` 478 行净 -3、`tests/mail_core/test_t091_structured_failure_and_diagnostics.py` 586 行 < 600，未触发膨胀提示。）
    - 圈复杂度（AST McCabe CC）提示：本 task 新增或分支净增的函数均未达到 CC ≥ 15。新增或增量后处于 `10 ≤ CC < 15` 建议后续拆分简化的函数为：`src/mail_core/mail/domain/failures.py:355` `_classify_text_domain`（14）、`src/mail_core/sync/context.py:162` `structured_failure_from_outcome`（14）、`src/mail_core/mail/domain/failures.py:320` `_classify_exception_domain`（13）、`src/mail_core/net/dialer.py:374` `dial_stream`（11→13）、`src/mail_core/providers/oauth.py:553` `_retry_delay_for_http_outcome`（12→13）、`src/mail_core/mail/domain/failures.py:389` `_parse_kv_fields`（10）、`src/mail_core/security/redact.py:67` `_is_raw_http_body`（10）、`src/mail_core/sync/context.py:122` `_classify_result_dict`（7→10）、`src/mail_core/mail/application/remote_ops.py:186` `mark_remote_operation`（9→10）、`src/mail_core/providers/oauth.py:588` `_retry_delay_for_transport_error`（5→10）、`src/mail_core/sync/remote_push.py:305` `is_rate_limited_error`（8→10）。既有未增分支的高复杂度函数（如 `apply_remote_operations` 85、`push_remote_operations` 86、`apply_delta_page` 52、`fetch_metadata_page` 50、`delta_changes` 47、`sync_folder_delta` 43、`sync_account_folders` 41 等）未在本次新增分支。
    - 死代码与细节提示：`src/mail_core/mail/domain/failures.py:43` 的 `FailurePhase.OPERATION` 在全仓 `src/` 与 `tests/` 中零引用；`src/mail_core/providers/imap.py:1904-1941` 的 `open_idle_session` 在 `_connect()` 之后执行 `capability`/`select` 抛出的非 `IMAP4.error` 异常（如 `TimeoutError`）未附加 `FailurePhase.IMAP`（不影响其 `TRANSPORT` 分类）。
    - 验证范围说明：按避免与并行 Test Reviewer 冲突约束，Code Reviewer 未执行 Docker PG 测试脚本 `scripts/run-mail-core-tests.sh run` 与 Playwright E2E `blackbox_verify`（及 `npm run build`）。
- 总体判断：虽然 `StructuredFailure` 模型、`net/dialer.py` 阶段附加与 `redact()` 核心规则在多数常规路径工作正常，但存在 4 处实现/安全边界阻塞缺陷（`t091_code_f001`–`t091_code_f004`），verdict 为 FAIL。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VOID，re_verified。实跑无 DB 单测（`test_t091_structured_failure_and_diagnostics.py` 等 9 个文件 79 passed, 11 skipped；`test_net_*` / `test_jobs_backoff.py` / `test_remote_ops_redact.py` 22 passed, 1 skipped）及源码与 Python 复现核查发现 3 处阻塞缺口：`handlers.py:187,228` 二次转文本与 `failures.py:584` 拒绝 `gaierror` / `RemoteDisconnected` 导致诊断退化为 `"ProviderError"` 且丢失 `retry_after_s`（`f001`）；`failures.py:442,523` 与 `logging_config.py:56` / `redact.py:181` 对 `code=...`（含 `HTTPError`）仍触发 `code=[REDACTED]`（`f002`）；`imap.py:1827` 与 `remote_push.py:667,714` 使写回组异常退化为 `"ProviderError"` 且永久标败（`f003`）。
- AC-002：TICK-VOID，re_verified。已核查 `redact.py` 的 `_PATTERNS` 未放宽且实跑单测拦截常规 URL/JSON/Authorization/Cookie/JWT/DSN 有效，但源码与 Python 复现发现 `StructuredFailure.from_dict`（`failures.py:489`）对 `safe_reason` 使用未锚定尾部的 `_HTTP_BANNER_RE.match`，允许 `"HTTP 502 https://...?code=SECRET_LEAK ..."` 绕过脱敏直接进入诊断投影（`f004`）。
- AC-003：TICK-VALID，re_verified。核查 `src/mail_core/sync/context.py:122-221`、`src/mail_core/mail/domain/failures.py:237-387` 并实跑无 DB 单测确认 `classify_failure` 以 `StructuredFailure` 为单一事实来源，且 `ENOSPC`/`EMFILE`/`EACCES` 等非网络 `OSError` 与自由文本错误均严格归类为 `FailureDomain.UNKNOWN`。
- AC-004：TICK-VALID，trust_prior。已独立重跑并全部通过：`.venv/bin/pytest .repo_template/tests -q -m contract`（389 passed, 1 skipped）、`PYTHONPATH=src .venv/bin/python scripts/export_openapi.py --check`（46 paths 匹配）、`scripts/check_doc_sensitive.py docs --check`（35 文件 0 违规）、`md_format.py --changed --check`、`git diff --check`、前端 `npm run openapi:check` / `npx tsc -b --noEmit` / `npm test`（56 文件 597 passed 及 `css:check`）与 `src/desktop` `npm test`（12 项通过，vendor PG 与 OAuth 按设计跳过）；全量 PG 套件 `scripts/run-mail-core-tests.sh run` 与 `blackbox_verify` E2E / `npm run build` 未由 Code Reviewer 执行，依赖并行 Test Reviewer 与实施验证。
- AC-005：TICK-VALID，re_verified。核查 `docs/specs/mail_sync_and_storage.md:4,28`（已登记 `t091` 并补充结构化故障与白名单投影规范）、`docs/blueprint/conventions.md:167`、`docs/blueprint/testing.md:84` 与 `docs/pending/p095_gmail_imap_retry_proxy_and_background_pollution.md:1-7,36`（`status: closed`, `resolution: transferred`, `fix_ref: t089,t090,t091`），且文档敏感信息与格式检查均通过。

coverage = 4 / 5

verdict: FAIL

## Round 2 (2026-11-26T02:48:05+08:00)

- target：`git diff 917504e4e88bc804c133cac90481f1266fb82f7d`
- reviewed_at：2026-11-26T02:48:05+08:00

reviewed_scope: b575fc4300398750

## Findings

### t091_code_f005 - 本次修复新增分支使 3 个既超 15 圈复杂度阈值的函数进一步增复杂度

- 严重度：minor
- 锚点：圈复杂度标准（函数 CC ≥ 15 且本 task 新增分支，非阻断）
- 位置：`src/mail_core/providers/imap.py:1582`（`apply_remote_operations`，AST CC 85→90）、`src/mail_core/providers/imap.py:1919`（`open_idle_session`，AST CC 15→17）、`src/mail_core/sync/remote_push.py:345`（`push_remote_operations`，AST CC 86→88）
- 问题：Round 2 修复在 `apply_remote_operations`、`open_idle_session` 与 `push_remote_operations` 内新增了异常判定及重试分支（且 `push_remote_operations` 行数增至 843 行、`imap.py` 增至 1966 行），使上述原本已达 CC ≥ 15 的函数继续增加分支复杂度，未引发可观测缺陷但降低可读性。
- 建议：后续可按阶段将 `ImapProvider.apply_remote_operations` 的异常分流与 `push_remote_operations` 的单条结算分支拆入独立私有辅助函数。

## 结论

- 前轮 finding 复核：
    - `t091_code_f001`：**已消除**。`src/mail_core/worker/handlers.py:187,228,468,476` 已改为直接传递 `StructuredFailure` 对象，`src/mail_core/sync/jobs.py:508,566-595` 已同步更新 `reschedule_job` / `fail_job` 签名与 `_retry_after_delay` / `_project_job_error` 对 `StructuredFailure` 及 `BaseException` 的直接处理；`src/mail_core/mail/domain/failures.py:137-148,407-444` 已移除无效 `errno.EAI_AGAIN` 引用、新增 `_NON_NETWORK_ERRNOS`、将 `gaierror` / `herror` / `RemoteDisconnected` / `IncompleteRead` / `BadStatusLine` 纳入 `_KNOWN_ERROR_NAMES` 与 `_TRANSPORT_EXACT_NAMES` 并使 `FailurePhase.DNS` 正确归入 `FailureDomain.TRANSPORT`。已通过 Python 实测复核 `gaierror`、`RemoteDisconnected` 往返与 `is_transient_error` 判定无退化。
    - `t091_code_f002`：**已消除**。`src/mail_core/mail/domain/failures.py:243-258,587-591,658` 的 `_coerce_symbolic_code` 新增 `http_status` 去重，使 `urllib.error.HTTPError(..., 401, ...)` 输出 `"HTTPError status=401"` 不再重复输出 `code=401`；`src/mail_core/security/redact.py:120-262` 与 `src/mail_core/logging_config.py:55-59` 新增 `_protect_structured_args`、`format_redacted_log_record` 与 `_SAFE_EXC_ATTR` 隔离机制，使 `StructuredFailure` 参数及 allowlist 异常链不再被二次 `redact()` 改写为 `code=[REDACTED]`。已实测覆盖 `RedactingTraceFormatter` 单用、`RedactingFilter` + `RedactingTraceFormatter` 合用、`RedactingFilter` + 普通 `Formatter` 及 `format_safe_exception_chain` 全部通过，且非结构化凭据仍严格替换 `[REDACTED]`。
    - `t091_code_f003`：**已消除**。`src/mail_core/providers/base.py:135-140` 为 `RemoteOperationResult` 新增 `failure: StructuredFailure | None = None`；`src/mail_core/providers/imap.py:1824-1845` 与 `src/mail_core/providers/graph.py:433-446` 移除 `"IMAP operation group error: ..."` / `"Graph batch error: ..."` 字符串拼接，在未有成功项的传输/IMAP 异常时直接上抛，在部分成功时附带结构化 `failure`；`src/mail_core/sync/remote_push.py:318-343,668-745` 新增 `_resolve_push_op_failure` 保留结构化 `failure` 与非敏感业务诊断文本（如 `"IMAP server does not support atomic MOVE/delete"`）。已通过 `ImapProvider.apply_remote_operations` 与 `_resolve_push_op_failure` 实测确认异常类型/阶段留存及瞬态重试无误。
    - `t091_code_f004`：**已消除**。`src/mail_core/mail/domain/failures.py:91,548` 将 `StructuredFailure.from_dict` 中的 `safe_reason` HTTP banner 校验改为 `_SAFE_HTTP_REASON_RE.fullmatch(safe_reason)`（`r"^HTTP [1-5]\d{2}$"`），实测确认 `"HTTP 502 https://oauth/cb?code=SECRET_LEAK ..."` 与 `"HTTP 502\n"` 均被清空为 `None`，合法 `"HTTP 502"` 正常保留。
- 本轮新发现：1 条（`minor` 1 条，`critical` 0 条，`important` 0 条）
- 未进表的提示：
    - 文件膨胀提示（达实现源码 400 / 800 行阈值且本 task 净增或新建即超阈值，按规则不进 finding 表）：
        - `src/mail_core/providers/imap.py`：1966 行（净 +45，≥ 800）
        - `src/mail_core/sync/remote_push.py`：843 行（净 +33，≥ 800）
        - `src/mail_core/sync/jobs.py`：743 行（净 +19，≥ 400）
        - `src/mail_core/mail/domain/failures.py`：721 行（新建，≥ 400）
        - `src/mail_core/sync/delta.py`：701 行（净 +1，≥ 400）
        - `src/mail_core/providers/oauth.py`：692 行（净 +76，≥ 400）
        - `src/mail_core/net/dialer.py`：447 行（净 +18，≥ 400）
            （`src/mail_core/sync/engine.py` 783 行净 +0、`src/mail_core/worker/handlers.py` 478 行净 -3、`src/mail_core/security/redact.py` 286 行 < 400、`tests/mail_core/test_t091_structured_failure_and_diagnostics.py` 596 行 < 600、`tests/mail_core/test_t091_pg_worker_diagnostics_integration.py` 524 行 < 600。）
    - 圈复杂度 `10 ≤ CC < 15` 新增或增量函数提示：`src/mail_core/sync/context.py:162` `structured_failure_from_outcome`（14）、`src/mail_core/mail/domain/failures.py:363` `_classify_exception_domain`（13）、`src/mail_core/net/dialer.py:374` `dial_stream`（11→13）、`src/mail_core/providers/oauth.py:553` `_retry_delay_for_http_outcome`（12→13）、`src/mail_core/mail/domain/failures.py:427` `_classify_text_domain`（12）、`src/mail_core/security/redact.py:205` `_protect_structured_args`（12）、`src/mail_core/mail/application/remote_ops.py:186` `mark_remote_operation`（9→11）、`src/mail_core/sync/remote_push.py:287` `is_rate_limited_error`（8→11）、`src/mail_core/sync/remote_push.py:318` `_resolve_push_op_failure`（11）、`src/mail_core/mail/domain/failures.py:447` `_parse_kv_fields`（10）、`src/mail_core/security/redact.py:69` `_is_raw_http_body`（10）、`src/mail_core/security/redact.py:236` `format_redacted_log_record`（10）、`src/mail_core/sync/context.py:122` `_classify_result_dict`（7→10）、`src/mail_core/providers/oauth.py:588` `_retry_delay_for_transport_error`（5→10）。（另 `FailurePhase.OPERATION` 死枚举成员已在 Round 2 中清理删除。）
    - 静态类型与范围外观察：`typing.get_type_hints()` 检查全部 17 个触及 `src/` 模块，所有新增与修改符号均解析通过（仅未触及既有符号 `src/mail_core/sync/remote_push.py` `get_unconverged_field_intents` 因 `Session` 前向引用报 `NameError`）；按避免与并行 Test Reviewer 冲突约束，未执行 Docker PG 脚本与 Playwright E2E，且 `.repo_template/scripts/md_format.py --changed --check` 仅因并行写出的 `review_test.md` 格式漂移而退出非零，本次改动文档单独执行 `--check` 格式一致。
- 总体判断：Round 1 的 4 条阻塞 finding（`t091_code_f001`–`t091_code_f004`）已全部从根因修复并经无 DB 单测、Python 复现与静态检查独立验证消除，无新增阻塞缺陷（仅 1 条 `minor` 复杂度提示 `t091_code_f005`），verdict 为 PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。核查 Round 2 修复后的 `src/mail_core/mail/domain/failures.py`、`src/mail_core/worker/handlers.py`、`src/mail_core/sync/jobs.py`、`src/mail_core/providers/{base,imap,graph,oauth}.py`、`src/mail_core/sync/{delta,reconcile,remote_push}.py`、`src/mail_core/security/redact.py` 与 `src/mail_core/logging_config.py`，并实跑无 DB 单测（13 个相关测试文件 93 passed, 15 skipped）及 Python 复现脚本验证 `gaierror`、`RemoteDisconnected`、`HTTPError(401)`、`DbError(code=57P03)` 与 IMAP 写回异常均完整保留 `phase`/`error_type`/`status`/`errno` 且不出现 `code=[REDACTED]` 或裸 `"OSError"` / `"ProviderError"` 退化。
- AC-002：TICK-VALID，re_verified。核查 `src/mail_core/security/redact.py`（`_PATTERNS` 未放宽且 `format_redacted_log_record` / `format_safe_exception_chain` 严格隔离结构化片段与自由文本脱敏）及 `src/mail_core/mail/domain/failures.py:548`（`_SAFE_HTTP_REASON_RE.fullmatch` 封闭 `from_dict` `safe_reason` 注入），实跑单测与 Python 复现确认 URL `?code=` / JSON / `Authorization` / `Cookie` / JWT / DSN 与异常栈凭据均完整替换为 `[REDACTED]`。
- AC-003：TICK-VALID，re_verified。核查 `src/mail_core/sync/context.py:122-221` 与 `src/mail_core/mail/domain/failures.py:271-444` 并实跑单测确认 `classify_failure` 以 `StructuredFailure` 为单一事实来源，`ENOSPC`/`EMFILE`/`EACCES` 等非网络 `OSError` 与自由文本错误均严格归类为 `FailureDomain.UNKNOWN`。
- AC-004：TICK-VALID，trust_prior。已独立重跑并通过 `.venv/bin/pytest .repo_template/tests -q -m contract`（389 passed, 1 skipped）、`PYTHONPATH=src .venv/bin/python scripts/export_openapi.py --check`（46 paths 匹配）、`npm --prefix src/frontend run openapi:check`、`scripts/check_doc_sensitive.py docs --check`（35 文件 0 违规）、改动文档 `md_format.py --check`、`git diff --check`、无 DB 单测（93 passed, 15 skipped）及 `typing.get_type_hints()` 复核（且前端 `src/frontend/` 与桌面端 `src/desktop/` 代码相对 Round 1 已实跑通过的 `vitest`/`tsc`/`css:check`/桌面单测零改动）；按不运行 Docker PG 脚本约束，全量 PG 套件 `scripts/run-mail-core-tests.sh run` 与 `blackbox_verify` E2E / `npm run build` 依赖并行 Test Reviewer 与实施侧验证。
- AC-005：TICK-VALID，re_verified。核查 `docs/specs/mail_sync_and_storage.md:4,28`（登记 `t091`）、`docs/blueprint/conventions.md:167`、`docs/blueprint/testing.md:84` 与 `docs/pending/p095_gmail_imap_retry_proxy_and_background_pollution.md:1-7,36`（`status: closed`, `resolution: transferred`, `fix_ref: t089,t090,t091`），且文档敏感信息与格式检查通过。

coverage = 4 / 5

verdict: PASS
