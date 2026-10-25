# Task review t048（reviewer_focus: 测试用例）

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
- 未进表的提示：测试充分覆盖 AC-001 ~ AC-004 的正向行为、异常场景及边界隔离，无弱化断言或假绿。

### AC 复验方式

- AC-001：`re_verified`。`tests/mail_core/test_archive_decode_failure.py` 新增 `test_wecom_qp_unescaped_defect_retains_readable_html_and_sets_parse_error`，断言企微未转义 QP 邮件归档后 `parse_error` 非空且 `text_html` 保留可读正文；PostgreSQL 实测通过。
- AC-002：`re_verified`。`src/frontend/src/components/MessageReader.test.tsx` 新增两项用例断言非空 `body` + `parse_error` 时同时渲染错误告警与正文，空 `body` + `parse_error` 时仅展示错误告警且无空占位；Vitest 实测通过。
- AC-003：`re_verified`。`tests/mail_core/test_on_demand_body_sync.py` 更新用例断言拉取超时仅记录 `st.last_error` 且 `body.parse_error` 为 None；实测通过。
- AC-004：`re_verified`。`tests/mail_core/test_archive_scheduler.py` 新增用例断言同批次 3 封 IMAP 邮件归档期间 `login` 与 `logout` 分别仅调用 1 次；实测通过。

- coverage = 4 / 4

- 总体判断：测试用例全面覆盖各项 AC，断言严格触达生产逻辑与数据模型，0 finding，判定 PASS。

- 系统性 follow-up：无。

verdict: PASS
