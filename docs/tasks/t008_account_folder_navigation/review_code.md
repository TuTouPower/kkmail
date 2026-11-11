# Task review t008（reviewer_focus: 代码）

- task：`t008_account_folder_navigation`
- spec：`docs/tasks/t008_account_folder_navigation/spec.md`
- diff_anchor：`06f714cfaf9d77157b1eb90cf4c289ff14982836`
- target：`git -C '<local-path>' diff 06f714cfaf9d77157b1eb90cf4c289ff14982836`
- round：1
- reviewed_at：2026-10-23T00:35:00+08:00

reviewed_scope: be2cf72fee07feec

## Findings

无。

## 结论

- 本轮新发现：0 条
- 未进表的提示：无
- 总体判断：实现完全符合 AC-001 至 AC-007 规范。IMAP SPECIAL-USE 标志与 mUTF-7 解码正确分离协议 remote_id 与可读展示名；后端 keyset 分页按 message_id 去重支持多位置邮件；folder_id 精确查询与 mark-all-read 正确隔离作用域；前端状态机在导航切换时干净重置搜索与选择。OpenAPI 及生成代码保持严格同步。
- 系统性 follow-up：无

verdict: PASS
