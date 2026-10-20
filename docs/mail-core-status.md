# mail-core 实施进度（对照 architecture §16）

> 更新日期：2026-10-21（Asia/Shanghai）  
> 规格：[`mail-core-architecture.md`](./mail-core-architecture.md)  
> 运行：[`../mail_core/README.md`](../mail_core/README.md) · 桌面：[`mail-core-desktop.md`](./mail-core-desktop.md) · 切换：[`mail-core-cutover.md`](./mail-core-cutover.md)  
> CI：[`../scripts/run-mail-core-tests.sh`](../scripts/run-mail-core-tests.sh) · workflow 模板：[`ci/mail-core.workflow.yml`](./ci/mail-core.workflow.yml)（含 imap-l2；需 `workflow` scope 拷入 `.github/workflows/`）

Flask 登录/发信壳层保留；mail-core 为邮件权威。

---

## §16.1 推荐顺序 — 完成度

| # | 项 | 状态 | 备注 |
|---|---|---|---|
| 1 | 骨架：Compose / PG / Alembic / FastAPI / Worker | **done** | postgres+migrate+api+worker；Dovecot `imap` 服务 |
| 2 | 账号与密钥；桌面 PG 子进程 PoC | **partial** | OAuth JSON credential_ref + keyring/env；vendor PG fetch 脚本；未打正式安装包 |
| 3 | 统一模型与表 | **done** | |
| 4 | IMAP 适配 + Dovecot 测试床 | **partial** | L2 Dovecot fixture + live 测试；CI 模板含 imap-l2 |
| 5 | Lease + fencing + SKIP LOCKED | **done** | |
| 6 | Gmail / Graph History/Delta | **partial** | OAuth refresh + Bearer transport + parsers；真实租户联调仍待 |
| 7 | remote_operations 闭环与 reconcile | **partial** | |
| 8 | MIME 有界归档 + 配额状态机 | **done** | |
| 9 | Blob 加密、延迟 GC、备份 | **done** | |
| 10 | FTS + trgm、线程、统一收件箱 API | **done** | + message/body API |
| 11 | Outbox + SSE + Last-Event-ID | **done** | |
| 12 | 前端列表/阅读/乐观/沙箱 HTML | **partial** | cutover 开关下 list/reader 优先 mail-core；Flask 回退；无发信 |
| 13 | 桌面打包 PG 二进制 / 启停 / 卸载保留 | **partial** | vendor 路径 + fetch 脚本；start/stop 有二进制时可用 |
| 14 | CI 三层 | **partial** | L1 脚本 + 模板；L3 未齐 |

---

## §16.2 里程碑验收

| 里程碑 | 状态 |
|---|---|
| M1 本地权威 | **partial** — API/list/reader 可切 mail-core |
| M2 互斥 | **done** |
| M3 归档 | **done** |
| M4 实时 | **done**（服务端） |
| M5 安全 | **done** |
| M6 桌面 | **partial** |

---

## 明确未做（§17）

发送 / 联系人 / 系统推送 / 旧 cache 兼容 / ES·Redis·Kafka / WebSocket / 字段级可搜索加密 / 公网裸暴露 API。

---

## Cutover 开关

- `MAIL_CORE_DEFAULT=1`（Flask 注入）或 `VITE_MAIL_CORE_DEFAULT=1` / `VITE_MAIL_CORE=1`
- `VITE_MAIL_CORE=0` 强制 Flask 列表/阅读
