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
(cd src/frontend && npm test && npx tsc -b && npm run build && npm run lint)
(cd src/desktop && npm test && npm run test:packaged)
```

## blackbox_verify

浏览器端到端轻量冒烟验证与真实全栈端到端自动化：

```bash
# 快速 UI 冒烟测试（基于 stubApi，无外部服务依赖，4s）
npm --prefix src/frontend run test:e2e

# 真实全栈端到端测试（基于真实 FastAPI、PostgreSQL、Worker、Dovecot 与生产 SPA，16s）
python3 scripts/run_full_stack_e2e.py
```

### Electron 原生标题栏人工验证（t032）

`BrowserWindow` 参数单测不能证明 macOS 原生交通灯、真实拖动区或全屏行为。改动桌面标题栏后，使用隔离 `userData` 与测试服务启动独立 Electron 窗口，并以系统截图和操作记录验证：原生交通灯与侧栏按钮相邻、侧栏收起后按钮可用、空白区可拖动而按钮点击不拖窗、最小化/恢复、关闭/重新打开、全屏进出及窗口缩放后不重叠。不得用网页原型绘制的假交通灯代替证据。

Windows/Linux 原生窗口行为应在对应系统实际运行验证；无法使用对应平台时，明确标注仅完成窗口参数单测，不宣称该平台已实测。

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
|**UI 稳定编号与引用**|快捷键、气泡浮标、复制格式与唯一性|`(cd src/frontend && npm test -t uiReference)`|
|**写回收敛与统计一致性**|批次自动续跑、意图保护与孤儿恢复|`scripts/run-mail-core-tests.sh run -k test_mark_read_convergence_suite`|
|**MIME 解析错误与前端可见性**|正文/报头/附件名解析失败、API 传递与跨邮件状态隔离|`scripts/run-mail-core-tests.sh run -k test_archive_decode_failure` 及 `(cd src/frontend && npm test -t MessageReader)`|

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

## 真实加密备份与跨库恢复演练（t019）

生产备份逻辑支持真实 PostgreSQL `pg_dump`、AES-GCM 封装加密与真实 `pg_restore` 还原到全新目标实例：

```bash
scripts/run-mail-core-tests.sh run -k test_backup_restore_drill_live
scripts/mail-core-backup-restore-drill.sh
```

恢复规范与安全机制：

- **真实客户端与隔离目标**：通过 `restore_backup_package` 驱动真实 `pg_restore` 恢复至独立测试库，并安全解包还原 `blobs.tar` 至目标 Blob 目录；
- **防覆盖与越界阻断**：严格拒绝源库与目标库相同，防止破坏性覆盖生产库；严格校验目标 Blob 目录拒绝路径穿越与越界符号链接；
- **真实业务核验**：恢复后通过独立会话核验账号、邮件、正文、附件关联，并使用密钥解密读取 Blob 确保字节与原始附件完全一致；
- **篡改与伪造拒绝**：校验错误密钥、篡改数据、缺失 Blob 抛出明确异常；声明禁止将 SQL stub 备份伪造为可恢复证据。

## 多进程 Worker 竞争与故障恢复测试（t020）

多进程并发与混沌恢复门禁验证真实操作系统级 Worker 竞争与异常退出后的系统自我修复能力：

```bash
scripts/run-mail-core-tests.sh run -k test_worker_process_recovery
```

验证覆盖：

- **真实进程并发与非重叠 Claim**：启动多个独立 Worker 子进程竞争任务，验证 PostgreSQL `FOR UPDATE SKIP LOCKED` 互斥生效，各 Worker 独占认领不同账号任务并成功推进，无重叠或重复执行；
- **真实 SIGKILL 杀进程与自然 Reclaim**：对正在持有任务的 Worker 进程发送 `SIGKILL` 强制终止，存活 Worker 在自然时间超过 `MAIL_CORE_RECLAIM_STALE_SECONDS`（生产默认 300s）后自动将陈旧任务回收为 PENDING 并重新认领执行，不通过手动修改数据库时间字段；
- **Fencing Token 阻止陈旧提交**：模拟已被替代的旧 Worker 重新提交操作时，触发 `FencingMismatch` 异常，保证已推进的 Checkpoint、Message 与 Blob 不被覆盖；
- **跨进程事件通知与回滚隔离**：Worker 进程提交事务后通过真实 PostgreSQL `LISTEN/NOTIFY` 唤醒 API 进程的 SSE 分发，未提交或已 rollback 的事务严格不广播；
- **进程组安全销毁**：测试中所有子进程使用独立的进程组（`start_new_session=True`），测试退出时通过 `os.killpg` 严格清理，绝无孤儿进程残留。

## 桌面打包产物与嵌入式数据库生命周期门禁（t021）

桌面测试区分快速基础测试与严格实际打包产物冒烟：

```bash
# 桌面进程管理器、路径与基础单测 (2s)
npm --prefix src/desktop test

# 严格实际打包产物与内置 PostgreSQL 生命周期冒烟
npm --prefix src/desktop run test:packaged
```

验证覆盖：

- **非 Stub 生产产物验证**：断言 `--dir` 产物内部 `frontend/dist` 包含真实 SPA（拒绝临时 stub 伪装通过），校验内置 `pgsql/bin` 包含匹配原生平台架构的 `initdb`、`pg_ctl`、`postgres` 二进制；
- **嵌入式 PostgreSQL 首启与建库**：在隔离测试数据目录由 `PostgresManager` 调度包内二进制完成 `initdb`、密码文件生成（权限 0600）与端口监听；
- **优雅停机与端口释放**：验证 `pg_ctl stop` 后子进程完全终止、监听端口完全释放，不残留孤儿服务；
- **数据跨重启持久化保留**：在同一数据目录重新启动，验证不会被重新初始化覆盖，先前写入的状态完整继承。

## 大邮箱查询同步与资源使用基准（t022）

支持确定性规模大邮箱基准与系统资源用量测量：

```bash
# 自动化测试门禁 (1k 规模)
scripts/run-mail-core-tests.sh run -k test_mailbox_performance_baseline

# 独立命令行基准运行 (支持 1k / 10k / 100k)
python3 scripts/benchmark_mailbox.py --scale 1000 --runs 3 --out .scratch/benchmark_report.json

# 两份基准报告差异对比
python3 scripts/benchmark_mailbox.py --compare .scratch/base.json .scratch/candidate.json
```

核心指标与测试场景：

- **场景覆盖**：首页 keyset 分页（50封）、深 keyset 翻页（逐页推进至后序多页）、中文与 ASCII 全文搜索（tsvector/trigram）、文件夹未读与总数重算、Blob 流式解密读取；
- **度量指标**：延迟分位数（p50、p95）、吞吐（QPS）、进程峰值 RSS 内存、数据库物理体积、Message 表大小、Blob 磁盘空间及 PostgreSQL EXPLAIN 查询计划（确认索引利用）；
- **跨报告对比**：结构化输出各场景延迟百分比变化与资源变动，若运行平台不一致明确警示不可直接比对。

## 本地分层门禁与 CI 流水线映射（t023）

统一本地开发重放命令与 GitHub Actions 流水线，消除数据库静默跳过并实现全自动化守护：

### 1. 本地快速与全量门禁矩阵

|分层|覆盖内容|本地执行命令|
|---|---|---|
|**前置契约**|模板契约与工具链冒烟|`pytest .repo_template/tests -q -m contract`|
|**前端全量**|样式/类型/单元/构建/OpenAPI|`(cd src/frontend && npm test && npx tsc -b && npm run build && npm run lint)`|
|**桌面全量**|进程管理单测 + 原生打包冒烟|`(cd src/desktop && npm test && npm run test:packaged)`|
|**后端快速**|无数据库/内存 Provider 单元|`scripts/run-mail-core-tests.sh unit` (256 passed / 105 skipped)|
|**后端全量**|专用 PG (15433) + 真实 IMAP (1143)|`scripts/run-mail-core-tests.sh run` (361 passed / 0 skipped)|
|**全栈 E2E**|真实 FastAPI + PG + Worker + SPA|`python3 scripts/run_full_stack_e2e.py` (3 passed, 16s)|
|**快速 E2E**|轻量浏览器 stubApi 冒烟|`npm --prefix src/frontend run test:e2e` (3 passed, 4s)|
|**扩展演练**|备份跨库还原 / 迁移升级 / 混沌恢复|`scripts/run-mail-core-tests.sh run -k "test_backup_restore_drill_live or test_migration_validation or test_worker_process_recovery"`|
|**性能基准**|确定性规模延迟分位数与资源测定|`python3 scripts/benchmark_mailbox.py --scale 1000 --runs 3`|

### 2. CI 工作流映射

- **PR 与 Push 门禁 (`.github/workflows/ci.yml`)**：
    并行调度 `template-contract`、`frontend-quality`、`desktop-quality` 和 `backend-and-integration` 四大 Job，任何 Job 失败均在 `ci-status` 汇总阻断；在 Linux runner 自动构建前端并拉起测试数据库与 IMAP 服务，执行真实全栈端到端测试；
- **定时与手动扩展套件 (`.github/workflows/scheduled.yml`)**：
    每天定时或手动触发，完整执行真实备份跨库恢复、多版本历史数据平滑升级、多进程 Worker 故障恢复和大邮箱性能基准测试；
- **权限与环境安全**：工作流配置最小 `contents: read` 权限，不申请发布权限；测试使用的数据库密码与环境变量严格隔离于专用测试环境。

## 分组侧栏与分组邮件范围（t027）

组织数据、邮件范围与浏览器交互必须组合验证，不能只测组件状态或仅检查 API 响应：

```bash
scripts/run-mail-core-tests.sh run
(cd src/frontend && npm test && npx tsc -b && npm run build && npm run lint && npm run openapi:check)
npm --prefix src/frontend run test:e2e
python3 scripts/run_full_stack_e2e.py
```

- PostgreSQL 集成测试验证分组 CRUD、删除非空组后保留账号、完整布局原子校验、独立排序、空组与未知组范围、列表/搜索/统计/全部已读，以及最新迁移的降级再升级；测试必须使用专用测试数据库。
- 浏览器冒烟测试验证六类全局分类、分组分类、真实文件夹树和导航布局；真实全栈 Playwright 通过 HTML5 拖拽验证空组、跨组、移出、主列表内排序和分组排序，并刷新后读取服务端确认成员关系与顺序持久化。
- 前端测试覆盖查询 key 按 scope 隔离、分组参数贯通、偏好持久化与设置入口；`schemas/openapi.json` 和生成 TypeScript 必须通过 codegen 漂移检查。

## 供应商账户表单与 Google OAuth 回调（t053 / t054）

后端：`scripts/run-mail-core-tests.sh run -k "provider_account or google_oauth_callback or accounts_api or oauth_transport or account_credentials" --no-cov`，覆盖真实加密凭据更新、回滚、Microsoft IMAP 拒绝、Google OAuth PKCE 换码与 `users.getProfile` 核验、跨会话/重放/并发回调拦截及多客户端令牌轮换。前端：`npm --prefix src/frontend test`；浏览器：`npm --prefix src/frontend run test:e2e -- provider_account_forms.spec.ts settings_workspace.spec.ts`，覆盖 Google OAuth 跳转登录、重新授权、帮助弹窗焦点与窄屏输入。

OAuth Electron 集成门禁：先构建生产 SPA，再运行 `KKMAIL_TEST_ELECTRON=1 scripts/run-mail-core-tests.sh run -k google_oauth_callback --no-cov`。独立 Electron profile、真实 FastAPI/隔离 PG、假供应商 HTTP 服务覆盖动态 loopback、生产外链处理器、无 Cookie 回调、窗口焦点恢复及最终保存；不连接真实 Google 账号。

Microsoft 回归：`KKMAIL_TEST_ELECTRON=1 scripts/run-mail-core-tests.sh run -k "microsoft_oauth or google_oauth_callback" --no-cov`，先构建生产 SPA。覆盖 Graph 身份/邮箱/许可、已有账户重新授权、租户与应用不匹配、设备码 interval/slow_down/429、取消/epoch/迟到成功、并发单次轮询、官方地址白名单及日志错误脱敏。微软独立 Electron 实例经真实 API/隔离 PG 与供应商 HTTP 夹具验证 localhost 动态端口、系统外链、无 Cookie 回调、恢复与最终保存。真实 Entra 注册/2FA/管理员同意不作为模拟通过，需另记真实账号冒烟结果。
