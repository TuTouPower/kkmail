# 测试 (Testing & Verification)

项目质量门禁与验证命令。章节名 `doctor_cmd` / `test_cmd` / `blackbox_verify` 是 preflight 与 skill 的机械锚点，不可更改。

## doctor_cmd

环境前置检查：工具链契约测试可成功收集；Markdown 格式化器存在。

```bash
pytest .repo_template/tests -q --collect-only -m contract
command -v md_kx || true
```

## test_cmd

日常全量门禁命令（单元测试、静态类型检查、生产构建与契约核验）：

```bash
pytest .repo_template/tests -q -m contract
scripts/run-mail-core-tests.sh run
(cd src/frontend && npm test && npx tsc -b && npm run build)
(cd src/desktop && npm test)
```

## blackbox_verify

浏览器端到端轻量冒烟验证与真实全栈端到端自动化：

```bash
# 快速 UI 冒烟测试（基于 stubApi，无外部服务依赖，4s）
npm --prefix src/frontend run test:e2e

# 真实全栈端到端测试（基于真实 FastAPI、PostgreSQL、Worker、Dovecot 与生产 SPA，16s）
python3 scripts/run_full_stack_e2e.py
```

## Schema / codegen 验证

- **触发路径**：`src/mail_core/api/` (路由与 DTO 改动)、`schemas/openapi.json`、`src/mail_core/db/alembic/versions/`
- **生成命令**：
    ```bash
    python3 scripts/export_openapi.py
    (cd src/frontend && npm run openapi:gen)
    ```
- **验证命令**：
    ```bash
    python3 scripts/export_openapi.py --check
    (cd src/frontend && npm run openapi:check)
    ```
- **合并后动作**：确认生成文件已暂存，无 schema drift。
- **migration 窗口**：涉及数据库表变动时编写 Alembic 迁移脚本，版本号保持严格线性无分叉。

## 门禁类别覆盖清单

|类别|项目对应实现|命令或验证方式|
|:---|:---|:---|
|**前端单元/组件测试**|React 组件与缓存逻辑|`(cd src/frontend && npm test)`|
|**前端类型检查**|全局 TypeScript 强类型|`(cd src/frontend && npx tsc -b)`|
|**前端生产构建**|Vite 生产打包|`(cd src/frontend && npm run build)`|
|**桌面端测试**|Node 进程管理、路径与安全|`(cd src/desktop && npm test)`|
|**模板契约测试**|工具链合法性冒烟|`pytest .repo_template/tests -q -m contract`|
|**后端单元/集成测试**|FastAPI + PG + Worker|`scripts/run-mail-core-tests.sh run`|

## PostgreSQL 测试运行时（t013）

环境安装与测试执行分开，复用仓库 `.venv`：

```bash
UV_CACHE_DIR=.scratch/uv_cache uv venv .venv
UV_CACHE_DIR=.scratch/uv_cache uv pip install --python .venv/bin/python -r requirements-dev.txt
```

启动前由操作者设置随机专用 `KKMAIL_TEST_PG_PASSWORD`。禁止复用业务 `.env` 密码。服务采用 `config/test_pg_compose.yaml`，独立 Compose project `kkmail_test_pg`，PostgreSQL 16 仅绑定 `127.0.0.1`，默认端口 15433；端口可经 `KKMAIL_TEST_PG_PORT` 指定。不得连接业务 Compose 或挂载业务卷。

```bash
scripts/run-mail-core-tests.sh start
scripts/run-mail-core-tests.sh run
scripts/run-mail-core-tests.sh unit
scripts/run-mail-core-tests.sh stop
```

`start` 显式启动或复用测试服务；`run` 要求服务已启动，每轮创建唯一 `kkmail_test_<UUID>` 数据库，经生产 Alembic 升级后运行 Python 套件。容器 ID、PG cluster system identifier、数据库 comment 和仓库所有权记录必须一致，才允许迁移、fixture 删除和清理。直接 pytest 也执行保护；URL 查询参数一律拒绝。`unit` 明确报告未执行 PG 套件，不代表全量通过。

每轮数据库、Blob、备份、临时文件和 JUnit 报告对应 `.scratch/test_runs/<UUID>/`。正常结束、断言失败、SIGINT/SIGTERM 后清理本轮子进程和数据库，不停止常驻服务；所有权记录与报告保留。阶段日志输出耗时和状态，不打印数据库 URL 或密码。强制终止后，仅允许指定确切 UUID 回收：

```bash
scripts/run-mail-core-tests.sh cleanup <run_uuid>
```

所有权或实例身份不符时拒绝清理；不扫描删除未知数据库。显式 `stop` 遇到带运行标记的数据库时拒绝停止。每轮使用独立 NOLOGIN owner role 原子标记建库归属，覆盖建库与 comment 写入间中断；creating 状态仅回收所有者匹配的确切数据库，运行态额外要求 comment 匹配。

当前验证：17 项保护测试通过，独立仓库并发、真实迁移失败与 SIGTERM 清理已验证。t014 已收口 Outbox 残留与旧测试前置；最终 seed 41、17 连续两轮均 352 passed / 2 skipped（仅 IMAP 服务未启用），无 PG 条件跳过。两轮容器和 PG 服务进程复用，数据库独立，结束后无测试库或 owner role 残留。

## 后端逐用例隔离与确定性验证（t014）

共享 fixture 在独占测试库中清理全部业务表，保留 Alembic 版本。测试仍使用真实 commit、多连接与生产锁；不通过外层 rollback 吞掉跨连接语义。每例停止 Worker/LISTEN、关闭实际 checkout 连接并 dispose Engine，恢复 provider、credential store、dispatcher、鉴权、限流、schema cache 与 SSE 计数。setup/teardown 清理失败立即停止套件，禁止污染后续用例。

快速模式明确不运行 DB 套件；独立单测使用逐项 PG 标记，避免整文件跳过。完整模式拒绝 PG 条件 skip，协议服务未显式启用时的 IMAP 跳过单独报告，不能解释为真实协议验证通过。

固定 seed 可重放全套顺序：

```bash
KKMAIL_TEST_SEED=17 scripts/run-mail-core-tests.sh run
KKMAIL_TEST_SEED=41 scripts/run-mail-core-tests.sh run
```

失败输出包含 seed 与 nodeid；可追加 pytest 参数，例如 `-k test_committed_data_starts_empty` 缩小复现。`tests/mail_core/mailbox_factory.py` 提供确定 UUID、中文 multipart MIME、固定排序时间、重复 Message-ID、多账号/空目录与真实加密 Blob/附件数据，不使用墙钟或随机碰撞建立分页断言。

每轮目录包含 `.coverage`、`coverage.xml`、`coverage.json`、`junit.xml` 和 `test_summary.json`。覆盖仅统计生产 `mail_core`，启用分支覆盖；汇总列出实际收集、执行、错误、跳过原因和未执行清单，不用统一覆盖率百分比代替行为验收。依赖安装单独执行，pytest-cov 缺失会失败，不在测试入口自动安装。

实测基线：快速套件 252 passed / 102 skipped；完整 seed 41、17 各 352 passed / 2 IMAP skipped，约 260/273 秒。87 个生产模块文件行/分支综合覆盖 78.63% / 78.66%，不代表未覆盖行为安全。IMAP 真实路径由 t016 接续，不将当前协议跳过计为通过。

## 前端测试运行时与隔离（t015）

前端单测与组件测试采用 Vitest + jsdom 环境，要求 Node >= 20（本地推荐 Node 22/24）：

```bash
(cd src/frontend && npm test)
(cd src/frontend && npm run test:coverage)
(cd src/frontend && npm run lint)
(cd src/frontend && npx tsc -b && npm run build)
```

在测试启动入口 `src/frontend/src/test/test_setup.ts` 中，在导入任何 Zustand store 之前确保将 jsdom 真实存储实例注入 `globalThis.localStorage` 与 `globalThis.sessionStorage`，防止 Node 环境宿主存储影响。

每用例前后执行隔离与清理：

- 重置 Zustand store 至初始状态；
- 清理 `localStorage` 与 `sessionStorage`；
- 清空 TanStack QueryClient 缓存；
- 重置内存 CSRF token；
- 移除测试中绑定的全局 window 事件监听器；
- 卸载已渲染 DOM 组件节点，恢复全局 fetch、timers 与 navigator 替身。

覆盖率报告基于 `@vitest/coverage-v8` 输出至 `.scratch/frontend_coverage`，覆盖范围仅限 `src/**/*.{ts,tsx}` 生产代码，排除测试文件与生成代码。实测全量 34 个测试文件共 168 项用例全通，行覆盖率约 78%。

## 真实 IMAP 与服务商协议契约验证（t016）

真实 IMAP 服务由专用测试 Compose 提供（`config/test_pg_compose.yaml` 中的 `imap` 服务，基于 Dovecot，绑定 `127.0.0.1:1143`），由 `scripts/start-mail-core-imap.sh` 启动，与业务数据库及业务 Compose 完全隔离，不使用业务口令或生产卷：

```bash
scripts/start-mail-core-imap.sh
scripts/run-mail-core-tests.sh run -k test_imap
```

真实协议层门禁特性：

- **无静默跳过**：完整测试运行期间必须确保测试 IMAP 服务处于监听与认证就绪状态，全量套件实现 0 项 IMAP 条件跳过（361 passed / 0 skipped）；
- **全链路同步验证**：覆盖中文多部分正文、二进制附件落库加密与流式解密校验、相同 Message-ID 邮件处理，以及多轮同步的严格幂等性；
- **增量收敛与服务端可观察性**：测试远端 Flag 变更与删除在本地库的增量同步；验证本地读状态更新经 `push_remote_operations` 写回到真实服务端后能在 IMAP 协议（`\Seen`）上直接观测；
- **安全废纸篓与 TLS 防护**：验证仅移动目标邮件至 Trash，在缺少 MOVE 能力时拒绝不安全的全目录 EXPUNGE；非 SSL 端口开启 TLS 时必须握手失败直接阻断；
- **Gmail / Graph 服务商传输契约**：覆盖循环/重复 pageToken 检测、过期游标不前进、OAuth token 刷新失败脱敏、429 重试等待及 5xx/超时重试幂等性。普通 CI 不依赖外网真实 OAuth 凭据。

## 全栈端到端真实测试（t017）

全栈端到端测试覆盖真实环境（FastAPI、Worker、PostgreSQL、Dovecot、生产 SPA 构建同源托管）：

```bash
python3 scripts/run_full_stack_e2e.py
```

执行流程与环境规范：

- 由 `scripts/run_full_stack_e2e.py` 自动化控制器统筹调度；
- 动态在测试 PostgreSQL 实例中分配 `kkmail_e2e_<uuid>` 测试库与专属所有者 role，执行 Alembic head 迁移；
- 启动真实 FastAPI 服务（通过 `KKMAIL_FRONTEND_DIST` 挂载 `src/frontend/dist` 生产构建），分配空闲端口并探测 `/health`；
- 启动后台真实 Worker 进程处理同步与入库；
- Playwright 执行 `tests/e2e/full_stack.spec.ts` 验证真实登录认证、Cookie、CSRF 校验、多会话失效、添加 IMAP 账号后 Worker 自动同步与邮件详情展示、XSS 防护过滤、双页面 SSE 实时协同；
- 运行后优雅终止进程，安全销毁测试库与 role，失败时保留截图、日志和 trace 于 `.scratch/`。同时保留 `npm --prefix src/frontend run test:e2e` 作为 4 秒快速 UI 冒烟入口。

## 数据库迁移与结构一致性门禁（t018）

数据库迁移质量门禁验证真实 PostgreSQL 下历史版本数据跨版本平滑升级无损保留与结构一致性：

```bash
scripts/run-mail-core-tests.sh run -k test_migration_validation
```

验证覆盖：

- **线性单 Head 校验**：严格确保迁移版本历史无分叉、无孤立 revision，唯一当前 head 对应生产最新版本；
- **历史窗口升级数据无损保留**：覆盖 `f5f312751c77` (unified schema)、`20261021_0011` (认证入库前) 及 `20261022_0014` 三个历史 revision 窗口，在旧库状态写入当时合法数据后直接升级至当前 head，验证邮件正文、附件、凭证哈希与 session_epoch 无损保留；
- **真实完整性约束生效**：断言数据库底层唯一约束、外键级联与 RESTRICT 阻断生效，检验 keyset 索引与 FTS trigram 搜索能力；
- **ORM Schema Drift 校验**：使用 Alembic autogenerate 比较 SQLAlchemy 模型与真实 PostgreSQL catalog 差异，结合显式 catalog 校验确保 0 未登记 drift；
- **可逆降级再升级循环**：对最新版本执行 `downgrade -1` 与重新 `upgrade head`，验证 DDL 双向对称可逆。
