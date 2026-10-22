# t022 综合审查 (Single Level)

## 范围与执行方式

审查 t022 确定性大邮箱基准与资源性能测试改动：

- `scripts/benchmark_mailbox.py`: 建立支持 1k / 10k / 100k 规模的数据集确定性生成器、首页 keyset 分页、深分页、中文全文检索、未读统计与流式 Blob 读取性能测量工具，计算 p50/p95 延迟分位数、吞吐、进程 RSS、PG 存储大小和 EXPLAIN 执行计划，支持报告差异比对
- `tests/mail_core/test_mailbox_performance_baseline.py`: 建立基准测试与跨报告差异对比自动化门禁

## 门禁验证结果

1. **基准自动化门禁**: `scripts/run-mail-core-tests.sh run -k test_mailbox_performance_baseline` 2 passed (6.56s)。各项指标齐全、分页无漏项无重复。
2. **报告差异比对校验**: 验证延迟变化百分比、RSS 内存差异与数据库空间变化能够清晰展现，平台不一致时发出警示。

## 结论

PASS。无未解决 critical 或 important 问题。
