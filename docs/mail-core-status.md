# mail-core 实施进度（对照 architecture §16）

> 更新日期：2026-10-21（Asia/Shanghai）  
> 规格：[`mail-core-architecture.md`](./mail-core-architecture.md)  
> 运行 / 切换：[`../mail_core/README.md`](../mail_core/README.md) · [`mail-core-cutover.md`](./mail-core-cutover.md) · [`mail-core-desktop.md`](./mail-core-desktop.md)  
> CI：[`../scripts/run-mail-core-tests.sh`](../scripts/run-mail-core-tests.sh) · chaos：[`../scripts/mail-core-chaos-lease.sh`](../scripts/mail-core-chaos-lease.sh) · backup drill：[`../scripts/mail-core-backup-restore-drill.sh`](../scripts/mail-core-backup-restore-drill.sh)  
> Workflow 模板：[`ci/mail-core.workflow.yml`](./ci/mail-core.workflow.yml) — **推送到 `.github/workflows/` 仍需具备 `workflow` scope 的凭据**（当前 OAuth App 被拒）

Flask 登录/发信壳层保留；mail-core 为邮件权威。未对真实 Microsoft/Google 租户做 OAuth（无注入密钥）。

---

## §16.1 推荐顺序 — 完成度

| # | 项 | 状态 | 备注 |
|---|---|---|---|
| 1 | 骨架 Compose / PG / Alembic / FastAPI / Worker | **done** | + Dovecot `imap` |
| 2 | 账号与密钥；桌面 PG | **partial** | OAuth refresh + keyring stub；Linux vendor 二进制可 `fetch-pg-binaries.sh` 拉取并 start/stop 冒烟；mac/win = download-at-build；未打安装包 |
| 3 | 统一模型与表 | **done** | |
| 4 | IMAP + Dovecot L2 | **partial** | fixture + live 测试；CI 模板含 imap-l2 |
| 5 | Lease + fencing + SKIP LOCKED | **done** | + chaos：杀 worker 后 lease steal / stale claim reclaim |
| 6 | Gmail / Graph History/Delta | **partial** | OAuth transport + parsers；无真实租户 |
| 7 | remote_operations / reconcile | **partial** | |
| 8 | MIME 归档 + 配额 | **done** | |
| 9 | Blob 加密 / GC / 备份 | **done** | + key re-wrap 轮换；加密备份 verify drill |
| 10 | FTS / 线程 / inbox / message API | **done** | |
| 11 | Outbox + SSE | **done** | |
| 12 | 前端 list/reader | **partial** | `MAIL_CORE_DEFAULT` / compose 默认优先 mail-core；Flask 回退；无发信乐观写 |
| 13 | 桌面打包 | **partial** | vendor 路径 + Linux fetch；无正式安装包 |
| 14 | CI 三层 | **partial** | L1 脚本 + 模板；`.github` 推送被 scope 挡住；L3 仅 lease chaos 测试 |

---

## §16.2 里程碑

| 里程碑 | 状态 |
|---|---|
| M1 本地权威 | **partial** |
| M2 互斥 | **done**（含 chaos reclaim） |
| M3 归档 | **done** |
| M4 实时 | **done**（服务端） |
| M5 安全 | **done**（含 key re-wrap） |
| M6 桌面 | **partial**（Linux vendor 冒烟通过；打包未完成） |

---

## 明确未做（§17）

发送 / 联系人 / 系统推送 / 旧 cache 兼容 / ES·Redis·Kafka / WebSocket / 字段级可搜索加密 / 公网裸暴露 / 真实云 OAuth 联调。

---

## 本轮诚实备注

1. EDB PG 镜像 403 → 改 theseus-rs；二进制在 `desktop/vendor/`（gitignore），不进仓库。  
2. `.github/workflows/mail-core.yml` 再次推送被拒；以 `docs/ci/` + scripts 为准。  
3. Cutover 默认已写进 `docker-compose.mail-core.yml` / `frontend/.env.example`；产品 Flask compose 未强行改默认。
