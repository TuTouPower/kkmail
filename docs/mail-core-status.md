# mail-core 实施进度（对照 architecture §16）

> 更新日期：2026-10-21（Asia/Shanghai）  
> 规格：[`mail-core-architecture.md`](./mail-core-architecture.md)  
> 运行 / 切换 / 桌面：[`../mail_core/README.md`](../mail_core/README.md) · [`mail-core-cutover.md`](./mail-core-cutover.md) · [`mail-core-desktop.md`](./mail-core-desktop.md)  
> CI 脚本：`scripts/run-mail-core-tests.sh` · chaos · backup drill · fetch-pg-binaries  
> Workflow 模板：[`ci/mail-core.workflow.yml`](./ci/mail-core.workflow.yml)（`.github` 推送仍需 `workflow` scope）

Flask 登录/发信壳层保留。无真实云 OAuth、无发信。

---

## §16.1 推荐顺序 — 完成度

| # | 项 | 状态 | 备注 |
|---|---|---|---|
| 1 | 骨架 | **done** | |
| 2 | 账号密钥 / 桌面 PG | **partial** | OAuth refresh；Linux vendor fetch + start/stop；`npm run pack:linux` 可打入 `resources/pgsql`；mac/win download-at-build；无公证安装包 |
| 3 | 统一模型 | **done** | |
| 4 | IMAP + Dovecot L2 | **partial** | |
| 5 | Lease / fencing | **done** | + chaos reclaim |
| 6 | Gmail / Graph delta | **partial** | parsers + OAuth transport；无真租户 |
| 7 | remote_operations | **partial→improved** | Memory/IMAP 真实写回 set_read/flag/move/trash；Gmail/Graph 可注入 transport mocks；未接 UI 乐观写 |
| 8 | 归档 / 配额 | **done** | |
| 9 | Blob / 备份 | **done** | + re-wrap / backup drill |
| 10 | FTS / inbox / message API | **done** | |
| 11 | Outbox + SSE | **done** | |
| 12 | 前端 list/reader | **partial** | cutover 默认优先 mail-core；Flask 回退 |
| 13 | 桌面打包 | **partial** | electron-builder linux `--dir` scaffold + optional pgsql；CI soft-ok |
| 14 | CI 三层 | **partial** | |

---

## §16.2 里程碑

| 里程碑 | 状态 |
|---|---|
| M1 | **partial** |
| M2 | **done** |
| M3 | **done** |
| M4 | **done**（服务端） |
| M5 | **done** |
| M6 | **partial**（Linux vendor+pack scaffold；mac/win/正式发行未齐） |

---

## §17 仍不做

发送 / 联系人 / 系统推送 / 旧 cache 兼容 / ES·Redis·Kafka / WebSocket / 字段级可搜索加密 / 公网裸暴露 / 真云 OAuth。
