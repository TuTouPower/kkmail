# Task spec

## 背景

启动入口使用 `args.no_worker` 决定是否创建 Worker 线程，就绪探针独立读取 `MAIL_CORE_EMBEDDED_WORKER`。基于 `060e0893` 的最小复现走生产启动和就绪入口，以同一新鲜模拟 DB 心跳、无本地戳且开启强制 Worker 就绪门禁作为条件，`--no-worker` 返回 503，`MAIL_CORE_EMBEDDED_WORKER=0` 返回 200。

## 契约区

### 范围

- 在启动配置边界合并 CLI 与环境变量，交付线程启动与就绪探针共用的生效 Worker 模式。保留直接启动 ASGI 与独立 Worker 的环境配置入口。
- 统一存活戳的显式路径、数据目录默认及进程默认路径解析。Worker 写入、API 校验和 Worker 健康检查共享统一路径规则。
- 补齐就绪及存活戳隔离用例，清理相关测试中的未用 `SimpleNamespace` 导入。

### 非范围

- 数据库迁移、容器拓扑、Worker 看门狗时序及 HTTP 响应 schema。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [ ] AC-001：分别使用 CLI `--no-worker` 和 `MAIL_CORE_EMBEDDED_WORKER=0` 启动 API，两者均不创建内嵌 Worker。强制 Worker 就绪门禁开启、DB/schema/LISTEN 正常且心跳新鲜时，两者在未显式配置戳的情况下均返回 200，且忽略残留的默认本地戳。
- [ ] AC-002：独立 Worker 模式显式配置存活戳路径或启用内嵌 Worker 时，缺失、不可读、损坏或陈旧的必需戳使 Worker 未就绪。强制门禁开启时返回 503。DB 心跳与必需戳均新鲜且其它条件正常时返回 200。DB 心跳过期仍使 Worker 未就绪。
- [ ] AC-003：存活戳写入与读取使用同一生效路径。显式路径优先于数据目录，指定数据目录且无显式路径时使用数据目录下的戳。测试隔离写入实际落在该用例的 `tmp_path`，共享默认路径无写入。
- [ ] AC-004：DB/schema/LISTEN 每次重新检查，Worker 派生结果使用短 TTL。就绪失败或 LISTEN 断开后，恢复检查重新读取 Worker 信号。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。

## 上下文区

- 关联 spec：docs/specs/mail_sync_and_storage.md
- 来源：p105，2026-11-28 复现于 `060e0893`。承接 t096 的分布式显式戳与测试隔离覆盖。

### 有意不测

- 生产环境部署由现有流程负责。本 task 用进程入口、实际文件操作和就绪请求验证运行配置。

### 测试策略

- 将 CLI、环境变量及显式戳矩阵跑过生产启动和 `/ready` 入口。使用受控时钟及文件 mtime。
- 以单元测试验证隔离夹具与路径优先级。复跑 t095/t096 的缓存、监听失效、Watcher/Worker 组合回归及双 Compose 配置检查。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

无。

### 风险与回退

- 风险：直接 ASGI 启动和 Python CLI 的配置注入路径可能分歧，嵌入式部署可能误报就绪。以入口矩阵与独立 Worker 健康检查覆盖。
- 回退：回退实现 commit 即恢复旧启动与探针行为，整个变更无数据库迁移。

### 依赖与约束

- 无硬依赖。t099 若并行修改 `__main__.py`，合并时保留两处入口调用并复验。

### Finalization 时更新的 blueprint

- `docs/blueprint/conventions.md`：更新生效运行模式和存活戳路径规则。
- `docs/blueprint/testing.md`：登记 CLI/环境变量与存活戳的端到端就绪矩阵。
