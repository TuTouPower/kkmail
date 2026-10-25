# Task review t048（reviewer_focus: 代码）

- task：`t048_mime_parse_error_with_body_and_fetch_isolation`
- spec：`docs/tasks/t048_mime_parse_error_with_body_and_fetch_isolation/spec.md`
- diff_anchor：`0c8c13278374c46de79d3732554b6eb74406ca3e`
- target：`git -C '<local-path>' diff 0c8c13278374c46de79d3732554b6eb74406ca3e`
- round：1
- reviewed_at：2026-10-23T23:25:00+08:00
reviewed_scope: 6b35458f0220547a

## Findings

无。

## 结论

- 前轮 finding 复核：首轮，无前轮 finding。
- 本轮新发现：0 条。
- 未进表的提示：规格合规、实现正确性、安全、契约·类型、性能·资源、架构·可维护性、健壮性·可观测、测试与文档均已全面核验；无范围外修改。

### AC 复验方式

- AC-001：`re_verified`。核验 `src/mail_core/blobs/archive.py`：`parse_mime_content` 遇到未转义 QP 或解码瑕疵时记录 `first_error`，同时通过多编码回退完整提取可读正文并附于 `MimeParseError`；`run_archive_batch` 捕获后记录 `body.parse_error` 但保留 `body.text_html` / `body.text_plain`，不被置为 None。
- AC-002：`re_verified`。核验 `src/frontend/src/components/MessageReader.tsx`：当 `detail.parse_error` 非空且存在 `body` 时，同时渲染 `data-ui="MR-PARSE-ERROR"` 告警框与正文 iframe/text；当 `body` 为空时仅展示告警框，不出现空正文占位；核验 `queries.py` 中 `_body_previews` 移除对 `parse_error.is_(None)` 的过滤，只要有正文即生成摘要。
- AC-003：`re_verified`。核验 `src/mail_core/blobs/archive.py:657-688`：`provider.fetch_mime` 发生异常时仅更新 `MessageArchiveState.last_error`，移除对 `MessageBody.parse_error` 的写入；未归档邮件打开时无误报且重试同步入口正常工作。
- AC-004：`re_verified`。核验 `src/mail_core/providers/imap.py`：新增 `open_session` 与 `close_session`，`fetch_mime` 复用 `_active_client`；`run_archive_batch` 在同批同一账号下建立一次连接登录，并在循环后统一登出。

- coverage = 4 / 4

- 总体判断：全部 4 条 AC 均已精确实现并经过集成与单测验证，0 finding，判定 PASS。

- 系统性 follow-up：无。

verdict: PASS
