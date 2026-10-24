# p038 QQ“其他文件夹”元数据同步失败

- 现象：三个 QQ 账号的 `其他文件夹` 均没有 `folder_stats`，侧栏显示蓝色 `-`。队列中留有 5 个该目录元数据任务失败，各重试 8 次；错误为 `UID SEARCH <folder> failed: NO`。只读探测发现三个服务器都把该路径标为 `\NoSelect \HasChildren`，账号之一存在可同步的子目录 `QQ邮件订阅`。
- 影响：三个 QQ 账号的旧父目录记录仍显示为可点击邮箱，却没有邮件统计；不可选择的父目录曾被当作邮箱执行同步并失败。蓝色 `-` 是未读数未知标记，不是错误图标。子目录邮件仍有独立统计与同步状态。
- 根因：IMAP `list_folders` 已过滤 `\NoSelect`，但 `sync_account_folders` 只 upsert 本轮返回目录，不标记或移除数据库中已不再返回的旧目录。旧父目录因此保留在 `folders`，folder-stats API 仍返回它，历史元数据任务在 `SELECT` 返回 OK 后执行 `UID SEARCH`，QQ 回应 `[CLIENTBUG] No mailbox selected`。父目录和子目录的关系来自有效 IMAP 路径；修复必须保留子目录及历史邮件位置，不能级联删除旧目录数据。
- 测试缺口：`test_imap_list_folders_filters_noselect_and_nonexistent` 已确认 Provider 过滤 `\NoSelect`，但没有覆盖数据库中已有旧目录的发现后状态、待处理任务处置、层级容器呈现及计数标记。应补同步发现回归：远端 `\NoSelect` 父目录不再作为可点击/可同步邮箱，子目录仍保留层级和消息位置，历史邮件数据不被删除。
- 线索：`.scratch/mailbox_folder_grouping_repro.sql`、`.scratch/qq_imap_protocol_probe.py`；三账号 raw LIST 均为 `\NoSelect \HasChildren`，只读 `SELECT`/`UID SEARCH` 复现 QQ 返回的 no-mailbox-selected 响应。
- 处理：t052
