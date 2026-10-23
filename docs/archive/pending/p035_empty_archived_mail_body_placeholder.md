# p035 已归档合法空正文邮件在阅读器误提示邮件正文尚未完成同步

- 现象：库内真实邮件（如 126 邮箱中由 163 发送的主题为 `12313` 的邮件 `[REDACTED_UUID]`，发件方未填写正文内容，原始 MIME 只有报头、正文 0 字节）在后台已成功归档（`message_archive_state.state = 'archive_complete'`, `is_archived = True`, `parse_error = None`, `body = ""`），但在前端 `MessageReader` 中打开该邮件时，正文占位区域仍显示大字提示“邮件正文尚未完成同步”，使用户误以为该邮件处于未同步异常状态。用户确认：合法空邮件正文直接保持留白即可，不需要任何提示文字干扰用户。
- 影响：
    1. 任何纯主题无正文的合法空邮件（`is_archived === true && !body && !parse_error`）在阅读器中均被误报为“邮件正文尚未完成同步”，造成用户对同步状态产生混淆。
    2. 产生无意义的占位框与文案干扰，破坏留白体验。
- 根因：
    1. 前端状态机分支合并缺陷（`src/frontend/src/components/MessageReader.tsx:59-61, 216-276`）：
        - `isPendingArchive` 仅在 `detail.is_archived === false` 时为 `true`；
        - 在 `!body && !detail?.parse_error` 的占位渲染中，条件链路为 `syncingBody ? (...) : syncError ? (...) : isPendingArchive ? (...) : (...)`；
        - 最后的 fallback `else` 分支直接渲染了 `<p style={{ margin: 0, fontWeight: 600 }}>邮件正文尚未完成同步</p>`；
        - 当邮件已归档（`detail.is_archived === true`）且合法空正文时，`isPendingArchive` 为 `false`，因而直接掉入 fallback `else`，被错误当成未同步邮件显示“邮件正文尚未完成同步”。
    2. 用户确认的修复方向与同类位点：
        - `src/frontend/src/components/MessageReader.tsx:216-276`：仅在未归档（`detail.is_archived === false`）时渲染正文同步占位框（同步中 / 同步错误 / 待拉取提示及按钮）；当邮件已完成归档（`detail.is_archived === true`）且正文为空时，直接渲染 `null`，保持干净留白，不展示任何占位框或提示。
        - `src/frontend/src/components/MessageReader.test.tsx:288-292, 528-537`：既有测试曾把 `is_archived: true` 且正文为空的用例断言为包含“邮件正文尚未完成同步”，形成了测试假绿。
        - 后端 `api_get_message`（`src/mail_core/api/mail.py:315-323`）对该邮件已正确返回 `is_archived: True, body: "", parse_error: None`，后端无同类缺陷。
- 测试缺口：
    1. `src/frontend/src/components/MessageReader.test.tsx` 缺少对已归档合法空邮件（`is_archived: true, body: ""`）断言 `.empty-body-placeholder` 为 `null`、正文直接保持空白且绝不包含“邮件正文尚未完成同步”的用例。
- 线索：
    - `.scratch/repro_empty_body_placeholder.test.tsx`：最小复现用例，已证实当前对 `is_archived: true, body: ''` 的邮件输出了“邮件正文尚未完成同步”。
    - 数据库事实：`Message id: [REDACTED_UUID], subject: '12313', state: 'archive_complete', MIME payload length: 717 bytes (header only)`。
- 处理：main
