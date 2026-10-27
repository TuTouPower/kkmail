# Task spec

## 背景

当前系统存在配置分散与核心参数硬编码问题：

1. 业务模块直接通过 `os.environ.get()` 裸调读取环境变量（分散在数十个文件中），缺乏集中定义、类型检查与统一校验。
2. 若干核心运行时参数被硬编码在代码内部常量中（例如：外联并发槽位上限 `TOTAL_SLOTS = 8`、前后台槽位划分、容量不足重试延迟、邮件 MIME 大小上限 `50MB`、附件大小上限 `25MB`、初始归档回溯天数 `30天`、Worker 领单批次 `CLAIM_BATCH = 5` 与回收周期 `RECLAIM_INTERVAL_S = 60s` 等），无法在不修改代码的情况下根据硬件与部署规模调整。
3. `config/.env.example` 严重残缺，仅声明了 7 个变量，缺少数据库连接串、连接池参数、安全与会话策略、Worker 调度参数等部署关键项。
4. 当前正在实施的 `t057` 新增了收件箱轮询周期 `MAIL_CORE_INBOX_POLL_INTERVAL_S` 与调度周期 `SCHEDULE_INTERVAL_S`，需要在统一配置体系中无缝容纳。

本任务依据配置架构规范，采用代码集中定义类型化默认值（方案 A），建立集中式配置模型，抽离关键运行参数，容纳 t057 的新配置项，并补齐完整的环境变量配置示例。

## 契约区

### 范围

- 建立 `src/mail_core/config/` 集中配置模块，声明强类型配置结构、全量默认值权威来源与校验逻辑。
- 抽离以下写死的运行时核心参数并支持环境变量/配置覆盖：
    - 外联连接槽位：`TOTAL_SLOTS` (默认 8)、`BACKGROUND_START_SLOT` (默认 2)、`CAPACITY_RETRY_SECONDS` (默认 5.0)。
    - 邮件与存储规格：`MAX_MIME_BYTES` (默认 50MB)、`MAX_ATTACHMENT_BYTES` (默认 25MB)、`DEFAULT_RECENT_DAYS` (默认 30)。
    - Worker 调度策略：`CLAIM_BATCH` (默认 5)、`RECLAIM_INTERVAL_S` (默认 60.0)。
- 纳入并兼容 t057 的收件箱巡检配置：
    - `MAIL_CORE_INBOX_POLL_INTERVAL_S` (默认 1200.0)。
    - `MAIL_CORE_SCHEDULE_INTERVAL_S` (巡检扫描周期，默认 60.0)。
- 收口各子模块中直接调用 `os.environ.get()` 的分散逻辑，改为向集中配置单例获取。
- 在服务启动入口强化配置校验：启动首帧验证必填项（如 `MAIL_CORE_DATABASE_URL`）及数值范围合法性，非法时抛出明确异常并拒绝启动。
- 重写并补齐 `config/.env.example`，按模块清晰组织全部受支持的环境变量说明与默认占位符。
- 同步更新桌面端 `src/desktop/startup.js` 的 `SIDECAR_CONFIG_KEYS` 白名单，确保新增环境变量可穿透给 Sidecar 后端。
- 同步更新 `src/mail_core/README.md` 中的配置表格。

### 非范围

- 不修改加密二进制协议常量（如 `MAGIC`、`CHUNK_SIZE`、`NONCE_LEN` 等存储不变量）。
- 不把属于数据库的用户个性化偏好（如主题、侧栏分组排序、单账号个性化抓取超时）抽离至配置文件或环境变量。
- 不引入重型外部配置框架，复用既有依赖与基础模型。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：在未提供任何环境变量或外部配置文件时，集中配置单例能产出完整合法的默认值集合（含服务监听、连接池参数、槽位数 8、邮件大小 50MB、附件大小 25MB、Worker 轮询 2s、收件箱轮询 1200s 等）。
- [ ] AC-002：环境变量 `MAIL_CORE_TOTAL_SLOTS`、`MAIL_CORE_BACKGROUND_START_SLOT`、`MAIL_CORE_CAPACITY_RETRY_SECONDS` 可成功覆盖外联连接池配置，并在连接槽位分配与超限退避逻辑中实际生效。
- [ ] AC-003：环境变量 `MAIL_CORE_MAX_MIME_BYTES` 与 `MAIL_CORE_MAX_ATTACHMENT_BYTES` 可成功覆盖单封邮件及单附件体积上限，并在归档解析流程中实际生效。
- [ ] AC-004：环境变量 `MAIL_CORE_CLAIM_BATCH` 与 `MAIL_CORE_RECLAIM_INTERVAL_S` 可成功覆盖 Worker 领单批次与僵死任务回收周期，并在 Worker 主循环中实际生效。
- [ ] AC-005：集中配置系统兼容并统一接管 t057 的 `MAIL_CORE_INBOX_POLL_INTERVAL_S` 与 `MAIL_CORE_SCHEDULE_INTERVAL_S`，Worker 定时巡检可正确读取。
- [ ] AC-006：当缺少核心必填配置（如 `MAIL_CORE_DATABASE_URL`）或环境变量值非法（如端口超出范围、槽位数为负）时，应用启动期抛出明确结构化错误并终止启动。
- [ ] AC-007：`config/.env.example` 完整列出所有受支持的配置项（包括服务网络、数据库连接池、Provider 并发与配额、Worker 调度、安全会话、Blob 存储备份、OAuth 凭据等），并附带模块化注释与默认值说明。
- [ ] AC-008：桌面端 `src/desktop/startup.js` 中的 `SIDECAR_CONFIG_KEYS` 包含新增的环境变量白名单，能够将外部环境变量正确透传给 Sidecar 子进程。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。

## 上下文区

- 来源：用户配置审查与架构规范重构需求

### 有意不测

- 外部生产级环境全量环境变量组合爆炸测试（通过子系统级单元测试覆盖关键变量注入与覆盖）。

### 测试策略

- 单元测试：`tests/mail_core/test_config.py` 验证配置加载、类型转换、边界校验、必填报错以及环境变量优先级覆盖。
- 集成测试：针对连接槽位 `test_connection_slots.py`、邮件归档 `test_blobs_archive.py`、Worker 调度 `test_worker_scheduler.py` 补充动态参数验证。
- 桌面端测试：`src/desktop/startup.test.js` 验证 `SIDECAR_CONFIG_KEYS` 覆盖度。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

无

### 风险与回退

- 风险：集中配置加载顺序若过早或存在循环引用，可能影响轻量测试中部分独立函数的导入。
- 防御：配置模块设计为自包含底层模块，不依赖业务与数据库层；提供受控单例与覆盖重置辅助函数方便测试注入。
- 回退：git revert 对应 commit。

### 依赖与约束

- 依赖正在实施中的 `t057`（收件箱定时轮询与增量正文自动存库）合入后新增的收件箱定时配置。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：更新系统配置层分层架构与配置加载规范。
- `docs/blueprint/conventions.md`：禁止业务代码裸写 `os.environ.get()`，规范配置读取入口。
