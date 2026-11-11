---
pid: "p072"
slug: "idle_catchup_enqueue_failure_starvation"
status: "closed"
resolution: "resolved"
reason: "已在 t073 修复并验证"
fix_ref: "t073"
---
# p072 建连补偿 delta 入队失败后 held 账号可能持续缺失邮件

- 现象：t071 在建连/重连成功时入队一次收件箱补偿 `SYNC_FOLDER_DELTA`。若该次入队因数据库瞬时错误失败，`_enqueue_catchup` 只记录日志并继续 `idling`；账号仍处于 held 状态，t057 收件箱轮询继续跳过。若此后既无新的 IDLE 变化事件、也不发生重连，断线窗口内到达的邮件会持续缺失。
- 影响：AC-005 只要求入队失败不终止 watcher、不标记账号 failed，未要求自愈；但失败一次即可造成与 p070 相同的静默滞后，持续时间取决于下一次事件/重连，可能无限期。
- 根因：补偿入队是一次性副作用，失败被隔离后没有重试、降级轮询或延迟重入队机制；held 状态与“补偿已成功”之间没有状态耦合。
- 测试缺口：AC-005 测试只验证“首次入队失败后 watch 继续、后续 changed 事件仍能入队”，未覆盖“失败后没有后续事件”的长期缺失场景。应补：入队失败后按有界退避重试，或失败时暂时让出 IDLE 席位触发 t057 轮询，或持久化待补偿标记由调度器重试；测试需覆盖失败后无事件时的最终收敛。
- 线索：`src/mail_core/sync/idle_watcher.py` 的 `_enqueue_catchup` try/except；t071 代码 review Round 1/2/3 均将该项列为残余风险（非 blocking）。
- 处理：t073；resolution=resolved；reason=已在 t073 修复并验证
