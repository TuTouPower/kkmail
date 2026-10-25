# p048 新邮件打开触发按需同步时与后台归档竞态报 already archived 错误

- 现象：新收到的邮件列表已展示，点击邮件进入阅读器（MessageReader）时，界面显示“正在归档”占位（“后台正在同步邮件正文…”），随后右侧报错显示红色错误文字：“message body is already archived”（用户提示为“This mail is archived”），邮件正文无法加载；刷新页面后才能正确显示已归档邮件。
- 影响：用户在新邮件到达且后台 Worker 正在或刚好完成正文归档期间点击该邮件，必现/高概率触发 409 报错并阻断邮件正文正常展示，造成用户对归档状态产生困惑，必须依赖整页刷新才能解除异常。
- 根因：
    1. 后端非幂等抛错机制：`sync_message_body`（`src/mail_core/mail/application/message_details.py:60-61`）在状态为 `ARCHIVE_COMPLETE` 时抛出 `MessageBodyAlreadyArchived`，并在 API 层（`src/mail_core/api/mail.py:490-491`）转化为 HTTP 409 错误；按需同步正文未做到幂等容错（邮件已归档本属最终期望状态，不应视为客户端错误）。
    2. 前端阅读器竞态与异常阻断：`MessageReader`（`src/frontend/src/components/MessageReader.tsx:104-118, 129-145`）在首次读取到 `is_archived: false` 时触发 `handleSyncBody`，遇到 409 报错直接落入 `syncError` 并在界面渲染红色错误提示，未在此分支下失效查询并重新拉取最新已归档正文，导致界面停留在错误态。
    3. 已确认同类位点：
        - 后端：`src/mail_core/mail/application/message_details.py:60-61`、`src/mail_core/api/mail.py:490-491`（按需同步接口需支持幂等返回已归档或已完成，而非 409）。
        - 前端：`src/frontend/src/components/MessageReader.tsx:104-118`（错误处理应识别 `already archived` 冲突并自动重新拉取 detail，而非停留报错）。
- 测试缺口：
    1. `tests/mail_core/test_on_demand_body_sync.py` 缺失按需同步正文在并发/已完成归档时的幂等性验证。
    2. `src/frontend/src/components/MessageReader.test.tsx` 缺少当接口返回已归档冲突时前端自动刷新并恢复正文展示的测试用例。
- 线索：`.scratch/repro_already_archived.py` 验证了后端 `MessageBodyAlreadyArchived` 抛出与未幂等处理机制。
- 处理：review_20261026_005019
