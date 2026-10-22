---
tid: "t026"
slug: "mime_archive_decode_failure"
title: "邮件 MIME 解析失败在前端明确报错"
status: "done"
branch: "t026_mime_archive_decode_failure"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "76865ff7a3a72e3cd40aff368bd6297d4b3d775f"
depends_on: ""
conflicts_with: ""
note: "来源 p020；用户确认不处理历史乱码；正文/报头/附件名解析失败持久记录并在前端报错；保留原文，无产品契约阻塞"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

来源 p020。2026-10-23 已核实 MIME 解析缺口及 parse_error 在前端转换丢失。用户澄清历史乱码已手动处理，无需历史乱码修复；任何本 task 涉及的 MIME 解析错误必须直接在前端报错。

范围收敛为正文/报头/附件名解析失败持久记录与阅读器明确提示。正常缺失字段提取不扩改，沿用原文归档与解析结果分离模型。原两项产品契约阻塞已消除；原 AC-001/AC-002 撤销且不复用，新前端行为编号 AC-006/AC-007。当前仅维护 backlog，不 start、不改生产代码。

2026-10-23 实施记录：
1. TDD 先行增加前端单测与组件测试（mailCore.test.ts、MessageReader.test.tsx），驱动 MailDetail 补充 parse_error 字段、mailCoreToMailDetail 透传该状态，并在 MessageReader 中增加 role="alert" 解析失败横幅，避免被空占位覆盖；
2. 后端 blobs/archive.py 新增 MimeParseError 异常与严格解码/缺陷拦截，覆盖正文 UnicodeDecodeError/LookupError、报头 undecodable/charset 缺陷及附件文件名 undecodable 缺陷与提取异常；
3. run_archive_batch 遇 MIME 解析失败记录脱敏日志与 MessageBody.parse_error，保持原始 MIME 完整入库并跳过损坏派生物，不阻塞同批次其他合法邮件；
4. 编写 tests/mail_core/test_archive_decode_failure.py，在真实 PostgreSQL + BlobStore 上验证正文、报头、附件名三类失败及同批次隔离；添加 Playwright E2E 冒烟测试验证浏览器阅读器报错与跨邮件隔离；
5. 更新 blueprint 规范与 d001 技术发现；门禁全量通过，review 双轴 PASS。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-23T03:35:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`scripts/run-mail-core-tests.sh run` 392 passed；`npm test` 188 passed；`npm test` (desktop) passed；`pytest .repo_template/tests -q -m contract` 149 passed
- 黑盒：`npm --prefix src/frontend run test:e2e` 4 passed；`python3 scripts/run_full_stack_e2e.py` 3 passed
- review：code PASS, test PASS, overall PASS, review_scope ok
- AC 证据：见 `handoff.json`

### 结果摘要

- MIME 正文、报头、附件名解析失败持久记录 parse_error 并向前端传递；
- 阅读器明确展示“邮件解析失败”提示及脱敏原因，不再被空占位遮蔽；
- 失败邮件与正常邮件切换彻底隔离，原始 MIME 完整保留，同批次其他邮件正常归档。
