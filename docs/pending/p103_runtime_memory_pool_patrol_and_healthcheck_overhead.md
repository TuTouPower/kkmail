---
pid: "p103"
slug: "runtime_memory_pool_patrol_and_healthcheck_overhead"
status: "closed"
resolution: "transferred"
reason: "2026-11-28 核实熔断状态机被局部 dict 旁路、阻塞 IDLE 与 ORM 探针仍在，按开发铁律以根因重构方案转交 t095"
fix_ref: "t095"
---
# p103 运行时内存收敛、单进程嵌入模式、连接池与 PG 调优及巡检健康检查减负

- 来源：生产 Docker 全栈内存与性能审计（2026-11-28），`kkmail` 三容器常驻 `~624 MiB`（`worker` `312.2 MiB RSS + 33 MiB Swap` / 23 线程、`pg` `213.5 MiB` / 29 进程、`api` `97.9 MiB` / 8 线程），无用户操作时空闲合计占用 `~8.4%` CPU 且累计产生 `232,762` 次数据库事务 `ROLLBACK`。
- 内容：
    针对单机容器化运行态存在的双进程冗余、连接池过配、Worker 匿名堆驻留、故障邮箱高频无效巡检及重型容器健康探针五大开销源，系统实施减负与性能调优：
    1. **单机默认编排收敛为内嵌 Worker 单进程架构（预计立省 `~120–160 MiB`）**：
        - `docker-compose.mail-core.yml:104-190` 当前推荐以 `--profile distributed` 同时运行独立 `api` 与 `worker` 两个 Python 3.13 容器（各自加载完整 FastAPI/SQLAlchemy/psycopg/加密密钥环并各自维护独立连接池与 `LISTEN` 连接），而代码库已原生支持 `MAIL_CORE_EMBEDDED_WORKER=1` 单进程内嵌模式（`docker-compose.mail-core.yml:137, 155`）。为单机自托管提供开箱即用的单容器运行编排（保留 `distributed` profile 仅面向多机/高吞吐扩展场景）。
    2. **收敛 SQLAlchemy 连接池规模与 PostgreSQL 容器参数（减少十余个常驻后端进程与刷盘抖动）**：
        - 连接池：`src/mail_core/db/session.py:69-76` 默认每个进程配置 `MAIL_CORE_DB_POOL_SIZE=10`、`MAIL_CORE_DB_MAX_OVERFLOW=10`，导致双进程下 PostgreSQL 长期维持 `22–25` 个 `idle` 后端进程（每个后端进程映射共享缓冲区与目录缓存后 RSS 达 `63–153 MiB`），且实测观察到池连接归还前的短暂 `idle in transaction`。将默认池尺寸下调至匹配真实并发槽位（如 `pool_size=4, max_overflow=4`，单进程模式下总连接数控制在 `6–8` 以内）。
        - PostgreSQL 参数：`docker-compose.mail-core.yml:27-46` 裸跑默认配置 `postgres:16.15`（`max_connections=100`、`shared_buffers=128MB`、`checkpoint_timeout=5min`、`synchronous_commit=on`）。针对本地单机邮件工作负载显式调优 `shared_buffers=64MB`、`work_mem=2MB`、`max_connections=40`、`checkpoint_timeout=15min`，并评估对后台同步/心跳写事务采用局部 `SET LOCAL synchronous_commit = off` 消除每 5 分钟耗时数十秒的刷盘抖动。
    3. **Worker `312 MiB` 匿名堆驻留收敛与 IMAP IDLE 配额按需化**：
        - 实测 `kkmail-mail-core-worker` 匿名页 `[anon]` 达 `281.9 MiB`（另有 `33 MiB` Swap）。主因包括：`src/mail_core/sync/idle_watcher.py:76-95` 默认 `idle_quota=32`（同时维持最多 32 个线程与 SSL/IMAP 长连接上下文），以及最大 `50 MB` MIME 邮件解析与正文清洗在大并发槽位（`total_slots=8`）下造成 glibc 多线程内存分配器碎片高水位不归还。
        - 方案：将单机默认 `idle_quota` 下调至合理主力收件箱数（如 `6–8`），在 `Dockerfile.mail-core` 统一设置 `MALLOC_ARENA_MAX=2`，并审查大体积 HTML/附件入库链路的峰值字节拷贝。
    4. **全目录 `patrol` 与账号级连通性熔断/指数退避联动（消除无效网络探测与脏页写入）**：
        - 实测 `kkmail-mail-core-worker` 日志每隔数秒持续刷出同一批异常账号（如 `779e78c6`、`a64fed24`、`a4bf9bce`、`e53eead1`、`6ac21184`）旗下不同文件夹的 `patrol probe failed ... IMAP4Error phase=imap`，同时每探一个失败文件夹就执行一次 `UPDATE folder_patrol_status` 写盘。
        - 根因：`src/mail_core/sync/patrol.py:91-240` 虽按文件夹推进 `last_probe_at` 避免单文件夹死循环，但①未跳过已处于 `ConnectivityState.UNREACHABLE` 熔断打开态的账号；②同一轮 `selected` 中某账号首个文件夹因网络/认证级错误（非单文件夹不存在错误）失败后，未将该账号加入 `provider_errors` 短路本轮剩余文件夹，而是继续逐个文件夹建连碰壁并逐行 flush 更新数据库。应将账号级传输/认证故障直接短路同账号剩余目录并纳入账号级退避冷却。
    5. **重构高频容器 Healthcheck 与 `/ready` 只读事务回滚风暴**：
        - `docker-compose.mail-core.yml:183-187` 每 `10s` 执行 `python -m mail_core.worker.healthcheck`，每次冷启动一个全新 Python 3.13 解释器、导入 SQLAlchemy/psycopg 并建连查库（每天冷启动 **8,640 次**）。
        - `docker-compose.mail-core.yml:150-153` 每 `5s` 执行 `curl -fsS http://127.0.0.1:8000/ready`，而 `src/mail_core/api/app.py:210-245` 每次调用打开两个未显式提交的只读 ORM Session，关闭时向 PG 发送 `ROLLBACK`（实测 `pg_stat_activity` 满屏 `ROLLBACK`，全库累计 `xact_rollback = 232,762` 次），且 PG 自身也每 `3s` 跑 `pg_isready`。
        - 方案：API `/ready` 内的只读探针改用 `AUTOCOMMIT` 轻量查询并做短 TTL（如 `5s`）内存缓存；Worker 健康探针改为由常驻心跳线程原子刷新 `/tmp`（tmpfs）本地存活戳文件、探针仅校验文件新近度而不再冷启数据库连接；将 `postgres` / `api` / `worker` 的 Docker `healthcheck.interval` 统一放宽至 `30s`。
- 处理：t095；resolution=transferred；reason=2026-11-28 核实熔断状态机被局部 dict 旁路、阻塞 IDLE 与 ORM 探针仍在，按开发铁律以根因重构方案转交 t095
