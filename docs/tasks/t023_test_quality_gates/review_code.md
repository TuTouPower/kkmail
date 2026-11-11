# t023 代码审查

## 范围与执行方式

审查 t023 持续集成工作流、分层测试门禁与架构决策文档改动：

- `.github/workflows/ci.yml`: 建立 PR/Push 只读质量门禁流水线（四大并行 Job：template-contract、frontend-quality、desktop-quality、backend-and-integration，以及汇总守护 ci-status）
- `.github/workflows/scheduled.yml`: 建立定时与手动扩展演练流水线（备份跨库恢复、多版本迁移升级、多进程 Worker 故障恢复、大邮箱性能基准）
- `docs/blueprint/testing.md`: 统一测试分层矩阵、本地执行命令与 CI 映射
- `docs/blueprint/decisions.md`: 记录 CI 分层门禁与只读发布边界决策

## Finding 处置

- 已修 important: CI 失败产物收集范围。在 backend-and-integration 异常时上传 `.scratch/` 下的测试运行、E2E 截图与进程日志。
- 已修 important: ci-status 汇总门禁。采用 `if: always()` 与状态检查，防止上游 job 失败时汇总被自动跳过而导致假绿。

## 结论

PASS。无未解决 critical 或 important 问题。
