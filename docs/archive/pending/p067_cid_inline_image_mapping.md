# p067 `cid:` 内联附件图片未映射到附件地址导致图片不显示

- 现象：含内联图片的 HTML 邮件中，`<img src="cid:...">` 在阅读器内始终显示为碎图或占位；即使已允许加载远程图片也不恢复。
- 影响：依赖内联图的邮件正文视觉缺失，用户会误判为“远程图片放行未生效”；影响所有含 Content-ID 内联附件的邮件。
- 根因：归档解析已把 `Content-ID` 存入 `Attachment.content_id`（`src/mail_core/mail/storage/models.py:254`，写入见 `src/mail_core/blobs/archive.py:392-452`），但 `AttachmentOut`（`src/mail_core/api/mail.py:133`）不返回该字段，前端附件 DTO 转换（`src/frontend/src/api/mailCore.ts:189-194`）也未保留；阅读器从未把 `cid:` URL 重写为附件预览地址。CSP 虽声明 `img-src ... cid:`（`src/frontend/src/lib/mailBody.ts:148`），浏览器并不提供 `cid:` 协议处理器。已确认同类位点：未发现其他 `cid:` 转换入口。
- 测试缺口：现有阅读器测试仅覆盖 http(s) 图片与 CSP 字符串（`src/frontend/src/lib/mailBody.test.ts:39,64`），未覆盖含 Content-ID 附件的正文渲染与实际图片可见性；需补后端 DTO 暴露 `content_id`、前端 URL 重写单测与真实浏览器的内联图加载验证。
- 线索：`.scratch/repro_remote_images_issue.md:15-16`；`grep -rn "cid:" src/frontend/src src/mail_core`。
- 处理：t066
