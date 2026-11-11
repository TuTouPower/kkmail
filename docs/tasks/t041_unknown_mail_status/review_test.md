# Test review t041

- 审查基线：`3cedba6`；修复提交：`300d394`。
- 审查者：主代理；实现由独立 p024 子代理完成。
- 审查范围：首次 metadata 插入、未知状态统计、旧库导入、0019 迁移、API/codegen、列表显示与乐观回滚测试。直接 main 实施，不声称通过 worktree attempt 门禁。

## 结论

PASS，无未解决 finding。

## 证据

- `test_unknown_mail_status.py` 调用真实 metadata apply、PostgreSQL 持久化与查询：首次三状态为 NULL，明确 false 后未知更新保持 false，未知读数为 NULL。
- 迁移测试从 0018 写入确定状态后升级，核对原值与数据库 nullable/default；NULL 存在时拒绝降级，消除有损回退。
- 旧库导入测试保留来源 read/attachment，并检查不存在的 flag 为 NULL；不重新猜测历史默认 false 来源。
- 前端新增回归覆盖未知状态不显示未读/不自动写回、搜索未知未读计数、失败恢复 NULL，以及旧 item 与缓存状态不同时回滚缓存原值。两项审查缺陷均先红后绿。
- 旧 race mock 增加未知计数列，详情夹具明确输入 flag=false，均保留原有预期。失效固定 head 测试整体替换并说明迁移链扩展原因，没有把旧断言改为错误输出。
- 前端 260 passed；类型、构建、lint、OpenAPI 通过。PG 定向 migration/legacy/global stats 13 passed，最终 partial/race/detail 19 passed；最终全量结果由 task 总账记录。

## 边界

没有真实服务商 OAuth 凭据；使用协议 transport fixture 与真实数据库。历史默认 false 与服务商明确 false 无来源区分，保留旧值，不声称自动修复历史来源。

## IMAP 补扫复核

- IMAP 补扫由主代理实现；原 p024 子代理独立检查新增测试，代码 reviewer 独立复核完整 token。缺失、空 FLAGS、扩展旗标、大小写均覆盖 metadata 与 delta 生产入口。新增纯单测 9 项通过；连同报头解析为 15 passed / 1 PG 条件 skipped（仅单元模式），最终真实协议结果见 task 总账。
