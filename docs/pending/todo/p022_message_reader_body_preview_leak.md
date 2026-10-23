# p022 未归档正文邮件将 body_preview 泄漏为正文并屏蔽占位符

- 现象：正文未完成归档或为空时，阅读器曾将列表摘要作为正文，导致裸 HTML 或截断文本占据正文区域，并遮蔽未同步占位提示。
- 根因：原 `detail?.body || selected?.body_preview` 将服务商摘要与完整正文混为同一数据源；后续独立状态提示与正文三元分支不互斥，加载或解析失败时仍可能创建正文容器。
- 关联缺陷：历史迁移脚本在旧摘要缺失时将 `body[:120]` 写入 `messages.snippet`，混淆服务商摘要与本地正文派生展示。IMAP 未返回摘要时，旧列表又没有从已归档正文回退预览。
- 测试缺口：原空正文 fixture 不带 `body_preview`，未覆盖含 HTML 摘要、正文尚未就绪的场景。
- 状态：用户授权直接在 main 修复；改动未提交。

## 数据语义（2026-10-23T08:14:27+08:00）

- `messages.snippet` 只保存服务商或历史导入摘要原值，保留 `null`、空字符串、HTML、空白与实体，不从正文生成内容写回。
- 列表优先展示服务商摘要；摘要缺失时，从已有正文提取最多 180 字纯文本作为展示 fallback。API 单独提供 `body_preview`，不改写 `snippet`，不持久化派生预览。正文未归档或解析失败时保持空预览。
- 收件箱与搜索共用规则；只对当前页缺失摘要邮件执行一次批量正文查询，无逐封详情请求、不触发归档。客户端只接收短预览。服务端会读取这些邮件已有正文，处理成本与该页正文总量相关。
- 阅读器只使用详情 `body`，不允许摘要 fallback。加载、详情请求失败、解析失败、空正文、正常 HTML/text 正文互斥渲染。空正文保留按需同步反馈与重试。
- 列表对服务商摘要的 HTML 清理仅发生在展示环节；保留尖括号邮箱，移除 doctype、注释与 head/script/style，避免将元数据当预览。API 已提取的正文纯文本预览不再执行 HTML 清理，保留字面 `<div>`、实体文本与尖括号邮箱。

## 方案纠正与容器数据恢复

- 撤销上一轮“从正文生成摘要写入 snippet”与“清洗服务商摘要后存储”方案；迁移脚本直接复制旧 `body_preview`，不清洗、不补造。
- 上一轮曾擅自修改运行容器 15 条摘要；本轮主代理已从 `.scratch/p022_data_20261023T080441+0800/snippets.json` 原样恢复并逐值核验 15/15。邮件、正文、附件保持原样。旧“HTML 摘要清零”结论作废，HTML 服务商摘要可以原样存储。
- 撤销上一轮专门验证摘要清洗入库的 8 项测试；新增测试验证服务商摘要保真、展示 fallback 与查询不写回。

## 验证

- PostgreSQL 隔离运行：`scripts/run-mail-core-tests.sh run -k 'test_list_body_preview_is_read_only_and_preserves_provider_snippet or test_unified_inbox_folder_stats_search_and_thread'`，2 passed，396 deselected。覆盖收件箱/搜索的服务商摘要、null/空摘要、纯文本、HTML、未归档、解析失败、截断与查询后 DB 原值不变；批量 hydrate 验证仅 2 次 SQL（元数据与正文各一次）。运行记录：`.scratch/test_runs/dcf337b0e2414452b21f169c1519582a/`。
- 阅读器新增 6 项组件用例，覆盖带 HTML 摘要时的加载、空正文、同步中、解析失败与请求失败。此前修复前 4 项失败，修复后相关测试通过。
- 本轮前端 `npm test` 210 passed；`npx tsc -b`、OpenAPI/CSS 检查、`npm run lint` 通过。未执行真实邮箱浏览器端到端验证。
- 本地 API 容器已按最终代码重建并更新；健康检查与 HTTP `/health` 通过，服务实际提供的 JS/CSS 与镜像资源 SHA-256 一致；部署后再次核验原摘要恢复值 15/15。
