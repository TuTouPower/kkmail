# t017 测试审查

## 范围与执行方式

核查真实全栈端到端测试覆盖范围与门禁执行：

- 真实全栈端到端自动化: `scripts/run_full_stack_e2e.py`
- 快速 UI 模拟冒烟: `npm --prefix src/frontend run test:e2e`

## 门禁验证结果

1. **真实端到端测试**: `python3 scripts/run_full_stack_e2e.py` 3 passed (15.8s)。涵盖登录阻断与成功流、Cookie 与 CSRF 校验、多会话失效、添加账户后真实 Worker 自动同步与邮件详情展示、XSS 防护过滤、双页面 SSE 实时协同。
2. **轻量 UI 冒烟测试**: `npm --prefix src/frontend run test:e2e` 3 passed (4.4s)，保持快速开发验证能力。
3. **资源清理核实**: 测试生命周期结束后，`kkmail_e2e_*` 数据库及对应 role、后台 API 进程和 Worker 进程均已完全终止和销毁，无残留。

## 结论

PASS。测试触达用户与真实后端可观察行为，断言严格，符合全栈 E2E 验收要求。
