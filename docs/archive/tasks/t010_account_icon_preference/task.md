---
tid: "t010"
slug: "account_icon_preference"
title: "账号图标展示偏好"
status: "done"
branch: "t010_account_icon_preference"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "a673de4bc2d94863f8369f8d2dd3bc84b070f7c7"
depends_on: ""
conflicts_with: ""
note: "来源 p015；侧栏与设置页统一使用本地偏好"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 状态与偏好：在 `src/frontend/src/store/mailStore.ts` 中增加 `accountIconMode`（默认 `'brand'`），纳入 localStorage 持久化偏好；新建 `src/frontend/src/store/accountIcon.ts` 实现精确域名匹配（Gmail、Outlook/Hotmail/Live、163/126、QQ）与首字母提取（支持 Unicode 与代理对安全）。
2. 组件统一：新建 `src/frontend/src/components/AccountIcon.tsx`，支持 none（完全移除圆点不留占位）、brand 与 initials 模式，替换 `Sidebar.tsx` 与 `SettingsModal.tsx` 中写死的 account-dot；并在设置外观面板提供即时切换单选按钮。
3. 验证与门禁：编写 `accountIcon.test.ts`、`AccountIcon.test.tsx` 并更新 `persistence.test.ts`；通过全量前端测试、构建、桌面打包冒烟与 Playwright E2E。更新 `docs/blueprint/conventions.md`。

## Review 处置

无 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部通过
- 测试：前端单元 (178 passed), 桌面打包冒烟 passed, 后端全量 (381 passed)
- 黑盒：`npm --prefix src/frontend run test:e2e` (3 passed), `python3 scripts/run_full_stack_e2e.py` (3 passed)
- review：general PASS / overall PASS
- AC 证据：见 `handoff.json`

### 结果摘要

- 设置外观页提供“不展示 / 品牌图标 / 首字母”可访问选项，持久化存储并即时生效；
- none 模式完全移除圆点，不留空位占位；
- brand 模式按精确邮箱域名匹配常见服务商，未知域名回退至通用图标，防止子串伪造；
- initials 模式提取首字符，安全兼容 Unicode 代理对与异常空输入；
- 资源随包离线加载，不发起任何外网第三方请求。
