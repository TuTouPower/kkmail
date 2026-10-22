---
tid: "t007"
slug: "imap_header_decode"
title: "修复 IMAP 裸 GBK 报头解码"
status: "done"
branch: "t007_imap_header_decode"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "f9cc7ade0022aa687cf5d7eedaf5ce05203c18ef"
depends_on: ""
conflicts_with: ""
note: "来源 p011；生产解析入口已复现字节损坏"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 复现与红灯：编写 `tests/mail_core/test_imap_header_decode.py`，覆盖 AC-001 至 AC-004。确认在未修复前，裸 GBK 报头在 `_parse_message_meta_from_fetch` 入口被 UTF-8 replace 强制破坏导致 `\ufffd` 替换符。
2. 架构与实现：在 `src/mail_core/providers/imap.py` 中重构报头处理入口，以 `email.message_from_bytes` 保留原始字节；实现确定性解码策略：优先 RFC 2047 声明字符集，无声明或未知编码依次尝试严格 UTF-8、严格 GB18030（兼容 GBK/GB2312），无法恢复时确定性降级替换；隔离各报头字段防止损坏扩散。
3. 验证与绿灯：运行单元测试、PostgreSQL 迁移与集成测试（377 passed）、前端与桌面端测试、以及真实全栈 E2E（Playwright 3 passed），全门禁通过。

## Review 处置

无 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部通过
- 测试：`scripts/run-mail-core-tests.sh run` (377 passed), 前端与桌面测试全绿
- 黑盒：`npm --prefix src/frontend run test:e2e` (3 passed), `python3 scripts/run_full_stack_e2e.py` (3 passed)
- review：code PASS / test PASS / overall PASS
- AC 证据：见 `handoff.json`

### 结果摘要

- 修复 IMAP 报头未封装裸 GBK/GB2312 编码导致的主题与发件人乱码缺陷；
- 建立确定性字符集回退降级顺序与多字段隔离保护机制；
- 补充真实元数据重新拉取更新旧损坏记录与全文字搜索索引测试。
