# 主任务调用链补查

- 范围：当前全库 HEAD `daca631aec54c30ce02cdb5e6499ae196dc3a72d`；主体分视角完成后的调用点补查。
- 时间：2026-10-21T04:18:49+08:00
- 验证：只读代码与调用链，不运行DB/服务/完整测试；不修改源码。

## Findings

- [Medium][99] mail_core/mail/application/mutations.py:203 L197-L206 — trash 在 DELETE flush 前重算目录计数，统计仍包含已删邮件 — session factory 明确 `autoflush=False`（db/session.py:57）；trash_message 只 session.delete(loc/msg)，立即调用 recompute_folder_stats 的 SQL aggregate，此时DELETE还未发送。后续 _wake_push/enqueue_job 或函数末尾才flush，最终保存旧total/unread计数。触发：通过当前trash API删除任意目录中一封邮件；folder-stats API返回未扣除该邮件的计数，下一次触发完整重算前保持错误。与metadata/delta多location统计问题不同，本项是删除flush顺序。修复：DELETE后、重算前显式session.flush()，再按所有受影响目录重算；测试单目录与多目录trash后total/unread。证据：`session.delete(msg); _recompute_stats_for_folders(...); _wake_push(...); session.flush()`；[当前代码](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/mail/application/mutations.py#L197-L206)。依据：application层统计事务一致性。未进行PG复现，源码执行顺序与禁用autoflush确定。

- [Medium][99] frontend/src/components/MessageList.tsx:204 L204-L217 — 多选框键盘事件冒泡触发行打开，空格不能正常勾选并误标已读 — article的onKeyDown对所有Enter/空格直接preventDefault并openMessage(m)，没有校验e.target===e.currentTarget；内部checkbox button仅onClick stopPropagation，没有keydown隔离。在checkbox聚焦按空格/Enter时，事件先冒泡到article、默认button激活被阻止，却执行openMessage；用户本想多选，实际选择正文并可能发markRead请求。修复：行keydown只处理target为行本身的事件，或给内层button停止键盘冒泡并保留原生button默认激活。测试需focus多选按钮后按空格，断言selectedIds改变且没有select/open/read。证据：`if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openMessage(m) }` 与 `onClick={(e)=>{e.stopPropagation();toggleSelected(key)}}`；[源码](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/frontend/src/components/MessageList.tsx#L204-L217)。依据：项目可访问交互与操作范围应一致；现有测试只测行自身Enter。

- [Medium][99] desktop/main.js:185 L173-L187 — macOS关闭唯一窗口后保留无窗口进程，Dock点击无法重新打开 — window-all-closed在darwin不退出符合常规驻留，但全文件/全desktop没有activate处理，createWindow仅在whenReady调用一次。窗口关闭后backend/PG持续运行，应用仍在Dock；再激活没有代码重建BrowserWindow，必须退出后重启才能恢复界面。修复：app.on('activate')且BrowserWindow.getAllWindows().length===0时，用已启动后端URL调用createWindow；或明确关闭窗口就退出进程。证据：`if (process.platform !== 'darwin') app.quit()`，`rg activate desktop`无匹配；[生命周期源码](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/desktop/main.js#L173-L187)。依据：desktop当前macOS交付目标；未启动真实Electron验证。

- [Medium][95] frontend/src/api/queries.ts:106 L103-L110 — Reader从任意缓存取首个同ID消息，可能覆盖当前列表的新状态 — findCachedMail遍历所有mail-core query并立即返回第一个命中项，不参考当前view/query或dataUpdatedAt。SSE invalidateQueries默认只refetch活动query；先打开unified inbox，再切account inbox后远端flag/read变化，旧unified缓存仍保留旧行且先插入，当前account列表已新。MessageReader却使用旧unified行显示flag/read与构造操作，甚至基于旧flag发出相反desired-state。修复：Reader从当前活动列表读取selected实体，或按唯一消息ID维护单一实体状态，并使所有list投影同步；至少从最新成功更新时间选命中项，不把cache插入顺序当权威。证据：`for (const [,list] of queryClient.getQueriesData(...)) { const hit=...; if(hit)return hit }`；[源码](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/frontend/src/api/queries.ts#L103-L110)。本项与detail query未被SSE失效不同：即使detail刷新，reader按钮仍来自findCachedMail列表行；前端缓存行为待补组件复现。

## Traceability

- 规则：AGENTS.md；intensive-review正确性、健壮性、测试行为可达性视角。
- 全库任务报告存量缺陷，不归因为最新commit；未使用旧review作为事实依据。
- 上述四项由主任务补查，原分视角报告保留，最终统一去重。
