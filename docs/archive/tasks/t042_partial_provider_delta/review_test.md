# Task review t042（reviewer_focus: 测试）

- task：`t042_partial_provider_delta`
- spec：`docs/tasks/t042_partial_provider_delta/spec.md`
- diff_anchor：`3cedba6`
- target：`git -C '[REDACTED_LOCAL_PATH]' diff 3cedba6` 中 p025 明确交付路径，以及直接读取新增测试文件
- round：1
- reviewed_at：2026-10-23T19:15:16+08:00
- 范围：`providers/base.py` 的字段存在性契约、`providers/gmail.py`、`providers/parsing/{graph_delta,gmail_history}.py`、`sync/{metadata,delta}.py`、`tests/mail_core/test_partial_metadata_fidelity.py`、`test_gmail_graph_contracts.py` 相关差异与既有同步意图保护测试。不评审自身实施的 p024 改动。

reviewed_scope: 42ba42b7985fd9e2

## Findings

零 finding。

## 测试可信与危险模式扫描

- 新用例直接调用生产 Graph parser、GmailProvider、metadata upsert 与 delta apply；仅 transport 边界替换外部 Gmail API。持久化断言使用真实 PostgreSQL Session，并 expire 后重新读取字段，没有复制被测逻辑。
- `test_partial_graph_and_gmail_updates_preserve_omissions_and_apply_explicit_empty` 对 Graph 仅 subject/from、Gmail 完整 metadata projection 无 snippet、首次插入无 snippet、显式空 subject/snippet/地址组及附件 false 分别断言。Gmail projection fixture 没有假设 metadata 必须含 snippet/internalDate。
- `test_gmail_rejects_incomplete_or_mismatched_hydration` 覆盖 full scan 与 delta 两入口下缺 id、仅 id、ID 不匹配；`test_gmail_hydration_failure_never_uses_partial_history_headers` 验证 GET 异常即使 stub 带 subject 也不能吞错。
- `test_delta_application_combines_partial_changes_in_response_order` 经过真实 lease 与 apply，覆盖 partial/partial、flag/partial、partial/flag/partial、flag/完整快照、delete/再 upsert；完整快照分支通过替换标准 DTO 的 supplied_fields 输入触达生产完整快照路径，没有 mock coalesce 实现。
- 唯一既有测试改动给 pagination transport 补上合法 metadata hydration 响应，保留原有 cursor/pagination 断言；这是修复过于简化的边界 fixture，不是改预期迁就实现。
- 条件 PG skip 与项目统一隔离 runner 一致；纯 provider 失败路径无 skip。未发现 only、恒真断言、删减/弱化旧断言、mock 自身逻辑、延长 timeout 或忽略异常。测试中的条件分支仅构造完整快照输入，核心字段断言无条件执行。

## 结论

- 改测方向复核：无迁就实现的改测。
- 本轮新发现：0 条。
- 未进表提示：可以增加真实 `sync_folder_delta` 对 hydration 失败后 checkpoint 完全不变的组合回归；现有失败用例已证明 provider 不返回成功页，源码 `sync/delta.py` 的 provider-error 分支先返回且不调用 apply/checkpoint，因此不构成 AC 无测试或假覆盖。
- 工具边界：用户授权直接 main，task front matter 未伪造 active/done 或 diff_anchor；本报告使用实际基线。新增测试虽尚未暂存为 intent-to-add，reviewer 已直接完整读取；上述 scope 指纹由生产 monitoring helper 对实际 worktree 计算，包含未跟踪文件。全仓指纹并不表示对 p024 自身实施部分做独立评审。
- 执行披露：本 reviewer 只读核查源码与测试断言，未重跑数据库套件；主代理正在执行全量门禁，测试运行结果由主代理单独提供。
- 总体判断：p025 测试覆盖真实存储行为、缺省与显式清空的差异及 hydrate 失败边界，未发现阻断项。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：`re_verified`。核查真实 PG 用例逐字段断言 omitted sender/name/snippet/ID/To/Cc 保留，以及同页多次 partial 合并。
- AC-002：`re_verified`。核查显式空字符串、null sender/ID 与空地址数组经 parser/upsert 后真实持久化清空；不是真假值过滤后的假断言。
- AC-003：`re_verified`。核查两个 Gmail 入口返回不含 snippet 的合法 projection，经真实 upsert 保留旧摘要；新增 ID 首次插入后 snippet 仍为 None。
- AC-004：`re_verified`。核查两入口的形状/ID校验异常与 GET 异常断言；追踪真实 sync provider-error 分支不执行成功页 apply/checkpoint。
- AC-005：`re_verified`。核查既有完整 metadata/parser/provider 测试，以及 `test_ac004_ac005_local_intent_protection_and_convergence` 对真实 upsert/delta 保护读状态、同时正常更新 subject 的断言；未知状态覆盖由独立 t041 评审承担。
- coverage = 5 / 5

verdict: PASS
