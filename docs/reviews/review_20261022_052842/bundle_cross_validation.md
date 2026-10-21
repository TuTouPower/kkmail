# Intensive Review — 交叉验证与证伪报告 (Cross Validation)

## 证伪与核验原则

由独立核验视角针对全部 Critical 与 High 级别 Findings 进行直接反证探测：

- 若找到确凿反向证据证明其在当前代码或上下文中不可达、被框架隐式规避或已有前置保护，标记为 `CHALLENGED` 并下调置信度；
- 若核验无反证且代码复现链路完整，标记为 `CONFIRMED` 并提升置信度。

______________________________________________________________________

## 核验结果清单

### 1. [Critical] `outlook_mail_reader.py:20` 历史 Commit 泄露真实邮箱与 OAuth Token

- **核验结论**：`CONFIRMED` (置信度 100)
- **直接验证**：执行 `git show 34c8131069298bf14989f853decba8e3ee8c4dd2:outlook_mail_reader.py`，完整输出了真实 Outlook 邮箱、明文密码和长达数百字符的有效 OAuth Refresh Token。当前仓库已验证为公开开源仓（`gh repo view TuTouPower/kkmail --json isPrivate` 返回 false），任何人均可读取，严重泄露。

### 2. [Critical] `src/desktop/main.js:189` 桌面端缺失单实例锁

- **核验结论**：`CONFIRMED` (置信度 98)
- **直接验证**：全局搜索 `requestSingleInstanceLock` 结果为空。`main.js` 未向 Electron 申请单实例锁，多开时第 2 实例关闭会调用 `shutdownAll()` -> `pg.stop()`，直接杀掉运行中的共享 PostgreSQL 进程。

### 3. [Critical] `src/mail_core/realtime/dispatcher.py:144` 多进程下无本地订阅者误标已分发

- **核验结论**：`CONFIRMED` (置信度 95)
- **直接验证**：第 144 行 `if not targets: return True`，在进程存在本地订阅者（`has_local_subscribers()` 为 True）但无当前事件对应账号的目标时，直接返回 True 并将 ID 传入 `mark_dispatched()`。多进程 Uvicorn 部署下将引发确定性的跨进程消息静默丢失。

### 4. [Critical] `src/mail_core/security/auth.py:206-288` 会话认证无缓存直接查库

- **核验结论**：`CONFIRMED` (置信度 95)
- **直接验证**：`read_session()` 内部调用 `get_session_epoch()`，每次均 `with Session() as session: cred = session.get(AuthCredential, "default")`。所有带 Cookie 请求进入时均产生同步 SQL 借用连接池，无任何进程内或短期缓存。

### 5. [Critical] `src/mail_core/blobs/archive.py:158` message_archive_state 缺少索引

- **核验结论**：`CONFIRMED` (置信度 90)
- **直接验证**：检索 `src/mail_core/db/alembic/versions/` 全部文件，仅在建表时指定了 `message_id` 主键，后续迁移从未建立 `(state, priority)` 索引。Worker 高频轮询批量拉取必走全表扫描。

### 6. [Critical] `Dockerfile.mail-core:25` 生产镜像未装配日志脱敏格式化器

- **核验结论**：`CONFIRMED` (置信度 99)
- **直接验证**：Dockerfile CMD 仅调用 `uvicorn mail_core.api.app:app`，而 `app.py` lifespan 未调用 `configure_logging()`，RedactingTraceFormatter 未装配，容器生产日志完全失去脱敏过滤。

### 7. [High] `scripts/migrate_from_legacy_db.py:68` 硬编码默认密钥

- **核验结论**：`CONFIRMED` (置信度 100)
- **直接验证**：第 68 行字面量存在 `[REDACTED]`，严重违反 conventions.md「不预设弱口令或示例密钥」。

### 8. [High] `scripts/mail-core-chaos-lease.sh:16` 数据库名通配可误伤生产库

- **核验结论**：`CONFIRMED` (置信度 98)
- **直接验证**：`if [[ "$DB_NAME" != *test* && "$DB_NAME" != *chaos* ]]` 使用了子串匹配，若库名为 `production_latest` 或 `attest_db`，因包含 `test` 子串直接通过校验并升级表结构/注入混沌。

### 9. [High] `docs/guides/deployment.md:19` 与 Compose 端口冲突

- **核验结论**：`CONFIRMED` (置信度 98)
- **直接验证**：`deployment.md` 第 19 行指导访问 `http://127.0.0.1:8000`，而 `docker-compose.mail-core.yml` 第 71 行明确发布到 `127.0.0.1:37281:8000`，按文档访问直接拒绝连接。

### 10. [High] `src/frontend/src/App.tsx:108` ColumnResize 拖拽全局重渲染与写 localStorage

- **核验结论**：`CONFIRMED` (置信度 95)
- **直接验证**：`onDrag` 在 pointermove 触发 `setSidebarWidth`，`App` 重新渲染且子组件均无 `React.memo`，同时 `mailStore` persist 中间件在每次变动时同步写 localStorage。

### 11. [High] `src/frontend/src/components/MessageList.tsx:182` 邮件列表过滤与排序未 memoize

- **核验结论**：`CONFIRMED` (置信度 95)
- **直接验证**：`visible` 未包裹 `useMemo`，任何状态微调触发组件重跑，300 封邮件在 `compareMailDates` 中重复调用正则解析数千次。

### 12. [High] `src/mail_core/api/accounts.py:24` 路由层直接操作 ORM 实体击穿分层

- **核验结论**：`CONFIRMED` (置信度 98)
- **直接验证**：`accounts.py` 第 24 行直接导入 `Account, AccountGroup` ORM 类并在路由函数内手动 session.get、session.commit，违背分层架构约定。
