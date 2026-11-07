# bundle_local_docs_current

## responsibilities

- 维护系统全局权威真理：Blueprint 架构拓扑、领域实体、技术约定、决策记录与测试门禁契约
- 维护各业务模块与需求级功能规格（Specs）及生效索引清单（specs_index.md）
- 提供面向部署运维、版本发布、桌面端管理与安全配置的用户操作指南（Guides）
- 提供 AI Agent 与脚本操控接口契约及 CLI 客户端（kkmail-skill）
- 承载当前任务交接状态（handoff.md）、当前有效待办账目（pending/todo/）与关键技术发现（findings）

## interfaces

- docs/specs_index.md：生效需求规格清单索引
- docs/blueprint/testing.md：标准化门禁命令（doctor_cmd, test_cmd, blackbox_verify）
- docs/skills/kkmail-skill/SKILL.md 与 kkmail_cli.py：Agent CLI 操控命令行与参数定义
- schemas/openapi.json：机器可读接口模式契约

## dependencies

- schemas/openapi.json 接口模式契约
- src/mail_core/、src/frontend/、src/desktop/ 实际实现代码
- .repo_template/ 规范工作流与自动化脚本

## flows

- 需求拆分与 Spec 落地：基于 Blueprint 派生 task，编写规格与行为验收标准（AC），收尾时更新 Spec 并登记入 docs/specs_index.md
- 验证与门禁推进：依据 testing.md 执行分层测试，产出验证事实并更新 docs/handoff.md
- Agent 交互流：Agent 读取 SKILL.md，通过 kkmail_cli.py 调用 REST API 执行邮件读取与管理

## constraints

- 单一权威原则：每个规则和契约仅在一个权威位置完整定义，禁止跨文件重复复制
- 三态划分原则：当前有效、历史过时与未来待办分节明确，过时段落必须移入 archive
- 开源隐私安全：严禁硬编码生产凭据、真实个人邮箱与开发者本地绝对路径

## decisions

- 采用 Blueprint 作为长期真理源，替代原有分散架构说明
- 单用户 Capability-based 安全模型，资源 UUID 作为安全边界
- 永久废弃浏览器扩展与外部皮肤系统，收敛维护成本
- 邮件 HTML 渲染严格锁定在无脚本 iframe 沙箱，外链图片强制走服务端代理

## evidence

- docs/blueprint/architecture.md:9-19
- docs/blueprint/conventions.md:7-24
- docs/blueprint/testing.md:6-45
- docs/specs_index.md:5-13
- docs/handoff.md:6-13

## uncertainties

- docs/specs_index.md 后续新 task 完成时是否能由自动化工具链强制约束同步更新

## Findings

- [Medium][95] docs/handoff.md:6-13 — docs/handoff.md 交接记录严重滞后且 commit SHA 失步

    - ID: f_docs_current_handoff_stale; verification: static
    - Evidence: docs/handoff.md:6-13 记录停留在 2026-10-27T14:45:00+08:00、head_commit 为 a7255499，而当前仓库 HEAD 已推进至 2d17520 且包含了 t061~t075 大量 task 的合并与部署变更; 违反 AGENTS.md 约定：docs/handoff.md 仅保留最新一节，过时段落应迁入 docs/archive/handoff.md
    - Impact: 后续开发者或 Agent 读取 handoff.md 无法获知当前最新交接状态、已验证范围与当前焦点，导致工作上下文断裂
    - Fix: 将 2026-10-27 的过时交接记录追加归档至 docs/archive/handoff.md，并在 docs/handoff.md 写入最新提交点（2d17520）的交接内容

- [Low][90] docs/specs_index.md:8,11 — specs_index.md 中部分生效 spec 的 task 清单为空

    - ID: f_docs_current_specs_index_empty_tasks; verification: static
    - Evidence: docs/specs_index.md:8 的 auth_and_session 与 Line 11 的 mail_account_navigation_and_read_state 的 task 清单列为空白; 违反该文件头部契约："每个 task 收尾时写入或更新对应行（须已过黑盒）"
    - Impact: 破坏了规范与 task 实施记录的溯源链条，无法快速反查该 spec 是由哪些 task 演进交付的
    - Fix: 梳理对应历史 task（例如 t010/t025/t041/t042 等），在表格中补全关联 task 编号

## views

```json
{
  "security": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "correctness": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "contracts": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "performance": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "design": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "robustness": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "tests": {
    "status": "completed",
    "reviewer": "subagent_docs"
  },
  "documentation": {
    "status": "completed",
    "reviewer": "subagent_docs"
  }
}
```

## files_reviewed

```json
[
  "AGENTS.md",
  "DESIGN.md",
  "README.md",
  "docs/blueprint/architecture.md",
  "docs/blueprint/conventions.md",
  "docs/blueprint/decisions.md",
  "docs/blueprint/domain.md",
  "docs/blueprint/testing.md",
  "docs/findings/d001_python_email_policy_defects_and_strict_decoding.md",
  "docs/findings/d002_sandbox_iframe_omits_cookies_for_cid_attachments.md",
  "docs/findings/d003_srcdoc_csp_inheritance_and_proxy_architecture.md",
  "docs/guides/deployment.md",
  "docs/guides/desktop.md",
  "docs/guides/release.md",
  "docs/guides/security.md",
  "docs/guides/troubleshooting.md",
  "docs/guides/upgrade.md",
  "docs/handoff.md",
  "docs/pending/todo/p073_manual_refresh_inbox_latency.md",
  "docs/skills/kkmail-skill/SKILL.md",
  "docs/skills/kkmail-skill/scripts/kkmail_cli.py",
  "docs/specs/account_connection.md",
  "docs/specs/auth_and_session.md",
  "docs/specs/inbox_ui_and_search.md",
  "docs/specs/mail_account_navigation_and_read_state.md",
  "docs/specs/mail_sync_and_storage.md",
  "docs/specs/testing_quality.md",
  "docs/specs_index.md",
  "docs/tasks_index.json"
]
```
