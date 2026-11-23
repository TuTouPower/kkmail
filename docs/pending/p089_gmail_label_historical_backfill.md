---
pid: "p089"
slug: "gmail_label_historical_backfill"
status: "todo"
---
# p089 Gmail 历史邮件的 Important 标签成员一次性回填

- 来源：t086 code review `t086_code_f002`（minor 遗留）。
- 内容：t086 把 Gmail `\Important` 改为由常规 metadata FETCH 的 `X-GM-LABELS` 派生 `message_locations`，迁移 `20261123_0004` 只回填 `folders.kind` 与视图状态。迁移前已入库的历史邮件若尚未被带标签的常规同步重新抓取，其 Important 成员会暂时缺失，视图计数偏小；All Mail 视图因投影全部物理目录位置，不受影响。需要一次性回填作业：对既有 Gmail 账号按物理目录重放带 `X-GM-LABELS` 的 metadata 扫描（复用 `apply_metadata_page` 的同一路径），把 `\Important` 成员补写为 view folder 的 location；作业幂等、不增加 `messages` 行数。本 task 未做是因为它涉及独立的长时后台作业与进度/限流设计，且常规同步会随增量逐步收敛，不阻断 t086 的视图模型改造。
- 处理：未开
