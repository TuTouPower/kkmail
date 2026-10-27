# 已归档 task 说明

本目录（`docs/archive/tasks/`）下各 task 的 `spec.md` 均为该 task 执行时点的**历史快照**，不代表现行契约：其中契约可能已被后续 task 改写或取代，单看某一份 `spec.md` 不得视为现行依据。

现行契约以 `docs/specs/` 下的累积 spec 为准，生效清单见 `docs/specs_index.md`。各 task 的状态与收尾结论以同目录 `task.md` front matter 及收尾报告为准。

本声明适用于本目录全部 task，全目录口径一致；后续 task 归档迁入本目录时自动适用本声明。

## t013–t023 批次归档完整性统一声明（2026-10-27，A243）

t013–t023 批次于 2026-10-22 按用户授权直接在 main 分支顺序执行、未使用 task 工具链：本批各 task 目录均无 `handoff.json`，系按用户授权省略工具链 handoff，不视为归档缺失。本批中无独立 `review_test.md` 的 task，其复审覆盖口径如下：t013 未单独做 test review，其测试面由相邻的 t014 对共享测试入口与隔离完成的 code/test 复审覆盖（详见 t013 `task.md`「归档完整性补记（2026-10-27，A243）」）；t015、t022 为 single 复审级，复审记录为同目录 `review_general.md`。本批其余 task 的 `review_test.md` 均在各自目录内。
