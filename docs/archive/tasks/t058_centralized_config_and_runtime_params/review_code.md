# Task review t058（reviewer_focus: 代码）

## Round 1 (2026-10-27T20:20:00+08:00)

- reviewed_at: 2026-10-27T20:20:00+08:00
- reviewed_scope: 470e3f905ef2b928

代码复审 PASS。
实现严格遵照 spec 契约区与架构设计：
1. `src/mail_core/config/`：建立集中式配置模型 `MailCoreConfig` 与加载器 `load_config`，定义完整类型化默认值，提供单例 `get_config()` 与测试重置 `reset_config()`；`validate()` 严格校验端口范围、槽位非负与逻辑递增、存储字节限制及有效正浮点数。
2. `src/mail_core/providers/connection_slots.py`：外联连接槽位上限 `TOTAL_SLOTS`、后台起始槽位 `BACKGROUND_START_SLOT` 及退避延迟 `CAPACITY_RETRY_SECONDS` 成功抽离至集中配置，并通过 `__getattr__` 保持对现有常量的兼容性。
3. `src/mail_core/blobs/archive.py`：MIME 体积上限 `max_mime_bytes`、附件上限 `max_attachment_bytes` 及归档窗口 `archive_recent_days` 统一从集中配置读取，支持动态覆盖。
4. `src/mail_core/worker/main.py`：Worker 领单批次 `worker_claim_batch`、回收周期 `worker_reclaim_interval_s` 及收件箱巡检周期无缝接入集中配置。
5. `src/mail_core/__main__.py`：在应用启动首帧触发 `get_config()` 校验，非法配置直接拦截报错，阻止异常参数进入业务运行。
6. `src/desktop/startup.js`：`SIDECAR_CONFIG_KEYS` 严格补齐新增环境变量白名单，保证 Electron 桌面端正常向 Sidecar 透传配置。
7. 文档与模板：`config/.env.example` 与 `src/mail_core/README.md` 完整按模块重构，清晰展现全量受支持环境变量。

零 finding。

verdict: PASS
