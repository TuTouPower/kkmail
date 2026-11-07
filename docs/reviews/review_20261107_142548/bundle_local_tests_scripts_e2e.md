# bundle_local_tests_scripts_e2e

## responsibilities

- 驱动 Playwright 端到端测试，验证 React SPA 与 mail_core / stubApi 的完整交互体验与核心业务链路
- 验证项目核心 CLI、运维部署脚本、数据库迁移与备份恢复演练工具的可靠性与防御边界

## interfaces

- tests/e2e/stubApi.ts: setupStubApi(page, options)
- tests/conftest.py: fake_frontend_dist fixture

## dependencies

- @playwright/test, pytest, subprocess, urllib, tarfile

## flows

- Playwright E2E -> 启动浏览器上下文 -> 登录拦截 -> 操作 UI (添加账户/拖拽排序/阅读邮件/复制) -> 断言 DOM 状态与网络请求
- 脚本测试 -> pytest 启动子进程或动态导入脚本模块 -> 构造临时文件/虚拟环境 -> 触发 CLI/迁移 -> 断言退出状态码与产物完整性

## constraints

- E2E 真实全栈测试依赖外部 IMAP 容器与真实 PostgreSQL 实例
- 依赖锁定检查脚本 test_check_dep_locks.py 强制校验 lockfile hash 完整性

## decisions

- 将 E2E 分为全栈真实运行 (full_stack.spec.ts) 与快速 UI 交互打桩 (stubApi + smoke/sidebar/forms)
- 对 Shell 运维脚本采用动态 mock 环境变量与安全解压校验测试

## evidence

- tests/e2e/full_stack.spec.ts:30-82
- tests/e2e/full_stack.spec.ts:182-184
- tests/e2e/provider_account_forms.spec.ts:58
- tests/e2e/settings_workspace.spec.ts:43
- tests/conftest.py:1
- tests/scripts/test_check_dep_locks.py:11-41

## uncertainties

## Findings

- [Medium][95] tests/e2e/full_stack.spec.ts:182-184 — 全栈 E2E 双页面并发 SSE 同步测试使用恒真 body 可见性断言

    - ID: f_tse_tautological_body_visible_assertion; verification: static
    - Evidence: 用例 双页面并发下真实SSE推送与实时状态更新 (AC-005) 在 page1 标记已读后，page2 仅执行 await page2.waitForTimeout(1000) 与 await expect(page2.locator('body')).toBeVisible(); 任何加载中的网页 body 均可见，该断言属于恒真断言 (Tautological assertion)
    - Impact: 若 SSE 传输中断、事件处理异常或前端状态未更新，测试仍会绿灯通过，导致实时多端同步失效无法被 E2E 门禁拦截
    - Fix: 在 page2 上定位对应的邮件行，断言其已读样式类（如 .message-read 或未读红点消失），验证状态真实变更

- [Low][90] tests/e2e/provider_account_forms.spec.ts:58 — 微软设备登录验证码复制测试使用容忍失败的弱化正则断言

    - ID: f_tse_weak_regex_clipboard_assertion; verification: static
    - Evidence: 断言语句为 await expect(edit).toContainText(/已复制验证码|复制失败/); 将错误状态 复制失败 与成功状态 已复制验证码 作为并列匹配项
    - Impact: 即使剪贴板操作因权限或实现缺陷发生异常，测试依然判定成功，掩盖复制功能的破坏性缺陷
    - Fix: 配置 Playwright 上下文的 clipboard-write 权限，并将断言严格限定为 toContainText('已复制验证码')

- [Low][85] tests/e2e/settings_workspace.spec.ts:43 — 设置工作区测试残留向相对路径 .scratch 写入截图的调试代码

    - ID: f_tse_scratch_screenshot_side_effect; verification: static
    - Evidence: 测试执行中包含 await page.screenshot({ path: '../../.scratch/settings_design_review/current_accounts.png' })
    - Impact: 依赖特定工作目录层级与外部未受控的 .scratch 目录，在受限 CI 或无写权限环境下可能引发文件系统异常
    - Fix: 删除遗留的截图语句，或改用 Playwright 官方受管的 testInfo.attach 进行产物归档

- [Info][95] tests/conftest.py:1 — 根测试配置文件包含陈旧过时的测试范围声明

    - ID: f_tse_stale_conftest_docstring; verification: static
    - Evidence: 模块 docstring 标明：Root pytest config. All tests live under tests/mail_core/.; 实际上 tests/scripts/ 目录下包含 27 个脚本测试文件，与根级 docstring 描述不符
    - Impact: 文档描述与目录真实结构脱节，误导维护者对测试套件分布的认知
    - Fix: 修正 tests/conftest.py 顶层文档，补充对 tests/scripts/ 范围的说明

## views

```json
{
  "security": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "correctness": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "contracts": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "performance": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "design": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "robustness": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "tests": {
    "status": "completed",
    "reviewer": "subagent_tests"
  },
  "documentation": {
    "status": "completed",
    "reviewer": "subagent_tests"
  }
}
```

## files_reviewed

```json
[
  "tests/conftest.py",
  "tests/e2e/full_stack.spec.ts",
  "tests/e2e/provider_account_forms.spec.ts",
  "tests/e2e/settings_workspace.spec.ts",
  "tests/e2e/sidebar_tree.spec.ts",
  "tests/e2e/smoke.spec.ts",
  "tests/e2e/stubApi.ts",
  "tests/scripts/test_a160_drill_allowed_roots.py",
  "tests/scripts/test_backend_isolation_guards.py",
  "tests/scripts/test_backup_restore_drill_keys.py",
  "tests/scripts/test_benchmark_db_guard.py",
  "tests/scripts/test_benchmark_scale_p95.py",
  "tests/scripts/test_check_dep_locks.py",
  "tests/scripts/test_deploy_mail_core_r4adopt_p51.py",
  "tests/scripts/test_export_openapi_env.py",
  "tests/scripts/test_fetch_pg_binaries_helpers.sh",
  "tests/scripts/test_full_stack_e2e_blob_cleanup.py",
  "tests/scripts/test_full_stack_e2e_env_parse.py",
  "tests/scripts/test_full_stack_e2e_log_tail.py",
  "tests/scripts/test_full_stack_e2e_partial_cleanup.py",
  "tests/scripts/test_full_stack_e2e_port_retry.py",
  "tests/scripts/test_kkmail_cli.py",
  "tests/scripts/test_mail_core_chaos_lease.py",
  "tests/scripts/test_migrate_blob_key_validation.py",
  "tests/scripts/test_migrate_flag_state.py",
  "tests/scripts/test_migrate_from_legacy_db_accounts.py",
  "tests/scripts/test_migrate_from_legacy_db_cli.py",
  "tests/scripts/test_migrate_from_legacy_db_groups.py",
  "tests/scripts/test_migrate_legacy_graph_detection.py",
  "tests/scripts/test_migrate_read_attachment_flags.py",
  "tests/scripts/test_migrate_retained_batching.py",
  "tests/scripts/test_start_mail_core_imap.py",
  "tests/scripts/test_test_pg_runtime.py",
  "tests/scripts/test_test_pg_runtime_live.py"
]
```
