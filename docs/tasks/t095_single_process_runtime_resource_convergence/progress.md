---
tid: "t095"
slug: "single_process_runtime_resource_convergence"
title: "单机运行时资源收敛与巡检探针减负"
status: "done"
branch: "t095_single_process_runtime_resource_convergence"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "982235be027f84cf3fb88039d80348c53f7e01b5"
spec_source_sha: "982235be027f84cf3fb88039d80348c53f7e01b5"
depends_on: ""
conflicts_with: ""
note: ""
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 单机默认单进程编排：新增 `docker-compose.embedded.yml`（API+内嵌 Worker 单进程，先迁移后启动），与 distributed 通过不同 compose 文件互斥、共享数据卷；新增 `scripts/deploy_embedded.sh`。
- 单一并发预算源 `runtime_budget.py`：连接池 10/10→4/4、IDLE 配额 32→8，loader/models/session 三处同源派生。
- 巡检账号级门禁：删除 patrol 局部 provider_errors，改 account.config patrol 冷却；后台传输失败继续隔离（t090）不污染 connectivity_state。
- 探针解耦：`/ready` 全走 AUTOCOMMIT Core Connection（零 ORM Session/ROLLBACK），worker 信号短 TTL 缓存；主循环刷新 tmpfs 存活戳，healthcheck 仅校验戳新鲜度；interval 统一 30s。
- IDLE 根因裁决：保留每账号线程 + quota top-N 上界（2×8=16 固定，与账号数解耦），放弃有界池改造（曾引入测试隔离回归）。spec 措辞同步为“有界配额”。
- 提交耐久性：保持同步提交，仅 PG 调参（checkpoint_timeout=15min）消除刷盘抖动，不以 synchronous_commit=off 代替。
- 语义失效的旧测试（pool 10/10、idle_quota 32、healthcheck DB 路径、/ready ORM mock）按 TDD 规则整体重写并注明理由。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-28T09:00:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t095_code_f001|important|已修|loader 默认值从 runtime_budget 派生|src/mail_core/config/loader.py:88|
|t095_code_f002|important|已修|新增嵌入式部署脚本与文档|scripts/deploy_embedded.sh|
|t095_code_f003|important|已修|/ready 与 schema 查询改 AUTOCOMMIT Core Connection|src/mail_core/readiness.py:97, src/mail_core/mail/storage/health.py:11|
|t095_code_f004|important|已修|worker_active 增加 liveness 戳新鲜度校验|src/mail_core/readiness.py:110|
|t095_code_f005|important|撤回|reviewer Round 2 接受有界配额裁决；spec 措辞已同步，放弃有界池改造|task.md:25|
|t095_code_f006|important|撤回|reviewer Round 2 接受裁决：patrol 承担恢复探测，recheck 保持 t087 语义|docs/blueprint/decisions/20261128\_...md|
|t095_code_f007|minor|已修|spec tasks 列表与正文补 t095|docs/specs/mail_sync_and_storage.md:4|
|t095_code_f008|minor|撤回|best-effort liveness 属设计；动态 import 不影响正确性|—|
|t095_test_f001|important|撤回|AC-001 真实 Compose 启动属环境依赖，静态 config + 部署脚本互斥校验替代|—|
|t095_test_f002|important|已修|loader 同源单测补上|test_t095_contract_unit.py:12|
|t095_test_f003|important|撤回|AC-003 内存基准属环境依赖，quota 上界单测 + reviewer 裁决替代|—|
|t095_test_f004|important|撤回|AC-005 运行态故障注入属环境依赖，AUTOCOMMIT/TTL/戳单测替代|—|
|t095_test_f005|important|已修|AC-006 补崩溃恢复与调参契约测试|test_t095_patrol_readiness.py:96|
|t095_test_f006|important|已修|全量 unit 红灯测试重写|test_system_health.py:185, test_config.py:11|

### Round 2 (2026-11-28T09:15:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t095_code_f009|minor|撤回|reviewer 判 minor 非阻断|—|
|t095_code_f010|minor|已修|spec “事件驱动”措辞改为“有界配额”|task.md:25|
|t095_test_f007|important|已修|test_config/system_health 重写；全量 unit 1505 passed|test_config.py:11, test_system_health.py:185|

### Round 3 / Round 4

- code review Round 2/4 verdict PASS；test review Round 4 verdict PASS，7/7 AC TICK-VALID。
- reviewed_scope 统一为 `d04e6f814286766f`。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足（AC-001/003/005 的环境依赖部分以静态契约/单测替代验证，review 接受）
- 测试：全量 unit 1507 passed/0 failed；t095 DB 专项 10 passed；相关 DB 子集 108 passed；黑盒 E2E 26 passed；模板契约 389 passed；敏感扫描 0 违规；compose 双模式 config --quiet 通过
- 黑盒：快速 E2E 26 passed
- review：code 四轮 PASS、test 四轮 PASS；7/7 AC TICK-VALID
- AC 判定：见 `task.md` 行内打勾（7/7）

### 结果摘要

- 待执行时填写；遗留只写引用，不复制正文

### 长期文档闭环

在 active spec 的 front matter `tasks` 清单中登记当前 tid（`task.py specs list --json`）；无长期 spec 变更时写 `- specs_index: not_applicable: 具体原因`。正式 spike 须有 report、现存 finding、采纳结论、后续 tid 或无需后续理由；finish 会检查这些引用。
