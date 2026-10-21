# Task spec

## 背景

`src/mail_core/mail/application/accounts.py` 中的 `AccountDTO` 声明了 `slots=True`，导致其在 `src/mail_core/api/accounts.py` 中被 `dict(a.__dict__)` 展开时抛出 `AttributeError`，使得包含邮箱账户的 `GET /api/accounts`、`POST /api/accounts`、`PATCH /api/accounts` 均发生 HTTP 500 异常。同时，由于此前 `test_accounts_api_unit.py` 完全未编写针对业务成功流的 Stub/Mock 单元测试，而 `test_accounts_api_pg.py` 又强依赖外部数据库环境变量导致日常被静默跳过（假绿），致使该缺陷长期漏网。前端 `Sidebar.tsx` 对账户加载失败硬编码了误导性的“请确认已登录且后端可用”文案，且未提供重试入口，造成用户体验与系统状态严重割裂。

## 契约区

### 范围

- 后端 `src/mail_core/api/accounts.py` 修复对 `AccountDTO` 的解构方式，改用标准 `dataclasses.asdict` 消除 `__dict__` 访问。
- 后端 `tests/mail_core/test_accounts_api_unit.py` 引入完整的 Stub/Mock，增加已登录且存在账户数据时的 `GET /api/accounts`、`POST /api/accounts`、`PATCH /api/accounts` 200 序列化与异常映射单测，无需外部 PG 即可在日常门禁中无条件常态化运行。
- 前端 `src/frontend/src/components/Sidebar.tsx` 改用 `errorMessage` 透传真实错误原因，并提供「重试」按钮触发 query 重新拉取。
- 前端 `src/frontend/src/components/Sidebar.test.tsx` 补充针对接口 500/网络失败的 Mock 测试与重试交互断言。
- 验证期显式配置测试数据库运行 `test_accounts_api_pg.py`，验证端到端真实集成测试从 SKIPPED 恢复为 PASSED。

### 非范围

- 不修改底层数据模型与数据库迁移脚本。
- 不修改其它业务路由与同步服务。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：当存在一个或多个账户数据时，已鉴权请求 `GET /api/accounts` 返回 HTTP 200，并正确序列化各账户字段，不抛出 AttributeError 500。
- [ ] AC-002：`POST /api/accounts` 与 `PATCH /api/accounts/{account_id}` 正常响应时，成功序列化并返回 `AccountOut`。
- [ ] AC-003：当侧栏 `groupsQuery` 或 `accountsQuery` 失败时，侧栏“邮箱账户”区域显示真实错误提示信息（包含错误消息文本），不显示假定未登录的误导文案。
- [ ] AC-004：点击侧栏错误区域中的“重试”按钮，触发账户与分组 query 的 refetch。
- [ ] AC-005：`tests/mail_core/test_accounts_api_unit.py` 具备纯单测 Stub/Mock，脱离 `MAIL_CORE_DATABASE_URL` 环境变量即可常态化运行并通过 AC-001 与 AC-002 的序列化验证。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。

## 上下文区

- 来源：`p008_sidebar_accounts_failure_handling`

### 有意不测

- 无

### 测试策略

- 后端单测（门禁一）：在 `test_accounts_api_unit.py` 模拟 `list_accounts_app`、`create_account_app`、`update_account_app` 返回带 `slots=True` 的真实 `AccountDTO` 实例，断言 API 路由层返回 200 且 JSON 字段完整，不依赖外部数据库。
- 后端集成（门禁二）：显式注入 `MAIL_CORE_DATABASE_URL` 执行 `test_accounts_api_pg.py`，验证真实数据库下全生命周期通过且不再跳过。
- 前端测试：在 `Sidebar.test.tsx` 中 mock fetch 返回 500 错误，断言真实错误文本渲染，点击重试后断言 fetch 再次被调用。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：`asdict` 对扁平 `AccountDTO` 字段拷贝存在微小开销（数十微秒级别），无吞吐影响。
- 回退：`git revert` 或恢复上一 commit。

### 依赖与约束

- 无

### Finalization 时更新的 blueprint

- 无
