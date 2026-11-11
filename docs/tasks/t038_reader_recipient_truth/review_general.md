# Task review t038（reviewer_focus: 通用）

- task：`t038_reader_recipient_truth`
- spec：`docs/tasks/t038_reader_recipient_truth/spec.md`
- diff_anchor：`852c01372e17a4d858050eb2e9fed148870e5495`
- target：`git -C '<local-path>' diff 852c01372e17a4d858050eb2e9fed148870e5495`
- round：1
- reviewed_at：2026-10-23T08:30:25+08:00
    reviewed_scope: c7d98aa05d8bc76d

## Findings

### t038_gen_f001 - 详情未加载或请求失败时把未知 To 显示为“未提供”

- 严重度：important
- 锚点：行为缺陷。详情请求仍 pending 或失败时，尚无 To 数据；当前界面却把未知状态呈现为“未提供”，将请求状态误报为邮件收件人事实。
- 位置：`src/frontend/src/components/MessageReader.tsx:182`
- 问题：`detail` 尚未加载或请求失败时，`detail?.to || '未提供'` 都会显示“收件人：未提供”。例如详情 API 返回 500，页面同时显示请求错误和“收件人：未提供”，但请求失败不能证明邮件没有 To；网络延迟期间也会先显示该错误结论。
- 建议：按详情加载中、请求失败、详情已加载但 To 为空分别渲染；仅在详情成功且 To 缺失/空字符串时显示“未提供”。补充延迟响应和详情请求失败用例。

## 结论

- 前轮 finding 复核：首轮，无前轮 finding。
- 本轮新发现：1 条。
- 未进表的提示：规格、实现正确性、安全、契约与类型、性能与资源、架构与可维护性、健壮性与可观测、测试与文档配置均已检查；无其他提示。

### AC 复验方式

- AC-001：`re_verified`。`MessageReader.test.tsx` 的空 To 与缺失 To/Bcc-only 用例验证不显示账号邮箱/Bcc，并验证账号归属仍显示 `[REDACTED_EMAIL]`。

- AC-002：`re_verified`。多收件人用例断言 MR07 与详情 API 的 To 值完全一致；空/缺失 To fixture 也有自动化覆盖。全量前端测试通过。

- AC-003：`re_verified`。切换邮件用例从 m-1 切到 To 为空的 m-2，断言当前显示“未提供”且不再显示前一封地址；实现使用按邮件 ID 区分的详情 query，且 `placeholderData` 为 `undefined`。

- 复验命令：在 `src/frontend` 执行 `npm test`（38 个文件、214 项通过，OpenAPI 与 CSS token 检查通过）、`npm run build`、`npm run lint`，均通过。

- coverage = 3 / 3

- 总体判断：存在 1 条 important 行为缺陷，详情加载失败时会把未知收件人显示成未提供，需修复后复审。

- 系统性 follow-up：无。

verdict: FAIL

## Round 2 (2026-10-23T08:34:01+08:00)

reviewed_scope: 3ec8fbc6a0fd018d

## Findings

无。

## 结论

- 前轮 finding 复核：`t038_gen_f001` 已消除。`MessageReader.tsx:181-185` 仅在详情数据存在时渲染 MR07；详情 pending 与请求失败用例分别断言 MR07 不存在（`MessageReader.test.tsx:240-255,291-304`）。
- 本轮新发现：0 条。
- 未进表的提示：规格、实现正确性、安全、契约与类型、性能与资源、架构与可维护性、健壮性与可观测、测试与文档配置均已检查；无范围外观察、文件规模或复杂度提示。

### AC 复验方式

- AC-001：`re_verified`。空 To 与缺失 To/Bcc-only 用例断言显示“未提供”、不展示账号邮箱或 Bcc，并单独验证账号归属仍为 `[REDACTED_EMAIL]`（`MessageReader.test.tsx:338-357`）。

- AC-002：`re_verified`。多收件人用例逐字断言详情 API To 值；同文件覆盖空 To 与缺失 To（`MessageReader.test.tsx:323-357`）。

- AC-003：`re_verified`。切换用例先显示 m-1 的 To，再切到 m-2 的空 To，断言只显示“未提供”、不残留前一封地址（`MessageReader.test.tsx:360-383`）。

- 复验命令：`npx vitest run src/components/MessageReader.test.tsx`（23 项通过）；全量前端脚本（38 个测试文件、214 项通过，OpenAPI 与 CSS token 检查通过）。

- coverage = 3 / 3

- 总体判断：前轮 important finding 已修复；本轮未发现 critical / important 问题。

- 系统性 follow-up：无。

verdict: PASS
