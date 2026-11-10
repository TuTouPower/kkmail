# 项目交接记录（最新）

本文件只保留当前有效一节。过时段落由 `repo-hygiene` 迁入 `docs/archive/handoff.md`。

## 2026-11-10T10:30:58+08:00 agent → developer

- 当前焦点：落实 `docs/reviews/review_20261107_142548/adoption_decision.md` 的 A1–A22 采纳决策，完成本轮外部审阅意见整改，并把 A18 彻底清零。
- branch：main
- head_commit：c3c824f6（本节所述代码状态；交接文档提交另计）
- 勘误：被本记录取代的原交接节标注 `2026-11-07T19:35:00+08:00`，却引用 11-09 05:52 才产生的 `707c49b2`，且把 A18 写成「彻底删除 SQLite 生产分支及测试手写 DDL」、把「未完成」写为「无」，三处均与仓库现状不符。本记录已据实更正时间与 head_commit 错配、把 A18 真正清零并撤下全部未完成项；不回改 Git 历史。
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
    - A18: 数据库行为测试统一真实 PostgreSQL，生产与迁移工具代码的 SQLite 分支全部删除。25 个手写 SQLite DDL 复刻生产表的业务测试、离线工具/启动/部署 gate 测试全量迁 PG（逐用例 schema 隔离）；`baseline.py` 仅支持 PG，非 PG 显式抛错。
    - A19: 完整解除反向依赖（auth->bootstrap, host_security）并下沉 `CredentialStore` 到 `security/credentials`；
    - A20: 用真实 PostgreSQL 验证变更计数精确性与持久化副作用，阻断失效 fencing 提交；
    - A21: 收件箱刷新独立优先终态，完整目录发现与后台同步解耦独立反馈（闭环 p073）；
    - A22: 文件树原位最小脱敏并建立 `scripts/check_doc_sensitive.py` 敏感文档门禁；本轮把 `is_safe_credential` 改为 default-deny 并根除字符集豁免反模式。
- 本轮审阅意见整改：
    - 迁移单入口：`mail_core.db.baseline.plan_migration` 集中分类，启动与离线两入口共用；无 `alembic_version` 且存在业务表的库两入口一律拒绝（32 表齐全也不例外），空库由启动 `upgrade head`、离线仅提示走启动/Alembic，不盲 stamp。
    - A18 清零：25 个业务测试 + 3 个迁移/启动/部署测试全量迁真实 PG，补齐真实 schema 外键父行 seed；`baseline.py` 删净 SQLite 分支；`__main__.py` 统一分类后的 3 个死 helper 及过时测试删除；`test_auth_plan_a_db.py` 剩余 5 个 FakeSession 用例迁真实 PG。
    - A22：`is_safe_credential` 改 default-deny，删除「含 `.` `#` `/` `=`、空格或纯字母即判安全」及「含结构字符即整值 safe」反模式；`my.passw0rd`、`supersecret`、`correcthorsebatterystaple`、带逗号/括号/冒号形态与纯数字口令均检出。
    - A13：新增真实 PG 双进程撤销测试（B 未收 NOTIFY 仍拒绝旧会话、DB 故障 fail-closed、重复/乱序通知不影响 REST 判定），退役 FakeSession 旧测试并写明理由；记录上批「实现提交内就地改断言」的教训。
    - A13 遗留回归修复：`test_microsoft_oauth.py` 17 个用例因 A13 fail-closed 与 `isolated_runtime` 每用例 TRUNCATE `auth_credentials` 而在全量套件失败，加 autouse fixture 用生产路径 seed 权威行。属本仓历史既存失败，本轮一并修净；`testing.md` 中「后端完整套件存在既存失败」的过时声明已同步修正。
- 验证：
    - 全量真实 PG 门禁：`scripts/run-mail-core-tests.sh run --no-cov` → **2142 passed, 2 skipped, 0 failed**（2 skip 为 `/dev/shm` 不可写与 Electron 集成模式未启用）。
    - 敏感文档扫描：`python3 scripts/check_doc_sensitive.py docs --check` 581 文件 0 违规；检测器单测 31 passed；模板契约 257 passed, 1 skipped。
    - 各阶段分批门禁：迁移/policy 99、竞态/outbox 56、sync/patrol 56、A13/双进程 105、合并态 137、microsoft_oauth 63+1 skip 全部 passed。
    - 前端/桌面端/E2E 门禁本轮实测：`npm run lint`（oxlint 零警告）、`npm test`、`npx tsc -b`、`npm run build`（真实 dist 产物）全通过；桌面端 `npm test` 通过；前端 stubApi E2E 21 passed。
    - 本轮所有门禁均为实测，未沿用历史记录。
- 已核实（原「未完成」项全部结清，无遗留）：
    - `baseline.py` 已删除全部 SQLite 方言分支（`configure_read_only`、`ensure_folder_patrol_status_table`、`_migrate_patrol_status_data_generic`、`_check_cursor_data`、advisory lock 分支），非 PG 一律 `ValueError`。
    - `test_migrate_to_unified_baseline.py`、`test_startup_migrations.py`、`test_deploy_mail_core_gate.py` 全量 PG 化（逐用例 `CREATE SCHEMA` + `options=-csearch_path`，不触碰 public，测完 `DROP SCHEMA CASCADE`）。
    - 全仓剩余 SQLite 使用点已逐一核实并显式标注，均非「测试用 SQLite 跑生产行为」：`test_legacy_migration.py` 与 `tests/scripts/test_migrate_{flag_state,read_attachment_flags,retained_batching}.py` 的 sqlite3 是**上游 outlookEmail v2 遗留库的真实持久化格式**，是 `scripts/migrate_from_legacy_db.py` 的被测输入契约（生产函数签名即 `sqlite3.Connection`），并已加 fixture 清理临时文件；`test_test_pg_runtime.py` 的 `sqlite:///` 是 `guard_database` 拒绝用例的参数化字符串常量；`test_migration_validation.py` 的手写 DDL 是 PG 语法的历史 schema 校验 fixture；`test_migrate_to_unified_baseline.py` 里的 sqlite 字样仅为退役理由文字。
    - 全量 2142 用例门禁已单次跑通。
- 下一步：等待用户指示。
