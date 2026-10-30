---
tid: "t065"
slug: "dark_mode_mail_body_inversion"
title: "深色模式支持邮件正文智能深色渲染与原色切换"
status: "done"
branch: "t065_dark_mode_mail_body_inversion"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "750d2d0537350b3d539661b035de7c354995b60a"
depends_on: ""
conflicts_with: ""
note: "邮件正文在深色模式下智能反转浅色背景为深色底，保持图片原色并提供单信原色切换按钮"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 调研 5 款开源邮件客户端（Thunderbird、Mailspring、SnappyMail、Cypht、Zero）深色模式实现原理，确立基于 CSS 智能反转（Mailspring 方案）结合单信工具栏逃生通道（Thunderbird 方案）的架构路线；
- 采用 TDD 流程：先建立 `mailBody.test.ts`、`MessageReader.test.tsx`、`SettingsModal.test.tsx` 与 `persistence.test.ts` 失败测试（RED）；
- 在 `mailBody.ts` 中针对 `theme === 'dark'` 且 `classification === 'light'` 注入智能反转滤镜与图片二次反转+微光轮廓样式；
- 在 `MessageReader.tsx` 中移除浅色邮件默认的白底 `mail-paper-card`，并增加 `MR11` 工具栏开关灯切换按钮（`Sun`/`Moon`），支持单信覆盖；
- 在 `mailStore.ts` 中增加 `mailBodyDarkMode` 偏好项并持久化到 `mail-ui-storage`；在 `SettingsModal.tsx` 通用外观板块增加对应分段控制；
- 运行并通过全量前端单元测试、构建打包与 Playwright E2E 黑盒冒烟测试（新增单信开关灯与智能深色 E2E 场景）。

## Review 处置

### Round 1 (2026-10-30T10:05:00+08:00)

Round 1 零 finding

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：53 test files, 562 tests passed (`npm test && npx tsc -b && npm run build`)
- 黑盒：19 Playwright tests passed (`npm --prefix src/frontend run test:e2e`)
- review：single level Round 1 PASS (0 finding, reviewed_scope ok)
- AC 证据：见 `handoff.json`

### 结果摘要

- 深色模式下浅色 HTML 邮件默认以智能反转高保真深色呈现，不再呈现突兀白底卡片；图片等媒体二次反转还原色彩并附带微光轮廓；
- 邮件阅读器工具栏新增单信「原样视图 / 深色视图」切换按钮（`MR11`），兼顾极端复杂邮件的可读性逃生通道；
- 通用设置提供「邮件正文深色渲染」默认偏好配置（「智能深色」与「保留原色纸张」），选择即时生效并持久化到本地存储。
