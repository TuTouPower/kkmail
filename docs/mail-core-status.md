# mail-core 实施进度（对照 architecture §16）

> 更新日期：2026-10-21（Asia/Shanghai）  
> 规格：[`mail-core-architecture.md`](./mail-core-architecture.md)  
> 运行：[`../mail_core/README.md`](../mail_core/README.md) · 桌面：[`mail-core-desktop.md`](./mail-core-desktop.md)  
> CI 冒烟：[`../scripts/run-mail-core-tests.sh`](../scripts/run-mail-core-tests.sh) · workflow 模板：[`ci/mail-core.workflow.yml`](./ci/mail-core.workflow.yml)（需 `workflow` scope 拷入 `.github/workflows/`）

Flask 默认产品路径（`web_outlook_app.py`）保持不变；下列均属 greenfield `mail_core/`。

---

## §16.1 推荐顺序 — 完成度

| # | 项 | 状态 | 备注 |
|---|---|---|---|
| 1 | 骨架：Compose / PG / Alembic / FastAPI / Worker | **done** | `docker-compose.mail-core.yml` 含 postgres+migrate+api+worker |
| 2 | 账号与密钥；桌面 PG 子进程 PoC | **partial** | Dict/env credential store；Electron `PostgresManager` stub（未捆二进制） |
| 3 | 统一模型与表 | **done** | messages/folders/locations/stats/checkpoints/… |
| 4 | IMAP 适配 + Dovecot 测试床 | **partial** | IMAP 适配+测试；Dovecot L3 床未铺齐 |
| 5 | Lease + fencing + SKIP LOCKED | **done** | 含多 worker 相关测试 |
| 6 | Gmail / Graph History/Delta | **partial** | 可注入 HTTP transport + 原始 JSON 解析 + 429/cursor invalid；无真实 OAuth |
| 7 | remote_operations 闭环与 reconcile | **partial** | 推送/调和骨架与测试；真实供应商写回未接 |
| 8 | MIME 有界归档 + 配额状态机 | **done** | 调度器 + 配额暂停/恢复 |
| 9 | Blob 加密、延迟 GC、备份 | **done** | KKMB blob + KKBK 备份独立密钥 + verify stub |
| 10 | FTS + trgm、线程、统一收件箱 API | **done** | `/api/mail/inbox` keyset、search、threading；`GET /messages/{id}` + `/body` |
| 11 | Outbox + SSE + Last-Event-ID | **done** | LISTEN 扇出 |
| 12 | 前端列表/阅读/乐观/沙箱 HTML | **partial** | `VITE_MAIL_CORE=1` 时 MessageList+MessageReader 走 mail-core；远程图关；无完整乐观写/发信 |
| 13 | 桌面打包 PG 二进制 / 启停 / 卸载保留 | **partial** | 生命周期 API + 数据目录约定；未打正式安装包 |
| 14 | CI 三层 | **partial** | `scripts/run-mail-core-tests.sh` + workflow 模板（L1）；L2/L3 未齐 |

---

## §16.2 里程碑验收

| 里程碑 | 门槛 | 状态 |
|---|---|---|
| M1 本地权威 | 仅本地 API 浏览已同步元数据 | **partial** — inbox + message/body API 可用；端到端账号同步演示仍依赖 stub/IMAP |
| M2 互斥 | 两 worker 不双写；旧 fencing 拒绝 | **done**（测试覆盖） |
| M3 归档 | 列表完成 ≠ 归档完成；硬配额可恢复 | **done** |
| M4 实时 | SSE + Last-Event-ID | **done**（服务端）；SPA 续传体验仍浅 |
| M5 安全 | 附件无路径穿越；远程图默认关；加密卷文档 | **done** |
| M6 桌面 | 无 Docker 可启 PG+API+Worker；卸载保留数据 | **partial** — 数据目录/启停 API 有；二进制与打包未完成 |

---

## 明确未做（§17）

发送 / 联系人 / 系统推送 / 旧 cache 兼容 / ES·Redis·Kafka / WebSocket / 字段级可搜索加密 / 公网裸暴露 API。

---

## 近期可继续的廉价项

1. 将 `docs/ci/mail-core.workflow.yml` 拷入 `.github/workflows/`（需具备 `workflow` scope 的推送凭据）  
2. Gmail/Graph：OAuth credential_ref → 真实 HTTP client  
3. 桌面捆绑 PG 官方二进制与安装包冒烟  
4. Dovecot fixture 床（IMAP L2）  
5. SPA SSE `Last-Event-ID` 续传与 optimistic 本地写回  
