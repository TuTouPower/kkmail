# Task review t036（reviewer_focus: 测试）

- task：`t036_mail_datetime_provenance`
- spec：`docs/tasks/t036_mail_datetime_provenance/spec.md`
- diff_anchor：`ce342a38d6950fe08fd985262f0735f898b2b042`
- target：`git -C '[REDACTED_LOCAL_PATH]' diff ce342a38d6950fe08fd985262f0735f898b2b042`
- round：1

## Round 1 (2026-10-23T09:37:31+08:00)

reviewed_scope: 6606a8fb3c2a346a

### t036_test_f001 - OpenAPI nullable 测试未断言 null 分支

- 严重度：important
- 锚点：AC-003；API 契约要求未知时间以 null 表示
- 位置：`tests/mail_core/test_openapi_contract.py:78-79`
- 问题：断言只检查 `anyOf` 非空，没有检查其分支包含 `{"type": "null"}`。若 `sort_time` 或 `date` 的 schema 变成不含 null 的其他 union，该测试仍通过，生成客户端会错误认为未知时间不可空。数据库 API 测试覆盖了实际响应 null，但不能证明 OpenAPI 对外契约也允许 null。
- 建议：对两个属性分别断言 `anyOf` 中存在 `{"type": "null"}`。

### t036_test_f002 - 迁移测试未断言已有收件时间保留

- 严重度：minor
- 锚点：测试策略要求 PostgreSQL 迁移无损；范围明确要求保留已有效保存的时间
- 位置：`tests/mail_core/test_migration_validation.py:206-216`
- 问题：历史窗口测试将已有邮件升级到 0016，但最终查询只检查主题、发件人和 flags，不读取 `sort_time`；新的迁移往返测试检查列可空和含 NULL 时拒绝降级，也没有验证已知时间原值不变。若升级意外清空或改写旧收件时间，这些迁移测试仍通过。
- 建议：迁移前写入固定 `sort_time`，升级至 head 后断言原值保持不变。

## 结论

- 改测方向复核：旧 MIME Date 覆盖时间、把 nullable cursor 当非法、以及固定旧 migration head 的测试均改为新名称，并补充独立的新契约断言；task.md 记录了语义变更原因。未发现迁就实现的断言弱化或测试跳过。
- 本轮新发现：2 条。
- 未进表的提示：前端 Vitest 未能执行。worktree 缺少 `src/frontend/node_modules`，`npm test` 报 `vitest: command not found`；改用主仓依赖尝试仍无法从 worktree 解析 `zustand`。未修改环境文件。前端新增断言已检查源码。

### AC 复验方式

- AC-001：`re_verified`。独立检查 IMAP/Gmail/Graph 有效、缺失、非法日期测试；真实 PostgreSQL 定向套件通过。

- AC-002：`re_verified`。真实 PostgreSQL 归档用例断言 MIME Date 不覆盖已知时间，且空主题只补主题字段；套件通过。

- AC-003：`re_verified`。真实 PostgreSQL 用例检查 nullable 列、API null、ASC/DESC 含 NULL 跨页完整顺序；前端日期工具与阅读器断言已检查。OpenAPI null 分支断言不足，见 f001。

- AC-004：`re_verified`。逐项检查 IMAP/Gmail/Graph 有效及缺失/非法输入、相异 MIME Date、空主题和跨页测试；真实 PostgreSQL 定向套件通过。

- `coverage = 4 / 4`

- 独立复测：`test_pg_runtime.py run` 针对 9 个相关后端测试模块，`420 passed, 1 warning`，包含真实 PostgreSQL migration/query/API；warning 为 Starlette TestClient 弃用提示。前端 Vitest 因 worktree 依赖缺失未执行。

- 总体判断：存在 1 条未解决 important finding，当前 TEST 轴不通过。

- 系统性 follow-up：无。

verdict: FAIL

## Round 2 (2026-10-23T09:52:02+08:00)

reviewed_scope: 88dd3196a7257c27

## Findings

无。

## 结论

- 前轮 finding 复核：`t036_test_f001` 已消除；OpenAPI 测试分别检查 `MessageOut.sort_time` 与 `MessageDetailOut.date` 的 `anyOf` 含 `{"type": "null"}`。`t036_test_f002` 已消除；独立 PostgreSQL 测试在 0015 写入固定收件时间，升级到 head 后比较原值。
- 改测方向复核：无迁就实现的断言修改。原 MIME Date 收件时间语义、nullable cursor、当前 migration head 的测试均以新测试名表达，并在 `task.md` 记录替换理由；未发现断言弱化、危险跳过或关键 mock。
- 本轮新发现：0 条。
- 未进表的提示：前端 Vitest 未运行，worktree 的 `src/frontend/node_modules` 只有 `.vite`；已检查日期显示与阅读器断言。定向后端 PostgreSQL 测试独立通过 17 项。
- 总体判断：前轮两个 finding 均已修复，本轮无 blocking finding，TEST 轴 PASS。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：`re_verified`。IMAP 测试覆盖有效、缺失和非法 `INTERNALDATE`，并用相异 MIME Date 验证来源；Gmail full/history 路径与 Graph 的有效、缺失、非法时间均有断言。定向后端用例通过。
- AC-002：`re_verified`。归档测试检查 provider 时间不被相异 MIME Date 覆盖、未知时间不被 MIME Date 补造、空主题仍可回填；用例通过。
- AC-003：`re_verified`。OpenAPI 明确包含 null 分支；API inbox/detail 返回 null；真实 PostgreSQL ASC/DESC 分页断言完整稳定 ID 顺序；前端日期格式及阅读器测试断言未知日期留空。后端定向用例通过，前端仅静态检查。
- AC-004：`re_verified`。逐项检查 provider 时间边界、归档空主题/相异 MIME Date 和未知时间分页测试；定向后端测试 `17 passed, 405 deselected, 1 warning`。
- `coverage = 4 / 4`

verdict: PASS

## Round 3 (2026-10-23T10:36:44+08:00)

reviewed_scope: 87bdfa30d5113c56

### Findings

无。

### 结论

- 前轮 finding 复核：attempt 1 的 `t036_test_f001`（OpenAPI null 分支）与 `t036_test_f002`（迁移保值）已修复。前次 attempt 2 独立检查指出的两项 minor 覆盖缺口也已补足：Graph 非字符串时间现覆盖 `True`、浮点数和对象；归档现覆盖空主题、provider 时间为 null 且 MIME Date 有值的回填路径。
- 本轮新发现：0 条；前次两项缺口均已通过测试 diff 确认修复，无未解决 finding。
- AC 复验方式：
    - AC-001：`re_verified`。IMAP 有效、缺失、非法 `INTERNALDATE` 及与 MIME Date 分离均通过生产 parser/provider 测试覆盖；Gmail 两条路径覆盖缺失、非法、bool、float、超范围字符串和有效时间；Graph 覆盖有效 offset、无 offset、缺失、非法字符串及 bool/float/object。
    - AC-002：`re_verified`。新增归档测试调用 `run_archive_batch`；覆盖已知 provider 时间不被 MIME Date 覆盖，以及空主题触发回填时 null 时间仍保持 null。
    - AC-003：`re_verified`。真实 PostgreSQL 测试覆盖 migration 保留已知时间与含 NULL 时拒绝降级、API inbox/detail 返回 null、ASC/DESC NULL 跨页稳定；OpenAPI 测试检查 null 分支。
    - AC-004：`re_verified`。核对 parser、archive、migration、query、API 测试均调用生产逻辑并断言其结果。
- 覆盖率：`coverage = 4 / 4`。
- 完整后端套件：443 passed / 1 warning，373.07 秒（实施方本轮运行结果；reviewer 未重跑）。PostgreSQL 测试库已由测试运行器自动清理。
- 前端 Vitest 本轮未执行；日期 null 显示断言已静态核对，属于 AC-003 的辅助展示覆盖。
- 总体判断：attempt 2 的测试覆盖 AC-001~004；无未解决 finding，TEST 轴 PASS。
- 系统性 follow-up：无。

verdict: PASS
