# Bundle Review — dir:src/desktop/scripts

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 1 allowlisted tracked files

## Findings

- [Medium][99] src/desktop/scripts/pack-linux.js:25-L59 — Linux 打包脚本可能删除既有 frontend/dist 内容 — 证据：只要 dist 缺 index.html 就创建临时 stub，结束时递归删除整个 dist；已有部分构建资产会一并被删。 — 依据：pack-linux.js:25,56-59。 — 修复：只删除本次创建的 stub，或在临时目录构建并原子替换。

## Files examined

- src/desktop/scripts/pack-linux.js
