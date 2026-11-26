---
pid: "p096"
slug: "t089_outbound_minor_followups"
status: "closed"
resolution: "resolved"
reason: "已将 normalize_account_config 接入 create_account/api_create_account/consume_oauth_flow_for_create/reauthorize，_resolve_proxy_port 注解收敛为 SplitResult 并确认 testing.md:82 已包含 test_net_resilience.py；相关 PG 套 70 passed, 1 skipped，契约 389 passed, 1 skipped，前端 56 文件 599 passed、桌面端 12 项与敏感扫描通过"
fix_ref: "main"
---
# p096 t089 出站传输次要收口：创建/OAuth配置归一化、proxy注解导入与测试门禁命令

- 来源：t089 遗留（Round 2 Review 3 条非阻断 minor：`t089_code_f008`、`t089_code_f009`、`t089_test_f006`）
- 内容：
    1. `t089_code_f008`：将 `normalize_account_config()` 同步接入 `create_account`（`src/mail_core/accounts/service.py`）、`api_create_account`（`src/mail_core/api/accounts.py`）以及 `consume_oauth_flow_for_create` / `consume_oauth_flow_for_reauthorize`（`src/mail_core/accounts/oauth_flow.py`、`src/mail_core/mail/application/accounts.py`），避免创建或 OAuth 重授权路径传入空字符串 `proxy_mode=""` / `outbound_proxy=""` 时行为与普通 `PATCH` 不一致。
    2. `t089_code_f009`：在 `src/mail_core/net/proxy.py` 补充 `Any` 导入或将 `_resolve_proxy_port` 的参数注解收敛为 `urllib.parse.SplitResult`，确保 `typing.get_type_hints()` 运行期解析不报 `NameError`。
    3. `t089_test_f006`：更新 `docs/blueprint/testing.md` 第 82 行定向测试命令，一并包含拆分后的 `tests/mail_core/test_net_resilience.py`。
        以上均不影响 `t089` 核心行为 AC，已在 Round 2 PASS 后转入待办统一收口。
- 处理：main；resolution=resolved；reason=已将 normalize_account_config 接入 create_account/api_create_account/consume_oauth_flow_for_create/reauthorize，\_resolve_proxy_port 注解收敛为 SplitResult 并确认 testing.md:82 已包含 test_net_resilience.py；相关 PG 套 70 passed, 1 skipped，契约 389 passed, 1 skipped，前端 56 文件 599 passed、桌面端 12 项与敏感扫描通过
