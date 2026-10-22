# Bundle Review — dir:docs/reviews/review_20261021_034329/\_meta

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 2 allowlisted tracked files

## Findings

- [Low][55] docs/reviews/review_20261021_034329/\_meta/\_meta.json:4-L5 — 公开仓历史 review 产物包含本机绝对路径和用户目录信息 — 证据：旧 review metadata 及正文在多个行记录本机 home、项目和外部工具仓路径；可关联真实个人账户与目录结构。当前新报告已使用相对路径。 — 依据：同类证据见 review_20261021_034329/\_meta/rubric.md:35、review_20261021_040521/\_meta/\_meta.json:4-5 及若干 bundle。 — 修复：清理已公开报告中的本机路径或迁移到脱敏版本；避免新报告再次写绝对路径。
- [Low][50] docs/reviews/review_20261021_034329/\_meta/rubric.md:35-L35 — 公开 Git 作者元数据含多个个人邮箱格式地址，公开意图无法核实 — 证据：历史提交作者记录中存在多个个人邮箱格式地址；邮箱是否为公开联系地址或专用 noreply 地址无法从仓库验证，因此仅列隐私核对项。 — 依据：公开仓安全审计应确认作者元数据是否经本人授权公开。 — 修复：核实公开意图；若非公开地址，按仓库治理流程更新 author metadata。

## Files examined

- docs/reviews/review_20261021_034329/\_meta/\_meta.json
- docs/reviews/review_20261021_034329/\_meta/rubric.md
