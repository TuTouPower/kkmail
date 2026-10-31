# Task review t069（reviewer_focus: 测试）

- task：`t069_remote_image_extract_and_fetch_robustness`
- spec：`docs/tasks/t069_remote_image_extract_and_fetch_robustness/spec.md`
- diff_anchor：`7cbeb45e060ced1b683fe21664ed7c03ad801e1d`
- target：`git -C '$WORKTREE' diff 7cbeb45e060ced1b683fe21664ed7c03ad801e1d`
- round：1
- reviewed_at：2026-10-31T17:25:00+08:00
reviewed_scope: 6cf3ca1a9281fec0

## Round 1 (2026-10-31T17:25:00+08:00)

### Findings

Round 1 零 finding。

### 维度核验

1. 测试可信：
   - 提取测试触达生产 `extract_remote_image_urls`，覆盖无引号、单双引号、大写标签/属性、实体解码、协议相对、空值与超长 URL、生产 Google 邮件形态。
   - 连接回退测试注入可控 connector，验证真实 `_connect_with_fallback` 的排序与错误分类（不连外网、不 mock 被测逻辑本身）。
   - API 错误分类测试驱动真实 FastAPI 路由：504/502/415 断言状态码，并断言响应体不含内部细节。
   - E2E 新用例在真实 Chromium + 生产 CSP 下断言 3 张图片 `naturalWidth > 0`、背景图已重写为代理 URL、console 零 CSP 违规，属于用户可观察行为。
2. 覆盖：
   - AC-001~004：后端矩阵 + 前端重写单测 + E2E 三层覆盖；
   - AC-005：后端集成覆盖 504/502/415（400/401/403/404/413 由既有测试覆盖）；
   - AC-006：多 IP 顺序、超时、全不可达三例；
   - AC-007：静态 SVG 接受 + 7 类危险内容参数化拒绝 + 超限拒绝；
   - AC-008：既有 39 项代理集成全部保留通过；
   - AC-009：stub 夹具新增生产形态邮件并真实解码。
3. 危险模式扫描：
   - 无恒真断言、无删/反转 expect、无 `.skip`、无 `eslint-disable`/`ts-ignore`；
   - 改测审查：`test_detect_safe_image_mime` 删除两条「SVG 必须拒绝」旧断言，原因是 spec AC-007 明确将合法 SVG 纳入放行范围（规格变更，非迁就实现），并在测试内注释说明；新增 `test_detect_svg_mime` 与 `validate_svg_payload` 测试覆盖新语义，符合 TDD 规范。`_connect_with_fallback` 测试的首版期望顺序写错（误以为会尝试全部 IP），按实际短路逻辑修正为「前两个 IPv4，第二个成功即返回」——修正的是测试自身的错误预期，生产行为符合规格。
   - `test_fetch_safe_remote_image_mock_opener` 使用 `mock_opener` 是既有测试注入点，非本 task 新增的生产 mock。
4. 基线既存失败（非本 task 引入）：`test_microsoft_oauth.py::test_device_concurrent_poll_and_save_use_same_identity_guards_pg` 在 main 上同样 429 失败；前端 `npm run lint` 的 Sidebar exhaustive-deps 错误在 t068 合并时已存在。

### AC 复验方式

- AC-001：`re_verified` — 重跑 E2E 21 passed，新增用例断言无引号图片解码。
- AC-002：`re_verified` — 重跑后端与前端实体用例，断言 URL 无实体残留且重写命中。
- AC-003：`re_verified` — 重跑协议相对提取与前端重写用例。
- AC-004：`re_verified` — 重跑背景图（任意元素 style）三种形态用例。
- AC-005：`re_verified` — 重跑 504/502/415 集成断言与固定文案检查。
- AC-006：`re_verified` — 重跑回退顺序与错误分类单测。
- AC-007：`re_verified` — 重跑 SVG 接受/拒绝/超限参数化用例。
- AC-008：`re_verified` — 重跑 39 项代理 PG 集成（含 SSRF、大小、Token、撤销）。
- AC-009：`re_verified` — 重跑 E2E 新夹具，3 张代理图 `naturalWidth > 0`、零 CSP 违规；生产原文提取计数由 0 增至 6。

coverage = 9 / 9 (100%)

verdict: PASS
