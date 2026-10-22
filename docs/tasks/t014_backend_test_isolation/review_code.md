# t014 代码审查

## 范围

按用户授权，在 main 审查 t014 未提交实现，不使用 task.py、worktree 或 attempt。覆盖共享隔离 fixture、数据库清理、线程与连接回收、状态恢复、人工数据 factory、混合测试 PG 分类、SSE 前置条件、乱序执行及独立覆盖报告。本审查未读取密钥文件、操作数据库或修改实现。

## Finding 处置

- 已修 important：setup 阶段清理异常原先只导致当前用例 ERROR，后续用例仍执行。setup/teardown 现均记录失败并设置 `session.shouldstop`；子 pytest 回归检查 exit 2 且后续测试体未执行。
- 已补证据：提交隔离测试在 A 连接保持占用时申请 B，并比较 `pg_backend_pid()`，避免连接池复用同一物理连接掩盖问题。
- 已补证据：登记实际 checkout Connection，停止 Worker/LISTEN 后关闭连接并 dispose 相关 engine。正常及 AssertionError 回归均启动真实 Worker、LISTEN 并故意保留裸 Connection；检查线程停止、Connection.closed、旧 PID 不在 `pg_stat_activity`。
- 已补证据：真实 API lifespan 回归检查 listener 随退出停止。直接 psycopg LISTEN 回归检查 commit 前无通知、commit 后收到生产 NOTIFY，避免 idle dispatch 掩盖通知失效。

## 语义与范围

SSE 派发测试新增真实 subscriber，并校验收到原事件；gap-hint 测试补充独立 Outbox 数据，使原正数 cursor 不再依赖前序 sequence。原 cursor、hint 及派发断言保留，未改预期迎合输出。

混合文件改用逐项 PG 标记，独立单测保持收集。factory 使用固定时间、确定 UUID 和 MIME boundary，同时间分页触达生产查询，并验证跨账号重复 Message-ID、空目录和真实加密附件。覆盖范围限定 `mail_core`，覆盖数据、报告与汇总写入本轮目录。未修改生产行为。

## 验证边界与结论

主会话已核实最终两轮：seed 41、seed 17 均收集 354 项，352 passed / 2 skipped，JUnit node 集合完全相同，无 PG 条件 skip、错误或未执行项。两轮数据库不同，容器 ID、PG system identifier、postmaster start time 保持相同；结束后无测试数据库或 owner role 残留。生产模块报告覆盖 87 个文件，branch 覆盖率分别为 78.63% / 78.66%；快速模式 252 passed / 102 skipped。末次分类调整移除纯单元 SSE cap 测试 PG 标记，已完成无 PG 验证。

新增 NOTIFY 用例正向通过，独立子进程临时禁用生产 notify 后，该回归确实失败并返回 1，未保留变异。完整套件仅两项 IMAP 测试因缺服务跳过；真实 IMAP 协议交互仍不在本次已执行证据内。

结论：代码审查 PASS，无未解决 critical/important。最终版本连续两轮、两个固定 seed、报告与跳过原因已由主会话核实；本报告不代替整项 task 验收结论。
