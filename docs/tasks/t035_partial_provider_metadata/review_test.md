# Task review t035（reviewer_focus: 测试）

- task：`t035_partial_provider_metadata`
- spec：`docs/tasks/t035_partial_provider_metadata/spec.md`
- diff_anchor：`852c01372e17a4d858050eb2e9fed148870e5495`
- target：`git -C '<local-path>' diff 852c01372e17a4d858050eb2e9fed148870e5495`
- round：1
- reviewed_at：2026-10-23T08:47:26+08:00

reviewed_scope: 235037ac26070ab1

## Findings

### t035_test_f001 - 既有 Graph parser 测试原位改写

- 严重度：minor
- 锚点：AC-001 / 改测方向复核
- 位置：`tests/mail_core/test_gmail_graph_contracts.py:67`；当前断言见同文件第 95-99 行
- 问题：已有的 `test_parse_graph_delta_flag_only_without_content_metadata` 被改名并原位修改预期：仅有 `isRead` 时，旧断言要求 `is_flagged=False`，现改为只含 `is_read`。新预期符合 AC-001，未发现覆盖弱化；但旧测试语义因 spec 变更失效时，规则要求整体删除旧测试并另建新测试说明原因，不能原位迁移。
- 建议：整体删除旧测试，再用独立的新测试覆盖 AC-001 新契约，并记录旧断言对应行为已被 spec 替代。

## 结论

- 改测方向复核：1 处既有测试原位修改；新预期符合 AC-001，不属于迁就当前实现，但不符合旧测试失效后的处理规则。
- 本轮新发现：1 条
- 未进表的提示：parser 测试文件在 `KKMAIL_TEST_MODE=unit` 下运行，20 passed。PostgreSQL 更新用例未实际运行；本轮已核对其调用生产更新函数及精确存储断言。
- 总体判断：仅有 minor finding，无未解决 critical / important；测试轴 PASS。
- 系统性 follow-up：无

### AC 复验方式

以下 `re_verified` 包含独立核对测试断言与被测生产路径；PostgreSQL 用例未实际执行。

- AC-001：`re_verified`。parser 测试断言 Graph 局部状态仅含已返回键；数据库测试将 parse 结果传给 `apply_delta_page`，并检查读/标记字段保留与更新。
- AC-002：`re_verified`。Gmail/IMAP parser 测试覆盖附件状态缺失；metadata 更新测试检查已有 true/false 在 None 时保留、明确 true/false 时更新。
- AC-003：`re_verified`。自动化测试分别触达 Graph/Gmail/IMAP parser，以及 `apply_delta_page` 和 `apply_metadata_page` 的生产更新路径。
- coverage = 3 / 3

verdict: PASS

## Round 2 (2026-10-23T08:52:21+08:00)

reviewed_scope: d007d7f37a900891

### Findings

无。

### 结论

- 前轮 finding 复核：t035_test_f001 已消除。相对 diff anchor，旧测试 `test_parse_graph_delta_flag_only_without_content_metadata` 整体删除；独立的 `test_graph_delta_partial_status_field_presence_contract` 位于文件末尾（`tests/mail_core/test_gmail_graph_contracts.py:560`），重新覆盖 AC-001 的字段存在性。旧测试预期与新契约冲突的原因也已记录；以 diff 确认测试变更完成。
- 改测方向复核：无迁就实现的改测。旧测试整体删除，新契约测试独立新增。
- 本轮新发现：0 条
- 未进表的提示：parser 套件重跑结果为 20 passed。PostgreSQL 更新用例本轮未实际运行，已核读其生产调用路径与存储断言。
- 总体判断：f001 已消除；无未解决 critical / important，测试轴 PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：`re_verified`。Parser 测试位于 `tests/mail_core/test_gmail_graph_contracts.py:560`；数据库测试将 parse 结果传入 `apply_delta_page` 并断言字段更新与保留，见 `tests/mail_core/test_delta_flag_patch.py:78`。
- AC-002：`re_verified`。Provider parser 缺失状态覆盖见 `tests/mail_core/test_gmail_graph_contracts.py:67`；metadata 更新测试覆盖 None 保留既有值以及明确 true/false 更新，见 `tests/mail_core/test_metadata_apply.py:197`。
- AC-003：`re_verified`。parser 测试与 `apply_delta_page` / `apply_metadata_page` 更新测试均存在，并核对其真实生产调用路径。
- coverage = 3 / 3

verdict: PASS
