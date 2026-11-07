# 项目交接记录（最新）

本文件只保留当前有效一节。过时段落由 `repo-hygiene` 迁入 `docs/archive/handoff.md`。

## 2026-11-07T19:35:00+08:00 agent → developer

- 当前焦点：落实 `docs/reviews/review_20261107_142548/adoption_decision.md` 全部 22 项采纳决策（A1–A22）。
- branch：main
- head_commit：b0b55340
- 已完成：
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
    - A18: 统一数据库行为测试至真实 PostgreSQL，彻底删除 SQLite 生产分支及测试手写 DDL；
    - A19: 完整解除反向依赖（auth->bootstrap, host_security）并下沉 `CredentialStore` 到 `security/credentials`；
    - A20: 用真实 PostgreSQL 验证变更计数精确性与持久化副作用，阻断失效 fencing 提交；
    - A21: 收件箱刷新独立优先终态，完整目录发现与后台同步解耦独立反馈（闭环 p073）；
    - A22: 文件树原位最小脱敏并建立 `scripts/check_doc_sensitive.py` 敏感文档门禁。
- 验证：
    - 模板契约测试：`pytest .repo_template/tests -q -m contract`（257 passed）；
    - 敏感文档扫描：`python3 scripts/check_doc_sensitive.py docs --check`（566 文件 0 违规）；
    - 前端 lint：`npm run lint`（oxlint 零错误零警告）；
    - 前端单测/契约/样式：`npm test`（53 文件 576 用例全过）；
    - 前端类型检查：`npx tsc -b`（零错误）；
    - 前端构建打包：`npm run build`（生成 dist 产物）；
    - 桌面端测试：`cd src/desktop && npm test`（11 个测试套件全过）；
    - 快速 UI E2E：`npm --prefix src/frontend run test:e2e`（21 用例全过）；
    - 真实全栈端到端：`python3 scripts/run_full_stack_e2e.py`（8 个完整链路用例全过）；
    - 后端 PostgreSQL 核心及改造套件全过（86 passed）。
- 未完成：无
- 下一步：等待用户指示。
