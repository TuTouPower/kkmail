# Bundle Review — dir:docs/skills/kkmail

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 1 allowlisted tracked files

## Findings

- [Medium][95] docs/skills/kkmail/SKILL.md:101-L101 — 技能示例把账户密码直接放在命令行参数中 — 证据：示例使用 --password secret；真实密码通过 shell history 与进程参数暴露，且文档鼓励不安全用法。 — 依据：同文件第 15 行已有环境变量入口。 — 修复：示例改为环境变量/交互提示读取，不展示密码参数。

## Files examined

- docs/skills/kkmail/SKILL.md
