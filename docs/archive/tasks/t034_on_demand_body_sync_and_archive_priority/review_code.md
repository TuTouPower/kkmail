# Task review t034（reviewer_focus: 代码）

- task：`t034_on_demand_body_sync_and_archive_priority`
- spec：`docs/tasks/t034_on_demand_body_sync_and_archive_priority/spec.md`
- diff_anchor：`ed3bfeecc579b99de892b9c364de03101efb9531`
- target：`git -C '<local-path>' diff ed3bfeecc579b99de892b9c364de03101efb9531`
- round：1
- reviewed_at：2026-10-23T14:15:00+08:00

reviewed_scope: 86dfd16022521d64

## Findings

Round 1 零 finding。

## AC 验证

- AC-001：`re_verified`，查验 `src/mail_core/api/mail.py:289-308` 与 `340-362`，在 `api_get_message` 和 `api_sync_message_body` 中，处于未归档且无错误状态的邮件被置为最高优先级（`st.priority = 0`，推进到 `ARCHIVE_PENDING`），并入队高优归档任务（`priority=10`, `dedupe_key=f"archive_msg:{message_id}"`）；`src/mail_core/blobs/archive.py:250` 在认领时保护高优先级不被默认时间规则覆盖。
- AC-002：`re_verified`，查验 `src/mail_core/api/mail.py:364-374` 与 `src/mail_core/blobs/archive.py:511-530,932,950`，`run_archive_batch` 接收 `payload["message_id"]` 定向锁定单封邮件完成 MIME 拉取、解析及附件元数据入库，更新为 `archive_complete`，且单封完成后不递归入队常规批次。
- AC-003：`re_verified`，查验 `src/mail_core/blobs/archive.py:939,957` 与 `src/mail_core/sync/delta.py:437-438`，常规后台批量归档任务调整为 `priority=60`，文件夹增量空转轮询调整为 `priority=75` 并设置 `dedupe_key=f"delta:{account_id}:{folder_id}"`，严格遵循数值越小优先级越高的队列规则，消除了优先级倒挂与饥饿。
- AC-004：`re_verified`，查验 `src/frontend/src/components/MessageReader.tsx:61-92,245-251` 及 `MessageReader.test.tsx:389-399`，阅读器检测到 `is_archived === false` 且未完成时，自动触发按需拉取并展示旋转图标与“正在优先同步邮件正文…”动态反馈，拉取完成后即刻更新 query 缓存并平滑渲染正文。
- AC-005：`re_verified`，查验 `src/mail_core/blobs/archive.py:626-640` 与 `src/frontend/src/components/MessageReader.tsx:252-270` 及 `MessageReader.test.tsx:401-410`，远端 Provider 拉取失败时经 `safe_error` 记录并持久化至 `MessageBody.parse_error`，前端展示明确错误提示与“立即重试同步”操作，避免无限 loading。

coverage = 5/5 = 100%

## 结论

- 前轮 finding 复核：首轮无前轮
- 本轮新发现：0 条
- 未进表的提示：
  - 文件过大提示：`src/mail_core/blobs/archive.py`（967 行，>800 行）、`src/mail_core/api/mail.py`（504 行，>400 行）、`src/mail_core/sync/delta.py`（443 行，>400 行）为已有核心模块，本次修改为契约内增量且逻辑内聚，无跨层越界，不阻断。
- 总体判断：代码实现严谨高效，契约区 AC 全部实现且有确定性证据；按需正文拉取与调度优先级治理彻底解决了历史邮件归档饥饿问题；前后端错误状态透传闭环，无安全隐患。
- 系统性 follow-up：无

verdict: PASS
