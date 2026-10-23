---
tid: "t047"
slug: "dark_palette_and_reader_copy"
title: "调整深色模式冷青灰三栏色阶与阅读器空报头及未同步文案"
status: "done"
branch: "t047_dark_palette_and_reader_copy"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "70092c148d5fae963d0b1966f60b780e2b7ecacd"
depends_on: ""
conflicts_with: ""
note: "来源 p029、p030；统一三栏深冷青灰递进色阶、缺失发件人/收件人留白与未同步正文文案。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 调色盘与色阶对齐：
   - 更新深色模式核心三栏背景色：`--sidebar: #1C1F21`、`--list: #212628`、`--reader: #222729`、`--mail-body: #222729`，形成深冷青灰调自左向右递进。
   - 同步微调 `--canvas` 为更深冷底色 `#16191A`，Electron 桌面端 `windowBackgroundColor` 同步调整为 `#16191A`；微调 `--surface: #282D30`、`--surface-2: #31373A`、`--surface-hover: #2B3134`、`--selected: #33393D`、`--line: #2C3235`，保持色阶和谐并跑通 CSS Token 校验。
   - `mailBody.ts` 自适应深色正文底色同步更新为 `#222729`。
2. 缺失报头与文案优化：
   - 发件人缺失时留白：`displayName` 在 `!raw` 时返回 `""`，阅读器发件人地址行在邮箱缺失时直接留白，不再出现“未知”或悬空标签。
   - 收件人缺失时留白：`MessageReader` 的 `MR07` 收件人区域在 `detail.to` 缺失时直接留白，不再显示“未提供”。
   - 正文未同步占位文案：占位区域明确为“邮件正文尚未完成同步”，彻底剔除“或内容为空”等模糊描述。
3. 验证与规范：
   - 更新 `darkTheme.test.ts`、`mailBody.test.ts`、`windowOptions.test.js`、`displayName.test.ts`、`MessageReader.test.tsx` 既有测试断言，并在 `docs/blueprint/conventions.md` §九.2 同步最新占位文案规范。

## Review 处置

### Round 1 (2026-10-23T22:45:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`(cd src/frontend && npm test && npx tsc -b && npm run build && npm run lint)` 39 文件 265 项全通；`(cd src/desktop && npm test)` 全通；`pytest .repo_template/tests -q -m contract` 150 项全通；`scripts/run-mail-core-tests.sh unit` 309 项全通。
- 黑盒：`npm --prefix src/frontend run test:e2e`（14 项全部通过）；`python3 scripts/run_full_stack_e2e.py`（8 项全栈真实端到端测试全通）。
- review：`docs/tasks/t047_dark_palette_and_reader_copy/review_general.md` 单轮 PASS，0 finding。
- AC 证据：见 `handoff.json`

### 结果摘要

- 调整深色模式核心三栏背景为深冷青灰递进色阶（#1C1F21、#212628、#222729）及配套表面色，发件人/收件人缺失时统一留白不显“未知”/“未提供”，阅读器未同步正文占位文案明确化。遗留：无。
