# 项目交接记录（最新）

本文件只保留当前有效一节。过时段落由 `repo-hygiene` 迁入 `docs/archive/handoff.md`。

## 2026-11-10T04:52:52+08:00 agent → developer

- 当前焦点：落实 `docs/reviews/review_20261107_142548/adoption_decision.md` 的 A1–A22 采纳决策，并完成本轮外部审阅意见整改。
- branch：main
- head_commit：40685283（本节所述代码状态；交接文档提交另计）
- 勘误：上一节标注 `2026-11-07T19:35:00+08:00`，却引用 11-09 05:52 才产生的 `707c49b2`；且把 A18 写成「彻底删除 SQLite 生产分支及测试手写 DDL」、把「未完成」写为「无」，均与仓库现状不符。本节据实更正，不回改历史。
- 已完成（A1–A22）：
    - A1: 补齐 `remote_writeback`、`worker/main` 与 `search/index` 缺失的 typing 导入；
    - A2: 彻底移除废弃的 Outbox v1 `fetch_since` 接口与旧调用，重建 v2 publication seq 回放测试；
    - A3: 清除 `connection_slots` 与 `system_metrics` 历史反射别名及废弃 shim；
    - A4: 全栈双页面 SSE E2E 重构，断言未读状态与未读徽章/计数跨页面自动收敛；
    - A5: 明确测试设备码复制成功（剪贴板内容写入）与失败（授权降级提示）独立分支；
    - A6: 移除设置工作区 E2E 遗留相对路径截图副作用；
    - A7: 修正 pytest 根配置公共范围说明；
    - A8: 补充阅读器详情缓存更新泛型约束 (`setQueryData<MailDetail>`)；
    - A9: 归档旧交接段落并更新当前最新交接记录；
    - A10: 补齐 `docs/specs_index.md` 中生效 spec 的任务溯源；
    - A11: 补齐 `docs/archive/pending/README.md` 归档待办索引表格；
    - A12: 补登 `docs/reviews/README.md` 中历史审阅会话布局差异；
    - A13: 会话撤销校验以数据库为唯一权威，彻底移除 5 秒本地 TTL 放行窗口；
    - A14: 巡检状态与协议游标解耦，建立 `FolderPatrolStatus` 独立持久化模型；
    - A15: 密钥初始化统一为跨进程 OS 文件互斥锁与持久化原子发布，移除忙等自旋并建立 fail-closed；
    - A16: desktop sidecar 启动动态持有 loopback 端口 0 并经专用结构化握手回传，根除 TOCTOU 竞态；
    - A17: 压缩 Alembic 历史迁移为单一当前权威基线 `20261107_0001`，提供一次性离线校验与 stamp 工具；
    - A18: 25 个手写 SQLite DDL 复刻生产表的数据库行为测试（含本批新增的 publication/patrol 竞态）迁入真实 PostgreSQL，生产业务代码的 SQLite 回退已删除。迁移工具自身方言、上游遗留库输入与 policy 状态模拟仍使用 SQLite，见「未完成」；原「彻底删除」表述不成立。
    - A19: 完整解除反向依赖（auth->bootstrap, host_security）并下沉 `CredentialStore` 到 `security/credentials`；
    - A20: 用真实 PostgreSQL 验证变更计数精确性与持久化副作用，阻断失效 fencing 提交；
    - A21: 收件箱刷新独立优先终态，完整目录发现与后台同步解耦独立反馈（闭环 p073）；
    - A22: 文件树原位最小脱敏并建立 `scripts/check_doc_sensitive.py` 敏感文档门禁；本轮把 `is_safe_credential` 改为 default-deny 并根除字符集豁免反模式。
- 本轮审阅意见整改：
    - 迁移单入口：`mail_core.db.baseline.plan_migration` 集中分类，启动与离线两入口共用；无 `alembic_version` 且存在业务表的库两入口一律拒绝（32 表齐全也不例外），空库由启动 `upgrade head`、离线仅提示走启动/Alembic，不盲 stamp。
    - A18：25 个 SQLite 行为测试迁真实 PG，补齐真实 schema 外键所需的父行 seed；`__main__.py` 统一分类后遗留的 3 个死 helper 及其过时测试已删除。
    - A22：`is_safe_credential` 改 default-deny，删除「含 `.` `#` `/` `=`、空格或纯字母即判安全」及「含结构字符即整值 safe」反模式；`my.passw0rd`、`supersecret`、`correcthorsebatterystaple`、带逗号/括号/冒号形态与纯数字口令均检出。
    - A13：新增真实 PG 双进程撤销测试（B 未收 NOTIFY 仍拒绝旧会话、DB 故障 fail-closed、重复/乱序通知不影响 REST 判定），退役 FakeSession 旧测试并写明理由；记录上批「实现提交内就地改断言」的教训。
- 验证：
    - 本轮真实 PG 门禁（`scripts/run-mail-core-tests.sh run --no-cov` 按 `-k` 分批）：迁移/policy 99 passed、竞态/outbox 56 passed、其余 sync/patrol 56 passed、A13/双进程/迁移 105 passed。
    - 敏感文档扫描：`python3 scripts/check_doc_sensitive.py docs --check` 581 文件 0 违规；检测器单测 31 passed。
    - 上一节记录的模板契约、前端 lint/单测/类型/构建、桌面端、E2E、全栈端到端结果本轮未改动相关代码，未重跑。
- 未完成：
    - A18 残留：`tests/mail_core/test_startup_migrations.py`（迁移 policy 状态模拟）、`tests/scripts/test_deploy_mail_core_gate.py`（部署脚本 gate）、`tests/scripts/test_migrate_to_unified_baseline.py`（离线工具契约）、`tests/mail_core/test_legacy_migration.py`（上游 v2 SQLite 遗留库输入）、`tests/mail_core/test_migration_validation.py`（PG 手写历史 schema）仍含 SQLite/手写 DDL，属迁移工具自身方言、上游遗留库或 policy 测试替身，不属「复刻生产表」违规，但 A18 字面「彻底删除」仍不成立。
    - `src/mail_core/db/baseline.py` 仍保留离线迁移工具的 SQLite 分支（`configure_read_only`、`ensure_folder_patrol_status_table`、`_migrate_patrol_status_data_generic`、`_check_cursor_data`）。
    - `tests/mail_core/test_auth_plan_a_db.py` 仍有若干 FakeSession 单元用例（模拟真实 PG 无法确定性复现的事务失败）。
    - 全量 2142 用例门禁未在本轮单次跑完，按 `-k` 分批验证覆盖所有改动文件。
- 下一步：等待用户指示；若要求 A18 字面清零，按上述残留项立项。
