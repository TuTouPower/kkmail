# Task t002 Review: General

## Round 1

reviewed_scope: 94e5e5caf7d55d98

### 审查结论

verdict: PASS

### 检查项核验

1. **AC 覆盖**：
   - AC-001：侧边栏「个人收藏」展示「所有收件箱」、「所有未读」、「所有已发邮件」三个顶级条目，各自可独立折叠与展开。
   - AC-002：「所有收件箱」展开后展示账号列表，父项显示总未读数，账号项显示各自未读数（为 0 不显示）。
   - AC-003：「所有未读」与「所有已发邮件」展开后展示账号列表，父项与子项均不显示角标。
   - AC-004：点击顶级与账号子项切换对应分类与账号视图。
2. **测试与质量**：
   - 更新 `Sidebar.test.tsx` 覆盖折叠树、角标展示与点击交互。
   - 更新 `MessageList.test.tsx` 覆盖 `folder_role=sent` 与 `is_read=false` 查询。
   - 更新 `mailStore.test.ts` 覆盖 favorite 导航重置逻辑。
   - 全量单元测试（117 passed）、前端构建打包、桌面端测试以及 Playwright E2E 冒烟测试全部通过。
3. **架构与文档**：
   - 更新 `docs/blueprint/architecture.md`、`docs/specs/inbox_ui_and_search.md` 与 `docs/specs_index.md`。
