---
tid: "t014"
slug: "backend_test_isolation"
title: "隔离后端测试状态并建立确定性数据夹具"
status: "done"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: "t013"
conflicts_with: ""
note: "本会话批准测试增强；本地复用专用 PG 容器、每轮独立测试库；仅创建 backlog"
---

# Task 过程总账

按用户要求直接在 main 实施，不调用 task.py、不建 worktree、不写 attempt。front matter 保留工具链原值，本次执行结果以正文、review 报告及 Git commit 为准。

## 实施笔记

- 基线 `8f93e8e`。先加真实提交哨兵：第二用例读到第一用例 Account，测试明确失败；修复后通过。
- 全部用例采用最小一致策略：在独占本轮数据库内清理业务表，保留 Alembic 状态；不包裹外层 rollback，不改变生产 autoflush=False、commit、锁和 NOTIFY 语义。
- Worker/LISTEN 先停止并 join，再关闭实际 checkout Connection、Session 与 Engine，恢复 credential store、provider、dispatcher、鉴权/登录限流/schema cache、SSE 计数。setup/teardown 清理失败均停止套件；子 pytest 验证后续测试体不执行。
- 双连接哨兵保持 A 占用，同时申请 B，比对两个 pg_backend_pid，并验证 B 可见真实 commit。正常与断言失败路径均检查 Worker/LISTEN 停止、裸 Connection.closed 和旧 PG PID 消失。
- factory 包含多账号、空目录、中文 multipart MIME、跨账号重复 Message-ID、相同排序时间、真实加密 MIME/附件 Blob；生产 keyset 查询校验所有邮件无重无漏。
- 混合文件改逐项 PG 标记，释放此前被整文件跳过的纯单元用例，包含 SSE 连接上限测试。保留既有断言；SSE 派发仅补真实 subscriber，gap hint 仅补独立事件种子，不依赖前序自增值。
- 新增直接 psycopg LISTEN：commit 前无通知、commit 后收到生产 NOTIFY。独立子进程临时禁用 NOTIFY 后对应测试确实失败并返回 1，未将变异写入实现。
- `KKMAIL_TEST_SEED` 控制独立随机序列并输出重放入口；行/分支覆盖限定生产 mail_core。coverage 数据、XML/JSON、JUnit 和执行/跳过/未执行汇总均写本轮目录。

## Review 处置

- 已修 important：入口清理失败不能只报单例 ERROR；现设置 session.shouldstop 并记录失败，回归验证 exit 2 与后续用例不执行。
- 已补：双物理连接、checkout 连接关闭、真实 Worker 失败后停止和 API lifespan 收尾证据。
- 已补 important 测试缺口：旧 listener 测试有 idle polling 兜底；新增无轮询的 PG 通知测试，并实际验证禁用 NOTIFY 会失败。
- 独立代码审查见 `review_code.md`；独立测试审查见 `review_test.md`。无未解决 important/critical；最终两轮、资源回收及报告范围已由主会话核实。

## 收尾报告

### 验收与验证

- 结果：实现、独立 code/test review 与最终两轮验证完成。
- 红后绿：跨用例 committed Account 污染先失败、隔离后通过。
- 定向：14 passed；新增 NOTIFY 正向 1 passed，禁用 NOTIFY 的隔离变异按预期失败。
- 快速：252 passed / 102 skipped；纯单元 SSE cap 无 PG 执行通过。
- 乱序：最终 seed 41、17 均为 354 collected / 352 passed / 2 skipped，JUnit testcase 集合完全相同；无失败、错误或未执行项。两轮约 260/273 秒，报告包含各阶段耗时。
- 资源：两轮数据库名不同，容器 ID、PG system identifier、postmaster start time 保持复用；结束后无测试库或 owner role 残留。
- 覆盖：87 个生产模块文件，行/分支综合覆盖 78.63% / 78.66%；仅作为缺口观测，不设统一硬阈值。
- 黑盒：真实 PG 双连接提交、锁竞争、LISTEN/NOTIFY、API lifespan 与 Worker 清理，未依赖业务数据库或真实邮箱。
- 覆盖：生产模块行/分支 XML 和 JSON，已核验范围仅 src/mail_core/，不设统一百分比掩盖缺口。

### AC 证据

|AC|证据|
|---|---|
|AC-001|最终 seed 41、17 各 352 passed / 2 IMAP skipped；失败输出包含 seed 与 nodeid|
|AC-002|账号、设置、鉴权、邮件、WorkerJob、Outbox 提交哨兵；每例起始空表|
|AC-003|同时占用两连接且 PID 不同、既有 SKIP LOCKED/fencing、直接事务性 NOTIFY 与禁用通知负向验证|
|AC-004|正常/AssertionError 后 Worker/LISTEN 停、checkout 连接关闭和 PG PID 消失，API lifespan 正常退出|
|AC-005|确定 UUID、固定时间/MIME boundary、重复 Message-ID 跨账号、空目录、真实附件解密与生产分页|
|AC-006|纯单元 PG 标记拆分、快速模式显式边界、JUnit/执行汇总和生产行/分支覆盖|

### 结果摘要

未修改生产逻辑；修复测试状态泄漏及旧测试缺失前置。两项真实 IMAP 跳过属于 t016 尚未启动的专用协议服务，不能计为真实 IMAP 通过。
