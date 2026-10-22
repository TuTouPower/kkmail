# t013 代码审查

## 范围与执行方式

按用户授权，在 main 审查 t013 未提交实现；不使用 task.py、worktree 或 attempt 工具链。本审查覆盖专用 Compose、运行入口、数据库身份与所有权保护、分配和清理、子进程收尾、直接 pytest 保护及安全回归测试。未读取密钥文件，未操作数据库。

## Finding 处置

- 已修 important：分配函数返回前异常导致外层无法清理。`create_run()` 捕获 BaseException 并自行收尾；每轮 NOLOGIN owner role 原子赋予数据库所有权，覆盖 CREATE DATABASE 与 COMMENT 之间中断。OSError、KeyboardInterrupt 回归检查库与 role 均已删除。
- 已修 important：快速模式继承 PG 密码，误执行真实数据库探针。unit 移除 PG 密码与运行目录，live probes 明确跳过 unit。
- 已修 important：迁移失败测试通过共享目录集合差识别资源，并发时误报。改为捕获本测试实际创建运行目录。

## 末次变更复核

PG 条件 skip 处理改为 `pytest_runtest_makereport` hookwrapper，在最终 TestReport 上将 skipped 转为 failed，避免构造未实际抛出的 ExceptionInfo 导致 INTERNALERROR。新增真实子 pytest 回归，断言 exit code 为 1、包含失败原因且无 INTERNALERROR。静态复核未发现新增 critical/important。

## 验证与限制

实施侧报告：17 项安全测试通过；实际断言失败、迁移失败及 SIGTERM 均验证入口返回非零并清理本轮数据库。完整套件记录为 337 passed / 2 failed / 2 skipped：LISTEN 测试受前序 outbox 残留影响；旧 SSE 测试无 subscriber 时仍期待派发。两项失败留待 t014 排查，不能据此声明完整套件通过。

连续两轮完整测试及其容器、PG 服务进程复用证据仍缺；同进程双分配探针不能替代两个独立仓库/worktree 完整运行与取消隔离证据。SIGKILL 残留后显式回收也需补充实测记录。

结论：本轮代码审查无未解决 critical/important；整项 t013 验收尚未完成，不标记 task PASS。
