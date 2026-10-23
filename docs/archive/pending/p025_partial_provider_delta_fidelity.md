# p025 Graph/Gmail 部分邮件更新覆盖已有字段

- 现象：Graph message delta 的 updated resource 可只含 `id` 与已更新字段；当前 parser 将只含 `subject`/`from` 的项作为完整 metadata upsert，缺失字段转换为空值后覆盖本地值。Microsoft Graph 的 [delta query overview](https://learn.microsoft.com/en-us/graph/delta-query-overview) 说明 updated instance 用 `id` 加至少已更新属性表示；其他属性可能同时返回。message delta 也支持 `$select`，且 `id` 始终返回（[message delta API](https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0)）。
- 影响：Graph 部分更新会清空已有 `from_address`/`subject`、`from_name`、收件人、服务商 `snippet`、`internet_message_id` 等未包含字段。当前 t036 已让 `sort_time=None` 与状态/附件的 `None` 更新跳过；本条聚焦其余内容字段。
- Gmail 路径：Gmail History 文档说明 history 中 message 对象通常只填 `id`、`threadId`（[users.history.list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list)）。本仓 `GmailProvider.delta_changes` 会对 upsert 调 `messages.get(format=metadata)`：成功且响应有 `id` 时，以 hydrate metadata 替换 history stub；正常的 `id/threadId` stub 遇 GET 异常会抛出，不会返回 DeltaPage。仍有两条可达覆盖路径：成功的 `metadata` 响应只提供 ID、labels、headers（[Gmail Format](https://developers.google.com/workspace/gmail/api/reference/rest/v1/Format)），不含 snippet/internalDate；`_meta_from_gmail_message` 因而给 `snippet=None`，upsert 会清除已有 provider snippet；GET 返回无 `id` 时代码静默保留原 stub 并返回 upsert，返回仅 `id` 时则被当作完整 hydrate。若异常时 stub 已有 subject 或 from，现有 except 条件也会吞掉异常并保留 partial meta。`fetch_metadata_page` 复用同一 metadata 请求和转换函数，存在同样 snippet 清空路径。
- 根因：Graph `parse_graph_delta` 以任一内容字段判断 `upsert`，`_meta_from_graph` 把缺失 subject/from 变为 `""`，其余变为 `None`/空地址组；`apply_delta_page` 将其交给 `upsert_messages`。`metadata.py` 只跳过 `sort_time`、状态和附件字段的 `None`，其他字段及 to/cc 列表仍无条件赋值。Gmail `parse_gmail_history` 先将 History stub 转为 partial upsert；provider hydrate 后未验证所需字段完整性，且 metadata response 省略的 snippet 会被当作要清除的空值。
- 测试缺口：当前 Graph presence 测试只覆盖 read/flag/attachment 的 `None` 保留；缺少 Graph partial content delta 对已存在 `Message` 的集成断言。Gmail History parser 测试未覆盖真实 stub 经 provider hydrate 后的应用；provider 测试 fixture 在 `format=metadata` 响应里塞入 `snippet` 和 `internalDate`，与官方 projection 不符。应在 parser/provider 至 metadata upsert 层覆盖 Graph 仅含 `id+subject`、`id+from` 与显式空值的差别；Gmail 覆盖完整 metadata 响应不清除已有 snippet、无 id/id-only 响应不得作为完整记录、普通 id/thread stub 的 GET 异常，以及有部分 header 的 GET 异常；并覆盖 `fetch_metadata_page` 的同一转换路径。
- 线索：`.scratch/repro_partial_provider_delta.py` 调用真实 Graph parser、Gmail provider 与 `upsert_messages`，以无数据库 session double 复现覆盖；输出保存在 `.scratch/repro_partial_provider_delta.out.json`。Graph 用例显示已有 sender name、to/cc、snippet、internet message id 被清空；Gmail 正常 metadata hydration 也将已有 snippet 清成 null。输出同时显示正常 History stub 在 GET 异常时抛出，以及 no-id/id-only fallback 的行为。此前 `p024_unknown_mail_status_defaults.md` 另跟踪新邮件状态未知值落库默认 false；本条只纳入 Gmail partial fallback 显式伪造 read/flag 状态这一重叠路径。
- 处理：t042

## 本轮修复（t042）

- `RemoteMessageMeta.supplied_fields` 为 None 表示完整快照，字段集合表示部分 projection。Graph/Gmail 转换记录实际提供字段，upsert 只应用存在字段；明确空主题、空摘要与空地址组仍可清空旧值。
- Graph 按字段存在性识别内容更新，避免空值被误判为纯 flag 更新；未返回字段保留已有事实。
- Gmail metadata/history hydrate 校验响应 ID 与请求一致、labelIds 为列表、payload.headers 为列表；缺失、不匹配、id-only 与 GET 异常均中断该页，不再回退到 History stub。metadata projection 未提供 snippet 时保留已有摘要，首次无来源时保持空。
- 同页 partial upsert/flag 按返回顺序合并；同字段以后续明确值为准，未提供字段不丢失，delete 丢弃之前 patch；未知日期/状态不覆盖已知值，本地未收敛意图保护继续生效。
- 新增 `tests/mail_core/test_partial_metadata_fidelity.py` 覆盖 parser/provider 到真实 PostgreSQL upsert、显式清空、metadata 缺 snippet、非法 hydration、异常与顺序合并。修复已提交 `c755ebd`；代码与测试 review PASS。前端 260 passed，类型/构建/lint/OpenAPI/CSS 通过；PG 定向验证通过，最终串行全量 477 passed / 0 skipped。

## 最终闭环验证

- 主分支最终后端全量 477 passed / 0 skipped；前端 260 passed，类型、构建、lint、OpenAPI/CSS 均通过；真实全栈 E2E 8 passed，stub E2E 13 passed。
- 代码/测试审查及逐 AC 证据见对应 t041/t042/t043 总账。未部署生产，未改写运行邮件数据。
