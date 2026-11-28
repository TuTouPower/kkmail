# 20261128 单机运行时收敛与巡检健康门禁统一

## 背景

生产 Docker 全栈审计：三容器常驻 ~624 MiB、空闲 ~8.4% CPU、23 万次事务 ROLLBACK；巡检对同一异常账号每个目录反复建连并逐行写盘；根因不是配置值偏大，而是权威状态机被旁路、并发预算散落多处、探针耦合业务读模型。

## 决策

1. **单机默认单进程编排**：新增 `docker-compose.embedded.yml` 作为单机自托管默认入口（API + 内嵌 Worker 单进程，进程先迁移后启动）；`docker-compose.mail-core.yml --profile distributed` 保留为可选多机扩展。两种模式通过不同 compose 文件天然互斥，共享数据卷、切换时旧容器退场、数据沿用。

2. **单一并发预算源**：`mail_core/runtime_budget.py` 定义基准预算；连接池默认由 10/10 收敛至 4/4、IDLE 配额由 32 收敛至 8，均由该模块派生；DB 参数 `shared_buffers=64MB/work_mem=2MB/max_connections=40/checkpoint_timeout=15min`，并保持 `synchronous_commit=on`（不以异步提交代替检查点调优）。

3. **巡检账号级门禁**：删除 `patrol.py` 局部 `provider_errors`；首个账号级传输/认证失败写账号级 patrol 冷却（`account.config` 的 `patrol_cooldown_until`）并短路本轮剩余目录，跨轮冷却由该状态持有、单一 sweeper 天然无并发半开。后台传输失败继续隔离（t090），不污染 `connectivity_state`；永久认证失败走凭据状态；单目录错误只影响该目录；冷却过期后下一轮自然发起真实探测（恢复探测由 patrol 自身承担）。

4. **探针与业务读解耦**：`/ready` 全部走 Core Connection（无 ORM Session/ROLLBACK），worker 状态读带 5s TTL 缓存且只缓存 worker 信号（DB/schema/LISTEN 每次读新值，断开立即失效）；Worker 主循环刷新 tmpfs 存活戳，容器 healthcheck 仅校验戳新鲜度（不冷启解释器查库）；三类 healthcheck interval 统一 30s。

5. **提交耐久性**：仅独立心跳等可丢弃状态允许异步提交；邮件、checkpoint、Outbox、同步请求结算与带远端副作用的业务事务保持同步提交，崩溃不丢已答复结果。

## 影响

- 五项 AC 的可观察契约见 task.md；`runtime_budget` 为新增模块；compose 新增 `docker-compose.embedded.yml`。
- 语义失效的旧测试（pool 默认 10/10、healthcheck DB 路径）按 TDD 规则重写并注明理由。
- IDLE 线程数上界 = 2×idle_quota（watcher + 会话 reader），账号数超过 quota 时不建额外线程；内存绝对值由受控基准验证而非产品默认值推断。
- 与 t094（水位权威/队列索引）共同修改 Worker 运行入口与关联 spec，按章节归属协调写域。
