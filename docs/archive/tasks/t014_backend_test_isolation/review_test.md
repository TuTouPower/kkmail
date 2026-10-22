# Test review — t014

## 结论

Test review PASS。已复核本次测试隔离实现与测试，初次发现的 NOTIFY 验证缺口已关闭，当前无未解决的重要测试问题。最终两个固定 seed 的完整 PostgreSQL 套件均通过，测试集合一致；两项真实 IMAP 测试因服务未启用而跳过，不属于本次 PostgreSQL 隔离验收。

## 范围与方法

基线 `8f93e8e`，审查 t014 未提交变更、共享隔离实现、人工 mailbox factory 与对应 spec。未运行模板工具链、未读取任何 `.env` 或密钥、未操作 PostgreSQL；实际执行证据来自主会话，并只读核对 `.scratch/test_runs/` 中摘要与覆盖报告。

## 契约核对

- AC-001：收集阶段支持固定 seed 打乱，终端输出 seed，JSON 摘要保留 seed 与未执行 nodeid。最终 seed 41 与 seed 17 在两个独立测试库运行，JUnit testcase 集合均为相同 354 项，两轮均为 352 passed、2 skipped、0 failed/error/not_executed。
- AC-002：两个参数化哨兵在每次初态检查 Account、Message、AppSetting、AuthCredential、WorkerJob、OutboxEvent 均为空，然后真实 commit。覆盖后续用例不继承前次提交。全局 stats 与任务 claim 未在新哨兵中直接调用，但底层相关表为空，既有实际 claim 测试保留。
- AC-003：真实 commit 后保持首连接占用，比较两条连接的 `pg_backend_pid()`，并由第二物理连接观察已提交账号；保留真实 skip_locked、fencing 与 LISTEN 测试。新增通知测试直接通过 psycopg 执行 LISTEN，断言 writer commit 前无通知、commit 后收到正确 channel，不经过 dispatcher 轮询。
- AC-004：正常结束与刻意 AssertionError 两条路径均启动真实 Worker、LISTEN listener 并打开裸 Connection；退出后断言线程停止、Connection 关闭、对应 PostgreSQL PID 消失、provider 恢复、credential store 复位及已提交账号清空。API lifespan 单独验证 listener 启停。清理失败会停止测试会话，避免继续污染。
- AC-005：factory 使用固定 seed、UUID5、固定 sort_time 与固定 MIME boundary。两个账号拥有相同 Message-ID，生产 keyset 查询逐页验证账号归属、完整性与无重复；覆盖空目录 stats、中文 MIME 和真实附件 Blob。固定 seed MIME 字节重复生成相等。
- AC-006：混合文件中的纯单元测试移除整文件 PG skip，数据库用例逐项标记。运行摘要记录收集、执行、跳过原因与未执行清单。覆盖入口使用 `--cov=mail_core --cov-branch`，已核对报告仅包含 `src/mail_core/` 生产模块，未设统一覆盖率门槛掩盖缺口。

## 实际证据

|运行|结果|产物目录|
|---|---|---|
|快速套件|351 collected；250 passed；101 skipped；0 未执行|`.scratch/test_runs/unit_01ca83515c394277a30803f3a3cc8959/`|
|隔离与既有 SSE 定向集|14 passed；0 failed；0 skipped|`.scratch/test_runs/d679f504cf944bf48b92def4c11c7fc3/`|
|最终新增 NOTIFY 正向|1 passed|`.scratch/test_runs/7fdf491d91434fa5af5362072c7b123b/`|
|NOTIFY no-op 变异|1 failed；入口 exit 1，符合预期|`.scratch/test_runs/a7259cb1a8c8478fa36084622241b2b5/`|
|固定 seed 17 全量|353 collected；351 passed；2 skipped；0 failed；0 未执行|`.scratch/test_runs/1038238e1fe84459bb83e31e197d4b86/`|

最终两轮的两项跳过均因本地 IMAP 服务不可用：`test_live_imap_sync_via_worker_handler` 与 `test_imap_list_and_metadata_page`，不是 PostgreSQL skip。最终两轮均包含新增 NOTIFY 测试。主会话报告 no-op 变异仅在独立子进程临时替换生产 `notify_outbox`，断言确实失败，测试库清理完成，变异未写入实现；摘要已核对 exit 1。

上述各完成运行的 coverage.json 均启用 branch coverage，文件范围均仅生产 `src/mail_core/`。最终两轮各包含 87 个生产文件，综合行/分支覆盖率分别为 78.63% 与 78.66%，不以统一门槛掩盖未覆盖分支。先前失败运行作为历史证据保留，不替代最终通过结果。

## 最终验证与边界

主会话已核对 `.scratch/t014_final_seed_41.log` 与 `.scratch/t014_repeat_seed_17.log`，确认两轮独立测试库、相同 JUnit testcase 集合及 ownership 均为 cleaned。容器 ID、system_identifier 与 pg_postmaster_start_time 全程相同；最终无测试数据库或 owner role 遗留。测试审查另只读核对最终两轮及快速套件 JSON 摘要、覆盖报告，与上述结果一致。

连接上限测试属于纯单元，已去除 PG skip，最终快速套件实际执行；无 PG 独立运行也通过。真实 IMAP 服务未启用，保留两项 IMAP 集成验证边界，不声称已完成外部 IMAP 验证。Test review PASS 仅表示本次测试审查通过，不代替 task 状态维护与其余收尾。
