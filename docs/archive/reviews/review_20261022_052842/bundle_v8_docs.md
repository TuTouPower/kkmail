# Intensive Review — 视角8 文档规范与单一权威 (Documentation Standard)

## 视角摘要

三态划分（当前/规划/历史）、单一权威与引用、证据核验、会话残留清理、载体合规。

## Findings

- [High][98] docs/guides/deployment.md:19 — 部署手册 API 发布端口与真实 Compose 配置严重冲突 — 文档声称 `访问：http://127.0.0.1:8000 ... compose 只把 API（8000）和 PostgreSQL（主机 5433）发布到 127.0.0.1`；然而 `docker-compose.mail-core.yml` 第 71 行配置为 `- "127.0.0.1:37281:8000"`，且第 53 行显式设置 `MAIL_CORE_PUBLIC_BASE: "http://127.0.0.1:37281"`。用户按照部署手册访问 8000 端口将无法访问服务 — 核实权威端口，保持 `deployment.md` 与 `docker-compose.mail-core.yml` 完全一致。
- [Medium][95] docs/guides/security.md:71 — 反向代理受信 IP 配置说明内部自相矛盾 — 第 71 行要求 `设置可信的 FORWARDED_ALLOW_IPS`（环境变量形式）；但同文件第 9 行和 `deployment.md:30` 明确强调 `uvicorn 不读取环境变量，需在启动命令中传递命令行参数 --forwarded-allow-ips=<代理地址>`。同一指南内部自相矛盾，且环境变量形式在生产中无效 — 将第 71 行的环境变量写法修正为命令行参数。
- [Medium][95] docs/guides/troubleshooting.md:44 — 故障排查手册 SQL 改密示例遗漏自增 session_epoch 破坏会话吊销 — 排障手册给出直接修改密码 SQL：`UPDATE auth_credentials SET login_password_hash = '...', updated_at = NOW() WHERE id = 'default';`，遗漏了 `session_epoch = session_epoch + 1`，导致根据此命令重置密码后，原有已泄露或活跃的会话 Cookie 无法被吊销，破坏了 `auth_and_session.md` AC-004 的设计约定 — 在 SQL 中补充 `session_epoch = session_epoch + 1`。
- [Medium][95] src/mail_core/__init__.py:6 — 后端版本号与全局 VERSION 与发版指南漂移 — `VERSION` 文件和 `src/desktop/package.json` 为 `3.0.20`，而 `src/mail_core/__init__.py` 的 `__version__ = "0.1.0"`，导致 `/health` 接口对外报告错误版本号 `0.1.0`；且 `release.md` 发版步骤未包含后端版本的同步规则 — 统一版本号源并同步发版检查清单。
- [Medium][92] docs/handoff.md:9 — 交接文档记录严重滞后 — 记录的 `head_commit: 784f7a0494cf3e51247ffbe2e684073ae0315da1` 已滞后多个 commit，且未记录 t001、t002、t003 的合并完成状态 — 按 `AGENTS.md` 规则更新当前最新有效一节。
- [Low][98] docs/guides/desktop.md:46 — 桌面端使用指南相对链接失效 — 链接为 `[desktop/vendor/README.md](../desktop/vendor/README.md)`，自 `docs/guides/` 解析为 `docs/desktop/vendor/README.md`（文件不存在） — 修正为 `../../src/desktop/vendor/README.md`。
- [Low][98] src/frontend/README.md:9 — 前端自述文件命令与链接失效 — 第 9 行工作目录仍为 `cd frontend`（代码位于 `src/frontend`）；第 29 行链接 `../docs/deployment.md`、`../docs/api.md`、`../DESIGN.md` 全部断裂不存在 — 修正工作目录为 `cd src/frontend` 并更正文档相对路径。
- [Low][95] docs/guides/desktop.md:3 — 引用已废弃或重组的旧路径文档 — `desktop.md:3` 引用 `docs/mail-core-architecture.md`，`desktop.md:96` 引用 `docs/security.md`，`docker-compose.mail-core.yml:2` 与 `src/mail_core/__init__.py:3` 均直接指向旧路径 — 批量更正为 `docs/blueprint/architecture.md` 与 `docs/guides/security.md`。
- [Low][92] src/desktop/startup.js:100 — 桌面端代码遗留旧项目命名环境变量 — `startup.js:100`、`startup.test.js:16`、`main.js:20` 使用 `process.env.OUTLOOK_DESKTOP_PORT`，遗留旧项目命名 — 统一更名为 `KKMAIL_DESKTOP_PORT` 并保留向后兼容。
- [Low][90] docs/guides/security.md:79 — 备份命令跨文件全文复制破坏单一权威 — `security.md:79` 与 `upgrade.md:7` 均全文复制了备份执行命令及前置环境变量说明 — 统一将操作 Runbook 收拢至 `upgrade.md`，`security.md` 仅保留一句话摘要与相对链接。
