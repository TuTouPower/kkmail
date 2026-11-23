---
pid: "p089"
slug: "gmail_label_historical_backfill"
status: "closed"
resolution: "transferred"
reason: "已核实根因与回填范围并转交该 task"
fix_ref: "t088"
---
# p089 Gmail 历史邮件的 Important 标签成员一次性回填

- 来源：t086 code review `t086_code_f002`（minor 遗留）。
- 内容：t086 把 Gmail `\Important` 改为由常规 metadata FETCH 的 `X-GM-LABELS` 派生 `message_locations`，迁移 `20261123_0004` 只回填 `folders.kind` 与视图状态。迁移前已入库的历史邮件若尚未被带标签的常规同步重新抓取，其 Important 成员会暂时缺失，视图计数偏小；All Mail 视图因投影全部物理目录位置，不受影响。需要一次性回填作业：对既有 Gmail 账号按物理目录重放带 `X-GM-LABELS` 的 metadata 扫描，把 `\Important` 成员补写为 view folder 的 location；作业幂等、不增加 `messages` 行数。t086 未做是因为它涉及独立的长时扫描与进度/限流设计。核实更正：增量同步只取 `(FLAGS UID)`，不为旧 UID 重取标签，已完成的 full-scan checkpoint 也不会自动重跑，因此**不会随增量逐步收敛**，必须显式回填。
- 处理：t088；resolution=transferred；reason=已核实根因与回填范围并转交该 task
