---
pid: "p093"
slug: "gmail_label_backfill_folder_failure_resilience"
status: "closed"
resolution: "resolved"
reason: "单目录失败隔离并继续其它目录，瞬态 FETCH 最多重试 3 次；新增 PG 用例，定向 PG 24 passed、unit 1694 passed"
fix_ref: "main"
---
# p093 回填应隔离单目录失败并重试瞬态网络错误

- 现象：生产回填 5 个 Gmail 账号，2 个 completed，3 个因单个目录 `SELECT ... failed: NO` 或 `read operation timed out` / `socket EOF` 整体失败，且反复重跑仍卡在同一目录。
- 影响：t088 回填无法在存在不可 SELECT 目录或网络抖动的账号上收尾；已写入的 `message_locations` 保留但不写完成标记，命令每次都从头重放。
- 根因：`backfill_account` 把每个账号的全部目录放在同一个 try 里，任一目录的 provider 异常立即终止该账号，既不跳过坏目录也不重试瞬态错误。
- 测试缺口：现有 PG 用例的 provider 对所有目录都成功，未覆盖单目录失败与瞬态超时；应补用例：一个目录抛错、其它目录继续落库并写完成标记；一次超时后重试成功。
- 线索：生产命令输出（3 个账号 failed，`upserted` 分别 224/514/1550）；宿主网络可达 imap.gmail.com，容器不可达，回填从宿主直连生产库执行。
- 处理：main；resolution=resolved；reason=单目录失败隔离并继续其它目录，瞬态 FETCH 最多重试 3 次；新增 PG 用例，定向 PG 24 passed、unit 1694 passed
