---
tid: "t008"
slug: "account_folder_navigation"
title: "支持真实账号文件夹与收藏分类导航"
status: "done"
branch: "t008_account_folder_navigation"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "06f714cfaf9d77157b1eb90cf4c289ff14982836"
depends_on: ""
conflicts_with: ""
note: "来源 p013；复用 folder-stats 与角色检索，补齐精确文件夹范围"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 后端实现：在 `src/mail_core/providers/imap.py` 中增加 RFC 3501 Modified UTF-7 解码器与 SPECIAL-USE（\Sent, \Drafts, \Trash, \Junk, \Archive）标志解析；支持中文目录名映射与分隔符提取 parent_remote_id；在 `queries.py` 与 `mail.py` 中贯通精确 `folder_id` 过滤、多位置邮件 keyset 去重，以及在 `mutations.py` 中限定单目录批量标已读范围。重新导出并生成 OpenAPI 契约。
2. 前端实现：扩展 `mailStore`、`listTitle`、`Sidebar` 与 `MessageList`，支持六类个人收藏（收件、未读、已发、草稿、废纸篓、垃圾邮件）和账号独立展开入库文件夹树（支持真实父子层级与空目录）；导航切换时自动清空搜索与选择；缓存键追加 `folder:${folderId}` 隔离。
3. 验证与门禁：编写 `test_account_folder_navigation.py`、扩展前端单元测试，并通过全量门禁命令（381 passed）、Playwright UI 冒烟测试与真实全栈端到端测试。更新 blueprint decisions.md、architecture.md 与 conventions.md。

## Review 处置

无 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部通过
- 测试：`scripts/run-mail-core-tests.sh run` (381 passed), 前端单元 (169 passed), 桌面打包冒烟 passed
- 黑盒：`npm --prefix src/frontend run test:e2e` (3 passed), `python3 scripts/run_full_stack_e2e.py` (3 passed)
- review：code PASS / test PASS / overall PASS
- AC 证据：见 `handoff.json`

### 结果摘要

- 个人收藏扩充为“所有收件”“所有未读”“已发邮件”“草稿箱”“废纸篓”“垃圾邮件”六类独立展开类目；
- 邮箱账户支持独立展开真实入库文件夹树，呈现真实层级，空目录正常呈现，保留远端名称；
- 后端支持精确 `folder_id`keyst 翻页检索、多标签位置去重与单目录批量标已读；
- IMAP 协议层支持 SPECIAL-USE 标志优先级映射与 Modified UTF-7 解码，分离可读名称与协议标识符。
