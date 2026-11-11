# Task review t004（reviewer_focus: 通用）

- task：`t004_fix_accounts_dto_and_sidebar_error`
- spec：`docs/tasks/t004_fix_accounts_dto_and_sidebar_error/spec.md`
- diff_anchor：`f915e78bcfc81767386f86b5e9f2448235f44fa7`
- target：`git -C '<local-path>' diff f915e78bcfc81767386f86b5e9f2448235f44fa7`
- round: 1
- reviewed_at: 2026-10-22T07:37:00+08:00

reviewed_scope: d519784fe2200e8a

## Findings

Round 1 零 finding。

## 结论

- 前轮 finding 复核：首轮无前轮
- 本轮新发现：0 条
- 未进表的提示：无
- 总体判断：后端改用 dataclasses.asdict 彻底修复 slots 属性缺失导致的 AttributeError 500；补充单元测试以 Mock AccountDTO 形式在路由层固化测试，防止日常开发无 DB 环境假绿；前端使用 errorMessage 真实透传错误信息并添加重试按钮，由组件测试覆盖。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：`re_verified`，`test_accounts_api_unit.py::test_list_accounts_serializes_slotted_dtos_mock` 与 `test_accounts_api_pg.py::test_group_and_account_lifecycle` 执行通过，成功序列化各字段，无 500。
- AC-002：`re_verified`，`test_accounts_api_unit.py::test_create_account_serializes_slotted_dto_mock` 与 `test_update_account_serializes_slotted_dto_mock` 执行通过，正确返回 `AccountOut`。
- AC-003：`re_verified`，`Sidebar.test.tsx` 模拟 500 异常，断言错误节点正确渲染真实错误信息，不再显示假定未登录文案。
- AC-004：`re_verified`，`Sidebar.test.tsx` 模拟点击重试按钮触发 accountsQuery/groupsQuery 重新拉取并成功恢复渲染。
- AC-005：`re_verified`，在未设置 `MAIL_CORE_DATABASE_URL` 下执行 `pytest tests/mail_core/test_accounts_api_unit.py` 100% 通过（7/7 passed）。

coverage = 5/5 = 100%

verdict: PASS
