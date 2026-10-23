# General review t043

结论：PASS。

- 主分支原修复 `4c28237`、`4c4dd7a` 已存在，正文数据源仅为 detail.body；加载、请求失败、解析失败与空正文状态互斥，不创建正文容器。
- 既有 MessageReader 回归带 HTML body_preview、空 body 与 true/false/null 归档状态，要求展示占位且不出现摘要。当前前端 260 项全量测试通过。
- 列表仅在缺服务商摘要时生成展示预览；真实 PostgreSQL 查询不写回测试已存在，最终全量结果记录于 task 总账。
- p022 过时“未提交”状态已修正。未修改生产正文渲染逻辑，未处理历史邮件数据。
- 按 direct-main 授权进行人工审查，不伪造 worktree/attempt 状态。
