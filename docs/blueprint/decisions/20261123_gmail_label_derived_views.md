# 2026-11-23 Gmail 虚拟标签改为派生视图

- **决策**：废除把 Gmail `\All` / `\Important` 当作 `paused` 同步单元的模型（`t056`）。`folders.kind` 区分物理 mailbox（`container`，唯一同步单元）与派生只读视图（`view`，不入任何作业队列、无 `paused` 语义）。
- **理由**：同一封邮件被虚拟全量标签重复抓取会造成邮件数成倍膨胀；`paused` 只是回避重复 IO，却让两个一等导航视图永久为空，`p060` 进一步删除手动兜底，UI 用未知角标 `-` 掩盖空壳。根因是"汇总标签被建模为同步容器"。
- **机制**：常规 metadata FETCH 在 `X-GM-EXT-1` capability 下增补 `X-GM-LABELS`；标签成员落为 `message_locations`。All Mail 投影为账号下全部非垃圾/废纸篓物理目录的位置，Important 投影为 `\Important` 标签的位置；计数与列表均按邮件身份去重，零额外往返。
- **后果**：`engine` / `delta` / `reconcile` / `patrol` / `idle_watcher` / `mutations` / `worker` / `sync_requests` 统一以 `kind==container` 过滤同步目标；迁移 `20261123_0004` 回填 `kind` 并把历史虚拟目录重置为 `idle`。t056 的"手动点进触发同步"与 p060 的前端同步路径表述作废。
- **兼容**：无双读路径，旧 `paused` 虚拟目录语义随迁移整体移除。
