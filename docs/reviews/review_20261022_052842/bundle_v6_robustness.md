# Intensive Review — 视角6 健壮性与可观测性 (Robustness & Observability)

## 视角摘要

错误处理、重试与回滚、日志上下文与脱敏、破坏性运维脚本防御、异常降级。

## Findings

- [Critical][99] Dockerfile.mail-core:25 — 生产容器启动模式未装配日志脱敏格式化器击穿安全基线 — 生产镜像 CMD 为 `["uvicorn", "mail_core.api.app:app", "--host", "0.0.0.0", "--port", "8000"]`，绕过了 `__main__.py`；而 `src/mail_core/api/app.py` 的 lifespan 未调用 `configure_logging()`。导致生产容器运行时 root logger 缺失 `RedactingTraceFormatter`，无法自动过滤日志与异常堆栈中的敏感凭据，也缺失 `trace_id` 格式化，击穿 `conventions.md` 安全基线 — 在 `app.py` 的 `lifespan` 初始化时显式调用 `configure_logging(service_name="mail-core-api")`。
- [High][98] scripts/mail-core-chaos-lease.sh:16 — Chaos 破坏性脚本数据库前置检查通配符包含可穿透到生产库 — 第 16 行判断逻辑为 `if [[ "$DB_NAME" != *test* && "$DB_NAME" != *chaos* ]]`。若生产环境数据库名称为 `production_latest`、`attest_db`、`contest` 等带有 `test` 子串的库名，前置检查将被完全绕过，随后直接对目标数据库执行 `alembic upgrade head` 与并发租约抢占注入破坏数据 — 将子串通配改为严格的精确匹配或前缀/后缀正则约束（如 `^.*_test$` / `^test_.*$`）。
- [High][100] scripts/migrate_from_legacy_db.py:68 — 数据库迁移脚本硬编码默认解密密钥 — 第 68 行 `legacy_secret = os.environ.get("LEGACY_SECRET_KEY", "[REDACTED]")`，自设硬编码默认 secret，严重违反全局规范与 conventions.md「不预设弱口令或示例密钥，缺失时拒绝启动」— 移除默认值，若环境变量未提供则直接报错退出。
- [Medium][92] scripts/run-mail-core-tests.sh:11 — 测试执行脚本缺失目标数据库名安全性前置检查 — 脚本未对数据库名做任何包含 `test` 的校验即执行 `alembic upgrade head` 和 `pytest tests`，若误传入带有生产连接的环境变量将直接冲刷业务表 — 补充非生产库名防御门禁。
- [Medium][92] src/frontend/src/hooks/useMailCoreRealtime.ts:151 — SSE 遭遇 401/403 认证失效后未同步派发前端登出事件 — `subscribeMailCoreStream` 收到 401/403 时调用 `onUnauthorized` 并终止重连，但 `useMailCoreRealtime` 仅输出 `console.warn`，未派发 `UNAUTHORIZED_EVENT`。此时界面仍保持在登录态，但实时同步通道已被静默永久关闭，用户无法感知凭据失效 — 在 `onUnauthorized` 回调中触发 `window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))`，联动触发登录页展示。
- [Medium][90] src/desktop/postgresManager.js:131 — 数据目录及其邮件存储目录采用 0755 权限存在多用户泄露风险 — `ensureDirs()` 创建 `p.dataRoot`、`p.blobs`、`p.backups` 时传入 `mode: 0o755`，`initIfNeeded()` 创建 `p.pgData` 未声明 mode。当运行环境为共享机器且 fallback 至 `~/.kkmail` 或 `[REDACTED]<uid>` 时，同机其他本地用户可直接遍历读取所有邮件附件与备份文件 — 统一使用 `0o700` 创建 `dataRoot`、`pgData`、`blobs` 与 `backups` 目录。
- [Medium][90] src/mail_core/worker/handlers.py:190 — 同步异常处理中静默吞掉账户状态更新异常 — 更新 `status_label` 与 `sync_enabled` 的代码块中使用 `except Exception: pass`，发生 DB 异常时无任何日志，且会导致后续调用 `fail_job` 时 session 处于失效状态引发未预期的异常 — 记录 warning 日志并在失败时显式回滚事务。
- [Low][90] src/frontend/src/components/SettingsModal.tsx:36 — 后台 Query 静默刷新直接覆盖用户正在编辑的未保存表单数据 — `useEffect` 监听 `settingsQuery.data`，一旦数据变动即通过 `setTimezone`、`setTimeoutSeconds` 覆盖 state。若用户正在编辑时触发了后台异步刷新，输入框内容将被强制回退 — 仅在表单初始挂载或字段处于 pristine 状态时回填，输入框 dirty 状态下禁止自动覆盖。
- [Low][85] src/desktop/startup.js:117 — freePort 探测后立即关闭套接字存在 TOCTOU 竞态漏洞 — `freePort` 在端口侦听成功后立即执行 `srv.close()`，在 `mail-core` 正式 bind 之前端口处于释放状态，存在被同机并发进程抢占的可能 — 考虑支持让后端子进程直接绑定 port 0，并在启动后通过 stdout/IPC 向主进程回传实际分配的端口。
