---
tid: "t091"
slug: "typed_structured_failure_and_allowlist_diagnostics"
title: "强类型结构化故障模型与白名单诊断投影重构"
status: "done"
branch: "t091_typed_structured_failure_and_allowlist_diagnostics"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "917504e4e88bc804c133cac90481f1266fb82f7d"
spec_source_sha: "b78e0e7724517dc1e101bbabb10ebe135dc75680"
depends_on: "t090"
conflicts_with: ""
note: "来源 p095；StructuredFailure 贯通传输/Worker/健康态，消除正则误脱敏与二次剥离"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- Round 1 修复了全部 4 条 Code blocking finding（`t091_code_f001`–`f004`）与 3 条 Test finding（`t091_test_f001`–`f003`）：消除 `handlers.py` 到 `health.py`/`jobs.py` 的字符串往返；补充 `gaierror`/`RemoteDisconnected`/`IncompleteRead`/`BadStatusLine`/`IMAP4Abort` 支持；去重 `http_status` 与 `symbolic_code` 并将 `StructuredFailure` 参数及异常链投影从日志二次 `redact()` 中哨兵隔离；移除 `apply_remote_operations` 组异常 prose 包装及 `remote_push.py` 业务诊断抹平；收紧 `from_dict` `safe_reason` 为严格正则全匹配 `^HTTP [1-5]\d{2}$`；删除未使用的 `FailurePhase.OPERATION` 与 `_exception_status_code`。
- 因 `handlers.py:187` 已直接向 `record_connectivity_failure` 传递强类型 `StructuredFailure`（符合 `t091_code_f001` 与开发铁律“零兼容性负担”），`tests/mail_core/test_worker_loop.py` 中旧的 mock 字符串断言用例 `test_handle_job_sanitizes_error_in_connectivity_failure` 已整体删除，并由 `tests/mail_core/test_t091_pg_worker_diagnostics_integration.py` 中无 mock 的真实 PG 链路用例等价替代（`ConnectionError("postgresql://...my_secret_password...")` 经 `SYNC_FOLDER_METADATA` -> `handle_job` -> `WorkerJob`/`Account.config`）。
- 测试文件拆分为 `tests/mail_core/test_t091_structured_failure_and_diagnostics.py`（596 行）与 `tests/mail_core/test_t091_pg_worker_diagnostics_integration.py`（524 行），均 `< 600` 行且 AST `CC < 15`、零 `# type: ignore`。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-26T01:52:16+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t091_code_f001|important|已修|`handlers.py` 直接传入 `StructuredFailure` 至 `health.py`/`jobs.py`，`failures.py` 支持 `gaierror`/`RemoteDisconnected`/`IncompleteRead`/`BadStatusLine` 及 DNS `phase=dns` 与去除无效 `errno.EAI_AGAIN`|`src/mail_core/worker/handlers.py:187,228,468,476`、`src/mail_core/mail/domain/failures.py:137-146,243-259,405-443`|
|t091_code_f002|important|已修|`symbolic_code` 对 `http_status` 去重；`logging_config.py` 与 `redact.py` 引入 `format_redacted_log_record` 哨兵保护及 `_SAFE_EXC_ATTR` 免二次脱敏覆写 `code=`；`delta`/`reconcile`/`remote_push`/`remote_ops` 直接传递 `StructuredFailure`|`src/mail_core/mail/domain/failures.py:213-225`、`src/mail_core/security/redact.py:121-252`、`src/mail_core/logging_config.py:55`、`src/mail_core/sync/delta.py:563`、`src/mail_core/sync/reconcile.py:222`、`src/mail_core/mail/application/remote_ops.py:224-229`|
|t091_code_f003|important|已修|`RemoteOperationResult` 增设 typed `failure` 字段；`ImapProvider`/`GraphProvider` 移除 group/batch prose 前缀并对未成功批次直接上抛；`remote_push.py` 统一基于 `StructuredFailure` 判定瞬态/限流并保留非结构化业务错误|`src/mail_core/providers/base.py:138`、`src/mail_core/providers/imap.py:1824-1843`、`src/mail_core/providers/graph.py:433-446`、`src/mail_core/sync/remote_push.py:251-355,670-740`|
|t091_code_f004|important|已修|`StructuredFailure.from_dict` 使用严格全匹配正则 `^HTTP [1-5]\d{2}$` 过滤 `safe_reason`，彻底阻断 `?code=`/Bearer 尾部注入|`src/mail_core/mail/domain/failures.py:82,540-548`|
|t091_test_f001|important|已修|新增 `test_t091_pg_worker_diagnostics_integration.py` 覆盖 `SYNC_ACCOUNT_FOLDERS`/`SYNC_FOLDER_METADATA`/`fail_job` 对 HTTP 503/429/401、`Retry-After`、DNS `gaierror`、`ETIMEDOUT`、`SSLCertVerificationError` 全链路验证|`tests/mail_core/test_t091_pg_worker_diagnostics_integration.py:130-420`|
|t091_test_f002|important|已修|补充生产 `StructuredFailure` 日志/异常链与 `DbError code=57P03`/`HTTPError 401` 去重、多路径不破坏 `?code=`/`Bearer` 脱敏及 `gaierror`/`RemoteDisconnected` 回归用例|`tests/mail_core/test_t091_pg_worker_diagnostics_integration.py:72-182`|
|t091_test_f003|minor|已修|导入 `from typing import Any` 并将 `ImapProvider` 测试桩注入替换为公开参数 `client_factory` 调用 `list_folders()`|`tests/mail_core/test_t091_structured_failure_and_diagnostics.py:18,185-220`|

### Round 2 (2026-11-26T02:49:14+08:00)

- Round 2 `review_test.md` 零 finding；`review_code.md` 无新增 blocking finding，仅余 1 条非阻断 `minor` 复杂度提示。

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t091_code_f005|minor|遗留|既有高复杂度函数在本 task 增量分支（不阻断 AC，转入待办统一拆分）|p098|

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：`./scripts/run-mail-core-tests.sh run` 全量 PG 套件 `2274 passed, 2 skipped`（覆盖率 `86%`）；`.venv/bin/pytest .repo_template/tests -q -m contract` `389 passed, 1 skipped`；`npm --prefix src/frontend test` `56 files / 597 passed`（含 `openapi:check`、`css:check`、`tsc -b`、`vite build`）；`npm --prefix src/desktop test` `22 passed`（4 个测试文件，vendor PG 与 OAuth 按设计跳过）；`scripts/export_openapi.py --check`（46 paths 匹配）；`scripts/check_doc_sensitive.py docs --check`（35 文件 0 违规）
- 黑盒：`npm --prefix src/frontend run test:e2e` `25 passed (32.8s)`
- review：Round 2 独立审查双通过（`review_code.md` `verdict: PASS`，0 blocking / 1 minor `t091_code_f005`→`p098`；`review_test.md` `verdict: PASS`，0 finding；`reviewed_scope: b575fc4300398750`、`ac_review=ok`、`review-status` `overall=PASS`）
- AC 判定：见 `task.md` 行内打勾（`AC-001` ~ `AC-005` 全部 `- [x]`）

### 结果摘要

- 新增 `src/mail_core/mail/domain/failures.py` 定义 `StructuredFailure` 与受控 `FailurePhase`（`dns` / `proxy_connect` / `tcp_connect` / `tls` / `auth` / `http` / `imap`）作为诊断投影与 `sync/context.py` 故障域分类单一事实来源，彻底消除 `OSError code=[REDACTED]` 与二次摘要剥离问题；同时保持 `security/redact.py` 自由文本凭据脱敏零退化并通过哨兵隔离与 `_SAFE_EXC_ATTR` / `_SAFE_HTTP_REASON_RE.fullmatch` 阻断 `code=` 误杀及尾注注入。
- 贯通 `net/dialer.py`、`net/tunnel.py`、`providers/{base,http,imap,oauth,graph}.py`、`sync/{delta,reconcile,remote_push,jobs}.py`、`worker/handlers.py`、`accounts/health.py`、`mail/application/remote_ops.py` 与 `logging_config.py`，端到端保留结构化阶段、`http_status`、`errno`、`socks_reply` 与 `retry_after_s`。
- 遗留非阻断项见 `p098`（拆分 3 个既有高复杂度函数分支）。

### 长期文档闭环

- `docs/specs/mail_sync_and_storage.md`（front matter `tasks` 已登记 `t091` 并补入强类型结构化故障与白名单诊断投影规范）
- `docs/blueprint/conventions.md` 与 `docs/blueprint/testing.md` 已同步更新白名单诊断分离契约与门禁说明
- 转办来源待办 `docs/pending/p095_gmail_imap_retry_proxy_and_background_pollution.md`（`status: closed`, `resolution: transferred`, `fix_ref: t089,t090,t091`）完整闭环；Round 2 次要遗留登记至 `docs/pending/p098_t091_code_minor_complexity_followup.md`
