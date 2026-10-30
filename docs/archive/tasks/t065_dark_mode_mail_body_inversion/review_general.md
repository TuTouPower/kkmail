# Task review t065（reviewer_focus: 通用）

- task：`t065_dark_mode_mail_body_inversion`
- spec：`docs/tasks/t065_dark_mode_mail_body_inversion/spec.md`
- diff_anchor：`750d2d0537350b3d539661b035de7c354995b60a`
- target：`git -C '<local-path>' diff 750d2d0537350b3d539661b035de7c354995b60a`
- round：1
- reviewed_at：2026-10-30T10:05:00+08:00
reviewed_scope: db962c595a47beae

## Findings

无。

## 结论

- 前轮 finding 复核：首轮，无前轮 finding。
- 本轮新发现：0 条。
- 未进表的提示：规格、实现正确性、安全、契约与类型、性能与资源、架构与可维护性、健壮性与可观测、测试与文档配置均已逐一审查。
  - 规格合规：AC-001 ~ AC-006 行为均完整实现且有自动化测试覆盖；
  - 正确性与安全：iframe 严格沙箱无脚本基线未受影响，CSS 智能反转在隔离 iframe 内部运行，媒体元素二次反转保真；
  - 架构与类型：`mailBodyDarkMode` 偏好在 store 与 `mail-ui-storage` 中原子持久化；
  - 外部依赖与契约：无新增外部包，无 schema 变动。
- 总体判断：全部 6 条 AC 均已精确实现并经过单元、组件及端到端浏览器测试验证，0 finding，判定 PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：`re_verified`。核验 `src/frontend/src/lib/mailBody.ts:167` 及 `src/frontend/src/components/MessageReader.tsx:501`：深色模式且 `classification === 'light'` 时注入 `filter: invert(100%) hue-rotate(180deg)`，且不渲染 `.mail-paper-card`；`mailBody.test.ts`、`MessageReader.test.tsx` 及 Playwright `smoke.spec.ts` 实测通过。
- AC-002：`re_verified`。核验 `src/frontend/src/lib/mailBody.ts:168`：对 `img,video,canvas,picture` 施加二次反转 `filter:invert(100%) hue-rotate(180deg)` 及 `drop-shadow(0 0 1px rgba(255, 255, 255, 0.7))`；`mailBody.test.ts` 实测断言通过。
- AC-003：`re_verified`。核验 `src/frontend/src/lib/mailBody.ts:157`：`isDarkPlain = isDark && !shouldInvert && classification !== 'light'`，纯文本与深色邮件保持原生深底背景 `#222729`，不应用反转滤镜；`mailBody.test.ts` 实测通过。
- AC-004：`re_verified`。核验 `src/frontend/src/components/MessageReader.tsx:298` 及 `:501`：深色模式下浅色邮件在工具栏展示切换按钮（`MR11`），点击切换为原样视图时出现 `.mail-paper-card` 且正文移除反转滤镜，再次点击恢复深色；`MessageReader.test.tsx` 与 Playwright `smoke.spec.ts` 实测通过。
- AC-005：`re_verified`。核验 `src/frontend/src/components/MessageReader.tsx:229` 及 `:298`：`showDarkToggle = resolvedTheme === 'dark' && Boolean(html) && isLightMail`，浅色模式下 `showDarkToggle` 为 `false` 且不渲染切换按钮，正文不反转；`mailBody.test.ts` 与 `MessageReader.test.tsx` 实测通过。
- AC-006：`re_verified`。核验 `src/frontend/src/store/mailStore.ts:87`、`src/frontend/src/components/SettingsModal.tsx:520` 及 `src/frontend/src/test/persistence.test.ts`：设置面板提供「智能深色」与「保留原色纸张」选项，切换即时更新 `mailBodyDarkMode` 并持久化到 `mail-ui-storage`；`SettingsModal.test.tsx` 与 `persistence.test.ts` 实测通过。

- coverage = 6 / 6

verdict: PASS
