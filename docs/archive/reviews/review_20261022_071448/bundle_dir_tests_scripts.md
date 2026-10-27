# Bundle Review — dir:tests/scripts

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 1 allowlisted tracked files

## Findings

- [Medium][95] tests/scripts/test_fetch_pg_binaries_helpers.sh:8-L69 — 安全 helper 测试复制实现而不是调用生产脚本 — 证据：测试文件内重写 assert_tar_safe 与 url_allowed，测试通过不能证明 scripts/fetch-pg-binaries.sh 的实际函数行为未回归。 — 依据：生产实现见 scripts/fetch-pg-binaries.sh:174-200。 — 修复：抽取可 source 的 helper 或直接运行生产脚本函数进行 fixture 验证。

## Files examined

- tests/scripts/test_fetch_pg_binaries_helpers.sh
